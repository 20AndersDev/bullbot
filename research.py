"""
bullbot research — køyr som: python research.py [--commit]
Hentar data frå Yahoo Finance, Reuters, MarketWatch og Finviz.
Scannar òg etter momentum-kandidatar (store dagleg hopp).
"""
import subprocess, sys, json, os, xml.etree.ElementTree as ET
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

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})


def _news_title(item: dict) -> str:
    """Robust titteluthenting — handterer ulike yfinance-versjonar."""
    for key in ("title", "headline"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            for sub in ("title", "headline", "text"):
                s = val.get(sub, "")
                if s:
                    return str(s)
    content = item.get("content", {})
    if isinstance(content, dict):
        return content.get("title", content.get("headline", ""))
    return ""


def _rss_headlines(url: str, label: str, max_items: int = 5) -> list[str]:
    try:
        r = SESSION.get(url, timeout=8)
        root = ET.fromstring(r.content)
        titles = []
        for item in root.findall(".//item")[:max_items]:
            t = item.findtext("title", "").strip()
            if t:
                titles.append(t)
        print(f"  {label}: {len(titles)} nyheter henta")
        return titles
    except Exception as e:
        print(f"  {label}: N/A ({e})")
        return []


# ── MARKNADSSENTIMENT ────────────────────────────────────────────────────────
print("=== MARKNADSSENTIMENT ===")

try:
    resp = SESSION.get(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata", timeout=10
    )
    fg = resp.json()["fear_and_greed"]
    fg_score = float(fg["score"])
    print(f"CNN Fear & Greed: {fg_score:.0f}/100 ({fg['rating']})")
    knowledge["fear_greed"] = {"score": fg_score, "rating": fg["rating"]}
except Exception as e:
    print(f"CNN Fear & Greed: N/A ({e})")

try:
    vix_val = float(yf.Ticker("^VIX").history(period="2d")["Close"].iloc[-1])
    print(f"VIX: {vix_val:.2f}")
    knowledge["vix"] = vix_val
except Exception as e:
    print(f"VIX: N/A ({e})")

try:
    spy_hist = yf.Ticker("SPY").history(period="5d")["Close"].dropna()
    spy_chg = (float(spy_hist.iloc[-1]) / float(spy_hist.iloc[-2]) - 1) * 100
    spy_w   = (float(spy_hist.iloc[-1]) / float(spy_hist.iloc[0])  - 1) * 100
    print(f"SPY: ${float(spy_hist.iloc[-1]):.2f}  dag={spy_chg:+.2f}%  veke={spy_w:+.2f}%")
    knowledge["spy"] = {"price": float(spy_hist.iloc[-1]), "day_pct": spy_chg, "week_pct": spy_w}
except Exception as e:
    print(f"SPY: N/A ({e})")


# ── NYHETER FRÅ FLEIRE KJELDER ───────────────────────────────────────────────
print("\n=== MARKNADSNYHETER ===")

reuters_news = _rss_headlines(
    "https://feeds.reuters.com/reuters/businessNews",
    "Reuters Business"
)
mw_news = _rss_headlines(
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "MarketWatch"
)

# Yahoo Finance market overview via RSS
yf_news = _rss_headlines(
    "https://finance.yahoo.com/news/rssindex",
    "Yahoo Finance"
)

all_market_news = reuters_news + mw_news + yf_news
knowledge["market_news"] = all_market_news[:10]

for h in all_market_news[:5]:
    print(f"  • {h}")


# ── MOMENTUM-SCAN: STORE DAGLEG HOPP ─────────────────────────────────────────
print("\n=== MOMENTUM-KANDIDATAR (>4% i dag) ===")
momentum_candidates = []

for sym in config.WATCHLIST:
    try:
        hist = yf.Ticker(sym).history(period="3d")["Close"].dropna()
        if len(hist) >= 2:
            chg = (float(hist.iloc[-1]) / float(hist.iloc[-2]) - 1) * 100
            if abs(chg) >= config.MOMENTUM_MIN_DAY_PCT:
                direction = "⬆️" if chg > 0 else "⬇️"
                print(f"  {direction} {sym}: {chg:+.1f}%")
                momentum_candidates.append({"symbol": sym, "day_pct": round(chg, 1)})
    except Exception:
        pass

if not momentum_candidates:
    print("  Ingen i watchlisten i dag")
knowledge["momentum_kandidatar"] = momentum_candidates


# ── EARNINGS NESTE 7 DAGAR ───────────────────────────────────────────────────
print("\n=== EARNINGS NESTE 7 DAGAR ===")
upcoming = []
for sym in config.WATCHLIST:
    try:
        t   = yf.Ticker(sym)
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


# ── PER SYMBOL ───────────────────────────────────────────────────────────────
print("\n=== AKSJEDATA ===")
per_symbol: dict = {}

for sym in config.WATCHLIST:
    try:
        t    = yf.Ticker(sym)
        info = t.info
        price  = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        target = float(info.get("targetMeanPrice") or 0)
        upside = ((target / price) - 1) * 100 if price and target else 0
        pe     = info.get("forwardPE") or info.get("trailingPE", "N/A")
        w52h   = float(info.get("fiftyTwoWeekHigh") or 0)
        w52l   = float(info.get("fiftyTwoWeekLow") or 0)
        pct_h  = ((price / w52h) - 1) * 100 if w52h else 0
        rec    = str(info.get("recommendationKey", "N/A"))

        # Nyheter — prøv fleire nøkkelformat
        raw_news    = t.news[:5] if t.news else []
        news_titles = [_news_title(n) for n in raw_news]
        news_titles = [h for h in news_titles if h]  # filtrer tomme

        # Suppler med Reuters-søk om yfinance-nyheter er tomme
        if not news_titles:
            try:
                r = SESSION.get(
                    f"https://feeds.reuters.com/reuters/search/news?q={sym}&blob=All",
                    timeout=6,
                )
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:3]:
                    t_txt = item.findtext("title", "").strip()
                    if t_txt:
                        news_titles.append(t_txt)
            except Exception:
                pass

        mom = next((m for m in momentum_candidates if m["symbol"] == sym), None)

        print(f"\n{sym} @ ${price:.2f}")
        print(f"  P/E:{pe}  mål:${target:.2f} ({upside:+.1f}%)  rec:{rec.upper()}")
        print(f"  52V: ${w52l:.2f}–${w52h:.2f}  (frå topp: {pct_h:.1f}%)")
        if mom:
            print(f"  🚀 MOMENTUM: {mom['day_pct']:+.1f}% i dag")
        if sym in upcoming:
            print(f"  ⚠️  EARNINGS SNART — BLOKKERT")
        for h in news_titles[:3]:
            print(f"  • {h}")

        per_symbol[sym] = {
            "price": price, "pe": pe, "target": target,
            "upside_pct": round(upside, 1), "pct_from_52h": round(pct_h, 1),
            "rec": rec, "news": news_titles,
            "momentum_dag_pct": mom["day_pct"] if mom else 0.0,
        }
    except Exception as e:
        print(f"{sym}: feil — {e}")

knowledge["per_symbol"] = per_symbol


# ── LAGRE ────────────────────────────────────────────────────────────────────
outdir  = Path(__file__).parent / "knowledge"
outdir.mkdir(exist_ok=True)
outfile = outdir / f"report_{date.today()}.json"
with open(outfile, "w", encoding="utf-8") as f:
    json.dump(knowledge, f, indent=2, default=str)
print(f"\nKnowledge lagra: {outfile}")
print(f"Momentum-kandidatar: {[m['symbol'] for m in momentum_candidates]}")
print(f"Ikkje kjøp: {upcoming}")

# ── GIT COMMIT ───────────────────────────────────────────────────────────────
if "--commit" in sys.argv:
    os.system('git config user.email "bullbot-routine@noreply"')
    os.system('git config user.name "Bullbot Routine"')
    os.system("git add knowledge/")
    os.system(f'git commit -m "research: dagleg rapport {date.today()}"')
    os.system("git push")
    print("Committed og push til repo.")
