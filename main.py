import os
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from alpha_engine import AlphaEngine

load_dotenv()

# Initialize Engine with env variables
MAX_RISK = float(os.getenv("MAX_RISK_PER_TRADE", 5000))
MIN_RR = float(os.getenv("MIN_RR_RATIO", 1.5))
engine = AlphaEngine(max_risk_capital=MAX_RISK, min_rr=MIN_RR)

app = FastAPI(title="Alpha Engine Algo Desk")

# Mount static folder for frontend deployment
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory store for connected WebSocket clients (Frontend UI)
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.get("/")
async def get_dashboard():
    with open("static/index.html", "r") as file:
        html_content = file.read()
    return HTMLResponse(html_content)

@app.post("/api/signal")
async def receive_signal(request: Request):
    """
    Endpoint to receive trade signals via POST.
    Expected JSON: {"instrument": "NIFTY 23600 CE", "entry": 165, "sl": 150, "tgt": 200}
    """
    signal_data = await request.json()
    
    # Process through the Quant Engine
    engine_decision = engine.process_signal(signal_data)
    
    # Broadcast decision to the live dashboard
    await manager.broadcast(json.dumps(engine_decision))
    
    return engine_decision

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time frontend terminal updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)