import datetime
import time
import asyncio
from smartcard.System import readers
from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.util import toHexString
from smartcard.Exceptions import CardConnectionException, NoCardException

import config

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

class MessObserver(CardObserver):
    """
    Simplified observer for Mess System.
    Only reads student ID and calls callback. All logic handled in main.py.
    """
    def __init__(self, callback_func):
        self.callback = callback_func
        self.loop = None

    def update(self, observable, actions):
        (addedcards, removedcards) = actions
        for card in addedcards:
            self.process_card(card)

    def process_card(self, card):
        reader_name = card.reader
        connection = None
        
        try:
            connection = card.createConnection()
            connection.connect()

            # 1. Get UID
            success, uid_data = send_command(connection, config.CMD_GET_UID)
            if not success: 
                return
            card_uid = toHexString(uid_data)

            # 2. Debounce Check
            now = time.time()
            if card_uid in last_scanned_uid:
                if now - last_scanned_uid[card_uid] < debounce_time:
                    return # Skip duplicate
            last_scanned_uid[card_uid] = now

            # 3. Disable Beep (Silent mode until success)
            send_command(connection, config.CMD_DISABLE_BEEP)

            # 4. Read Data
            student_id = read_student_data(connection)
            if not student_id:
                print(f"Failed to read student data from {card_uid}")
                return

            # 5. Call the callback with student_id
            # Main.py will handle all logic (session check, duplicate check, logging)
            event_data = {
                "type": "tag",
                "tag_id": student_id,
                "card_uid": card_uid,
                "reader": reader_name
            }
            
            print(f"[NFC_HANDLER] Calling callback with: {event_data}")
            if self.loop:
                future = asyncio.run_coroutine_threadsafe(self.callback(event_data), self.loop)
                try:
                    result = future.result(timeout=5.0)
                    print(f"[NFC_HANDLER] Callback result: {result}")
                    
                    # Only beep on SUCCESS
                    if result and result.get("status") == "success":
                        send_command(connection, config.CMD_BEEP_SUCCESS)
                        print("[NFC_HANDLER] Beep sent (success)")
                    else:
                        print("[NFC_HANDLER] No beep (denied/error)")
                        
                except Exception as e:
                    print(f"[NFC_HANDLER] Callback error: {e}")
            else:
                print("[NFC_HANDLER] ERROR: No event loop available!")


        except Exception as e:
            print(f"Card Error: {e}")
        finally:
            if connection:
                try:
                    connection.disconnect()
                except: 
                    pass

class ReaderManager:
    def __init__(self, loop, broadcast_func):
        self.monitor = CardMonitor()
        self.observer = MessObserver(broadcast_func)
        self.observer.loop = loop # Inject event loop
        self.monitor.addObserver(self.observer)
        
    def get_readers(self):
        try:
            return [str(r) for r in readers()]
        except:
            return []

    def stop(self):
        self.monitor.deleteObserver(self.observer)