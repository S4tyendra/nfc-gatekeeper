#!/usr/bin/env python3
"""
NFC Student ID Processor (Reader, Locker, Logger)

Combines logic to:
1.  Read Student ID (Pages 0x04-0x06).
2.  Read Card UID.
3.  Check lock status (Page 0x28).
4.  Write lock bytes (Page 0x28) if not already locked.
5.  Log the (StudentID, CardUID) pair to a local SQLite database.
6.  Provide controlled beep/LED feedback (Red Blink) ONLY on full success.
7.  Disables auto-beep on tap for a silent-until-success operation.
"""

import sys
import time
import signal
import sqlite3
from smartcard.Exceptions import CardConnectionException, NoCardException
from smartcard.System import readers
from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.util import toHexString

# ============================================================================
# Configuration & Constants
# ============================================================================

DB_FILE = 'student_cards.db'

# --- Page and Data Definitions ---
STUDENT_DATA_PAGE_NUM = 0x04  # Starts at Page 4
STUDENT_DATA_NUM_BYTES = 0x10  # Read 16 bytes (4 pages) to cover 0x04, 0x05, 0x06
LOCK_PAGE_NUM = 0x28  # Page 40 (Static Lock Bytes / CFG)
LOCK_PAGE_NUM_BYTES = 0x04  # Read 4 bytes from Page 40
# This is the data your *original* script was writing to Page 0x28.
# BE WARNED: This writes to NTAG213 Config bytes (CFG0, CFG1), not just lock bytes.
# This is preserved from your script, but modify if it's incorrect.
LOCK_DATA_TO_WRITE = [0xFF, 0xFF, 0xFF, 0xBD]

# ============================================================================
# APDU Commands (Standard)
# ============================================================================

# Disable auto-beep on card detection (ACR122U specific)
DISABLE_AUTO_BEEP = [0xFF, 0x00, 0x52, 0x00, 0x00]

# Beep + Red LED Blink on success (ACR122U specific)
BEEP_RED_BLINK_SUCCESS = [0xFF, 0x00, 0x40, 0x01, 0x04, 0x01, 0x01, 0x02, 0x02]

# Get Card UID (Standard)
GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]

# Read N bytes from Page X (Standard)
# Format: [0xFF, 0xB0, 0x00, <page_num>, <num_bytes>]
READ_STUDENT_DATA_APDU = [0xFF, 0xB0, 0x00, STUDENT_DATA_PAGE_NUM, STUDENT_DATA_NUM_BYTES]
READ_LOCK_PAGE_APDU = [0xFF, 0xB0, 0x00, LOCK_PAGE_NUM, LOCK_PAGE_NUM_BYTES]

# Write N bytes to Page X (Standard)
# Format: [0xFF, 0xD6, 0x00, <page_num>, <num_bytes_to_write>, <data...>]
WRITE_LOCK_PAGE_APDU_HEADER = [0xFF, 0xD6, 0x00, LOCK_PAGE_NUM, len(LOCK_DATA_TO_WRITE)]


# ============================================================================
# Database Functions
# ============================================================================

def init_db(db_path):
    """Initializes the SQLite database and creates the 'cards' table."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('''
                  CREATE TABLE IF NOT EXISTS cards
                  (
                      student_id
                      TEXT
                      NOT
                      NULL,
                      card_uid
                      TEXT
                      NOT
                      NULL,
                      timestamp
                      DATETIME
                      DEFAULT
                      CURRENT_TIMESTAMP,
                      PRIMARY
                      KEY
                  (
                      student_id,
                      card_uid
                  )
                      )
                  ''')
        conn.commit()
        print(f"   ✓ Database initialized: {db_path}")
    except Exception as e:
        print(f"   ❌ FATAL: Database initialization failed: {e}")
        sys.exit(1)  # Exit if we can't create the DB
    finally:
        if conn:
            conn.close()


# ============================================================================
# Utility & Card Functions
# ============================================================================

def send_command(connection, apdu, suppress_error=False):
    """
    Sends an APDU command, returns (success_bool, data_bytes).
    Handles basic error suppression for non-critical commands.
    """
    try:
        data, sw1, sw2 = connection.transmit(apdu)
        success = (sw1 == 0x90 and sw2 == 0x00)
        if not success and not suppress_error:
            print(f"   (APDU Fail: {apdu[0]:02X}.. SW={sw1:02X} {sw2:02X})")
        return success, data
    except (CardConnectionException, NoCardException):
        # Expected if card is removed during transmit
        return False, None
    except Exception as e:
        if not suppress_error:
            print(f"   (APDU Error: {e})")
        return False, None


def extract_ascii(data_bytes, start, length):
    """Extracts a clean, printable ASCII string from a byte slice."""
    return ''.join(chr(b) for b in data_bytes[start:start + length] if 32 <= b <= 126)


def get_card_uid(connection):
    """Reads the card's UID."""
    success, data = send_command(connection, GET_UID)
    return toHexString(data) if success and data else None


def read_student_data(connection):
    """
    Reads pages 0x04, 0x05, 0x06 for student data.
    Returns concatenated ASCII string or None.
    """
    success, data = send_command(connection, READ_STUDENT_DATA_APDU)

    # Need at least 12 bytes (for pages 4, 5, 6)
    if not success or not data or len(data) < 12:
        return None

    year = extract_ascii(data, 0, 4)  # Bytes 0-3 (Page 0x04)
    code = extract_ascii(data, 4, 4)  # Bytes 4-7 (Page 0x05)
    student_id = extract_ascii(data, 8, 4)  # Bytes 8-11 (Page 0x06)

    result = f"{year}{code}{student_id}"
    return result.strip() if result.strip() else None


def check_and_lock_card(connection):
    """
    Reads the lock page (0x28). If not locked, writes the new lock data.
    Returns True on success (either already locked or newly locked).
    Returns False on any failure (read, write, or verification).

    NOTE: This logic is ported from your first script. It checks
    bytes 1 and 2 of the 4-byte page 0x28 data.
    """

    # 1. Read current lock status
    success, data = send_command(connection, READ_LOCK_PAGE_APDU)
    if not success or not data or len(data) < 4:
        print("   ❌ Read lock page failed")
        return False

    print(f"   📖 Current lock bytes (Pg 0x28): {toHexString(data)}")

    # 2. Check if already locked (based on your script's logic)
    # Your script checked index 1 and 2 of the data payload.
    if data[1] == 0xFF and data[2] == 0xFF:
        print("   ℹ️  Card lock bytes already set.")
        return True  # Already locked, counts as success

    # 3. Not locked. Attempt to write new lock bytes.
    print(f"   📝 Writing lock data: {toHexString(LOCK_DATA_TO_WRITE)}")
    write_apdu = WRITE_LOCK_PAGE_APDU_HEADER + LOCK_DATA_TO_WRITE
    success, _ = send_command(connection, write_apdu)

    if not success:
        print("   ❌ Lock write command failed.")
        return False

    # 4. Verify the write
    time.sleep(0.05)  # Give the card a moment to process the write
    success, data = send_command(connection, READ_LOCK_PAGE_APDU)

    if success and data[1] == 0xFF and data[2] == 0xFF:
        print("   ✅ LOCKED successfully!")
        return True
    else:
        print(f"   ⚠️  Lock verification FAILED. Read back: {toHexString(data)}")
        return False


# ============================================================================
# Card Observer Class
# ============================================================================

class StudentCardObserver(CardObserver):
    """
    Handles card insertion/removal, orchestrates the read/lock/log process,
    and provides controlled feedback.
    """
    __slots__ = ('last_uid', 'db_path')  # Optimize memory

    def __init__(self, db_path):
        super().__init__()
        self.last_uid = None
        self.db_path = db_path

    def update(self, observable, actions):
        """Callback for card insertion/removal events."""
        addedcards, removedcards = actions

        # Reset last_uid when a card is removed.
        # This makes the system ready to re-process the *same card* immediately.
        if removedcards and self.last_uid:
            self.last_uid = None
            # print("   (Card removed. Ready for next scan.)") # Debug

        for card in addedcards:
            self._process_card(card)

    def _process_card(self, card):
        """Full processing logic for a single inserted card."""
        connection = None
        card_uid = None

        try:
            connection = card.createConnection()
            connection.connect()

            # 0. Get UID first. This is our "session" key.
            card_uid = get_card_uid(connection)
            if not card_uid:
                print("   ❌ Could not read card UID. Tap again.")
                return

            # If card is still on reader, don't re-process
            if card_uid == self.last_uid:
                return

            print(f"\n[CARD DETECTED] UID: {card_uid}")
            self.last_uid = card_uid  # Set UID immediately to prevent re-entry

            # 1. Proactively disable auto-buzzer
            send_command(connection, DISABLE_AUTO_BEEP, suppress_error=True)

            # 2. Read Student ID
            student_data = read_student_data(connection)
            if not student_data:
                print("   ❌ Could not read student ID data.")
                return  # Keep last_uid set so we don't spam this error

            # 3. Check and apply lock
            lock_success = check_and_lock_card(connection)
            if not lock_success:
                print("   ❌ Card locking process failed.")
                return  # Keep last_uid set

            # 4. ALL SUCCESS. Log to DB and provide feedback.
            print(f"   ✅ ID: {student_data}")

            try:
                rows_added = self.log_card_to_db(student_data, card_uid)
                if rows_added > 0:
                    print(f"   💾 Logged new entry to DB.")
                else:
                    print(f"   ℹ️  Entry (ID: {student_data}, UID: {card_uid}) already in DB.")
            except Exception as e:
                print(f"   ❌ DATABASE ERROR: {e}")
                return  # Failed to log

            # 5. Final success feedback
            send_command(connection, BEEP_RED_BLINK_SUCCESS, suppress_error=True)
            print("   --- Ready for next card ---")

        except (NoCardException, CardConnectionException):
            # Card was removed. Clear last_uid so it can be read again.
            self.last_uid = None
        except Exception as e:
            print(f"   ❌ UNEXPECTED PROCESSING ERROR: {e}")
            self.last_uid = card_uid  # Keep UID to prevent error spam
        finally:
            if connection:
                try:
                    connection.disconnect()
                except Exception:
                    pass  # Ignore disconnect errors

    def log_card_to_db(self, student_id, card_uid):
        """Logs the ID/UID pair to the database. Uses INSERT OR IGNORE."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO cards (student_id, card_uid) VALUES (?, ?)",
                  (student_id, card_uid))
        conn.commit()
        rows = c.rowcount
        conn.close()
        return rows


# ============================================================================
# Reader Setup and Main Application
# ============================================================================

def setup_and_configure_reader(reader_obj):
    """
    Connects to the reader *once at startup* to disable its auto-buzzer.
    """
    connection = None
    try:
        connection = reader_obj.createConnection()
        connection.connect()
        success, _ = send_command(connection, DISABLE_AUTO_BEEP, suppress_error=True)
        if success:
            print("   ✓ Auto-buzzer disabled successfully.")
        else:
            print("   ⚠ Could not disable auto-buzzer. Reader may beep on tap.")
    except Exception as e:
        print(f"   ⚠ Initial reader configuration failed: {e}")
    finally:
        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass


def main():
    """
    Main function: Initializes DB, configures reader, starts monitor.
    """
    print("==============================================")
    print("📖 NFC Student ID Reader, Locker, & Logger")
    print("==============================================")
    print("   Initializing...")

    # 1. Initialize Database
    init_db(DB_FILE)

    # 2. Find and configure reader
    reader_list = readers()
    if not reader_list:
        print("❌ No NFC readers found. Connect reader and retry.")
        return 1

    reader = reader_list[0]
    print(f"   Found reader: {reader}")
    setup_and_configure_reader(reader)

    # 3. Start monitoring
    monitor = CardMonitor()
    observer = StudentCardObserver(DB_FILE)
    monitor.addObserver(observer)

    print("\n   Ready. Waiting for cards...\n")

    # 4. Keep alive efficiently
    try:
        if hasattr(signal, 'pause') and (sys.platform.startswith('linux') or sys.platform.startswith('darwin')):
            # Use signal.pause() for minimal CPU on Linux/macOS
            signal.pause()
        else:
            # Fallback for Windows
            print("   (Running on Windows. Press Ctrl+C to exit.)")
            while True:
                time.sleep(3600)  # Sleep for 1 hour
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n❌ Unhandled error in main loop: {e}")
    finally:
        print("\n👋 Exiting...")
        try:
            if monitor and observer:
                monitor.deleteObserver(observer)
        except Exception:
            pass
        print("Reader monitoring stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())