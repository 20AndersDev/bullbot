"""
bullbot morning research — køyr som: python research.py [--commit]
Hentar nyheter, fundamentaldata og earnings for heile watchlisten.
"""
import subprocess, sys, json, os
from datetime import datetime, timezone, date
from pathlib import Path

subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "yfinance", "requests"])
import yfinance as yf
import requests

import config

knowledge: dict = {
    "dato": str(date.today()),
    "timestamp": datetime.now(timezone.utc).isoformat(),
}

# --- Marknadssentiment ---
print("=== MARKNADSSENTIMENT ===")
try:
    resp = requests.get(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        headers={"User-Agent": "Mozilla/5.0"}, timeout=10,
    )
    fg = resp.json()["fear_and_greed"]
    fg_score = float(fg["score"])
    print(f"CNN Fear & Greed: {fg_score:.0f}/100 ({fg['rating']})")
    knowledge["fear_greed"] = {"score": fg_score, "rating": fg["rating"]}
except Exception as e:
    print(f"Fear & Greed: N/A ({e})")

try:
    vix = yf.download("^VIX", period="2d", progress=False)["Close"].dropna()
    vix_val = float(vix.iloc[-1])
    print(f"VIX: {vix_val:.2f}")
    knowledge["vix"] = vix_val
except Exception as e:
    print(f"VIX: N/A ({e})")

try:
    spy = yf.download("SPY", period="5d", progress=False)["Close"].dropna()
    spy_chg = (float(spy.iloc[-1]) / float(spy.iloc[-2]) - 1) * 100
    spy_w = (float(spy.iloc[-1]) / float(spy.iloc[0]) - 1) * 100
    print(f"SPY: ${float(spy.iloc[-1]):.2f}  dag={spy_chg:+.2f}%  veke={spy_w:+.2f}%")
    knowledge["spy"] = {"price": float(spy.iloc[-1]), "day_pct": spy_chg, "week_pct": spy_w}
except Exception as e:
    print(f"SPY: N/A ({e})")

# --- Earnings neste 7 dagar ---
print("\n=== EARNINGS NESTE 7 DAGAR ===")
upcoming = []
for sym in config.WATCHLIST:
    try:
        t = yf.Ticker(sym)
        cal = t.calendar
        if cal is not None and hasattr(cal, "columns") and "Earnings Date" in cal.columns:
            ed = cal["Earnings Date"].iloc[0]
            if hasattr(ed, "date"):
                days = (ed.date() - date.today()).days
                if 0 <= days <= 7:
                    upcoming.append(sym)
                    print(f"  {sym}: om {days} dagar — IKKJE KJOEP")
    except Exception:
        pass
if not upcoming:
    print("  Ingen i watchlisten")
knowledge["ikke_kjoep"] = upcoming

# --- Per symbol ---
print("\n=== AKSJEDATA ===")
per_symbol: dict = {}
for sym in config.WATCHLIST:
    try:
        t = yf.Ticker(sym)
        info = t.info
        price = info.get("currentPrice") or info.get("regularMarketPrice", 0) or 0
        target = info.get("targetMeanPrice") or 0
        upside = ((target / price) - 1) * 100 if price and target else 0
        pe = info.get("forwardPE") or info.get("trailingPE", "N/A")
        w52h = info.get("fiftyTwoWeekHigh") or 0
        w52l = info.get("fiftyTwoWeekLow") or 0
        pct_high = ((price / w52h) - 1) * 100 if w52h else 0
        rec = str(info.get("recommendationKey", "N/A"))
        news_titles = [n.get("title", "") for n in t.news[:4]]

        print(f"\n{sym} @ ${price:.2f}")
        print(f"  P/E:{pe}  mål:${target:.2f} ({upside:+.1f}%)  rec:{rec.upper()}")
        print(f"  52V: ${w52l:.2f}–${w52h:.2f}  (frå topp: {pct_high:.1f}%)")
        if sym in upcoming:
            print(f"  *** EARNINGS SNART — BLOKKERT ***")
        for h in news_titles[:3]:
            print(f"  - {h}")

        per_symbol[sym] = {
            "price": price, "pe": pe, "target": target,
            "upside_pct": round(upside, 1), "pct_from_52h": round(pct_high, 1),
            "rec": rec, "news": news_titles,
        }
    except Exception as e:
        print(f"{sym}: feil — {e}")

knowledge["per_symbol"] = per_symbol

# --- Lagre rapport ---
outdir = Path(__file__).parent / "knowledge"
outdir.mkdir(exist_ok=True)
outfile = outdir / f"report_{date.today()}.json"
with open(outfile, "w", encoding="utf-8") as f:
    json.dump(knowledge, f, indent=2, default=str)
print(f"\nKnowledge lagra: {outfile}")

# Skriv ut JSON slik at Claude-agenten i rutinen ser heile strukturen
print("\n=== KNOWLEDGE JSON ===")
print(json.dumps(knowledge, indent=2, default=str))

# --- Git commit (viss --commit) ---
if "--commit" in sys.argv:
    os.system('git config user.email "bullbot-routine@noreply"')
    os.system('git config user.name "Bullbot Routine"')
    os.system("git add knowledge/")
    os.system(f'git commit -m "research: dagleg rapport {date.today()}"')
    os.system("git push")
    print("Committed og push til repo.")
