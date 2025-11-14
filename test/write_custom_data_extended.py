import sys
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers

# APDU to Write 4 bytes to a page
# [Class, INS, P1, P2, Lc, b0, b1, b2, b3]
WRITE_PAGE_APDU_TPL = [0xFF, 0xD6, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00]

print("✅ Custom Data Writer (Extended)")
print("   Connect reader and tap card...")

try:
    r = readers()
    if not r:
        print("   ❌ No readers found.")
        sys.exit()

    reader = r[0]
    print(f"   Using reader: {reader}")

    connection = reader.createConnection()
    connection.connect()
    print("\n💳 Card detected! Writing custom data...\n")

    # Data to write:
    # Pages 17, 18, 19 (0x11, 0x12, 0x13)
    # Pages 24, 25, 26 (0x18, 0x19, 0x1A)
    # Pages 33, 34, 35 (0x21, 0x22, 0x23)

    data_to_write = {
        0x11: [0x00, 0x00, 0x00, 0x00, ],  # Page 17
        0x12: [ord('K'), ord('O'), ord('T'), ord('A')],  # Page 18
        0x13: [ord('U'), ord('S'), ord('E'), ord('R')],  # Page 19
        0x18: [ord('I'), ord('I'), ord('I'), ord('T')],  # Page 24
        0x19: [ord('K'), ord('O'), ord('T'), ord('A')],  # Page 25
        0x1A: [ord('U'), ord('S'), ord('E'), ord('R')],  # Page 26
        0x21: [ord('I'), ord('I'), ord('I'), ord('T')],  # Page 33
        0x22: [ord('K'), ord('O'), ord('T'), ord('A')],  # Page 34
        0x23: [ord('U'), ord('S'), ord('E'), ord('R')]   # Page 35
    }

    for page, bytes_data in data_to_write.items():
        apdu = WRITE_PAGE_APDU_TPL[:]
        apdu[3] = page  # Set the page address
        apdu[5:9] = bytes_data  # Set the 4 bytes to write

        print(f"📝 Writing to page 0x{page:02X} ({page}): {bytes_data} ('{chr(bytes_data[0])}{chr(bytes_data[1])}{chr(bytes_data[2])}{chr(bytes_data[3])}')")

        data, sw1, sw2 = connection.transmit(apdu)

        if (sw1, sw2) == (0x90, 0x00):
            print(f"   ✅ Page 0x{page:02X} written successfully!")
        else:
            print(f"   ❌ Failed to write page 0x{page:02X}. Status: {sw1:02X} {sw2:02X}")
            break

    print("\n✅ Write operation complete!")
    print("   You can now read the card to verify the data.")

except CardConnectionException:
    print("\n❌ Card removed during operation.")
except KeyboardInterrupt:
    print("\n⚠️ Operation cancelled by user.")
except Exception as e:
    print(f"\n❌ An error occurred: {e}")

finally:
    try:
        connection.disconnect()
    except Exception:
        pass
    sys.exit()

