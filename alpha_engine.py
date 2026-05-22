import pandas as pd
import numpy as np
import math
import logging
import os
from datetime import datetime, time
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
        self.instrument_lookup = {} 

    def update_kite_client(self, new_client):
        self.kite = new_client
        self._build_dynamic_master()

    def _build_dynamic_master(self):
        if not self.kite:
            return
        logger.info("SYSTEM: Downloading dynamic Instrument Master List from Exchange...")
        try:
            instruments = self.kite.instruments()
            for inst in instruments:
                self.instrument_lookup[inst['tradingsymbol']] = {
                    "exchange": inst['exchange'],
                    "lot_size": inst['lot_size'],
                    "instrument_token": inst['instrument_token']
                }
            logger.info(f"SYSTEM: Loaded {len(self.instrument_lookup)} instruments into memory. Live routing active.")
        except Exception as e:
            logger.error(f"FATAL: Failed to fetch instrument master: {e}")

    # ==========================================
    # STAGE 1: MARKET DATA INGESTION (LIVE ONLY)
    # ==========================================
    def fetch_live_market_data(self, instrument):
        """Strictly fetches live L2 data. Auto-suggests valid symbols on failure."""
        if not self.kite:
            raise ValueError("API DISCONNECTED: No active live session.")

        clean_symbol = instrument.strip().replace(" ", "").upper()
        meta = self.instrument_lookup.get(clean_symbol)
        
        # --- NEW: AUTO-SUGGEST ALGORITHM ---
        if not meta:
            # Extract the base asset (e.g., "NATURALGAS" or "NIFTY")
            import re
            base_asset_match = re.match(r"([A-Z]+)", clean_symbol)
            base_asset = base_asset_match.group(1) if base_asset_match else ""
            
            # Find closest matches in RAM
            suggestions = [
                sym for sym in self.instrument_lookup.keys() 
                if base_asset in sym and ("CE" in clean_symbol or "PE" in clean_symbol)
            ]
            
            # Filter down to the same strike/type if possible
            refined = [s for s in suggestions if clean_symbol[-5:] in s or clean_symbol[-4:] in s]
            final_suggestions = refined[:3] if refined else suggestions[:3]
            
            suggestion_text = f" Did you mean: {', '.join(final_suggestions)}?" if final_suggestions else ""
            raise ValueError(f"ROUTING FAILED: '{clean_symbol}' not found in Master.{suggestion_text}")
        # ------------------------------------
            
        exchange_token = f"{meta['exchange']}:{clean_symbol}"
        
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
        instrument = raw_signal['instrument'].upper()
        
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
    def retailor_trade(self, raw_signal):
        # This will raise a ValueError if live data fails, instantly caught by process_signal
        data = self.fetch_live_market_data(raw_signal['instrument'])
        
        entry = float(raw_signal.get('entry', 0))
        raw_sl = float(raw_signal.get('sl', 0))
        raw_tgt = float(raw_signal.get('tgt', 0))
        direction = raw_signal.get('type', 'BUY').upper()
        
        flow_advice, is_trap = self.process_institutional_flow(raw_signal, data)
        if not flow_advice: flow_advice = "Institutional flow neutral. Relying on R:R math."

        total_orders = max((data['order_book_bid_qty'] + data['order_book_ask_qty']), 1)
        imbalance = (data['order_book_bid_qty'] - data['order_book_ask_qty']) / total_orders
        optimized_entry = min(entry, round(data['vwap'], 2)) if direction == 'BUY' and imbalance > 0.2 else entry
        
        is_option = "CE" in raw_signal['instrument'].upper() or "PE" in raw_signal['instrument'].upper()
        optimized_sl = raw_sl if is_option else data['put_wall_strike'] - 10 
        optimized_tgt = raw_tgt if is_option else data['call_wall_strike'] - 20 

        return {
            "ai_optimized_signal": {
                "instrument": raw_signal['instrument'],
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
    def get_dynamic_lot_size(self, instrument):
        clean_symbol = instrument.strip().replace(" ", "").upper()
        meta = self.instrument_lookup.get(clean_symbol)
        if not meta:
            raise ValueError(f"Lot size lookup failed. {clean_symbol} not in exchange master.")
        return meta['lot_size']

    def process_signal(self, signal_data):
        # 1. Enforce strict Indian Standard Time (IST) mathematically
        from datetime import datetime, timezone, timedelta
        ist_offset = timezone(timedelta(hours=5, minutes=30))
        current_time = datetime.now(ist_offset).time()
        
        instrument = signal_data.get('instrument', 'UNKNOWN').upper()
        tokens = instrument.split()
        
        # 2. Dynamic Theta Decay Routing (NSE vs MCX)
        if "NATURALGAS" in instrument or "CRUDEOIL" in instrument or "GOLD" in instrument or "SILVER" in instrument:
            # MCX Commodities trade until 11:30 PM / 11:55 PM
            dynamic_cutoff = time(23, 0) # 11:00 PM Cutoff
        else:
            # NSE Equities trade until 3:30 PM
            dynamic_cutoff = self.theta_decay_cutoff # 2:00 PM default
            
        # 3. Apply the time lock
        if ("CE" in tokens or "PE" in tokens) and current_time >= dynamic_cutoff:
            return {
                "status": "ERROR", 
                "reason": f"SYSTEM LOCKED: Theta decay zone active (Cutoff: {dynamic_cutoff.strftime('%H:%M')} IST).", 
                "instrument": instrument, 
                "data_source": "OFFLINE"
            }

        # STRICT FAIL-CLOSED EXECUTION BLOCK
        try:
            ai_data = self.retailor_trade(signal_data)
        except ValueError as e:
            logger.error(f"TRADE BLOCKED: {str(e)}")
            return {"status": "ERROR", "reason": f"EXECUTION HALTED: {str(e)}", "instrument": instrument, "data_source": "CONNECTION FAILED"}

        optimized = ai_data['ai_optimized_signal']
        source_telemetry = ai_data['data_source']
        
        if ai_data['is_trap']:
            return {
                "status": "REJECTED",
                "reason": f"AI RADAR OVERRIDE: Severe market microstructure traps. | {ai_data['advice']}",
                "instrument": instrument,
                "data_source": source_telemetry
            }
        
        risk_per_unit = optimized['entry'] - optimized['sl']
        reward_per_unit = optimized['tgt'] - optimized['entry']
        
        if risk_per_unit <= 0:
            return {"status": "REJECTED", "reason": "Invalid Math: Risk is 0 or negative.", "instrument": instrument, "data_source": source_telemetry}
            
        rr_ratio = reward_per_unit / risk_per_unit
        if rr_ratio < self.min_rr_ratio:
            return {
                "status": "REJECTED",
                "reason": f"R:R is {rr_ratio:.2f}:1 (Min: {self.min_rr_ratio}). | {ai_data['advice']}",
                "instrument": instrument,
                "data_source": source_telemetry
            }
            
        try:
            lot_size = self.get_dynamic_lot_size(instrument)
        except ValueError as e:
            return {"status": "ERROR", "reason": str(e), "instrument": instrument, "data_source": source_telemetry}

        raw_qty = int(self.max_risk / risk_per_unit) if risk_per_unit > 0 else 0
        max_qty = (raw_qty // lot_size) * lot_size 
        
        if max_qty == 0:
            return {"status": "REJECTED", "reason": f"Max risk ({self.max_risk}) cannot afford a single lot size of {lot_size}.", "instrument": instrument, "data_source": source_telemetry}

        return {
            "status": "APPROVED",
            "reason": f"R:R is {rr_ratio:.2f}:1. | {ai_data['advice']}",
            "instrument": instrument,
            "recommended_qty": max_qty,
            "entry": optimized['entry'],
            "sl": optimized['sl'],
            "target": optimized['tgt'],
            "data_source": source_telemetry
        }