from smartcard.System import readers
from smartcard.util import toHexString

print("🧹 Clearing NFC card pages 0x04 to 0x17...")

# WRITE APDU: [0xFF, 0xD6, 0x00, page, 0x04, b0, b1, b2, b3]
WRITE_APDU = [0xFF, 0xD6, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00]

try:
    r = readers()
    if not r:
        print("❌ No readers found.")
        exit()

    reader = r[0]
    connection = reader.createConnection()
    connection.connect()
    print("💳 Card detected!\n")

    # Clear pages 0x04 to 0x17 (4 to 23 in decimal)
    zeros = [0x00, 0x00, 0x00, 0x00]

    for page in range(0x04, 0x18):  # 0x18 = 24, so loop goes 4-23
        apdu = WRITE_APDU[:]
        apdu[3] = page
        apdu[5:9] = zeros

        data, sw1, sw2 = connection.transmit(apdu)

        if (sw1, sw2) == (0x90, 0x00):
            print(f"✅ Page {page:02X} cleared")
        else:
            print(f"❌ Failed to clear page {page:02X}: {sw1:02X} {sw2:02X}")
            break

    print("\n🎉 Card cleared successfully!")
    print("📝 Card is now blank and ready for new data")

    connection.disconnect()

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback

    traceback.print_exc()
