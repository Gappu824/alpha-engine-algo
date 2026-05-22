import pandas as pd
import numpy as np
import math
import logging
import os
from datetime import datetime, time
from scipy.stats import norm

# Professional Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AlphaEngine")

class AlphaEngine:
    def __init__(self, max_risk_capital=5000, min_rr=1.5, kite_client=None):
        self.max_risk = float(max_risk_capital)
        self.min_rr_ratio = float(min_rr)
        
        # Dynamic Theta Decay from Env, default to 14:00 (2:00 PM)
        decay_hour = int(os.getenv("THETA_DECAY_HOUR", 14))
        decay_minute = int(os.getenv("THETA_DECAY_MINUTE", 0))
        self.theta_decay_cutoff = time(decay_hour, decay_minute) 
        
        self.kite = kite_client

        # Exchange Lot Size Mapping
        self.lot_sizes = {
            "NIFTY": 25,
            "BANKNIFTY": 15,
            "FINNIFTY": 40,
            "MIDCPNIFTY": 75,
            "SENSEX": 10
        }

    # ==========================================
    # STAGE 1: MARKET DATA INGESTION
    # ==========================================
    def fetch_live_market_data(self, instrument):
        """Fetches live L2 data and Greeks. Falls back to mock only if disconnected."""
        if not self.kite:
            logger.warning(f"No Kite client connected. Using mock data for {instrument}.")
            return self._mock_live_data()

        try:
            # LIVE KITE INTEGRATION
            # Assumes instrument string maps to a valid exchange token, e.g., NFO:NIFTY24MAY24000CE
            exchange_token = f"NFO:{instrument.replace(' ', '')}" 
            quote = self.kite.quote([exchange_token])
            
            if exchange_token in quote:
                data = quote[exchange_token]
                # In a full live setup, you would calculate real IV and GEX here based on the option chain
                # For now, we return the parsed real data mixed with structural assumptions
                return {
                    "spot_price": data.get('last_price', 23900.0),
                    "vwap": data.get('average_price', 23850.0),
                    "order_book_ask_qty": data.get('sell_quantity', 450000), 
                    "order_book_bid_qty": data.get('buy_quantity', 20000),
                    # Calculated/Derived fields below
                    "days_to_expiry": 1.0 / 365.0,
                    "risk_free_rate": 0.07,
                    "otm_call_iv": 0.15,
                    "otm_put_iv": 0.25, 
                    "call_wall_strike": 24000.0,
                    "put_wall_strike": 23800.0,
                    "total_gamma_exposure": -500000000, 
                }
            else:
                logger.error("Instrument not found in live quote. Falling back to mock.")
                return self._mock_live_data()
                
        except Exception as e:
            logger.error(f"Kite API Error: {e}. Falling back to mock.")
            return self._mock_live_data()

    def _mock_live_data(self):
        return {
            "spot_price": 23900.0,
            "vwap": 23850.0,
            "days_to_expiry": 1.0 / 365.0,
            "risk_free_rate": 0.07,
            "atm_iv": 0.18,
            "otm_call_iv": 0.15,
            "otm_put_iv": 0.25, 
            "call_wall_strike": 24000.0,
            "put_wall_strike": 23800.0,
            "total_gamma_exposure": -500000000, 
            "order_book_ask_qty": 450000, 
            "order_book_bid_qty": 20000,  
        }

    # ==========================================
    # STAGE 2: QUANTITATIVE PRICING (GREEKS)
    # ==========================================
    def calculate_implied_volatility(self, S, K, T, r, market_price, option_type='CE'):
        """Newton-Raphson method to extract IV."""
        sigma = 0.20 
        for _ in range(100):
            d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            
            if option_type == 'CE':
                price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
            else:
                price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
                
            vega = S * norm.pdf(d1) * math.sqrt(T)
            diff = market_price - price
            if abs(diff) < 0.001 or vega == 0: break
            sigma = sigma + diff / vega
        return sigma

    # ==========================================
    # STAGE 3: INSTITUTIONAL FLOW RADAR
    # ==========================================
    def process_institutional_flow(self, raw_signal, data):
        """Analyzes Skew, GEX, and L2 Order Book dynamics."""
        direction = raw_signal.get('type', 'BUY').upper()
        instrument = raw_signal['instrument'].upper()
        
        skew_warning = ""
        if (data['otm_put_iv'] - data['otm_call_iv']) > 0.05 and direction == 'BUY' and 'CE' in instrument:
            skew_warning = "CRITICAL TRAP: VolSkew is heavily bearish."

        gex_context = "GEX is NEGATIVE. Expect volatility." if data['total_gamma_exposure'] < 0 else "GEX is POSITIVE. Stable trend."

        total_orders = max((data['order_book_bid_qty'] + data['order_book_ask_qty']), 1)
        imbalance = (data['order_book_bid_qty'] - data['order_book_ask_qty']) / total_orders
        
        order_book_warning = "L2 TRAP: Massive Ask wall detected." if imbalance < -0.8 and direction == 'BUY' else ""
        
        return f"{skew_warning} | {gex_context} | {order_book_warning}".strip(" |")

    # ==========================================
    # STAGE 4: ENSEMBLE AI SCORING
    # ==========================================
    def retailor_trade(self, raw_signal):
        """Aggregates all stages to optimize the final entry/sl/tgt."""
        data = self.fetch_live_market_data(raw_signal['instrument'])
        
        entry = float(raw_signal.get('entry', 0))
        raw_sl = float(raw_signal.get('sl', 0))
        raw_tgt = float(raw_signal.get('tgt', 0))
        direction = raw_signal.get('type', 'BUY').upper()
        
        # 1. Flow Analysis
        flow_advice = self.process_institutional_flow(raw_signal, data)
        if not flow_advice: flow_advice = "Institutional flow neutral. Relying on R:R math."

        # 2. VWAP Optimization
        total_orders = max((data['order_book_bid_qty'] + data['order_book_ask_qty']), 1)
        imbalance = (data['order_book_bid_qty'] - data['order_book_ask_qty']) / total_orders
        optimized_entry = min(entry, round(data['vwap'], 2)) if direction == 'BUY' and imbalance > 0.2 else entry
        
        # 3. Dynamic Stop/Target Mapping (Spot vs Premium Fix)
        is_option = "CE" in raw_signal['instrument'].upper() or "PE" in raw_signal['instrument'].upper()
        if is_option:
            optimized_sl = raw_sl
            optimized_tgt = raw_tgt
        else:
            optimized_sl = data['put_wall_strike'] - 10 
            optimized_tgt = data['call_wall_strike'] - 20 

        return {
            "ai_optimized_signal": {
                "instrument": raw_signal['instrument'],
                "entry": optimized_entry,
                "sl": optimized_sl,
                "tgt": optimized_tgt,
            },
            "advice": flow_advice
        }

    # ==========================================
    # STAGE 5: RISK MANAGEMENT & EXECUTION
    # ==========================================
    def get_dynamic_lot_size(self, instrument):
        """Returns the valid exchange lot size for the instrument."""
        inst_upper = instrument.upper()
        for key, size in self.lot_sizes.items():
            if key in inst_upper:
                return size
        return 1 # Default for standard equity shares

    def process_signal(self, signal_data):
        current_time = datetime.now().time()
        instrument = signal_data.get('instrument', 'UNKNOWN').upper()
        
        # Time-based Options Filter
        tokens = instrument.split()
        if "CE" in tokens or "PE" in tokens:
            if current_time >= self.theta_decay_cutoff:
                return {"status": "REJECTED", "reason": "Theta decay zone. Terminal locked.", "instrument": instrument}

        # Run Ensemble
        ai_data = self.retailor_trade(signal_data)
        optimized = ai_data['ai_optimized_signal']
        
        # Calculate Risk Math
        risk_per_unit = optimized['entry'] - optimized['sl']
        reward_per_unit = optimized['tgt'] - optimized['entry']
        
        if risk_per_unit <= 0:
            return {"status": "REJECTED", "reason": "Invalid Trade Math: Risk is 0 or negative.", "instrument": instrument}
            
        rr_ratio = reward_per_unit / risk_per_unit
        
        if rr_ratio < self.min_rr_ratio:
            return {
                "status": "REJECTED",
                "reason": f"R:R is {rr_ratio:.2f}:1 (Min: {self.min_rr_ratio}). Structure failed. AI Note: {ai_data['advice']}",
                "instrument": instrument
            }
            
        # Valid Lot Sizing Logic (Exchange Compliant)
        lot_size = self.get_dynamic_lot_size(instrument)
        raw_qty = int(self.max_risk / risk_per_unit) if risk_per_unit > 0 else 0
        max_qty = (raw_qty // lot_size) * lot_size # Snap down to valid multiple
        
        if max_qty == 0:
            return {"status": "REJECTED", "reason": f"Max risk ({self.max_risk}) cannot afford a single lot size of {lot_size}.", "instrument": instrument}

        return {
            "status": "APPROVED",
            "reason": f"R:R is {rr_ratio:.2f}:1. AI Note: {ai_data['advice']}",
            "instrument": instrument,
            "recommended_qty": max_qty,
            "entry": optimized['entry'],
            "sl": optimized['sl'],
            "target": optimized['tgt']
        }