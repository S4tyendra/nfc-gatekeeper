import sys
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers
from smartcard.util import toHexString

# APDU to Read 16 bytes (4 pages) at a time
# [Class, INS, P1, P2, Le]
READ_16_BYTES_APDU_TPL = [0xFF, 0xB0, 0x00, 0x00, 0x10]

print("✅ Full Card Dump Script")
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
    print("\n💳 Card detected! Reading full card...\n")

    # Read card continuously until we get an error
    # Typical NTAG cards have 45 pages, but we'll read until failure
    full_data = []
    page_num = 0
    max_attempts = 256  # Safety limit

    print("📖 Reading pages...")
    while page_num < max_attempts:
        apdu = READ_16_BYTES_APDU_TPL[:]
        apdu[3] = page_num  # Set the starting page

        try:
            data, sw1, sw2 = connection.transmit(apdu)
            if (sw1, sw2) != (0x90, 0x00):
                # Failed to read - we've reached the end
                break

            # Successfully read 16 bytes (4 pages)
            full_data.extend(list(data))
            page_num += 4

        except Exception:
            # Error reading - end of card
            break

    # total pages on the card (including empty)
    raw_total_pages = len(full_data) // 4

    # Build a list of non-empty pages to print. We treat a page as empty when all 4 bytes are 0x00.
    pages_to_print = []
    for i in range(raw_total_pages):
        byte_index = i * 4
        p = full_data[byte_index: byte_index + 4]
        if all(b == 0x00 for b in p):
            continue
        pages_to_print.append((i, p))

    printed_pages_count = len(pages_to_print)
    total_bytes = len(full_data)

    print(f"✅ Read complete!\n")
    print("=" * 70)
    print(f"📊 CARD SUMMARY")
    print("=" * 70)
    print(f"   Total Pages (raw): {raw_total_pages}")
    print(f"   Pages Printed (non-empty): {printed_pages_count}")
    print(f"   Total Bytes Read: {total_bytes}")
    print("=" * 70)
    print()
    print("=" * 70)
    print(f"{'PAGE':<6} | {'HEX DATA':<23} | {'ASCII':<6}")
    print("=" * 70)

    for page_index, p in pages_to_print:
        p_hex = toHexString(p)

        ascii_data = "".join(chr(b) if 32 <= b <= 126 else '.' for b in p)


        print(f"{page_index:04X}   | {p_hex:<23} | '{ascii_data}'")

    print("=" * 70)

except CardConnectionException:
    print("\nCard removed.")
except KeyboardInterrupt:
    print("\nExiting.")
except Exception as e:
    print(f"\n   ❌ An error occurred: {e}")

finally:
    try:
        connection.disconnect()
    except Exception:
        pass
    sys.exit()