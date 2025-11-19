import asyncio
import datetime
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List
import os

import config
import database
import nfc_handler

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- WebSocket Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()
nfc_manager = None

# --- Lifecycle Events ---

import json

CONFIG_FILE = os.path.join(config.DB_DIR, "reader_config.json")

def load_saved_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return None
    return None

def save_reader_config(config_data):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config_data, f)
    except Exception as e:
        print(f"Error saving config: {e}")

@app.on_event("startup")
async def startup_event():
    global nfc_manager
    loop = asyncio.get_running_loop()
    # Start NFC Monitor
    print("Starting NFC Reader Manager...")
    try:
        nfc_manager = nfc_handler.ReaderManager(loop, manager.broadcast)
        
        # Try to load saved config
        saved_config = load_saved_config()
        r_list = nfc_manager.get_readers()
        
        config_applied = False
        if saved_config:
            in_r = saved_config.get("in_reader")
            out_r = saved_config.get("out_reader")
            
            # Prevent duplicate assignment
            if in_r and out_r and in_r == out_r:
                out_r = None # Default to clearing OUT

            # Verify readers still exist
            if (not in_r or in_r in r_list) and (not out_r or out_r in r_list):
                nfc_manager.update_config(in_r, out_r)
                print(f"Loaded Config: IN={in_r}, OUT={out_r}")
                config_applied = True
        
        if not config_applied:
            # Auto-configure first found readers
            if len(r_list) >= 2:
                nfc_manager.update_config(r_list[0], r_list[1])
                print(f"Auto-Config: IN={r_list[0]}, OUT={r_list[1]}")
            elif len(r_list) == 1:
                nfc_manager.update_config(r_list[0], None)
                print(f"Auto-Config: IN={r_list[0]}")
                
    except Exception as e:
        print(f"Error initializing NFC: {e}")

@app.on_event("shutdown")
def shutdown_event():
    if nfc_manager:
        nfc_manager.stop()
        print("NFC Monitor Stopped.")

# --- API Endpoints ---
@app.get("/api/readers")
def get_readers():
    if not nfc_manager:
        return {"readers": []}
    return {"readers": [{"name": r} for r in nfc_manager.get_readers()]}

# --- ADD THIS ENDPOINT ---
@app.get("/api/readers/config")
def get_reader_config():
    if not nfc_manager:
        return {"in_reader": None, "out_reader": None}
    return nfc_manager.get_config()
# -------------------------

@app.post("/api/readers/config")
def set_config(config_data: dict = Body(...)):
    in_r = config_data.get("in_reader")
    out_r = config_data.get("out_reader")
    
    # Prevent duplicate assignment
    if in_r and out_r and in_r == out_r:
        return JSONResponse(status_code=400, content={"error": "Cannot assign same reader to both roles"})

    if nfc_manager:
        nfc_manager.update_config(in_r, out_r)
        save_reader_config(config_data)
    return {"success": True}

@app.get("/api/entries/recent")
def get_recent(direction: str, limit: int = 30):
    return {"entries": database.get_recent_entries(direction, limit)}

@app.get("/api/images/{filename}")
def get_image(filename: str):
    path = os.path.join(config.IMG_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse(status_code=404, content={"error": "Not found"})

@app.post("/api/entry/manual")
async def manual_entry(data: dict = Body(...)):
    sid = f"{data['year']}{data['department']}{data['roll_number']}"
    direction = data['direction']
    
    student = database.get_student(sid)
    name = student['NAME'] if student else "Unknown"
    if sid == "IIITKOTAUSER":
        name = "Guest User"
    
    database.log_entry(direction, sid)
    database.log_system_message(f"Manual {direction.upper()}: {name}", sid)
    
    # Determine Image Path
    img_path = f"/api/images/{sid}.png"
    if sid == "IIITKOTAUSER":
        img_path = "/api/images/guest.png"

    # Notify UI
    await manager.broadcast({
        "type": "tap",
        "direction": direction,
        "student_id": sid,
        "name": name,
        "image_path": img_path,
        "timestamp": datetime.datetime.now().isoformat(),
        "status": "success",
        "message": "Manual Entry"
    })
    
    return {"success": True, "student_id": sid}

# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() # Keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Serve UI
@app.get("/")
def serve_ui():
    return FileResponse("index.html")

if __name__ == "__main__":
    # Run with: python main.py
    # Access at http://localhost:8080
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)