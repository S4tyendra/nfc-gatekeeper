import sys
import time
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers
from smartcard.CardMonitoring import CardMonitor, CardObserver

# APDU
READ_16_BYTES_APDU = [0xFF, 0xB0, 0x00, 0x00, 0x10]


def read_student_data(connection):
    """
    Read pages 0x04, 0x05, 0x06 and return as ASCII string.
    Returns None if read fails.
    """
    try:
        apdu = READ_16_BYTES_APDU[:]
        apdu[3] = 0x04

        data, sw1, sw2 = connection.transmit(apdu)

        if (sw1, sw2) != (0x90, 0x00):
            print(f"❌ Read failed. Status: {sw1:02X} {sw2:02X}")
            return None

        # Extract 3 pages (12 bytes total)
        page_04 = data[0:4]
        page_05 = data[4:8]
        page_06 = data[8:12]

        # Convert to ASCII, filtering out null bytes and non-printable chars
        year = ''.join(chr(b) for b in page_04 if 32 <= b <= 126)
        code = ''.join(chr(b) for b in page_05 if 32 <= b <= 126)
        student_id = ''.join(chr(b) for b in page_06 if 32 <= b <= 126)

        result = f"{year}{code}{student_id}"

        if not result:
            print("... Read success (90 00), but pages 4-6 are empty or non-ASCII.")
            return None

        return result

    except Exception as e:
        print(f"❌ Error during transmit/data processing: {e}")
        return None


# This class handles the card events
class MyCardObserver(CardObserver):
    """A card observer that reads data upon card insertion."""

    def __init__(self):
        super().__init__()
        self.last_data = None

    def update(self, observable, actions):
        (addedcards, removedcards) = actions

        # Handle card removals first
        for card in removedcards:
            if self.last_data:
                self.last_data = None  # Reset for next card

        # Handle card insertions
        for card in addedcards:
            connection = None
            try:
                # Create a connection to the card
                connection = card.createConnection()
                connection.connect()

                student_data = read_student_data(connection)

                if student_data:
                    # Only print if it's different from the last card
                    # This prevents re-printing if the card is just "re-tapped"
                    if student_data != self.last_data:
                        print(f"ID: {student_data}")
                        self.last_data = student_data
                    else:
                        pass
                else:
                    # Read failed, clear last_data
                    self.last_data = None

            except Exception as e:
                print(f"❌ Failed to connect or read: {e}")
                self.last_data = None

            finally:
                # IMPORTANT: Disconnect after read attempt
                if connection:
                    try:
                        connection.disconnect()
                    except:
                        pass  # Ignore errors on disconnect


def main():
    try:
        r = readers()
        if not r:
            print("❌ No readers found.")
            sys.exit()

        reader_name = r[0]
        print(f"Monitoring reader: {reader_name}")

        cardmonitor = CardMonitor()
        cardobserver = MyCardObserver()
        cardmonitor.addObserver(cardobserver)

        # We just sleep here; the observer will handle everything
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nExit.")
    except Exception as e:
        print(f"\n❌ Unhandled Error: {e}")

    finally:
        # Clean up the monitor
        if 'cardmonitor' in locals():
            cardmonitor.deleteObserver(cardobserver)
        print("Reader monitor stopped.")


if __name__ == "__main__":
    main()