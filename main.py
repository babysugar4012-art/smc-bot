"""
Entry point. One run of this script = one scan cycle:
  1. Pull HTF + LTF candles for every configured symbol
  2. Determine trend (regime) on HTF
  3. Manage existing open trades (SL/TP/invalidation) against latest LTF candle
  4. Look for a new order-block setup if there's no open trade on that symbol
  5. Send all Telegram alerts
  6. Save state.json (committed back to the repo by the workflow)

Run via GitHub Actions on a schedule — see .github/workflows/scan.yml
"""

from datetime import datetime, timezone, timedelta

import config
from twelve_data import fetch_candles
from telegram_bot import send_message
from structure_analysis import detect_trend, find_order_block, build_setup
from trade_manager import (
    load_state, save_state, has_open_trade, register_trade,
    evaluate_open_trades, check_invalidation,
    get_budget_remaining, record_api_call,
)


def in_forex_session():
    hour = datetime.now(timezone.utc).hour
    return hour in config.FOREX_SESSION_HOURS_UTC


def _cache_is_fresh(state, symbol, cache_key, max_age_minutes):
    entry = state.get(cache_key, {}).get(symbol)
    if not entry:
        return False
    updated_at = datetime.fromisoformat(entry["updated_at"])
    return datetime.now(timezone.utc) - updated_at < timedelta(minutes=max_age_minutes)


def get_trend_cached(state, symbol, interval, cache_key, max_age_minutes):
    """
    Returns a trend string, refetching candles from Twelve Data only if
    the cached value is older than max_age_minutes AND the daily API
    budget isn't exhausted. Keeps API usage low and safe when scanning
    frequently for 15m entries.
    """
    if _cache_is_fresh(state, symbol, cache_key, max_age_minutes):
        return state[cache_key][symbol]["trend"]

    if get_budget_remaining(state, config.DAILY_API_BUDGET) <= 0:
        cached = state.get(cache_key, {}).get(symbol)
        return cached["trend"] if cached else "ranging"

    candles = fetch_candles(symbol, interval, config.TWELVE_DATA_API_KEY, config.CANDLES_TO_FETCH)
    record_api_call(state)

    if candles == "QUOTA_EXHAUSTED" or not candles:
        cached = state.get(cache_key, {}).get(symbol)
        return cached["trend"] if cached else "ranging"

    trend, _ = detect_trend(candles)
    state.setdefault(cache_key, {})[symbol] = {
        "trend": trend,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return trend


def fmt_price(p):
    return f"{p:.5f}" if p < 50 else f"{p:.2f}"


def send_new_setup_alert(symbol, trend, setup):
    arrow = "🟢 LONG" if setup["direction"] == "long" else "🔴 SHORT"
    msg = (
        f"*NEW SETUP — {symbol}*\n"
        f"{arrow}\n"
        f"Regime: {trend.upper()} (4H structure)\n\n"
        f"Entry: `{fmt_price(setup['entry'])}`\n"
        f"Stop Loss: `{fmt_price(setup['sl'])}`\n"
        f"TP1: `{fmt_price(setup['tps'][0])}`  |  TP2: `{fmt_price(setup['tps'][1])}`  |  TP3: `{fmt_price(setup['tps'][2])}`\n"
        f"R:R to final target: 1:{setup['rr_final']}\n\n"
        f"Confluence: validated break of structure, order block + FVG, liquidity sweep\n"
        f"_Structural stop. Move SL to breakeven after TP1._"
    )
    send_message(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, msg)


def send_event_alert(event):
    trade = event["trade"]
    symbol = trade["symbol"]

    if event["type"] == "tp_hit":
        idx = event["tp_index"]
        pct = int(config.PARTIAL_TP_PCT[idx] * 100)
        msg = (
            f"🎯 *TP{idx + 1} HIT — {symbol}*\n"
            f"Closed ~{pct}% of position at `{fmt_price(trade['tps'][idx])}`\n"
            f"Trade ID: `{trade['id']}`"
        )
        send_message(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, msg)

    elif event["type"] == "breakeven":
        msg = (
            f"🛡️ *SL MOVED TO BREAKEVEN — {symbol}*\n"
            f"New stop: `{fmt_price(trade['entry'])}`\n"
            f"Trade ID: `{trade['id']}`"
        )
        send_message(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, msg)

    elif event["type"] == "closed":
        reason_map = {
            "stop_loss": "❌ STOP LOSS HIT",
            "breakeven_stop": "⚪ CLOSED AT BREAKEVEN",
            "invalidated": "⚠️ SETUP INVALIDATED — CLOSE TRADE",
            "final_tp": "✅ FINAL TARGET HIT",
        }
        header = reason_map.get(event["reason"], "CLOSED")
        msg = (
            f"*{header} — {symbol}*\n"
            f"Direction: {trade['direction'].upper()}\n"
            f"Entry: `{fmt_price(trade['entry'])}` | Exit level: `{fmt_price(trade['sl'])}`\n"
            f"Trade ID: `{trade['id']}`"
        )
        send_message(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, msg)


def send_health_ping(state, scanned, skipped):
    last_ping = state.get("last_health_ping")
    if last_ping:
        elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last_ping)
        if elapsed < timedelta(minutes=config.HEALTH_PING_INTERVAL_MINUTES):
            return  # too soon — stay quiet

    msg = (
        f"🩺 *Bot health check*\n"
        f"Scanned: {', '.join(scanned) if scanned else 'none'}\n"
        f"Skipped (session filter): {', '.join(skipped) if skipped else 'none'}\n"
        f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    send_message(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, msg)
    state["last_health_ping"] = datetime.now(timezone.utc).isoformat()


def run():
    state = load_state()
    scanned, skipped = [], []

    for entry in config.SYMBOLS:
        symbol = entry["symbol"]
        asset_class = entry["asset_class"]

        # Session filter — crypto trades 24/7, forex/metal only in session hours
        if asset_class in ("forex", "metal") and not in_forex_session():
            skipped.append(symbol)
            continue

        # HTF (4H) and MTF (1H) trend are cached and only refetched on their
        # own schedule — the 15m entry candles are fetched fresh every run.
        htf_trend = get_trend_cached(state, symbol, config.HTF_INTERVAL, "last_trend", config.HTF_REFRESH_MINUTES)
        mtf_trend = get_trend_cached(state, symbol, config.MTF_INTERVAL, "last_mtf_trend", config.MTF_REFRESH_MINUTES)

        if get_budget_remaining(state, config.DAILY_API_BUDGET) <= 0:
            print(f"[main] daily API budget reached — skipping {symbol} 15m fetch until tomorrow")
            continue

        ltf_candles = fetch_candles(symbol, config.LTF_INTERVAL, config.TWELVE_DATA_API_KEY, config.CANDLES_TO_FETCH)
        record_api_call(state)

        if ltf_candles == "QUOTA_EXHAUSTED" or not ltf_candles:
            print(f"[main] skipping {symbol} — 15m data fetch failed or quota hit")
            continue

        scanned.append(symbol)
        latest_ltf = ltf_candles[-1]

        # 1. Manage any open trade on this symbol first
        events = evaluate_open_trades(state, {symbol: latest_ltf})
        events += check_invalidation(state, symbol, htf_trend)
        for ev in events:
            send_event_alert(ev)

        # 2. Only look for a new entry if 4H has a clear directional trend
        # AND 1H isn't actively opposing it. A "ranging" 1H no longer vetoes
        # the setup — only a flat-out opposite 1H trend does.
        if htf_trend not in ("bullish", "bearish"):
            aligned_trend = None
        elif mtf_trend == htf_trend or mtf_trend == "ranging":
            aligned_trend = htf_trend
        else:
            aligned_trend = None  # 1H is actively opposing 4H

        print(f"[main] {symbol}: 4H={htf_trend} 1H={mtf_trend} aligned={aligned_trend or 'NO'} open_trade={has_open_trade(state, symbol)}")

        if aligned_trend and not has_open_trade(state, symbol):
            debug = {}
            ob = find_order_block(ltf_candles, aligned_trend, debug=debug)
            print(f"[main] {symbol}: OB search — {debug}")
            if ob:
                setup = build_setup(ob)
                if setup:
                    register_trade(state, symbol, setup)
                    send_new_setup_alert(symbol, aligned_trend, setup)
                    print(f"[main] {symbol}: NEW SETUP registered — {setup}")
                else:
                    print(f"[main] {symbol}: order block found but final R:R below {config.MIN_RR}, rejected")
        elif not aligned_trend:
            print(f"[main] {symbol}: skipped entry search — 4H/1H trend not aligned")
        elif has_open_trade(state, symbol):
            print(f"[main] {symbol}: skipped entry search — trade already open")

    # Health ping — throttled to config.HEALTH_PING_INTERVAL_MINUTES so the
    # channel stays quiet between real events instead of pinging every run.
    send_health_ping(state, scanned, skipped)

    save_state(state)


if __name__ == "__main__":
    run()
