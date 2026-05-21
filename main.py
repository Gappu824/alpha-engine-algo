import os
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from kiteconnect import KiteConnect

# Import your quantitative engine
from alpha_engine import AlphaEngine

# Load environment variables
load_dotenv()

# --- SYSTEM CONFIGURATION ---
MAX_RISK = float(os.getenv("MAX_RISK_PER_TRADE", 5000))
MIN_RR = float(os.getenv("MIN_RR_RATIO", 1.5))

kite_api_key = os.getenv("KITE_API_KEY")
kite_api_secret = os.getenv("KITE_API_SECRET")

# Initialize Engine with NO Kite client initially (Runs in Mock Data mode on boot)
engine = AlphaEngine(max_risk_capital=MAX_RISK, min_rr=MIN_RR, kite_client=None)

# --- FASTAPI SERVER SETUP ---
app = FastAPI(title="Alpha Engine Algo Desk")
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- WEBSOCKET CONNECTION MANAGER ---
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

# --- ONE-CLICK AUTHENTICATION ROUTES ---
@app.get("/login")
async def login_zerodha():
    """Redirects the user to the Zerodha Login Page"""
    if not kite_api_key:
        return HTMLResponse("<h1>Error: KITE_API_KEY not found in environment variables.</h1>")
    login_url = f"https://kite.trade/connect/login?api_key={kite_api_key}&v=3"
    return RedirectResponse(url=login_url)

@app.get("/api/callback")
async def kite_callback(request_token: str):
    """Zerodha redirects here after login. We generate the session and arm the system."""
    try:
        # Initialize a temporary client to exchange the token
        temp_kite = KiteConnect(api_key=kite_api_key)
        data = temp_kite.generate_session(request_token, api_secret=kite_api_secret)
        access_token = data["access_token"]
        
        # Lock the access token into the client
        temp_kite.set_access_token(access_token)
        
        # Inject the live client directly into the running Alpha Engine
        engine.kite = temp_kite
        print("SYSTEM: Live KiteConnect API Initialized Successfully.")
        
        # Redirect back to the trading dashboard with a success flag
        return RedirectResponse(url="/?status=connected")
        
    except Exception as e:
        print(f"SYSTEM: Auth Failed - {e}")
        return HTMLResponse(f"<h1>Zerodha Auth Failed</h1><p>{str(e)}</p>")

# --- CORE TRADING ROUTES ---
@app.get("/")
async def get_dashboard():
    """Serves the front-end terminal UI"""
    with open("static/index.html", "r") as file:
        html_content = file.read()
    return HTMLResponse(html_content)

@app.post("/api/signal")
async def receive_signal(request: Request):
    """Endpoint to receive trade signals via POST and process through the Engine."""
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
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)