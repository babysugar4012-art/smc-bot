# SMC Signal Bot (Telegram + GitHub Actions + Twelve Data)

Free, no-server signal bot. GitHub Actions runs the scanner on a schedule,
Twelve Data supplies price candles, and alerts go to your Telegram chat.

Pairs scanned: EUR/USD, GBP/JPY, USD/JPY, XAU/USD, BTC/USD (edit `config.py` to change).

## What it does
- Reads 4H structure for the top-down trend, and 1H structure as a confirmation
  filter — a 15m entry only fires when 4H and 1H agree on direction
- Finds 15m order blocks with FVG + liquidity-sweep confluence, and requires
  the FVG to clear a minimum size (relative to ATR) to filter out noise
- Publishes setups only when the final target is at least 1:4 R:R
- Manages open trades every run: partial TPs (1.5R / 2.5R / 4R), move-SL-to-breakeven
  after TP1, invalidation/close alerts, stop-loss alerts
- Sends a health ping each run so you know it's still scanning
- Skips forex pairs outside the London/NY session window (crypto scans 24/7)

**Note on expectations:** tightening the filters and raising the R:R target
makes setups more selective, not risk-free. No rule-based strategy has a
near-zero loss rate — treat this as a tool for finding higher-quality setups,
not a guarantee. Paper-track its signals for a while before risking real capital.

## One-time setup (15–20 minutes, no cost)

### 1. Get a free Twelve Data API key
1. Go to twelvedata.com and create a free account.
2. From your dashboard, copy your API key.
3. Free tier gives 800 requests/day. The bot runs every 15 minutes (96 runs/day)
   but caches the 4H and 1H trend readings (only refetching those every 4 hours
   and 1 hour respectively), fetching fresh 15m candles every run. That works
   out to roughly 400–500 requests/day for 3 symbols — comfortably under the limit.

### 2. Create your Telegram bot
1. In Telegram, message **@BotFather**.
2. Send `/newbot`, give it a name and username.
3. BotFather gives you a **bot token** — save it.
4. Create a channel or group you'll receive alerts in, and add your new bot to it as an admin.
5. To get the **chat ID**: send any message in that chat, then visit
   `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` in a browser.
   Look for `"chat":{"id":...}` in the response — that number (often negative
   for groups/channels) is your `TELEGRAM_CHAT_ID`.

### 3. Create the GitHub repo
1. Create a new repo (e.g. `smc-bot`) and upload all the files in this project,
   keeping the folder structure (`.github/workflows/scan.yml` must stay at that path).

### 4. Add your secrets
In the repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add all three:
- `TWELVE_DATA_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 5. Enable Actions and test it
1. Go to the **Actions** tab, enable workflows if prompted.
2. Click into **SMC Signal Scan** → **Run workflow** to trigger it manually.
3. Check the run logs, and check your Telegram chat for the health-check message.
4. If it worked, the workflow will now also run automatically every 15 minutes.

## Adjusting behavior
All the knobs are in `config.py`:
- Add/remove symbols in `SYMBOLS`
- Change `MIN_RR` to require a higher/lower minimum reward:risk
- Change `PARTIAL_TP_RR` / `PARTIAL_TP_PCT` to change tranche levels/sizes
- Change `cron: "0 * * * *"` in `scan.yml` to scan more/less often
  (stay mindful of the 800 req/day free limit — each run costs ~10 requests)

## Known limitations of this MVP (things from your reference screenshot not yet built)
- **No high-impact news blackout filter** — Twelve Data's free tier doesn't include
  an economic calendar. This can be added later with a free calendar API if you want it.
- **No SMT divergence or BTC-context-on-alts confluence yet** — the current logic
  is single-symbol structure + FVG + liquidity sweep. SMT (comparing correlated
  pairs) can be added as a second confluence layer.
- **No spread/choppiness filter** — Twelve Data's free tier doesn't return live
  spread; a simple ATR-based "choppiness" filter could be added instead.
- Trend/OB detection is a rules-based approximation of discretionary SMC reading,
  not a perfect replica of manual chart analysis — treat early signals as a
  starting point to refine, not a finished trading system.

## File overview
- `main.py` — orchestrator, run each cycle
- `config.py` — all settings
- `twelve_data.py` — price data fetching
- `structure_analysis.py` — trend/OB/FVG/liquidity-sweep detection
- `trade_manager.py` — open trade state, partial TPs, breakeven, invalidation
- `telegram_bot.py` — sends alerts
- `state.json` — persistent trade state (auto-updated by the workflow)
- `.github/workflows/scan.yml` — the free scheduler
