import datetime
import time
import asyncio
from smartcard.System import readers
from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.util import toHexString
from smartcard.Exceptions import CardConnectionException, NoCardException

import config
import database

# Global state to prevent double scanning
last_scanned_uid = {}
debounce_time = 3.0  # Seconds

def send_command(connection, apdu):
    try:
        data, sw1, sw2 = connection.transmit(apdu)
        if sw1 == 0x90 and sw2 == 0x00:
            return True, data
        return False, None
    except Exception:
        return False, None

def extract_ascii(data_bytes, start, length):
    return ''.join(chr(b) for b in data_bytes[start:start + length] if 32 <= b <= 126)

def read_student_data(connection):
    # Read 16 bytes from Page 4
    apdu = [0xFF, 0xB0, 0x00, config.STUDENT_DATA_PAGE, 0x10]
    success, data = send_command(connection, apdu)
    
    if not success or not data or len(data) < 12:
        return None

    year = extract_ascii(data, 0, 4)
    code = extract_ascii(data, 4, 4)
    sid = extract_ascii(data, 8, 4)
    
    result = f"{year}{code}{sid}".strip()
    return result if result else None

def process_lock(connection):
    # Check lock status (Page 0x28)
    read_apdu = [0xFF, 0xB0, 0x00, config.LOCK_PAGE, 0x04]
    success, data = send_command(connection, read_apdu)
    
    if success and data and len(data) >= 3:
        # If byte 1 and 2 are FF, it's locked
        if data[1] == 0xFF and data[2] == 0xFF:
            return True # Already locked
            
    # Not locked, try to write
    write_apdu = [0xFF, 0xD6, 0x00, config.LOCK_PAGE, 4] + config.LOCK_DATA
    success, _ = send_command(connection, write_apdu)
    return success

class GateObserver(CardObserver):
    def __init__(self, callback_func):
        self.callback = callback_func
        # Config mapping: Reader Name -> Direction
        self.reader_config = {
            "in_reader": None,
            "out_reader": None
        }

    def update(self, observable, actions):
        (addedcards, removedcards) = actions
        
        # Handle card removal (reset debounce if needed, though time-based is safer)
        if removedcards:
             pass

        for card in addedcards:
            self.process_card(card)

    def process_card(self, card):
        reader_name = card.reader
        direction = "unknown"
        
        # Determine direction
        if reader_name == self.reader_config.get("in_reader"):
            direction = "in"
        elif reader_name == self.reader_config.get("out_reader"):
            direction = "out"
        else:
            # Auto-assign if single reader or first time setup
            if not self.reader_config["in_reader"]:
                self.reader_config["in_reader"] = reader_name
                direction = "in"
            elif not self.reader_config["out_reader"]:
                self.reader_config["out_reader"] = reader_name
                direction = "out"

        connection = None
        try:
            connection = card.createConnection()
            connection.connect()

            # 1. Get UID
            success, uid_data = send_command(connection, config.CMD_GET_UID)
            if not success: return
            card_uid = toHexString(uid_data)

            # 2. Debounce Check
            now = time.time()
            if card_uid in last_scanned_uid:
                if now - last_scanned_uid[card_uid] < debounce_time:
                    return # Skip
            last_scanned_uid[card_uid] = now

            # 3. Disable Beep (Silent mode until success)
            send_command(connection, config.CMD_DISABLE_BEEP)

            # 4. Read Data
            student_id = read_student_data(connection)
            if not student_id:
                print(f"Failed to read student data from {card_uid}")
                return

            # 5. Lock Card
            process_lock(connection)

            # 6. Logic & DB
            student = database.get_student(student_id)
            student_name = student['NAME'] if student else "Unknown"
            
            if student_id == "IIITKOTAUSER":
                student_name = "Guest User"

            status = "success" if student or student_id == "IIITKOTAUSER" else "warning"
            msg = "Access Granted" if student or student_id == "IIITKOTAUSER" else "Student not found"

            # Log to DB
            database.log_entry(direction, student_id)
            database.log_system_message(f"{direction.upper()}: {student_name} ({student_id})", student_id, "info")

            # 7. Hardware Feedback (Beep + LED)
            send_command(connection, config.CMD_BEEP_SUCCESS)

            # 8. Notify UI (Async)
            img_path = f"/api/images/{student_id}.png"
            if student_id == "IIITKOTAUSER":
                img_path = "/api/images/guest.png"

            event_data = {
                "type": "tap",
                "direction": direction,
                "student_id": student_id,
                "name": student_name,
                "image_path": img_path,
                "timestamp": datetime.datetime.now().isoformat(),
                "status": status,
                "message": msg
            }
            asyncio.run_coroutine_threadsafe(self.callback(event_data), self.loop)

        except Exception as e:
            print(f"Card Error: {e}")
        finally:
            if connection:
                try:
                    connection.disconnect()
                except: pass

class ReaderManager:
    def __init__(self, loop, broadcast_func):
        self.monitor = CardMonitor()
        self.observer = GateObserver(broadcast_func)
        self.observer.loop = loop # Inject event loop
        self.monitor.addObserver(self.observer)
        
    def get_readers(self):
        try:
            return [str(r) for r in readers()]
        except:
            return []

    # --- ADD THIS METHOD ---
    def get_config(self):
        return self.observer.reader_config
    # -----------------------

    def update_config(self, in_reader, out_reader):
        self.observer.reader_config["in_reader"] = in_reader
        self.observer.reader_config["out_reader"] = out_reader

    def stop(self):
        self.monitor.deleteObserver(self.observer)