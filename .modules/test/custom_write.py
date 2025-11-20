import sys
import os
from smartcard.Exceptions import CardConnectionException
from smartcard.System import readers

# APDU to Write 4 bytes to a page
# [Class, INS, P1, P2, Lc, b0, b1, b2, b3]
WRITE_PAGE_APDU_TPL = [0xFF, 0xD6, 0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x00]

def select_reader():
    """Select NFC reader once at startup"""
    r = readers()
    if not r:
        print("   ❌ No readers found.")
        return None
    
    print("\nAvailable readers:")
    for i, reader_name in enumerate(r):
        print(f"  {i+1}: {reader_name}")

    # Ask the user to select one by number
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

def get_card_connection(reader):
    """Establish connection to NFC card using selected reader"""
    try:
        connection = reader.createConnection()
        connection.connect()
        print("💳 Card detected!")
        return connection
    except CardConnectionException:
        print("❌ No card detected. Please place a card on the reader.")
        return None

def get_4_bytes_input(page_name):
    """Get 4 bytes of input from user"""
    while True:
        data = input(f"Enter 4 characters for {page_name}: ").strip()
        if len(data) == 4:
            return [ord(c) for c in data]
        else:
            print("Please enter exactly 4 characters")

def parse_range(range_str):
    """Parse range string like '0001-1134' into start and end numbers"""
    try:
        start_str, end_str = range_str.split('-')
        start_num = int(start_str)
        end_num = int(end_str)
        if start_num > end_num:
            print("Start number must be less than or equal to end number")
            return None, None
        return start_num, end_num
    except ValueError:
        print("Invalid range format. Use format like '0001-1134'")
        return None, None

def number_to_4_bytes(num):
    """Convert number to 4 ASCII bytes (padded with zeros)"""
    num_str = f"{num:04d}"
    return [ord(c) for c in num_str]

def write_to_card(connection, page, bytes_data):
    """Write data to a specific page on the card"""
    apdu = WRITE_PAGE_APDU_TPL[:]
    apdu[3] = page  # Set the page address
    apdu[5:9] = bytes_data  # Set the 4 bytes to write

    char_repr = ''.join(chr(b) for b in bytes_data)
    print(f"📝 Writing to page 0x{page:02X}: {bytes_data} ('{char_repr}')")

    try:
        data, sw1, sw2 = connection.transmit(apdu)
        
        if (sw1, sw2) == (0x90, 0x00):
            print(f"   ✅ Page 0x{page:02X} written successfully!")
            return True
        else:
            print(f"   ❌ Failed to write page 0x{page:02X}. Status: {sw1:02X} {sw2:02X}")
            return False
    except CardConnectionException:
        print("\n❌ Card removed during operation.")
        return False

def main():
    print("\n" + "="*50)
    print("🔄 NFC Card Writer - Interactive Mode")
    print("="*50)
    
    # Step 1: Select reader once at startup
    print("\n📡 Step 1: Select NFC Reader")
    reader = select_reader()
    if not reader:
        return
    
    # Step 2: Get data for pages 0x04 and 0x05 once
    print("\n📝 Step 2: Configure fixed data")
    print("This data will be used for ALL cards in this session:")
    page_04_data = get_4_bytes_input("page 0x04")
    page_05_data = get_4_bytes_input("page 0x05")
    
    page_04_chars = ''.join(chr(b) for b in page_04_data)
    page_05_chars = ''.join(chr(b) for b in page_05_data)
    print(f"   ✅ Page 0x04 data set to: '{page_04_chars}'")
    print(f"   ✅ Page 0x05 data set to: '{page_05_chars}'")
    
    # Main range processing loop
    while True:
        try:
            # Step 3: Get range for page 0x06
            print("\n" + "-"*30)
            print("📝 Enter new range for page 0x06")
            while True:
                range_input = input("Enter range (e.g., 0001-1134): ").strip()
                start_num, end_num = parse_range(range_input)
                if start_num is not None and end_num is not None:
                    break
            
            # Step 4: Process the range
            print(f"\n🔄 Processing range {start_num:04d}-{end_num:04d}")
            print(f"Fixed data: 0x04='{page_04_chars}', 0x05='{page_05_chars}'")
            current_num = start_num
            
            while current_num <= end_num:
                try:
                    # Wait for card tap
                    input(f"\n⏳ Tap card for {current_num:04d} and press Enter...")
                    
                    # Get connection for this card
                    connection = get_card_connection(reader)
                    if not connection:
                        print("Skipping this card...")
                        continue
                    
                    # Write pages 0x04, 0x05, and 0x06
                    success = True
                    
                    # Write page 0x04
                    if not write_to_card(connection, 0x04, page_04_data):
                        success = False
                    
                    # Write page 0x05
                    if success and not write_to_card(connection, 0x05, page_05_data):
                        success = False
                    
                    # Write page 0x06 with current number
                    if success:
                        page_06_data = number_to_4_bytes(current_num)
                        if write_to_card(connection, 0x06, page_06_data):
                            print(f"   🎉 Card {current_num:04d} completed successfully!")
                            current_num += 1
                        else:
                            success = False
                    
                    connection.disconnect()
                    
                    if not success:
                        retry = input("   ❌ Failed to write card. Retry this number? (y/n): ").strip().lower()
                        if retry not in ['y', 'yes']:
                            current_num += 1
                    
                except CardConnectionException:
                    print(f"\n❌ Card connection lost at {current_num:04d}")
                    retry = input("Retry this number? (y/n): ").strip().lower()
                    if retry not in ['y', 'yes']:
                        current_num += 1
                except KeyboardInterrupt:
                    print(f"\n⚠️ Operation cancelled at {current_num:04d}")
                    break
            
            if current_num > end_num:
                print(f"\n✅ Range complete! Processed {start_num:04d}-{end_num:04d}")
            
            # Ask for next range or exit
            print("\n🔄 Range processing complete!")
            next_action = input("Enter 'n' for new range, or any other key to exit: ").strip().lower()
            if next_action != 'n':
                break
                
        except KeyboardInterrupt:
            print("\n⚠️ Operation cancelled by user.")
            break
        except Exception as e:
            print(f"\n❌ An error occurred: {e}")
            continue
    
    print("\n👋 Goodbye!")

if __name__ == "__main__":
    main()

