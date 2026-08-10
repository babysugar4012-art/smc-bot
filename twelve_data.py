"""
Thin wrapper around the Twelve Data time_series endpoint.
Free tier: 800 requests/day, 8 requests/minute — the scan schedule
in .github/workflows/scan.yml is tuned to stay well under this.
"""

import time
import requests

BASE_URL = "https://api.twelvedata.com/time_series"


def fetch_candles(symbol, interval, api_key, output_size=120, retries=3):
    """
    Returns a list of candle dicts, OLDEST first:
    [{"datetime": ..., "open": float, "high": float, "low": float, "close": float}, ...]
    Returns None on failure (after retries).
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": output_size,
        "apikey": api_key,
        "order": "ASC",
    }

    for attempt in range(retries):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=20)
            data = resp.json()
        except Exception as e:
            print(f"[twelve_data] request error for {symbol} {interval}: {e}")
            time.sleep(2)
            continue

        if data.get("status") == "error":
            print(f"[twelve_data] API error for {symbol} {interval}: {data.get('message')}")
            # Rate limit -> back off and retry
            if "limit" in str(data.get("message", "")).lower():
                time.sleep(10)
                continue
            return None

        values = data.get("values")
        if not values:
            print(f"[twelve_data] no data returned for {symbol} {interval}")
            return None

        candles = []
        for v in values:
            try:
                candles.append({
                    "datetime": v["datetime"],
                    "open": float(v["open"]),
                    "high": float(v["high"]),
                    "low": float(v["low"]),
                    "close": float(v["close"]),
                })
            except (KeyError, ValueError):
                continue

        return candles

    return None
