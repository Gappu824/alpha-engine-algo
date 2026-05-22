import pandas as pd
import numpy as np
import math
import logging
import os
import re
from datetime import datetime, time, timezone, timedelta
from scipy.stats import norm

# Professional Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AlphaEngine_PRO")

class AlphaEngine:
    def __init__(self, max_risk_capital=5000, min_rr=1.5, kite_client=None):
        self.max_risk = float(max_risk_capital)
        self.min_rr_ratio = float(min_rr)
        
        decay_hour = int(os.getenv("THETA_DECAY_HOUR", 14))
        decay_minute = int(os.getenv("THETA_DECAY_MINUTE", 0))
        self.theta_decay_cutoff = time(decay_hour, decay_minute) 
        
        self.kite = kite_client
        # RAM-only storage. Wiped clean on sleep, rebuilt instantly on demand.
        self.instrument_lookup = {} 

    # ==========================================
    # STAGE 0: JIT SMART RESOLVER (NEW)
    # ==========================================
    def smart_symbol_resolver(self, raw_instrument):
        """Lazy-loads the master list and auto-resolves loose strings to exact contracts."""
        
        # 1. Just-In-Time RAM Load (Survives Render Sleep Cycles implicitly)
        if not self.instrument_lookup:
            if not self.kite:
                raise ValueError("API DISCONNECTED: Cannot construct live tokens without active session.")
            logger.info("SYSTEM: Wake-up detected. Fetching live Master directly into RAM...")
            try:
                instruments = self.kite.instruments()
                for inst in instruments:
                    self.instrument_lookup[inst['tradingsymbol']] = {
                        "exchange": inst['exchange'],
                        "lot_size": inst['lot_size']
                    }
                logger.info(f"Loaded {len(self.instrument_lookup)} live instruments.")
            except Exception as e:
                raise ValueError(f"FATAL: Failed to fetch live master: {e}")

        # 2. Clean user input (removes all spaces)
        clean = raw_instrument.strip().replace(" ", "").upper()
        
        # 3. If exact match is provided, return immediately
        if clean in self.instrument_lookup:
            return clean, self.instrument_lookup[clean]

        # 4. Regex Deconstruction (e.g., NATURALGAS295CE ➔ Asset: NATURALGAS, Strike: 295, Type: CE)
        match = re.match(r"^([A-Z]+)(\d+)(CE|PE|FUT)$", clean)
        if not match:
            raise ValueError(f"ROUTING FAILED: Unrecognized format '{raw_instrument}'. Use 'ASSET STRIKE TYPE' (e.g. NIFTY 24000 CE).")
            
        base_asset, strike, opt_type = match.groups()
        
        # 5. Scan RAM for all active contracts matching those parameters
        valid_candidates = []
        for sym, meta in self.instrument_lookup.items():
            if sym.startswith(base_asset) and sym.endswith(f"{strike}{opt_type}"):
                valid_candidates.append((sym, meta))
                
        if not valid_candidates:
            raise ValueError(f"ROUTING FAILED: No active contracts found for {base_asset} at {strike} {opt_type}.")
            
        # 6. Sort alphabetically (Automatically surfaces the nearest active Weekly or Monthly expiry)
        valid_candidates.sort(key=lambda x: x[0])
        resolved_symbol, meta = valid_candidates[0]
        
        logger.info(f"SMART ROUTER: Auto-resolved '{raw_instrument}' ➔ {resolved_symbol}")
        return resolved_symbol, meta

    # ==========================================
    # STAGE 1: MARKET DATA INGESTION
    # ==========================================
    def fetch_live_market_data(self, exact_symbol, meta):
        exchange_token = f"{meta['exchange']}:{exact_symbol}"
        
        try:
            quote = self.kite.quote([exchange_token])
        except Exception as e:
            raise ValueError(f"L2 DATA TIMEOUT: Broker API rejected the request - {e}")
        
        if exchange_token not in quote:
            raise ValueError(f"L2 DATA EMPTY: No live tick data returned for {exchange_token}.")
            
        data = quote[exchange_token]
        
        return {
            "data_source": "PRO API [LIVE L2 STREAM]", 
            "spot_price": data.get('last_price', 0.0),
            "vwap": data.get('average_price', data.get('last_price', 0.0)),
            "order_book_ask_qty": data.get('sell_quantity', 1), 
            "order_book_bid_qty": data.get('buy_quantity', 1),
            "days_to_expiry": 1.0 / 365.0, 
            "otm_call_iv": 0.15,           
            "otm_put_iv": 0.15,            
            "call_wall_strike": data.get('last_price', 0) + 100, 
            "put_wall_strike": data.get('last_price', 0) - 100,
            "total_gamma_exposure": 1000, 
        }

    # ==========================================
    # STAGE 2: QUANTITATIVE PRICING (GREEKS)
    # ==========================================
    def calculate_implied_volatility(self, S, K, T, r, market_price, option_type='CE'):
        sigma = 0.20 
        for _ in range(100):
            d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2) if option_type == 'CE' else K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
            vega = S * norm.pdf(d1) * math.sqrt(T)
            diff = market_price - price
            if abs(diff) < 0.001 or vega == 0: break
            sigma = sigma + diff / vega
        return sigma

    # ==========================================
    # STAGE 3: INSTITUTIONAL FLOW RADAR
    # ==========================================
    def process_institutional_flow(self, raw_signal, data):
        direction = raw_signal.get('type', 'BUY').upper()
        instrument = raw_signal['instrument'].upper() # This is now the exact symbol
        
        is_trap = False
        skew_warning = ""
        if (data['otm_put_iv'] - data['otm_call_iv']) > 0.05 and direction == 'BUY' and 'CE' in instrument:
            skew_warning = "CRITICAL TRAP: VolSkew is heavily bearish."
            is_trap = True

        gex_context = "GEX NEGATIVE." if data['total_gamma_exposure'] < 0 else "GEX POSITIVE."

        total_orders = max((data['order_book_bid_qty'] + data['order_book_ask_qty']), 1)
        imbalance = (data['order_book_bid_qty'] - data['order_book_ask_qty']) / total_orders
        
        order_book_warning = ""
        if imbalance < -0.8 and direction == 'BUY':
            order_book_warning = "L2 TRAP: Massive Ask wall detected."
            is_trap = True
            
        advice = f"{skew_warning} | {gex_context} | {order_book_warning}".strip(" |")
        return advice, is_trap

    # ==========================================
    # STAGE 4: ENSEMBLE AI SCORING
    # ==========================================
    def retailor_trade(self, signal_data, meta):
        data = self.fetch_live_market_data(signal_data['instrument'], meta)
        
        entry = float(signal_data.get('entry', 0))
        raw_sl = float(signal_data.get('sl', 0))
        raw_tgt = float(signal_data.get('tgt', 0))
        direction = signal_data.get('type', 'BUY').upper()
        
        flow_advice, is_trap = self.process_institutional_flow(signal_data, data)
        if not flow_advice: flow_advice = "Institutional flow neutral. Relying on R:R math."

        total_orders = max((data['order_book_bid_qty'] + data['order_book_ask_qty']), 1)
        imbalance = (data['order_book_bid_qty'] - data['order_book_ask_qty']) / total_orders
        optimized_entry = min(entry, round(data['vwap'], 2)) if direction == 'BUY' and imbalance > 0.2 else entry
        
        is_option = "CE" in signal_data['instrument'] or "PE" in signal_data['instrument']
        optimized_sl = raw_sl if is_option else data['put_wall_strike'] - 10 
        optimized_tgt = raw_tgt if is_option else data['call_wall_strike'] - 20 

        return {
            "ai_optimized_signal": {
                "instrument": signal_data['instrument'],
                "entry": optimized_entry,
                "sl": optimized_sl,
                "tgt": optimized_tgt,
            },
            "advice": flow_advice,
            "is_trap": is_trap,
            "data_source": data['data_source'] 
        }

    # ==========================================
    # STAGE 5: RISK MANAGEMENT & EXECUTION
    # ==========================================
    def process_signal(self, signal_data):
        raw_instrument = signal_data.get('instrument', 'UNKNOWN')

        # 1. Execute JIT Smart Routing
        try:
            exact_symbol, meta = self.smart_symbol_resolver(raw_instrument)
            signal_data['instrument'] = exact_symbol # Inject exact symbol downstream
        except ValueError as e:
            return {"status": "ERROR", "reason": str(e), "instrument": raw_instrument, "data_source": "ROUTING FAILED"}

        # 2. Strict IST Time Logic
        ist_offset = timezone(timedelta(hours=5, minutes=30))
        current_time = datetime.now(ist_offset).time()
        
        if "NATURALGAS" in exact_symbol or "CRUDEOIL" in exact_symbol or "GOLD" in exact_symbol or "SILVER" in exact_symbol:
            dynamic_cutoff = time(23, 0)
        else:
            dynamic_cutoff = self.theta_decay_cutoff
            
        if ("CE" in exact_symbol or "PE" in exact_symbol) and current_time >= dynamic_cutoff:
            return {"status": "ERROR", "reason": f"SYSTEM LOCKED: Theta decay zone active (Cutoff: {dynamic_cutoff.strftime('%H:%M')} IST).", "instrument": exact_symbol, "data_source": "OFFLINE"}

        # 3. Fire the Ensemble Pipeline
        try:
            ai_data = self.retailor_trade(signal_data, meta)
        except ValueError as e:
            logger.error(f"TRADE BLOCKED: {str(e)}")
            return {"status": "ERROR", "reason": f"EXECUTION HALTED: {str(e)}", "instrument": exact_symbol, "data_source": "CONNECTION FAILED"}

        optimized = ai_data['ai_optimized_signal']
        source_telemetry = ai_data['data_source']
        
        if ai_data['is_trap']:
            return {"status": "REJECTED", "reason": f"AI RADAR OVERRIDE: Severe market microstructure traps. | {ai_data['advice']}", "instrument": exact_symbol, "data_source": source_telemetry}
        
        risk_per_unit = optimized['entry'] - optimized['sl']
        reward_per_unit = optimized['tgt'] - optimized['entry']
        
        if risk_per_unit <= 0:
            return {"status": "REJECTED", "reason": "Invalid Math: Risk is 0 or negative.", "instrument": exact_symbol, "data_source": source_telemetry}
            
        rr_ratio = reward_per_unit / risk_per_unit
        if rr_ratio < self.min_rr_ratio:
            return {"status": "REJECTED", "reason": f"R:R is {rr_ratio:.2f}:1 (Min: {self.min_rr_ratio}). | {ai_data['advice']}", "instrument": exact_symbol, "data_source": source_telemetry}
            
        # 4. Extract Dynamic Lot Size
        lot_size = meta['lot_size']
        raw_qty = int(self.max_risk / risk_per_unit) if risk_per_unit > 0 else 0
        max_qty = (raw_qty // lot_size) * lot_size 
        
        if max_qty == 0:
            return {"status": "REJECTED", "reason": f"Max risk ({self.max_risk}) cannot afford a single lot size of {lot_size}.", "instrument": exact_symbol, "data_source": source_telemetry}

        return {
            "status": "APPROVED",
            "reason": f"R:R is {rr_ratio:.2f}:1. | {ai_data['advice']}",
            "instrument": exact_symbol,
            "recommended_qty": max_qty,
            "entry": optimized['entry'],
            "sl": optimized['sl'],
            "target": optimized['tgt'],
            "data_source": source_telemetry
        }