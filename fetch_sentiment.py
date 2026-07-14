"""
Broad-market crowding tracker (CNN Fear & Greed Index proxy for AAII-style sentiment).
GitHub Actions version -- runs on GitHub's servers on a schedule, commits results
back to this repo. Nothing to run locally.

Purpose: weekly check on whether the broad market is crowded long or crowded short.
This is NOT the AI-exit scorecard and NOT the momentum-crash dashboard. It answers
one question only: is the herd, in aggregate, leaning too far one way right now.

Data source: CNN's public Fear & Greed Index endpoint, free and unauthenticated.

Output:
    sentiment_history.csv -- appends today's reading; safe to run multiple times
    per day, it will just update today's row rather than duplicate it.
"""

import requests
import pandas as pd
import os
from datetime import datetime

CSV_PATH = "sentiment_history.csv"
CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
}


def fetch_current():
    """Fetch the current Fear & Greed reading and its component scores."""
    resp = requests.get(CNN_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    current = data.get("fear_and_greed", {})

    component_keys = [
        "market_momentum_sp500",
        "stock_price_strength",
        "stock_price_breadth",
        "put_call_options",
        "junk_bond_demand",
        "market_volatility_vix",
        "safe_haven_demand",
    ]

    row = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "fear_greed_score": current.get("score"),
        "fear_greed_rating": current.get("rating"),
        "previous_close": current.get("previous_close"),
        "previous_1_week": current.get("previous_1_week"),
        "previous_1_month": current.get("previous_1_month"),
        "previous_1_year": current.get("previous_1_year"),
    }

    for key in component_keys:
        comp = data.get(key, {})
        if isinstance(comp, dict):
            row[f"{key}_score"] = comp.get("score")
            row[f"{key}_rating"] = comp.get("rating")

    return row


def append_to_csv(row):
    """Append today's row, or overwrite today's row if already present (idempotent)."""
    if os.path.exists(CSV_PATH):
        df = pd.read_csv(CSV_PATH)
        df = df[df["date"] != row["date"]]
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])

    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(CSV_PATH, index=False)
    return df


def main():
    print("Fetching CNN Fear & Greed data...")
    try:
        row = fetch_current()
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        print("If CNN is blocking GitHub's runner IPs, this will need to move")
        print("back to a home-run script, or a proxy/self-hosted runner.")
        raise
    except (KeyError, ValueError) as e:
        print(f"Unexpected response format: {e}")
        print("CNN may have changed their API response structure.")
        raise

    df = append_to_csv(row)

    print(f"\nDate: {row['date']}")
    print(f"Fear & Greed score: {row['fear_greed_score']} ({row['fear_greed_rating']})")
    print(f"  1 week ago:  {row.get('previous_1_week')}")
    print(f"  1 month ago: {row.get('previous_1_month')}")
    print(f"  1 year ago:  {row.get('previous_1_year')}")
    print(f"\nSaved to {CSV_PATH}")
    print(f"Total rows in history: {len(df)}")

    score = row.get("fear_greed_score")
    if score is not None:
        if score >= 75:
            print("\n>> EXTREME GREED. Historically the more actionable extreme --")
            print("   crowd is leaning hard long. Worth checking position sizing,")
            print("   not just on AI names but broadly.")
        elif score <= 25:
            print("\n>> EXTREME FEAR. Historically followed by above-average forward")
            print("   returns, but this is a weaker, noisier signal than extreme greed.")
        else:
            print("\n>> Neutral-ish reading. Not at an extreme either way.")


if __name__ == "__main__":
    main()
