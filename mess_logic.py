import datetime
try:
    from config import TESTING
except ImportError:
    TESTING = False

class MessManager:
    # Timings: 7:30-9:30, 12:00-14:30, 17:00-18:00, 19:30-21:30
    # +30 mins buffer for each (End time extended by 30 mins)
    SESSIONS = {
        "BREAKFAST": {"start": (7, 30), "end": (10, 0)}, # 9:30 + 30m
        "LUNCH": {"start": (12, 0), "end": (15, 0)},     # 14:30 + 30m
        "SNACKS": {"start": (17, 0), "end": (18, 30)},   # 18:00 + 30m
        "DINNER": {"start": (19, 30), "end": (22, 0)},   # 21:30 + 30m
    }

    @staticmethod
    def get_current_session():
        now = datetime.datetime.now()
        current_time = now.time()
        
        # Check standard sessions
        for name, timing in MessManager.SESSIONS.items():
            start_time = datetime.time(*timing["start"])
            end_time = datetime.time(*timing["end"])
            
            if start_time <= current_time <= end_time:
                return name
        
        # If no session is active and TESTING is True, return 'TEST'
        if TESTING:
            return "TEST"
            
        return None

    @staticmethod
    def get_session_times():
        return MessManager.SESSIONS
