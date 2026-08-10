"""
Manages persistent trade state across runs, stored in state.json
(committed back to the repo by the GitHub Action after every run).

Handles:
 - registering new setups as pending/open trades
 - checking price against SL/TP levels each run
 - partial take-profits + move-to-breakeven
 - invalidation / close-trade alerts
"""

import json
import os
import uuid
from datetime import datetime, timezone

from config import STATE_FILE, PARTIAL_TP_PCT, MOVE_SL_TO_BE_AFTER_TP_INDEX


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"open_trades": [], "last_trend": {}, "last_mtf_trend": {}, "last_health_ping": None}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def has_open_trade(state, symbol):
    return any(t["symbol"] == symbol and t["status"] == "open" for t in state["open_trades"])


def register_trade(state, symbol, setup):
    trade = {
        "id": str(uuid.uuid4())[:8],
        "symbol": symbol,
        "direction": setup["direction"],
        "entry": setup["entry"],
        "sl": setup["sl"],
        "original_sl": setup["original_sl"],
        "tps": setup["tps"],
        "risk": setup["risk"],
        "rr_final": setup["rr_final"],
        "partials_hit": [],
        "breakeven": False,
        "status": "open",
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    state["open_trades"].append(trade)
    return trade


def evaluate_open_trades(state, latest_prices):
    """
    latest_prices: dict of symbol -> latest closed candle (dict with high/low/close)
    Returns a list of event dicts describing what happened this run, e.g.:
      {"type": "tp_hit", "trade": trade, "tp_index": 0}
      {"type": "breakeven", "trade": trade}
      {"type": "closed", "trade": trade, "reason": "stop_loss" | "invalidated" | "final_tp"}
    """
    events = []

    for trade in state["open_trades"]:
        if trade["status"] != "open":
            continue
        candle = latest_prices.get(trade["symbol"])
        if not candle:
            continue

        is_long = trade["direction"] == "long"

        # 1. Check stop loss first (protects capital / matches real execution priority)
        sl_hit = (candle["low"] <= trade["sl"]) if is_long else (candle["high"] >= trade["sl"])
        if sl_hit:
            trade["status"] = "closed"
            reason = "breakeven_stop" if trade["breakeven"] else "stop_loss"
            events.append({"type": "closed", "trade": trade, "reason": reason})
            continue

        # 2. Check take-profit tranches in order
        for idx, tp in enumerate(trade["tps"]):
            if idx in trade["partials_hit"]:
                continue
            tp_hit = (candle["high"] >= tp) if is_long else (candle["low"] <= tp)
            if tp_hit:
                trade["partials_hit"].append(idx)
                events.append({"type": "tp_hit", "trade": trade, "tp_index": idx})

                if idx == MOVE_SL_TO_BE_AFTER_TP_INDEX and not trade["breakeven"]:
                    trade["sl"] = trade["entry"]
                    trade["breakeven"] = True
                    events.append({"type": "breakeven", "trade": trade})

                if idx == len(trade["tps"]) - 1:
                    trade["status"] = "closed"
                    events.append({"type": "closed", "trade": trade, "reason": "final_tp"})
                break  # only register one new tp per run per trade

    return events


def check_invalidation(state, symbol, current_trend):
    """
    If HTF trend flips against an open trade's direction, flag it as
    invalidated so a close alert goes out even before SL is hit.
    """
    events = []
    for trade in state["open_trades"]:
        if trade["status"] != "open" or trade["symbol"] != symbol:
            continue
        wrong_way = (
            (trade["direction"] == "long" and current_trend == "bearish") or
            (trade["direction"] == "short" and current_trend == "bullish")
        )
        if wrong_way:
            trade["status"] = "closed"
            events.append({"type": "closed", "trade": trade, "reason": "invalidated"})
    return events
