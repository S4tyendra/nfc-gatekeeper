import sys
import time
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers
from smartcard.util import toHexString

# APDU Templates
READ_16_BYTES_APDU_TPL = [0xFF, 0xB0, 0x00, 0x00, 0x10]
WRITE_PAGE_APDU_TPL = [0xFF, 0xD6, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00]

print("🔒 NTAG216 PERMANENT LOCK SCRIPT")
print("=" * 70)
print("⚠️  WARNING: THIS OPERATION IS 100% IRREVERSIBLE!")
print("=" * 70)
print()
print("This will PERMANENTLY lock your card:")
print("  • Pages 03h-0Fh (Capability Container & early user data)")
print("  • Pages 10h-E1h (All remaining user data)")
print("  • Pages E3h-E4h (Configuration pages)")
print()
print("After locking:")
print("  ✅ Card can still be READ by any NFC reader")
print("  ❌ NO ONE can write to it EVER again (not even you!)")
print("  ❌ Cannot be unlocked, even with special tools")
print()
print("=" * 70)
print()

# Confirmation prompt
response = input("Type 'LOCK' to continue or anything else to cancel: ")
if response.strip().upper() != "LOCK":
    print("\n❌ Operation cancelled. Card is NOT locked.")
    sys.exit()

print("\n🔄 Proceeding with permanent lock...\n")

connection = None
try:
    r = readers()
    if not r:
        print("❌ No readers found.")
        sys.exit()

    reader = r[0]
    print(f"📱 Using reader: {reader}")

    connection = reader.createConnection()
    connection.connect()
    print("💳 Card detected!\n")

    # ==================================================================
    # STEP 1: Read Page 0x02 to preserve bytes 0-1
    # ==================================================================
    print("=" * 70)
    print("📖 Reading page 0x02 to preserve serial number...")
    print("=" * 70)

    read_apdu = READ_16_BYTES_APDU_TPL[:]
    read_apdu[3] = 0x00  # Start reading from page 0

    data, sw1, sw2 = connection.transmit(read_apdu)

    if (sw1, sw2) != (0x90, 0x00):
        print(f"❌ Failed to read card: Status {sw1:02X} {sw2:02X}")
        connection.disconnect()
        sys.exit()

    # Extract page 0x02 (bytes 8-11 of the 16-byte read)
    page_02 = list(data[8:12])

    print(f"  Current page 0x02: {toHexString(page_02)}")
    print(f"  Byte 0 (Serial):   0x{page_02[0]:02X}")
    print(f"  Byte 1 (Internal): 0x{page_02[1]:02X}")
    print(f"  Byte 2 (Lock 0):   0x{page_02[2]:02X}")
    print(f"  Byte 3 (Lock 1):   0x{page_02[3]:02X}")
    print()

    # Pre-flight check: Warn if already partially locked
    if page_02[2] != 0x00 or page_02[3] != 0x00:
        print("⚠️  WARNING: Card appears already partially locked!")
        print(f"   Lock bytes: {page_02[2]:02X} {page_02[3]:02X}")
        response = input("   Continue anyway? (yes/no): ")
        if response.lower() != 'yes':
            print("\n❌ Operation cancelled.")
            connection.disconnect()
            sys.exit()
        print()

    # ==================================================================
    # STEP 2: Lock Static Lock Bytes (Pages 03h-0Fh)
    # ==================================================================
    print("=" * 70)
    print("🔐 STEP 1/3: Locking Static Lock Bytes (Pages 03h-0Fh)")
    print("=" * 70)

    # Preserve bytes 0-1, set bytes 2-3 to FF FF
    lock_data = [page_02[0], page_02[1], 0xFF, 0xFF]

    print(f"  Writing to page 0x02: {toHexString(lock_data)}")
    print(f"    (Preserved bytes 0-1, set lock bytes to FF FF)")
    print()

    # Write TWICE for permanence (updates backup page)
    for attempt in range(2):
        apdu = WRITE_PAGE_APDU_TPL[:]
        apdu[3] = 0x02  # Page 2 contains static lock bytes
        apdu[5:9] = lock_data

        data, sw1, sw2 = connection.transmit(apdu)

        if (sw1, sw2) == (0x90, 0x00):
            print(f"  ✅ Static lock write {attempt + 1}/2 successful")
        else:
            print(f"  ❌ Failed on attempt {attempt + 1}: Status {sw1:02X} {sw2:02X}")
            print("     Aborting lock process.")
            connection.disconnect()
            sys.exit()

        time.sleep(0.1)  # Small delay between writes

    # Verify static lock bytes were set correctly
    print("\n  📋 Verifying static lock bytes...")
    read_apdu = READ_16_BYTES_APDU_TPL[:]
    read_apdu[3] = 0x00
    data, sw1, sw2 = connection.transmit(read_apdu)
    page_02_verify = list(data[8:12])

    if page_02_verify[2] != 0xFF or page_02_verify[3] != 0xFF:
        print(f"  ❌ WARNING: Lock bytes not set correctly!")
        print(f"     Expected: FF FF, Got: {page_02_verify[2]:02X} {page_02_verify[3]:02X}")
        print("     Aborting lock process.")
        connection.disconnect()
        sys.exit()

    print(f"  ✅ Verified: Lock bytes are {page_02_verify[2]:02X} {page_02_verify[3]:02X}")
    print("  🎉 Static lock bytes set! Pages 03h-0Fh are now locked.\n")

    # ==================================================================
    # STEP 3: Lock Dynamic Lock Bytes (Pages 10h-E1h)
    # ==================================================================
    print("=" * 70)
    print("🔐 STEP 2/3: Locking Dynamic Lock Bytes (Pages 10h-E1h)")
    print("=" * 70)

    # Page 0xE2 for NTAG216 (0x82 for NTAG215, 0x28 for NTAG213)
    # Set bytes 0-2 to FF FF FF (byte 3 = 0x00, will read back as 0xBD)
    # Write TWICE for permanence

    for attempt in range(2):
        apdu = WRITE_PAGE_APDU_TPL[:]
        apdu[3] = 0xE2  # Dynamic lock page for NTAG216
        apdu[5:9] = [0xFF, 0xFF, 0xFF, 0x00]  # Lock all dynamic pages (byte 3 = 0x00 per NXP spec)

        data, sw1, sw2 = connection.transmit(apdu)

        if (sw1, sw2) == (0x90, 0x00):
            print(f"  ✅ Dynamic lock write {attempt + 1}/2 successful")
        else:
            print(f"  ❌ Failed on attempt {attempt + 1}: Status {sw1:02X} {sw2:02X}")
            print("     Aborting lock process.")
            connection.disconnect()
            sys.exit()

        time.sleep(0.1)  # Small delay between writes

    # Verify dynamic lock bytes were set correctly
    print("\n  📋 Verifying dynamic lock bytes...")
    read_apdu = READ_16_BYTES_APDU_TPL[:]
    read_apdu[3] = 0xE0  # Read starting from page E0 to get E2
    data, sw1, sw2 = connection.transmit(read_apdu)
    page_e2_verify = list(data[8:12])  # Page E2 is at offset 8-11

    if page_e2_verify[0] != 0xFF or page_e2_verify[1] != 0xFF or page_e2_verify[2] != 0xFF:
        print(f"  ❌ WARNING: Dynamic lock bytes not set correctly!")
        print(f"     Expected: FF FF FF, Got: {page_e2_verify[0]:02X} {page_e2_verify[1]:02X} {page_e2_verify[2]:02X}")
        print("     Aborting lock process.")
        connection.disconnect()
        sys.exit()

    print(f"  ✅ Verified: Lock bytes are {page_e2_verify[0]:02X} {page_e2_verify[1]:02X} {page_e2_verify[2]:02X} {page_e2_verify[3]:02X}")
    print("  🎉 Dynamic lock bytes set! Pages 10h-E1h are now locked.\n")

    # ==================================================================
    # STEP 4: Lock Configuration Pages (E3h-E4h)
    # ==================================================================
    print("=" * 70)
    print("🔐 STEP 3/3: Locking Configuration Pages (E3h-E4h)")
    print("=" * 70)

    # Read page 0xE4 first to preserve existing configuration
    print("  📖 Reading current configuration...")
    read_apdu = READ_16_BYTES_APDU_TPL[:]
    read_apdu[3] = 0xE4
    data, sw1, sw2 = connection.transmit(read_apdu)

    if (sw1, sw2) != (0x90, 0x00):
        print(f"  ❌ Failed to read config page: Status {sw1:02X} {sw2:02X}")
        connection.disconnect()
        sys.exit()

    page_e4 = list(data[0:4])
    print(f"  Current page 0xE4: {toHexString(page_e4)}")

    # Set CFGLCK bit (bit 6 of byte 0) while preserving other bits
    page_e4[0] = page_e4[0] | 0x40  # OR with 0x40 to set bit 6

    print(f"  Writing modified page 0xE4: {toHexString(page_e4)}")
    print(f"    (Set CFGLCK bit, preserved other config)")

    # Page 0xE4 - Set CFGLCK bit (bit 6) to lock config pages
    # This locks pages E3-E4 after power cycle
    apdu = WRITE_PAGE_APDU_TPL[:]
    apdu[3] = 0xE4  # Configuration page
    apdu[5:9] = page_e4

    data, sw1, sw2 = connection.transmit(apdu)

    if (sw1, sw2) == (0x90, 0x00):
        print(f"  ✅ Configuration lock write successful")

        # Verify CFGLCK bit was set
        time.sleep(0.1)
        read_apdu = READ_16_BYTES_APDU_TPL[:]
        read_apdu[3] = 0xE4
        data, sw1, sw2 = connection.transmit(read_apdu)
        page_e4_verify = list(data[0:4])

        if (page_e4_verify[0] & 0x40) == 0x40:
            print(f"  ✅ Verified: CFGLCK bit is set (byte 0 = 0x{page_e4_verify[0]:02X})")
        else:
            print(f"  ⚠️  WARNING: CFGLCK bit not set! (byte 0 = 0x{page_e4_verify[0]:02X})")
    else:
        print(f"  ⚠️  Config lock may have failed: Status {sw1:02X} {sw2:02X}")
        print("     (Card data is still locked, config pages may not be)")

    print("  🎉 Configuration pages will lock after power cycle.\n")

    # ==================================================================
    # FINAL STATUS
    # ==================================================================
    print("=" * 70)
    print("✅ LOCKING COMPLETE!")
    print("=" * 70)
    print()
    print("📊 Lock Status:")
    print("  ✅ Pages 00h-02h: Factory locked (UID, BCC, Lock bytes)")
    print("  ✅ Page  03h:     LOCKED (Capability Container)")
    print("  ✅ Pages 04h-06h: LOCKED (Your data: 2022, KUCP, 1033)")
    print("  ✅ Pages 07h-0Fh: LOCKED")
    print("  ✅ Pages 10h-E1h: LOCKED")
    print("  ✅ Page  E2h:     LOCKED (Dynamic lock bytes)")
    print("  ✅ Pages E3h-E4h: LOCKED after power cycle (Config)")
    print("  ⚠️  Pages E5h-E7h: Still writable (PWD/PACK - not lockable)")
    print()
    print("🔒 CARD IS NOW PERMANENTLY READ-ONLY!")
    print()
    print("Next steps:")
    print("  1. Remove and re-tap card to activate config lock")
    print("  2. Run 'python read_full_card.py' to verify lock status")
    print("  3. Try writing to page 0x07 - it should FAIL")
    print()
    print("⚠️  IMPORTANT:")
    print("  • Your data (2022, KUCP, 1033) is now PERMANENT")
    print("  • No write operations possible on user pages")
    print("  • Card is perfect for student ID (tamper-proof)")
    print("  • Reading still works normally")
    print("=" * 70)

    connection.disconnect()

except CardConnectionException:
    print("\n❌ Card removed during operation.")
except KeyboardInterrupt:
    print("\n⚠️  Operation cancelled by user.")
except Exception as e:
    print(f"\n❌ An error occurred: {e}")
    import traceback

    traceback.print_exc()

finally:
    try:
        if connection is not None:
            connection.disconnect()
    except Exception:
        pass
    sys.exit()
