import pandas as pd
import numpy as np
from datetime import datetime, time

class AlphaEngine:
    def __init__(self, max_risk_capital=5000, min_rr=1.5):
        self.max_risk = float(max_risk_capital)
        self.min_rr_ratio = float(min_rr)
        # Institutional time-lock: Block fresh OTM options buying after 2:00 PM on D-1/D-0 Expiry
        self.theta_decay_cutoff = time(14, 0) 

    def rr_kill_switch(self, entry, sl, target):
        """Mathematically verifies if the trade edge exists."""
        risk = entry - sl
        reward = target - entry
        
        if risk <= 0:
            return False, 0.0
            
        ratio = reward / risk
        is_approved = ratio >= self.min_rr_ratio
        
        return is_approved, ratio

    def fetch_market_structure(self, instrument):
        """
        MOCK FUNCTION: To be connected to your live WebSocket DB later.
        Returns the current VWAP, closest Call OI (Resistance), and Put OI (Support).
        """
        return {
            "current_price": 75150.0,
            "vwap": 75100.0,
            "max_put_oi_strike": 75000.0,  
            "max_call_oi_strike": 75300.0, 
            "cvd_trend": "BULLISH" 
        }

    def retailor_trade(self, raw_signal):
        """
        The AI logic that intercepts a raw tip and recalculates Entry, SL, and Target.
        """
        structure = self.fetch_market_structure(raw_signal['instrument'])
        
        optimized_entry = float(raw_signal.get('entry', 0))
        entry_advice = "Entry is mathematically sound."
        
        if "BUY" in raw_signal.get('type', 'BUY').upper() and structure['cvd_trend'] == 'BULLISH':
            vwap_level = round(structure['vwap'], 2)
            if optimized_entry > vwap_level + 30: 
                optimized_entry = vwap_level
                entry_advice = f"Do not chase. Wait for pullback to VWAP at {optimized_entry}."
                
        # Hide SL behind Institutional Put Writers
        optimized_sl = structure['max_put_oi_strike'] - 10 
        
        # Front-run the Institutional Call Writers
        optimized_tgt = structure['max_call_oi_strike'] - 20 

        return {
            "original_signal": raw_signal,
            "ai_optimized_signal": {
                "instrument": raw_signal['instrument'],
                "entry": optimized_entry,
                "sl": optimized_sl,
                "tgt": optimized_tgt,
            },
            "market_context": structure,
            "advice": entry_advice
        }

    def process_signal(self, signal_data):
        """
        Ingests JSON signal, runs AI optimization, and applies the Kill Switch.
        """
        current_time = datetime.now().time()
        instrument = signal_data.get('instrument', 'UNKNOWN')
        
        # 1. Theta Decay Time-Lock (Only applies to Options)
        if "CE" in instrument.upper() or "PE" in instrument.upper():
            if current_time >= self.theta_decay_cutoff:
                return {
                    "status": "REJECTED",
                    "reason": "Theta decay high-velocity zone (Post 2:00 PM). Terminal locked.",
                    "instrument": instrument
                }

        # 2. Run the AI Re-tailor engine
        ai_data = self.retailor_trade(signal_data)
        optimized = ai_data['ai_optimized_signal']
        
        # 3. Run the Kill Switch on the AI's new numbers
        approved, rr_ratio = self.rr_kill_switch(optimized['entry'], optimized['sl'], optimized['tgt'])
        
        if not approved:
            return {
                "status": "REJECTED",
                "reason": f"Even with AI optimization, R:R is {rr_ratio:.2f}:1. Structural edge is dead.",
                "instrument": instrument
            }
            
        # 4. Position Sizing Calculation
        risk_per_unit = optimized['entry'] - optimized['sl']
        max_qty = int(self.max_risk / risk_per_unit) if risk_per_unit > 0 else 0
            
        return {
            "status": "APPROVED",
            "reason": f"Signal re-tailored to structural levels. R:R is {rr_ratio:.2f}:1. {ai_data['advice']}",
            "instrument": instrument,
            "recommended_qty": max_qty,
            "entry": optimized['entry'],
            "sl": optimized['sl'],
            "target": optimized['tgt']
        }