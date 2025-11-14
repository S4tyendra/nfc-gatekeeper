from smartcard.System import readers
from smartcard.util import toHexString

r = readers()[0]
connection = r.createConnection()
connection.connect()

# 1. Disable auto-polling (critical for stable reads)
DISABLE_AUTO_POLL = [0xFF, 0x00, 0x51, 0xFF, 0x00]
data, sw1, sw2 = connection.transmit(DISABLE_AUTO_POLL)
print(f"Disable auto-poll: {sw1:02X} {sw2:02X}")

if sw1 != 0x90:
    print("Failed to disable auto-polling!")
    exit(1)

# 2. Load card (activate PICC after disabling auto-poll)
LOAD_CARD = [0xFF, 0x00, 0x00, 0x00, 0x04, 0xD4, 0x4A, 0x01, 0x00]
data, sw1, sw2 = connection.transmit(LOAD_CARD)
print(f"Load card: {sw1:02X} {sw2:02X}")

# 3. Now read page 4 with stable connection
page = 0x04
READ_CMD = [0xFF, 0x00, 0x00, 0x00, 0x04, 0xD4, 0x42, 0x30, page]
data, sw1, sw2 = connection.transmit(READ_CMD)

print(f"Read page {page}: {sw1:02X} {sw2:02X}")
if sw1 == 0x90 and sw2 == 0x00:
    page_data = data[2:]
    print(f"Data (hex): {toHexString(page_data)}")
    print(f"Data (ASCII): {''.join(chr(b) if 32 <= b < 127 else '.' for b in page_data)}")
else:
    print(f"Read failed")
