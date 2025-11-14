import sys
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers

# APDU to Write 4 bytes to a page
# [Class, INS, P1, P2, Lc, b0, b1, b2, b3]
WRITE_PAGE_APDU_TPL = [0xFF, 0xD6, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00]

print("✅ Custom Data Writer")
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
    # Page 0x04: "2022" (ASCII)
    # Page 0x05: "KUCP" (ASCII)
    # Page 0x06: "1033" (ASCII)

    data_to_write = {
        0x04: [ord('I'), ord('I'), ord('I'), ord('T')],  # "2022"
        0x05: [ord('K'), ord('O'), ord('T'), ord('A')],  # "KUCP"
        0x06: [ord('U'), ord('S'), ord('E'), ord('R')]   # "1033"
    }

    for page, bytes_data in data_to_write.items():
        apdu = WRITE_PAGE_APDU_TPL[:]
        apdu[3] = page  # Set the page address
        apdu[5:9] = bytes_data  # Set the 4 bytes to write

        print(f"📝 Writing to page 0x{page:02X}: {bytes_data} ('{chr(bytes_data[0])}{chr(bytes_data[1])}{chr(bytes_data[2])}{chr(bytes_data[3])}')")

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

