from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.util import toHexString
from smartcard.Exceptions import NoCardException, CardConnectionException
import time

class LockCardObserver(CardObserver):
    """Observer that locks cards when inserted"""

    def __init__(self):
        super().__init__()
        self.card_count = 0
        self.locked_count = 0
        self.already_locked_count = 0
        self.failed_count = 0

    def update(self, observable, actions):
        (addedcards, removedcards) = actions

        for card in addedcards:
            self.card_count += 1
            print(f"\n[Card #{self.card_count}] Card detected! Processing...")

            try:
                connection = card.createConnection()
                connection.connect()

                # Disable auto-polling
                DISABLE_AUTO_POLL = [0xFF, 0x00, 0x51, 0xFF, 0x00]
                data, sw1, sw2 = connection.transmit(DISABLE_AUTO_POLL)

                if sw1 != 0x90:
                    print(f"   ❌ Reader init failed")
                    self.failed_count += 1
                    self.print_stats()
                    continue

                # Load card
                LOAD_CARD = [0xFF, 0x00, 0x00, 0x00, 0x04, 0xD4, 0x4A, 0x01, 0x00]
                data, sw1, sw2 = connection.transmit(LOAD_CARD)

                if sw1 != 0x90:
                    print(f"   ❌ Card load failed")
                    self.failed_count += 1
                    self.print_stats()
                    continue

                # Read current lock status
                page = 0x28
                READ_CMD = [0xFF, 0x00, 0x00, 0x00, 0x04, 0xD4, 0x42, 0x30, page]
                data, sw1, sw2 = connection.transmit(READ_CMD)

                if sw1 != 0x90 or len(data) < 6:
                    print(f"   ❌ Read failed")
                    self.failed_count += 1
                    self.print_stats()
                    continue

                current_lock = data[2:6]
                print(f"   📖 Current lock bytes: {toHexString(current_lock)}")

                # Check if already locked (byte 0 is read-only at 0x00, check bytes 1-2)
                # NTAG213: byte 0 stays 0x00 (read-only), bytes 1-2 = FF FF when locked
                if current_lock[1] == 0xFF and current_lock[2] == 0xFF:
                    print(f"   ⚠️  Already locked - skipped")
                    self.already_locked_count += 1
                    self.print_stats()
                    print("   Remove card and tap next...")
                    continue

                # Write lock bytes
                lock_data = [0xFF, 0xFF, 0xFF, 0xBD]
                WRITE_CMD = [0xFF, 0x00, 0x00, 0x00, 0x08, 0xD4, 0x42, 0xA2, page] + lock_data
                print(f"   📝 Writing lock data: {toHexString(lock_data)}")
                data, sw1, sw2 = connection.transmit(WRITE_CMD)
                print(f"   📤 Write response: SW1={sw1:02X} SW2={sw2:02X}")

                if sw1 == 0x90 and sw2 == 0x00:
                    # Verify
                    data, sw1, sw2 = connection.transmit(READ_CMD)
                    if sw1 == 0x90:
                        page_data = data[2:6]
                        print(f"   📥 Read back: {toHexString(page_data)}")
                        # NTAG213: byte 0 is read-only (stays 0x00), verify bytes 1-2 = FF FF
                        if page_data[1] == 0xFF and page_data[2] == 0xFF:
                            print(f"   ✅ LOCKED successfully! (Byte 0 is read-only at 0x00)")
                            self.locked_count += 1
                        else:
                            print(f"   ⚠️  Lock verification failed - expected x FF FF, got {toHexString(page_data[:3])}")
                            self.failed_count += 1
                    else:
                        print(f"   ⚠️  Verification read failed (SW1={sw1:02X} SW2={sw2:02X})")
                        self.failed_count += 1
                else:
                    print(f"   ❌ Lock write failed ({sw1:02X} {sw2:02X})")
                    self.failed_count += 1

                self.print_stats()
                print("   Remove card and tap next...")

            except (NoCardException, CardConnectionException) as e:
                print(f"   ❌ Connection error: {e}")
                self.failed_count += 1
                self.print_stats()
            except Exception as e:
                print(f"   ❌ Error: {e}")
                self.failed_count += 1
                self.print_stats()

        for card in removedcards:
            # Card removed - ready for next
            pass

    def print_stats(self):
        print(f"   📊 Total: {self.card_count} | Locked: {self.locked_count} | Already: {self.already_locked_count} | Failed: {self.failed_count}")


print("🔒 EVENT-DRIVEN BATCH LOCK SCRIPT")
print("=" * 60)
print("   Using CardMonitor for automatic detection")
print("   Tap cards one by one")
print("   Press Ctrl+C to exit")
print("=" * 60)
print("\nMonitoring... Ready for cards!\n")

# Create observer and monitor
cardmonitor = CardMonitor()
cardobserver = LockCardObserver()
cardmonitor.addObserver(cardobserver)

try:
    # Keep running
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n\n" + "=" * 60)
    print("🛑 BATCH LOCKING STOPPED")
    print("=" * 60)
    print(f"   Cards processed:     {cardobserver.card_count}")
    print(f"   ✅ Newly locked:      {cardobserver.locked_count}")
    print(f"   ⚠️  Already locked:   {cardobserver.already_locked_count}")
    print(f"   ❌ Failed:            {cardobserver.failed_count}")
    print("=" * 60)
finally:
    cardmonitor.deleteObserver(cardobserver)
