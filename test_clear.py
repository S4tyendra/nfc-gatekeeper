import sys
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers

# APDU to Write 4 bytes to a page
# [Class, INS, P1, P2, Lc, b0, b1, b2, b3]
WRITE_PAGE_APDU_TPL = [0xFF, 0xD6, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00]

print("✅ Test Clear (pages 0x10-0x28)")
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
    print("\n💳 Card detected! Clearing...\n")

    # Generate data to write - all zeros for pages 0x10 to 0x28
    data_to_write = {}
    for page in range(0x00, 0x29):  # 0x10 to 0x28 inclusive
        data_to_write[page] = [0x00, 0x00, 0x00, 0x00]

    for page, bytes_data in data_to_write.items():
        apdu = WRITE_PAGE_APDU_TPL[:]
        apdu[3] = page  # Set the page address
        apdu[5:9] = bytes_data  # Set the 4 bytes to write

        print(f"📝 Writing to page 0x{page:02X} ({page}): {bytes_data}")

        data, sw1, sw2 = connection.transmit(apdu)

        if (sw1, sw2) == (0x90, 0x00):
            print(f"   ✅ Page 0x{page:02X} written successfully!")
        else:
            print(f"   ❌ Failed to write page 0x{page:02X}. Status: {sw1:02X} {sw2:02X}")
            # DON'T break - continue trying

    print("\n✅ Operation complete!")

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

