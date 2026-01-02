import asyncio
import datetime
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import os
import io
import csv

import config
import database
import nfc_handler
from mess_logic import MessManager

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()
nfc_manager = None

# --- NFC Tap Handler ---
async def handle_nfc_tap(message: dict):
    """
    Callback from nfc_handler when a card is tapped.
    Returns the result dict so nfc_handler can decide whether to beep.
    """
    print(f"[DEBUG] handle_nfc_tap received: {message}")
    
    if message.get("type") != "tag":
        print(f"[DEBUG] Ignoring non-tag message type: {message.get('type')}")
        return {"status": "ignored"}

    tag_id = message.get("tag_id")
    if not tag_id:
        print("[DEBUG] No tag_id in message")
        return {"status": "error"}
    
    print(f"[DEBUG] Processing entry for: {tag_id}")
    result = await process_entry(tag_id)
    print(f"[DEBUG] process_entry result: {result}")
    
    print(f"[DEBUG] Broadcasting to {len(manager.active_connections)} clients")
    await manager.broadcast(result)
    print("[DEBUG] Broadcast complete")
    
    return result  # Return so nfc_handler knows if successful


async def process_entry(student_id: str) -> dict:
    """Core mess entry logic."""
    # 1. Identify Student
    student = database.get_student(student_id)
    name = student['NAME'] if student else "Unknown"
    if student_id == "IIITKOTAUSER":
        name = "Guest User"
    
    img_path = f"/api/images/{student_id}.png"
    if student_id == "IIITKOTAUSER": 
        img_path = "/api/images/guest.png"

    # 2. Check Session
    session = MessManager.get_current_session()
    
    if not session:
        return {
            "type": "mess_response",
            "status": "error",
            "message": "No Active Session",
            "student_id": student_id,
            "name": name,
            "image_path": img_path,
            "timestamp": datetime.datetime.now().isoformat()
        }

    # 3. Check Duplicate (Guest users can eat multiple times)
    if student_id != "IIITKOTAUSER" and database.has_eaten(student_id, session):
        return {
            "type": "mess_response",
            "status": "denied",
            "message": f"Already taken {session}",
            "student_id": student_id,
            "name": name,
            "image_path": img_path,
            "session": session,
            "timestamp": datetime.datetime.now().isoformat()
        }

    # 4. Log Entry
    success = database.log_mess_entry(student_id, session)
    
    if success:
        return {
            "type": "mess_response",
            "status": "success",
            "message": f"Enjoy your {session}!",
            "student_id": student_id,
            "name": name,
            "image_path": img_path,
            "session": session,
            "timestamp": datetime.datetime.now().isoformat()
        }
    else:
        return {
            "type": "mess_response",
            "status": "error",
            "message": "Database Error",
            "student_id": student_id,
            "name": name,
            "image_path": img_path,
            "timestamp": datetime.datetime.now().isoformat()
        }

# --- Lifespan (Modern FastAPI pattern) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global nfc_manager
    loop = asyncio.get_running_loop()
    print("Starting Mess NFC Reader Manager...")
    try:
        nfc_manager = nfc_handler.ReaderManager(loop, handle_nfc_tap)
        readers_list = nfc_manager.get_readers()
        if readers_list:
            print(f"Found readers: {readers_list}")
        else:
            print("No NFC readers found.")
    except Exception as e:
        print(f"Error initializing NFC: {e}")
    
    yield
    
    if nfc_manager:
        nfc_manager.stop()
        print("NFC Monitor Stopped.")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Endpoints ---

@app.post("/api/entry/manual")
async def manual_entry(data: dict = Body(...)):
    sid = f"{data['year']}{data['department']}{data['roll_number']}"
    
    # Check if student exists (allow IIITKOTAUSER as guest)
    student = database.get_student(sid)
    if not student and sid != "IIITKOTAUSER":
        return JSONResponse(status_code=404, content={"success": False, "error": "Student not found"})

    result = await process_entry(sid)
    await manager.broadcast(result)
    
    return {"success": True, "data": result}

@app.get("/api/mess/export")
def export_csv(month: str = None):
    data = database.get_mess_entries_csv_data(month_year=month)
    
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=["Timestamp", "Student ID", "Name", "Session"])
    writer.writeheader()
    writer.writerows(data)
    
    filename = f"mess_export_{month if month else datetime.date.today()}.csv"
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response

@app.get("/api/mess/stats")
def get_stats(month: str = None):
    # month format: "YYYY-MM"
    m, y = None, None
    if month:
        try:
            parts = month.split('-')
            y = int(parts[0])
            m = int(parts[1])
        except: 
            pass
    return database.get_mess_stats(month=m, year=y)

@app.get("/api/mess/recent")
def get_recent_entries(limit: int = 30):
    """Get recent mess entries for today's current session."""
    session = MessManager.get_current_session()
    if not session:
        return []
    return database.get_recent_mess_entries(session, limit)

@app.get("/api/mess/session")
def get_session_info():
    return {
        "current_session": MessManager.get_current_session(),
        "timings": MessManager.get_session_times()
    }

@app.get("/api/images/{filename}")
def get_image(filename: str):
    path = os.path.join(config.IMG_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"error": "Not found"})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/")
def serve_ui():
    return FileResponse("index.html")


@app.get("/iiitkota.png")
def serve_ui():
    return FileResponse("iiitkota.png")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)