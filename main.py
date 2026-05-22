import os
import json
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from kiteconnect import KiteConnect

from alpha_engine import AlphaEngine

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API_Main")

load_dotenv()

MAX_RISK = float(os.getenv("MAX_RISK_PER_TRADE", 5000))
MIN_RR = float(os.getenv("MIN_RR_RATIO", 1.5))
kite_api_key = os.getenv("KITE_API_KEY")
kite_api_secret = os.getenv("KITE_API_SECRET")

# Initialize Engine with NO Kite client initially
engine = AlphaEngine(max_risk_capital=MAX_RISK, min_rr=MIN_RR, kite_client=None)

app = FastAPI(title="Alpha Engine Algo Desk")
app.mount("/static", StaticFiles(directory="static"), name="static")

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

# --- 1. NEW TAB LOGIN ROUTE ---
@app.get("/login")
async def login_zerodha():
    if not kite_api_key:
        return HTMLResponse("<h1>Error: KITE_API_KEY not found in environment.</h1>")
    login_url = f"https://kite.trade/connect/login?api_key={kite_api_key}&v=3"
    return RedirectResponse(url=login_url)

# --- 2. DISPLAY TOKEN ROUTE ---
@app.get("/api/callback")
async def kite_callback(request_token: str):
    html_content = f"""
    <html>
        <body style="background: #0d1117; color: #c9d1d9; font-family: monospace; padding: 50px; text-align: center;">
            <h2 style="color: #3fb950;">Login Successful</h2>
            <p>Copy this Request Token and paste it into your Alpha Engine dashboard:</p>
            <div style="background: #000; padding: 20px; border: 1px solid #30363d; display: inline-block; font-size: 24px; font-weight: bold; user-select: all; color: #58a6ff;">
                {request_token}
            </div>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# --- 3. CONNECT BROKER ROUTE ---
@app.post("/api/connect")
async def connect_broker(request: Request):
    try:
        data = await request.json()
        req_token = data.get("request_token")
        
        temp_kite = KiteConnect(api_key=kite_api_key)
        session_data = temp_kite.generate_session(req_token, api_secret=kite_api_secret)
        access_token = session_data["access_token"]
        
        temp_kite.set_access_token(access_token)
        
        # Inject live client into the engine
        engine.kite = temp_kite
        logger.info("SYSTEM: Live KiteConnect API Initialized Successfully.")
        
        return {"status": "success", "access_token": access_token}
    except Exception as e:
        logger.error(f"Auth Failed: {e}")
        return {"status": "error", "message": str(e)}

# --- CORE TRADING ROUTES ---
@app.get("/")
async def get_dashboard():
    with open("static/index.html", "r") as file:
        return HTMLResponse(file.read())

@app.post("/api/signal")
async def receive_signal(request: Request):
    signal_data = await request.json()
    logger.info(f"Received Signal: {signal_data['instrument']}")
    
    engine_decision = engine.process_signal(signal_data)
    
    await manager.broadcast(json.dumps(engine_decision))
    return engine_decision

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)