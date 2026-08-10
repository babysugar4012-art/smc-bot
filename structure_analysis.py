"""
Smart Money Concepts structure detection:
- Swing highs/lows (fractals)
- HTF trend (HH/HL vs LH/LL)
- Fair value gaps (FVG)
- Liquidity sweeps
- Order block identification + entry/SL/TP calculation

This is a rules-based approximation of discretionary SMC analysis.
It is deliberately conservative: if confluence isn't clearly present,
it returns no setup rather than guessing.
"""

from config import (
    SWING_LOOKBACK, MIN_SWINGS_FOR_TREND, MIN_RR, SL_BUFFER_PCT, PARTIAL_TP_RR,
    MIN_FVG_ATR_RATIO, ATR_PERIOD,
)


def compute_atr(candles, period=ATR_PERIOD):
    """Simple ATR (average true range) over the last `period` candles."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(len(candles) - period, len(candles)):
        prev_close = candles[i - 1]["close"]
        c = candles[i]
        tr = max(
            c["high"] - c["low"],
            abs(c["high"] - prev_close),
            abs(c["low"] - prev_close),
        )
        trs.append(tr)
    return sum(trs) / len(trs)


def find_swings(candles, lookback=SWING_LOOKBACK):
    """
    Returns list of (index, price, type) for confirmed swing highs/lows.
    type is 'high' or 'low'. Only bars with `lookback` candles on both
    sides are evaluated, so the most recent `lookback` bars are never
    swing points (they're unconfirmed).
    """
    swings = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        window = candles[i - lookback:i + lookback + 1]
        high = candles[i]["high"]
        low = candles[i]["low"]
        if high == max(c["high"] for c in window):
            swings.append((i, high, "high"))
        if low == min(c["low"] for c in window):
            swings.append((i, low, "low"))
    return swings


def detect_trend(candles):
    """
    Looks at the sequence of recent confirmed swing highs and swing lows
    to classify structure as 'bullish' (HH/HL), 'bearish' (LH/LL), or
    'ranging' (neither, or not enough data).
    """
    swings = find_swings(candles)
    highs = [s for s in swings if s[2] == "high"]
    lows = [s for s in swings if s[2] == "low"]

    if len(highs) < MIN_SWINGS_FOR_TREND or len(lows) < MIN_SWINGS_FOR_TREND:
        return "ranging", swings

    last_highs = highs[-MIN_SWINGS_FOR_TREND:]
    last_lows = lows[-MIN_SWINGS_FOR_TREND:]

    highs_ascending = all(last_highs[i][1] < last_highs[i + 1][1] for i in range(len(last_highs) - 1))
    lows_ascending = all(last_lows[i][1] < last_lows[i + 1][1] for i in range(len(last_lows) - 1))
    highs_descending = all(last_highs[i][1] > last_highs[i + 1][1] for i in range(len(last_highs) - 1))
    lows_descending = all(last_lows[i][1] > last_lows[i + 1][1] for i in range(len(last_lows) - 1))

    if highs_ascending and lows_ascending:
        return "bullish", swings
    if highs_descending and lows_descending:
        return "bearish", swings
    return "ranging", swings


def find_fvg(candles, i, direction, atr=None):
    """
    Checks for a fair value gap centered on candle i (the impulse candle).
    Bullish FVG: low of candle i+1 > high of candle i-1.
    Bearish FVG: high of candle i+1 < low of candle i-1.
    If atr is provided, the gap must also be at least MIN_FVG_ATR_RATIO * atr
    wide — this filters out tiny, noisy gaps that aren't real imbalances.
    """
    if i - 1 < 0 or i + 1 >= len(candles):
        return False
    prev_c = candles[i - 1]
    next_c = candles[i + 1]

    if direction == "bullish":
        gap = next_c["low"] - prev_c["high"]
    else:
        gap = prev_c["low"] - next_c["high"]

    if gap <= 0:
        return False
    if atr and gap < atr * MIN_FVG_ATR_RATIO:
        return False
    return True


def find_liquidity_sweep(candles, i, direction, swings):
    """
    Checks whether, shortly before the impulse candle at index i, price
    wicked beyond a recent minor swing (grabbing liquidity) then closed
    back on the correct side — a stop-hunt signature.
    """
    lookback_start = max(0, i - 6)
    recent_swings = [s for s in swings if lookback_start <= s[0] < i]
    if not recent_swings:
        return False

    if direction == "bullish":
        recent_lows = [s for s in recent_swings if s[2] == "low"]
        if not recent_lows:
            return False
        target_low = min(s[1] for s in recent_lows)
        for c in candles[lookback_start:i + 1]:
            if c["low"] < target_low and c["close"] > target_low:
                return True
        return False
    else:
        recent_highs = [s for s in recent_swings if s[2] == "high"]
        if not recent_highs:
            return False
        target_high = max(s[1] for s in recent_highs)
        for c in candles[lookback_start:i + 1]:
            if c["high"] > target_high and c["close"] < target_high:
                return True
        return False


def find_order_block(candles, trend):
    """
    Scans the last ~15 LTF candles for a valid order block in the
    direction of `trend`, requiring:
      - a break of recent minor structure (impulse move)
      - a fair value gap in the impulse
      - a preceding liquidity sweep
    Returns a dict describing the OB, or None if nothing qualifies.
    """
    if trend not in ("bullish", "bearish"):
        return None

    n = len(candles)
    if n < 20:
        return None

    swings = find_swings(candles)
    atr = compute_atr(candles)
    search_range = range(max(SWING_LOOKBACK + 1, n - 16), n - SWING_LOOKBACK - 1)

    # Scan newest-first so we find the most recent qualifying OB.
    for i in reversed(list(search_range)):
        c = candles[i]
        is_bull_candle = c["close"] > c["open"]
        is_bear_candle = c["close"] < c["open"]

        if trend == "bullish" and is_bull_candle:
            if find_fvg(candles, i, "bullish", atr) and find_liquidity_sweep(candles, i, "bullish", swings):
                # The order block is the last down-close (or down-bodied) candle
                # immediately before this impulse candle.
                ob_index = i - 1
                while ob_index >= 0 and candles[ob_index]["close"] > candles[ob_index]["open"]:
                    ob_index -= 1
                if ob_index < 0:
                    continue
                ob = candles[ob_index]
                return {
                    "direction": "long",
                    "ob_index": ob_index,
                    "ob_high": ob["high"],
                    "ob_low": ob["low"],
                    "impulse_index": i,
                }

        if trend == "bearish" and is_bear_candle:
            if find_fvg(candles, i, "bearish", atr) and find_liquidity_sweep(candles, i, "bearish", swings):
                ob_index = i - 1
                while ob_index >= 0 and candles[ob_index]["close"] < candles[ob_index]["open"]:
                    ob_index -= 1
                if ob_index < 0:
                    continue
                ob = candles[ob_index]
                return {
                    "direction": "short",
                    "ob_index": ob_index,
                    "ob_high": ob["high"],
                    "ob_low": ob["low"],
                    "impulse_index": i,
                }

    return None


def build_setup(ob, min_rr=MIN_RR):
    """
    Turns an order block dict into a full trade setup with entry, SL,
    and partial TP levels. Returns None if the resulting R:R is below
    min_rr.
    """
    ob_range = ob["ob_high"] - ob["ob_low"]
    buffer = ob_range * SL_BUFFER_PCT

    if ob["direction"] == "long":
        entry = ob["ob_high"]
        sl = ob["ob_low"] - buffer
        risk = entry - sl
        if risk <= 0:
            return None
        tps = [round(entry + risk * m, 6) for m in PARTIAL_TP_RR]
        rr_final = (tps[-1] - entry) / risk
    else:
        entry = ob["ob_low"]
        sl = ob["ob_high"] + buffer
        risk = sl - entry
        if risk <= 0:
            return None
        tps = [round(entry - risk * m, 6) for m in PARTIAL_TP_RR]
        rr_final = (entry - tps[-1]) / risk

    if rr_final < min_rr:
        return None

    return {
        "direction": ob["direction"],
        "entry": round(entry, 6),
        "sl": round(sl, 6),
        "original_sl": round(sl, 6),
        "tps": tps,
        "risk": round(risk, 6),
        "rr_final": round(rr_final, 2),
        "ob_high": round(ob["ob_high"], 6),
        "ob_low": round(ob["ob_low"], 6),
    }
