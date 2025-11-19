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

@app.on_event("startup")
async def startup_event():
    global nfc_manager
    loop = asyncio.get_running_loop()
    # Start NFC Monitor
    print("Starting NFC Reader Manager...")
    try:
        nfc_manager = nfc_handler.ReaderManager(loop, manager.broadcast)
        # Auto-configure first found readers
        r_list = nfc_manager.get_readers()
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
    if nfc_manager:
        nfc_manager.update_config(config_data.get("in_reader"), config_data.get("out_reader"))
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
    
    database.log_entry(direction, sid)
    database.log_system_message(f"Manual {direction.upper()}: {name}", sid)
    
    # Notify UI
    await manager.broadcast({
        "type": "tap",
        "direction": direction,
        "student_id": sid,
        "name": name,
        "image_path": f"/api/images/{sid}.png",
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