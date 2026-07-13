"""
SOXX Volatility Tracker
------------------------
Run this daily (via Windows Task Scheduler) in the 'pead' conda env:

    C:\\Users\\malav\\miniconda3\\envs\\pead\\python.exe soxx_vol_tracker.py

What it does each run:
  1. Pulls 1+ year of SOXX daily closes, computes 30-day annualized
     realized (historical) volatility, and ranks today's HV against
     the past year of rolling HV values -> HV percentile, available
     immediately, no warm-up period needed.
  2. Pulls the current SOXX option chain, finds the nearest monthly
     expiration that's 30+ days out, and averages ATM call/put
     implied volatility -> today's IV reading.
  3. Appends {date, close, hv_30d, hv_percentile, iv_30d} to a local
     CSV log (soxx_vol_log.csv, created if it doesn't exist).
  4. Once the log has enough rows (default: 20+), also computes an
     IV percentile against the accumulated log and prints/exports it.
     Before that, IV percentile shows as NA/insufficient history.

Output: appends to soxx_vol_log.csv, and writes soxx_vol_latest.json
for a dashboard to consume (not built yet, just the file).
"""

import json
import os
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

TICKER = "SOXX"
LOG_PATH = "soxx_vol_log.csv"
JSON_PATH = "soxx_vol_latest.json"
HV_WINDOW = 30          # trading days for realized vol calc
HV_LOOKBACK_DAYS = 365  # how far back to rank HV against
IV_MIN_HISTORY = 20     # minimum logged rows before computing IV percentile
MIN_DAYS_OUT = 30        # nearest expiration must be at least this many days out


def compute_hv_and_percentile(ticker: str):
    hist = yf.Ticker(ticker).history(period="2y")
    if hist.empty:
        raise RuntimeError(f"No price history returned for {ticker}")

    log_ret = np.log(hist["Close"] / hist["Close"].shift(1))
    rolling_hv = log_ret.rolling(HV_WINDOW).std() * np.sqrt(252)
    rolling_hv = rolling_hv.dropna()

    today_hv = rolling_hv.iloc[-1]
    lookback = rolling_hv.iloc[-HV_LOOKBACK_DAYS:] if len(rolling_hv) > HV_LOOKBACK_DAYS else rolling_hv
    hv_percentile = (lookback < today_hv).mean() * 100

    return round(today_hv * 100, 2), round(hv_percentile, 1), round(hist["Close"].iloc[-1], 2)


def compute_current_iv(ticker: str):
    tk = yf.Ticker(ticker)
    expirations = tk.options
    if not expirations:
        return None

    today = datetime.now()
    target_exp = None
    for exp in expirations:
        days_out = (datetime.strptime(exp, "%Y-%m-%d") - today).days
        if days_out >= MIN_DAYS_OUT:
            target_exp = exp
            break
    if target_exp is None:
        target_exp = expirations[-1]  # fallback: furthest available

    chain = tk.option_chain(target_exp)
    spot = tk.history(period="1d")["Close"].iloc[-1]

    calls = chain.calls.copy()
    puts = chain.puts.copy()
    calls["dist"] = (calls["strike"] - spot).abs()
    puts["dist"] = (puts["strike"] - spot).abs()

    atm_call_iv = calls.sort_values("dist").iloc[0]["impliedVolatility"]
    atm_put_iv = puts.sort_values("dist").iloc[0]["impliedVolatility"]
    avg_iv = (atm_call_iv + atm_put_iv) / 2

    return round(avg_iv * 100, 2), target_exp


def load_or_init_log():
    if os.path.exists(LOG_PATH):
        return pd.read_csv(LOG_PATH, parse_dates=["date"])
    return pd.DataFrame(columns=["date", "close", "hv_30d", "hv_percentile", "iv_30d", "iv_expiration"])


def main():
    hv_30d, hv_percentile, close = compute_hv_and_percentile(TICKER)
    iv_result = compute_current_iv(TICKER)
    iv_30d, iv_exp = iv_result if iv_result else (None, None)

    log = load_or_init_log()
    today_str = datetime.now().strftime("%Y-%m-%d")

    log = log[log["date"].astype(str) != today_str]  # avoid dupes if run twice same day
    new_row = pd.DataFrame([{
        "date": today_str,
        "close": close,
        "hv_30d": hv_30d,
        "hv_percentile": hv_percentile,
        "iv_30d": iv_30d,
        "iv_expiration": iv_exp,
    }])
    log = pd.concat([log, new_row], ignore_index=True)
    log.to_csv(LOG_PATH, index=False)

    iv_percentile = None
    if iv_30d is not None and len(log) >= IV_MIN_HISTORY:
        iv_history = log["iv_30d"].dropna()
        iv_percentile = round((iv_history < iv_30d).mean() * 100, 1)

    result = {
        "date": today_str,
        "close": close,
        "hv_30d_pct": hv_30d,
        "hv_percentile": hv_percentile,
        "iv_30d_pct": iv_30d,
        "iv_percentile": iv_percentile,
        "iv_percentile_status": (
            "ready" if iv_percentile is not None
            else f"building history ({len(log)}/{IV_MIN_HISTORY} days logged)"
        ),
        "log_rows": len(log),
    }

    with open(JSON_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
