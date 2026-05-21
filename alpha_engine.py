import pandas as pd
import numpy as np
import math
from datetime import datetime, time
from scipy.stats import norm

class AlphaEngine:
    # Notice the kite_client=None here. This fixes the crash.
    def __init__(self, max_risk_capital=5000, min_rr=1.5, kite_client=None):
        self.max_risk = float(max_risk_capital)
        self.min_rr_ratio = float(min_rr)
        self.theta_decay_cutoff = time(14, 0) 
        self.kite = kite_client # Live Zerodha API Client

    # --- QUANTITATIVE MATHEMATICS (BLACK-SCHOLES) ---
    def black_scholes_greeks(self, S, K, T, r, sigma, option_type='CE'):
        """Calculates Delta and Gamma for GEX."""
        if T <= 0 or sigma <= 0: return 0.0, 0.0
        
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
        delta = norm.cdf(d1) if option_type == 'CE' else norm.cdf(d1) - 1
        return delta, gamma

    def calculate_implied_volatility(self, S, K, T, r, market_price, option_type='CE'):
        """Newton-Raphson method to extract IV from live premium."""
        sigma = 0.20 # Initial guess
        for i in range(100):
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

    # --- LIVE DATA INGESTION ---
    # --- LIVE DATA INGESTION ---
    def fetch_live_market_data(self, instrument):
        """Pulls live Tick Data, Market Depth, and Option Chain."""
        if not self.kite:
            print("SYSTEM: No Kite client. Using mock data.")
            return self._mock_live_data()

        try:
            # We are connected to Zerodha! 
            # TODO: Next step is to add Kite Instrument Token mapping here.
            # Example: quote = self.kite.quote(["NFO:NIFTY26MAY24000CE"])
            
            # For right now, return the mock structural data so the AI Radar math doesn't crash
            return self._mock_live_data()
            
        except Exception as e:
            print(f"Kite API Error: {e}")
            return self._mock_live_data()

    def _mock_live_data(self):
        """Simulated Live Environment."""
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

    def rr_kill_switch(self, entry, sl, target):
        """Mathematically verifies if the trade edge exists."""
        risk = entry - sl
        reward = target - entry
        
        if risk <= 0:
            return False, 0.0
            
        ratio = reward / risk
        is_approved = ratio >= self.min_rr_ratio
        
        return is_approved, ratio

    # --- THE INSTITUTIONAL RADAR ---
    def retailor_trade(self, raw_signal):
        data = self.fetch_live_market_data(raw_signal['instrument'])
        
        entry = float(raw_signal.get('entry', 0))
        direction = raw_signal.get('type', 'BUY').upper()
        
        skew_warning = ""
        if (data['otm_put_iv'] - data['otm_call_iv']) > 0.05 and direction == 'BUY' and 'CE' in raw_signal['instrument'].upper():
            skew_warning = "CRITICAL TRAP: Volatility Skew is heavily bearish. Institutions are pricing in a drop."

        gex_context = "GEX is NEGATIVE. Expect wild price swings." if data['total_gamma_exposure'] < 0 else "GEX is POSITIVE. Trend is stable."

        imbalance = (data['order_book_bid_qty'] - data['order_book_ask_qty']) / max((data['order_book_bid_qty'] + data['order_book_ask_qty']), 1)
        order_book_warning = "L2 TRAP: Massive institutional Ask wall detected." if imbalance < -0.8 and direction == 'BUY' else ""

        optimized_entry = min(entry, round(data['vwap'], 2)) if direction == 'BUY' and imbalance > 0.2 else entry
        optimized_sl = data['put_wall_strike'] - 10 
        optimized_tgt = data['call_wall_strike'] - 20 

        advice = f"{skew_warning} | {gex_context} | {order_book_warning}".strip(" |")
        if not advice: advice = "Institutional flow is neutral. Edge relies entirely on R:R math."

        return {
            "ai_optimized_signal": {
                "instrument": raw_signal['instrument'],
                "entry": optimized_entry,
                "sl": optimized_sl,
                "tgt": optimized_tgt,
            },
            "advice": advice
        }

    def process_signal(self, signal_data):
        current_time = datetime.now().time()
        instrument = signal_data.get('instrument', 'UNKNOWN')
        
        # Split the instrument string into individual words (tokens)
        tokens = instrument.upper().split()
        
        # Check if "CE" or "PE" exists as an exact, standalone word
        if "CE" in tokens or "PE" in tokens:
            if current_time >= self.theta_decay_cutoff:
                return {"status": "REJECTED", "reason": "Theta decay zone. Terminal locked.", "instrument": instrument}

        ai_data = self.retailor_trade(signal_data)
        optimized = ai_data['ai_optimized_signal']
        
        approved, rr_ratio = self.rr_kill_switch(optimized['entry'], optimized['sl'], optimized['tgt'])
        
        if not approved:
            return {
                "status": "REJECTED",
                "reason": f"R:R is {rr_ratio:.2f}:1. Structural edge is dead. AI Note: {ai_data['advice']}",
                "instrument": instrument
            }
            
        risk_per_unit = optimized['entry'] - optimized['sl']
        max_qty = int(self.max_risk / risk_per_unit) if risk_per_unit > 0 else 0
            
        return {
            "status": "APPROVED",
            "reason": f"R:R is {rr_ratio:.2f}:1. AI Note: {ai_data['advice']}",
            "instrument": instrument,
            "recommended_qty": max_qty,
            "entry": optimized['entry'],
            "sl": optimized['sl'],
            "target": optimized['tgt']
        }