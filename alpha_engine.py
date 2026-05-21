import numpy as np

class AlphaEngine:
    # ... [Keep your existing __init__ and rr_kill_switch methods] ...

    def fetch_market_structure(self, instrument):
        """
        MOCK FUNCTION: In the final build, this connects to your live WebSocket DB.
        It returns the current VWAP, closest massive Call OI (Resistance), 
        and closest massive Put OI (Support).
        """
        # Simulating live data for Sensex/Nifty based on recent action
        return {
            "current_price": 75150.0,
            "vwap": 75100.0,
            "max_put_oi_strike": 75000.0,  # The Floor
            "max_call_oi_strike": 75300.0, # The Ceiling
            "cvd_trend": "BULLISH" # Are institutions buying or selling?
        }

    def retailor_trade(self, raw_signal):
        """
        The AI logic that intercepts a raw tip and recalculates Entry, SL, and Target
        based on actual institutional Open Interest and Volume.
        """
        structure = self.fetch_market_structure(raw_signal['instrument'])
        
        # 1. Re-tailor Entry: Never chase. Buy near VWAP or structural support.
        if raw_signal['type'] == 'BUY' and structure['cvd_trend'] == 'BULLISH':
            optimized_entry = round(structure['vwap'], 2)
            # If the raw entry is way too high above VWAP, pull it down.
            if raw_signal['entry'] > optimized_entry + 30: 
                entry_advice = f"Do not chase. Wait for pullback to VWAP at {optimized_entry}."
            else:
                optimized_entry = raw_signal['entry']
                entry_advice = "Entry is mathematically sound."
                
        # 2. Re-tailor Stop Loss: Hide behind the Institutional Put Writers
        # Instead of arbitrary points, set SL just below the Max Put OI wall.
        optimized_sl = structure['max_put_oi_strike'] - 10 
        
        # 3. Re-tailor Target: Front-run the Institutional Call Writers
        # Set target slightly below the Max Call OI wall to guarantee an exit.
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
        UPDATED PIPELINE:
        1. AI Re-tailors the trade.
        2. Kills the trade if the NEW optimized math fails the R:R check.
        """
        # Step 1: Run the AI Re-tailor engine
        ai_data = self.retailor_trade(signal_data)
        optimized = ai_data['ai_optimized_signal']
        
        # Step 2: Run the Kill Switch on the AI's new numbers
        approved, rr_ratio = self.rr_kill_switch(optimized['entry'], optimized['sl'], optimized['tgt'])
        
        if not approved:
            return {
                "status": "REJECTED_BY_AI",
                "reason": f"Even with AI optimization, R:R is {rr_ratio:.2f}:1. Structural edge is dead.",
                "original_tip": signal_data,
                "optimized_ticket": optimized
            }
            
        return {
            "status": "AI_APPROVED",
            "reason": f"Signal re-tailored to structural levels. R:R is {rr_ratio:.2f}:1.",
            "execution_ticket": optimized,
            "advice": ai_data['advice']
        }