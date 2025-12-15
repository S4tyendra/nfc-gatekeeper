#!/usr/bin/env python3
"""
Smart NFC Card Writer
- Auto-selects reader (or asks if multiple)
- Asks for page 0x04 and 0x05 data
- Asks for starting number for page 0x06, then auto-increments
- For each card: write, read back, display, and offer lock option
"""

import sys
import time
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers

# APDU Templates
WRITE_PAGE_APDU_TPL = [0xFF, 0xD6, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00]
READ_16_BYTES_APDU_TPL = [0xFF, 0xB0, 0x00, 0x00, 0x10]

# BEEP_SUCCESS = [0xFF, 0x00, 0x40, 0x01, 0x04, 0x01, 0x01, 0x02, 0x02]  # Optional beep


def select_reader():
    """Select NFC reader - auto-select if only one, ask if multiple"""
    r = readers()
    if not r:
        print("   ❌ No readers found.")
        return None

    if len(r) == 1:
        # Auto-select the only reader
        reader = r[0]
        print(f"   ✅ Auto-selected reader: {reader}")
        return reader

    # Multiple readers - ask user to select
    print("\n📡 Multiple readers found:")
    for i, reader_name in enumerate(r):
        print(f"  {i+1}: {reader_name}")

    while True:
        try:
            prompt = f"Select the reader (1-{len(r)}): "
            choice = input(prompt).strip()
            if not choice:
                choice = "1"
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(r):
                reader = r[choice_idx]
                print(f"   ✅ Selected reader: {reader}")
                return reader
            else:
                print(f"Please enter a number between 1 and {len(r)}")
        except ValueError:
            print("Please enter a valid number")


def get_4_bytes_input(page_name):
    """Get 4 bytes of input from user"""
    while True:
        try:
            if page_name == 'page 0x04':
                data = int(input("Enter 4 characters for Year: (e.g., 2022): ").strip())
            elif page_name == 'page 0x05':
                data = input("Enter 4 characters for Branch Code: (e.g., KUCP): ").strip()
                data = data.upper()
            else:
                data = input(f"{page_name} - Enter 4 characters ID: ").strip()
            if len(str(data)) == 4:
                return [ord(c) for c in str(data)]
            else:
                print("❌ Please enter exactly 4 characters")
        except ValueError:
            print("❌ Please enter a valid Data")


def get_starting_number():
    """Get the starting number for page 0x06"""
    while True:
        try:
            num_str = input("Enter starting number for page 0x06 (e.g., 1001): ").strip()
            num = int(num_str)
            if num < 0 or num > 9999:
                print("❌ Number must be between 0 and 9999")
                continue
            return num
        except ValueError:
            print("❌ Please enter a valid number")


def number_to_4_bytes(num):
    """Convert number to 4 ASCII bytes (padded with zeros)"""
    num_str = f"{num:04d}"
    return [ord(c) for c in num_str]


def wait_for_card(reader):
    """Wait for a card to be placed on the reader"""
    while True:
        try:
            connection = reader.createConnection()
            connection.connect()
            return connection
        except CardConnectionException:
            # No card detected, keep waiting
            time.sleep(0.1)


def write_page(connection, page, bytes_data):
    """Write 4 bytes to a specific page"""
    apdu = WRITE_PAGE_APDU_TPL[:]
    apdu[3] = page
    apdu[5:9] = bytes_data

    try:
        data, sw1, sw2 = connection.transmit(apdu)
        return (sw1, sw2) == (0x90, 0x00)
    except CardConnectionException:
        return False


def read_pages(connection, start_page, num_pages=3):
    """Read multiple pages starting from start_page"""
    apdu = READ_16_BYTES_APDU_TPL[:]
    apdu[3] = start_page

    try:
        data, sw1, sw2 = connection.transmit(apdu)
        if (sw1, sw2) == (0x90, 0x00):
            # Extract the requested pages (4 bytes each)
            pages = []
            for i in range(num_pages):
                page_data = data[i*4:(i+1)*4]
                pages.append(page_data)
            return pages
        return None
    except CardConnectionException:
        return None


def format_page_data(page_data):
    """Format page data as both hex and ASCII"""
    hex_str = ' '.join(f"{b:02X}" for b in page_data)
    ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in page_data)
    return f"{hex_str}  ({ascii_str})"


def lock_card(connection):
    """Lock the card by setting static and dynamic lock bytes"""
    print("\n   🔒 Locking card...")

    # Read page 0x02 first to preserve bytes 0-1
    read_apdu = READ_16_BYTES_APDU_TPL[:]
    read_apdu[3] = 0x00
    data, sw1, sw2 = connection.transmit(read_apdu)

    if (sw1, sw2) != (0x90, 0x00):
        print("   ❌ Failed to read page 0x02")
        return False

    page_02 = list(data[8:12])

    # Lock static bytes (page 0x02, bytes 2-3 = FF FF)
    lock_data = [page_02[0], page_02[1], 0xFF, 0xFF]

    # Write twice for permanence
    for attempt in range(2):
        if not write_page(connection, 0x02, lock_data):
            print(f"   ❌ Static lock write {attempt + 1}/2 failed")
            return False
        time.sleep(0.05)

    print("   ✅ Static lock bytes set (pages 03h-0Fh locked)")

    # Lock dynamic bytes (page 0xE2)
    for attempt in range(2):
        if not write_page(connection, 0xE2, [0xFF, 0xFF, 0xFF, 0x00]):
            print(f"   ❌ Dynamic lock write {attempt + 1}/2 failed")
            return True
        time.sleep(0.05)

    for attempt in range(2):
        if not write_page(connection, 0x28, [0xFF, 0xFF, 0xFF, 0xBD]):
            print(f"   ❌ Dynamic lock write {attempt + 1}/2 failed")
            return True
        time.sleep(0.05)

    print("   ✅ Dynamic lock bytes set (pages 10h-E1h locked)")

    # Lock config pages (page 0xE4 - set CFGLCK bit)
    read_apdu = READ_16_BYTES_APDU_TPL[:]
    read_apdu[3] = 0xE4
    data, sw1, sw2 = connection.transmit(read_apdu)

    if (sw1, sw2) != (0x90, 0x00):
        print("   ⚠️  Failed to read config page (card data still locked)")
        return True  # Data is locked, config lock is optional

    page_e4 = list(data[0:4])
    page_e4[0] = page_e4[0] | 0x40  # Set CFGLCK bit

    if not write_page(connection, 0xE4, page_e4):
        print("   ⚠️  Config lock may have failed (card data still locked)")
        return True

    print("   ✅ Config lock set (will activate after power cycle)")
    print("   🎉 Card is now PERMANENTLY LOCKED!")

    return True


def main():
    print("\n" + "="*60)
    print("🎯 Smart NFC Card Writer")
    print("="*60)

    # Step 1: Select reader
    print("\n📡 Step 1: Select NFC Reader")
    reader = select_reader()
    if not reader:
        return

    # Step 2: Get data for pages 0x04 and 0x05
    print("\n📝 Step 2: Configure fixed data for pages 0x04 and 0x05")
    page_04_data = get_4_bytes_input("page 0x04")
    page_05_data = get_4_bytes_input("page 0x05")

    page_04_str = ''.join(chr(b) for b in page_04_data)
    page_05_str = ''.join(chr(b) for b in page_05_data)
    print(f"   ✅ Page 0x04: '{page_04_str}'")
    print(f"   ✅ Page 0x05: '{page_05_str}'")

    # Step 3: Get starting number for page 0x06
    print("\n📝 Step 3: Configure starting number for page 0x06")
    current_num = get_starting_number()
    print(f"   ✅ Starting from: {current_num:04d}")

    print("\n" + "="*60)
    print("🔄 Ready to process cards!")
    print("="*60)
    print("Instructions:")
    print("  • Tap card when prompted")
    print("  • After write & read, press Enter to LOCK or 'r' to REWRITE")
    print("  • Press Ctrl+C to exit")
    print("="*60)

    # Main processing loop
    while True:
        try:
            # Ask user to tap card
            input(f"\n⏳ Tap card for ID {current_num:04d} and press Enter...")

            print("   Waiting for card...")
            connection = wait_for_card(reader)
            print("   💳 Card detected!")

            # Convert current number to bytes for page 0x06
            page_06_data = number_to_4_bytes(current_num)
            page_06_str = ''.join(chr(b) for b in page_06_data)

            # Write all three pages
            success = True

            print(f"\n   📝 Writing page 0x04: '{page_04_str}'")
            if not write_page(connection, 0x04, page_04_data):
                print("   ❌ Failed to write page 0x04")
                success = False

            if success:
                print(f"   📝 Writing page 0x05: '{page_05_str}'")
                if not write_page(connection, 0x05, page_05_data):
                    print("   ❌ Failed to write page 0x05")
                    success = False

            if success:
                print(f"   📝 Writing page 0x06: '{page_06_str}'")
                if not write_page(connection, 0x06, page_06_data):
                    print("   ❌ Failed to write page 0x06")
                    success = False

            if not success:
                connection.disconnect()
                retry = input("\n   ❌ Write failed. Press Enter to retry same ID, or 'n' to skip: ").strip().lower()
                if retry == 'n':
                    current_num += 1
                continue

            print("   ✅ Write successful!")

            # Read back the data
            print("\n   📖 Reading back data...")
            pages = read_pages(connection, 0x04, 3)

            if pages:
                print("\n   📊 Card Data:")
                print(f"      Page 0x04: {format_page_data(pages[0])}")
                print(f"      Page 0x05: {format_page_data(pages[1])}")
                print(f"      Page 0x06: {format_page_data(pages[2])}")

                # Extract full ID
                full_id = ''.join(chr(b) for page in pages for b in page if 32 <= b <= 126)
                print(f"\n   🎯 Full ID: {full_id}")
            else:
                print("   ⚠️  Failed to read back data")

            # Ask to lock or rewrite
            print("\n   🔐 Lock this card?")
            action = input("      Press Enter to LOCK, 'r' to REWRITE, 'n' to SKIP: ").strip().lower()

            if action == 'r':
                # Rewrite - stay on same number
                print("   🔄 Will rewrite same ID on next card...")
                connection.disconnect()
                continue
            elif action == 'n':
                # Skip locking, move to next
                print("   ⏭️  Skipped locking. Moving to next ID...")
                connection.disconnect()
                current_num += 1
                continue
            else:
                # Lock the card (Enter or anything else)
                lock_success = lock_card(connection)

                if lock_success:
                    print(f"\n   ✅ Card {current_num:04d} completed and locked!")
                    current_num += 1
                else:
                    print(f"\n   ⚠️  Card {current_num:04d} written but lock may have failed")
                    retry = 'n'
                    if retry != 'y':
                        current_num += 1

            connection.disconnect()

        except CardConnectionException:
            print("\n   ❌ Card removed during operation")
            retry = input("   Press Enter to retry same ID, or 'n' to skip: ").strip().lower()
            if retry == 'n':
                current_num += 1
        except KeyboardInterrupt:
            print(f"\n\n⚠️  Stopped at ID {current_num:04d}")
            print("👋 Goodbye!")
            break
        except Exception as e:
            print(f"\n   ❌ Error: {e}")
            retry = input("   Press Enter to retry same ID, or 'n' to skip: ").strip().lower()
            if retry == 'n':
                current_num += 1


if __name__ == "__main__":
    main()

