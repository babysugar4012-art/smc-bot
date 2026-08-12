"""
Central configuration for the SMC signal bot.
Edit this file to add/remove pairs or tune risk settings.
"""

import os

# --- API keys (read from GitHub Actions secrets / environment variables) ---
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- Symbols to scan (must match Twelve Data's symbol format) ---
# "asset_class" is just used for session-hour filtering.
SYMBOLS = [
    {"symbol": "EUR/USD", "asset_class": "forex"},
    {"symbol": "USD/JPY", "asset_class": "forex"},
    {"symbol": "BTC/USD", "asset_class": "crypto"},
]

# --- Timeframes ---
HTF_INTERVAL = "4h"     # top-down trend / regime
MTF_INTERVAL = "1h"     # mid-timeframe confirmation filter
LTF_INTERVAL = "15min"  # entry timeframe
CANDLES_TO_FETCH = 120

# How long to trust a cached trend reading before re-fetching that timeframe.
# Keeps API usage low even when scanning 15m entries frequently.
HTF_REFRESH_MINUTES = 240   # re-check 4H trend at most every 4 hours
MTF_REFRESH_MINUTES = 60    # re-check 1H trend at most every 1 hour

# --- Structure detection ---
SWING_LOOKBACK = 2      # bars on each side to confirm a fractal swing high/low
MIN_SWINGS_FOR_TREND = 2
MIN_FVG_ATR_RATIO = 0.15   # FVG gap must be at least this fraction of ATR(14) to count — filters noise gaps
ATR_PERIOD = 14

# --- Risk / trade management ---
MIN_RR = 4.0              # minimum reward:risk to publish a setup (1:4)
SL_BUFFER_PCT = 0.03      # extra buffer beyond the order block, as % of OB range
PARTIAL_TP_RR = [1.5, 2.5, 4.0]   # take-profit tranches, in R multiples
PARTIAL_TP_PCT = [0.33, 0.33, 0.34]  # % of position closed at each tranche
MOVE_SL_TO_BE_AFTER_TP_INDEX = 0  # after TP1 (index 0) hits, move SL to breakeven

# --- Health ping ---
# How often to send a "still scanning" ping to Telegram, regardless of how
# often the scan itself runs. Keeps the channel quiet between real events.
HEALTH_PING_INTERVAL_MINUTES = 240  # every 4 hours

# --- Order block search window ---
# How many recent LTF candles to scan for a qualifying order block.
OB_SEARCH_BARS = 40

# --- Session filter (UTC hours) — forex/metal only trade inside these windows ---
FOREX_SESSION_HOURS_UTC = list(range(7, 21))  # London + New York overlap window

# --- API budget guard ---
# Stays below the free 800/day limit even if the schedule fires more often
# than expected, or an external trigger (e.g. cron-job.org) duplicates runs.
DAILY_API_BUDGET = 700

# --- State file (committed back to the repo by the GitHub Action) ---
STATE_FILE = "state.json"
