import os

# Paths
BASE_DIR = "/var/lib/iiitk-nfc/"
DB_DIR = os.path.join(BASE_DIR, "databases")
IMG_DIR = os.path.join(BASE_DIR, "images")
STUDENTS_DB = os.path.join(DB_DIR, "students.db")

# Create dirs if not exist
os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(IMG_DIR, exist_ok=True)

# NFC Constants
STUDENT_DATA_PAGE = 0x04
LOCK_PAGE = 0x28
LOCK_DATA = [0xFF, 0xFF, 0xFF, 0xBD]

# APDU Commands for ACS- ACR122U
CMD_GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]
CMD_DISABLE_BEEP = [0xFF, 0x00, 0x52, 0x00, 0x00]
CMD_BEEP_SUCCESS = [0xFF, 0x00, 0x40, 0x01, 0x04, 0x01, 0x01, 0x02, 0x02]

# Mess Settings
TESTING = True # If True, enables off-time entries as "TEST" and relaxes timing constraints