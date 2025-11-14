import sys
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers

print("🧹 Clearing NFC card (all pages except last 7)...")
print("   Connect reader and tap card...")

# WRITE APDU: [0xFF, 0xD6, 0x00, page, 0x04, b0, b1, b2, b3]
WRITE_PAGE_APDU_TPL = [0xFF, 0xD6, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00]
# READ APDU: [0xFF, 0xB0, 0x00, page, 0x10]
READ_APDU = [0xFF, 0xB0, 0x00, 0x00, 0x10]

try:
    r = readers()
    if not r:
        print("   ❌ No readers found.")
        sys.exit()

    reader = r[0]
    print(f"   Using reader: {reader}")

    connection = reader.createConnection()
    connection.connect()
    print("\n💳 Card detected!\n")

    # First, detect total number of pages on the card
    print("🔍 Detecting card size...")
    total_pages = 0
    for test_page in range(0, 256, 4):
        apdu = READ_APDU[:]
        apdu[3] = test_page
        try:
            data, sw1, sw2 = connection.transmit(apdu)
            if (sw1, sw2) == (0x90, 0x00):
                total_pages = test_page + 4
            else:
                break
        except Exception:
            break

    print(f"📊 Card has approximately {total_pages} pages")

    # Calculate which pages to clear (page 16/0x10 to total_pages - 7)
    # Pages 0-15 (0x00-0x0F) are typically protected (UID, lock bytes, capability container)
    start_page = 0x10
    end_page = total_pages - 7

    if end_page <= start_page:
        print(f"⚠️ Card too small to clear safely (would need to clear pages {start_page} to {end_page})")
        connection.disconnect()
        exit()

    print(f"🧹 Clearing pages {start_page} (0x{start_page:02X}) to {end_page-1} (0x{end_page-1:02X})")
    print(f"   Preserving last 7 pages ({end_page} to {total_pages-1})\n")

    # Generate data to write - all zeros for each page
    data_to_write = {}
    for page in range(start_page, end_page):
        data_to_write[page] = [0x00, 0x00, 0x00, 0x00]

    # Clear pages - continue even if one fails
    success_count = 0
    fail_count = 0

    for page, bytes_data in data_to_write.items():
        apdu = WRITE_PAGE_APDU_TPL[:]
        apdu[3] = page  # Set the page address
        apdu[5:9] = bytes_data  # Set the 4 bytes to write

        data, sw1, sw2 = connection.transmit(apdu)

        if (sw1, sw2) == (0x90, 0x00):
            print(f"✅ Page {page} (0x{page:02X}) cleared")
            success_count += 1
        else:
            print(f"❌ Failed to clear page {page} (0x{page:02X}): {sw1:02X} {sw2:02X}")
            fail_count += 1

    print(f"\n🎉 Clear operation complete!")
    print(f"   ✅ Successfully cleared: {success_count} pages")
    print(f"   ❌ Failed to clear: {fail_count} pages")
    print(f"   🔒 Protected last 7 pages (pages {end_page} to {total_pages-1})")

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
