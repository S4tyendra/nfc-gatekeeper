#!/usr/bin/env python3
"""
NFC Student ID Reader - Optimized and Fully Compliant Version
Reads student data from NFC cards (pages 0x04-0x06)
with precise controlled beep/LED feedback as per user requirements:

- No auto-beep on initial card tap (disabled proactively at startup).
- Beeps with a Red LED blink ONLY after successful data read.
- Prints student ID data *before* beeping.
- Immediately ready for the next card (fast detection and reset).
- High CPU efficiency for long-running operation.
"""

import sys
import time  # For Windows fallback and general time-based operations
import signal  # For POSIX efficiency (Linux, macOS)
from smartcard.Exceptions import CardConnectionException, NoCardException
from smartcard.System import readers
from smartcard.CardMonitoring import CardMonitor, CardObserver

# ============================================================================
# APDU Commands (Pre-compiled for performance)
# ACR122U specific commands for LED and Buzzer control
# ============================================================================
READ_STUDENT_DATA = [0xFF, 0xB0, 0x00, 0x04, 0x10]  # Read 16 bytes (4 pages) starting from page 0x04

# APDU to disable the automatic buzzer on card detection (no beep on tap).
# This is an essential command for the user's primary requirement.
DISABLE_AUTO_BEEP = [0xFF, 0x00, 0x52, 0x00, 0x00]

# Beep with Red LED Blink APDU for ACR122U:
# [FF, 00, 40, P1, Lc, D1, D2, D3, D4]
#   - FF 00 40: Command header for buzzer/LED control (polling mode).
#   - P1 (0x01): Buzzer control (0x01 = Tone 1, a standard beep sound).
#   - Lc (0x04): Length of data (D1-D4) bytes that follow.
#   - D1 (0x01): Tone duration (e.g., 1 unit of 100ms, total 100ms beep).
#   - D2 (0x01): Tone repetitions (e.g., 1 repetition).
#   - D3 (0x02): LED State (0x01=Green ON, 0x02=Red ON, 0x03=Both ON). -> Red ON.
#   - D4 (0x02): LED Blinking (0x01=Green blink, 0x02=Red blink, 0x03=Both blink). -> Red Blinking.
BEEP_RED_BLINK_SUCCESS = [0xFF, 0x00, 0x40, 0x01, 0x04, 0x01, 0x01, 0x02, 0x02]


# ============================================================================
# Utility Functions
# ============================================================================

def send_command(connection, apdu, suppress_error=False):
    """
    Sends an APDU command to the card connection.
    Returns (success_status, data_bytes).
    'suppress_error=True' can be used for non-critical commands like LED/buzzer.
    """
    try:
        data, sw1, sw2 = connection.transmit(apdu)
        success = (sw1 == 0x90 and sw2 == 0x00)

        if not success and not suppress_error:
            # Optionally log detailed APDU failures for debugging, but not for user output
            # print(f"   (APDU command {apdu} failed: SW={sw1:02X} {sw2:02X})")
            pass
        return success, data
    except CardConnectionException as e:
        # Expected if card is removed during command transmission, or connection lost.
        # Often occurs with fast card removal/insertion, no need to print unless debugging.
        if not suppress_error:
            # print(f"   (APDU transmit connection error: {e})")
            pass
        return False, None
    except Exception as e:
        # Catch other unexpected errors during command transmission.
        if not suppress_error:
            print(f"   (APDU transmit unexpected error: {e})")
        return False, None


def extract_ascii(data_bytes, start, length):
    """
    Extracts a printable ASCII string from a slice of bytes.
    Filters out non-printable characters (ASCII codes 32-126) to ensure clean output.
    """
    return ''.join(chr(b) for b in data_bytes[start:start + length] if 32 <= b <= 126)


def read_student_data(connection):
    """
    Reads 3 pages (0x04, 0x05, 0x06) of student data from the card.
    Returns the concatenated ASCII string (e.g., "YearCodeID") on success,
    or None on failure (read error, insufficient data, or empty result).
    """
    success, data = send_command(connection, READ_STUDENT_DATA)

    # Ensure command succeeded and enough data was received for the 3 pages (12 bytes)
    if not success or not data or len(data) < 12:
        return None

    # The READ_STUDENT_DATA APDU reads 16 bytes starting from page 0x04.
    # Pages 0x04, 0x05, 0x06 correspond to the first 12 bytes of this response.
    year = extract_ascii(data, 0, 4)  # Bytes 0-3 (Page 0x04)
    code = extract_ascii(data, 4, 4)  # Bytes 4-7 (Page 0x05)
    student_id = extract_ascii(data, 8, 4)  # Bytes 8-11 (Page 0x06)

    result = f"{year}{code}{student_id}"

    # Return data only if it contains actual printable characters after stripping whitespace.
    return result.strip() if result.strip() else None


# ============================================================================
# Card Observer Class
# ============================================================================

class SmartCardObserver(CardObserver):
    """
    Handles card insertion and removal events, processing student ID data,
    and providing controlled feedback. Ensures immediate readiness for next card.
    """

    __slots__ = ('last_data',)  # Optimize memory for observer instances

    def __init__(self):
        super().__init__()
        self.last_data = None  # Stores last successfully read data to prevent duplicate processing

    def update(self, observable, actions):
        """
        Callback method for card insertion/removal events, triggered by CardMonitor.
        """
        addedcards, removedcards = actions

        # Reset last_data when a card is removed.
        # This allows the same card to be read again if re-inserted, ensuring immediate readiness.
        if removedcards and self.last_data:
            self.last_data = None
            # print("   (Card removed. Ready for next scan.)") # Optional debug message

        # Process each newly inserted card.
        for card in addedcards:
            self._process_card(card)

    def _process_card(self, card):
        """
        Connects to a card, reads student data, and provides feedback.
        Note: Auto-beep disable is handled proactively at startup in main(),
        but also re-attempted here for robustness against reader setting resets.
        """
        connection = None
        try:
            connection = card.createConnection()
            connection.connect()

            # Re-attempt to disable auto-buzzer silently for robustness.
            # This handles cases where reader settings might reset, though primary disable is at startup.
            send_command(connection, DISABLE_AUTO_BEEP, suppress_error=True)

            # Attempt to read student data from the card.
            student_data = read_student_data(connection)

            # Check if data was read successfully and if it's new data to prevent re-processing.
            if student_data and student_data != self.last_data:
                print(f"✅ ID: {student_data}")  # Requirement: Print data first
                send_command(connection, BEEP_RED_BLINK_SUCCESS,
                             suppress_error=True)  # Requirement: Beep with Red LED blink
                self.last_data = student_data  # Store data to prevent duplicate processing
            elif not student_data:
                # If read failed or data was empty, reset last_data to allow immediate retry.
                # (e.g., if card was held incorrectly the first time, allows retry without card removal).
                self.last_data = None
                # Optional: Add different feedback (e.g., error beep/LED) for read failures here.
                # send_command(connection, BEEP_ERROR_RED_LED, suppress_error=True)

        except (CardConnectionException, NoCardException):
            # These exceptions are common if a card is quickly removed or connection lost.
            # Reset last_data to ensure readiness for the next attempt without printing an error.
            self.last_data = None
            # print("   (Card connection/no card exception during processing.)") # Optional debug
        except Exception as e:
            # Catch any other unexpected errors during card processing.
            print(f"❌ Error processing card: {e}")
            self.last_data = None
        finally:
            # Always attempt to disconnect to release the connection resource.
            if connection:
                try:
                    connection.disconnect()
                except Exception:
                    # Ignore errors on disconnect, as they can occur if card removed quickly.
                    pass


# ============================================================================
# Reader Setup and Main Application Entry Point
# ============================================================================

def setup_and_configure_reader(reader_obj):
    """
    Connects to the reader *once at startup* to disable its auto-buzzer.
    This ensures no unwanted beeps on the very first card tap.
    """
    connection = None
    try:
        connection = reader_obj.createConnection()
        connection.connect()

        # Disable automatic buzzer to prevent any initial tap beeps. This is CRITICAL.
        success, _ = send_command(connection, DISABLE_AUTO_BEEP, suppress_error=True)
        if success:
            print("   ✓ Auto-buzzer disabled successfully.")
        else:
            print("   ⚠ Could not disable auto-buzzer. Reader may beep on tap.")

    except Exception as e:
        # This setup connection might fail if the reader is temporarily busy or
        # some obscure condition, but we print a warning and proceed.
        print(f"   ⚠ Initial reader configuration failed: {e}. Auto-buzzer may not be disabled.")
    finally:
        if connection:
            try:
                connection.disconnect()
            except Exception:
                pass  # Ignore errors during disconnect.


def main():
    """
    Main function to initialize the reader, proactively configure it,
    start card monitoring, and keep the application running efficiently.
    """
    print("📖 NFC Student ID Reader")
    print("   Initializing...\n")

    # Locate and setup the reader device.
    reader_list = readers()
    if not reader_list:
        print("❌ No NFC readers found. Please ensure the reader is connected and drivers are installed.")
        return 1  # Exit with error code

    # Use the first detected reader.
    reader = reader_list[0]
    print(f"   Found reader: {reader}")

    # Proactively configure the reader (disable auto-buzzer) at startup.
    # This is crucial for the "no beep while tapping" requirement.
    setup_and_configure_reader(reader)

    print("\n   Ready. Waiting for cards...\n")

    # Initialize card monitoring.
    monitor = CardMonitor()
    observer = SmartCardObserver()
    monitor.addObserver(observer)

    try:
        # Keep the application alive efficiently.
        # `signal.pause()` is highly efficient on Unix-like systems (Linux, macOS).
        if hasattr(signal, 'pause') and (sys.platform.startswith('linux') or sys.platform.startswith('darwin')):
            signal.pause()
        else:
            # Fallback for Windows or systems where signal.pause is not available.
            # Sleeps for a long duration to minimize CPU usage, wakes up to check for KeyboardInterrupt.
            print("   (signal.pause not available, using time.sleep. Press Ctrl+C to exit.)")
            while True:
                time.sleep(3600)  # Sleep for 1 hour, minimal wake-ups
    except KeyboardInterrupt:
        # User pressed Ctrl+C to exit.
        pass
    except Exception as e:
        print(f"\n❌ Unhandled error in main loop: {e}")
    finally:
        # Cleanup: Stop monitoring and remove the observer gracefully.
        print("\n👋 Exiting...")
        try:
            if monitor and observer:
                monitor.deleteObserver(observer)
        except Exception:
            # Ignore errors during cleanup if monitor/observer might already be gone.
            pass
        print("Reader monitoring stopped.")

    return 0  # Exit successfully


if __name__ == "__main__":
    sys.exit(main())