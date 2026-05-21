import pandas as pd
import numpy as np
from datetime import datetime, time

class AlphaEngine:
    def __init__(self, max_risk_capital=5000, min_rr=1.5):
        self.max_risk = max_risk_capital
        self.min_rr_ratio = min_rr
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

    def process_signal(self, signal_data):
        """
        Ingests JSON signal and runs structural checks.
        signal_data = {'instrument': 'Sensex 75000 PE', 'type': 'BUY', 'entry': 40.0, 'sl': 10.0, 'tgt': 80.0}
        """
        current_time = datetime.now().time()
        instrument = signal_data.get('instrument', 'UNKNOWN')
        entry = float(signal_data.get('entry', 0))
        sl = float(signal_data.get('sl', 0))
        tgt = float(signal_data.get('tgt', 0))
        
        # 1. Theta Decay Time-Lock (Only applies to Options)
        if "CE" in instrument or "PE" in instrument:
            if current_time >= self.theta_decay_cutoff:
                return {
                    "status": "REJECTED",
                    "reason": "Theta decay high-velocity zone (Post 2:00 PM). Terminal locked.",
                    "instrument": instrument
                }

        # 2. R:R Kill Switch
        approved, rr_ratio = self.rr_kill_switch(entry, sl, tgt)
        if not approved:
            return {
                "status": "REJECTED",
                "reason": f"Inverted Risk/Reward. R:R is {rr_ratio:.2f}:1. Minimum required is {self.min_rr_ratio}:1.",
                "instrument": instrument
            }
        
        # 3. Position Sizing Calculation
        risk_per_unit = entry - sl
        max_qty = int(self.max_risk / risk_per_unit) if risk_per_unit > 0 else 0
        
        return {
            "status": "APPROVED",
            "reason": f"System clear. R:R verified at {rr_ratio:.2f}:1.",
            "instrument": instrument,
            "recommended_qty": max_qty,
            "entry": entry,
            "sl": sl,
            "target": tgt
        }