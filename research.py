"""
bullbot research — køyr som: python research.py [--commit]
Hentar data frå Yahoo Finance, Finnhub, FRED, Alpha Vantage og Reddit/WSB.
Lagar komplett marknadsrapport og sender dagsstrategi til Discord.
"""
import subprocess, sys, json, os, re, xml.etree.ElementTree as ET, time
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from collections import Counter  # noqa: F401  (kept for possible future use)

# Windows-terminalen støttar ikkje alle Unicode-teikn — bruk UTF-8 med erstatning
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

import yfinance as yf
import requests
import config

FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
FRED_KEY    = os.getenv("FRED_API_KEY", "")
AV_KEY      = os.getenv("ALPHAVANTAGE_API_KEY", "")

knowledge: dict = {
    "dato":      str(date.today()),
    "timestamp": datetime.now(timezone.utc).isoformat(),
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; bullbot/1.0)"})


# ── HJELPEFUNKSJONAR ──────────────────────────────────────────────────────────

def _news_title(item: dict) -> str:
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


def _rss_headlines(url: str, label: str, max_items: int = 5) -> list:
    try:
        r = SESSION.get(url, timeout=8)
        root = ET.fromstring(r.content)
        titles = [
            item.findtext("title", "").strip()
            for item in root.findall(".//item")[:max_items]
        ]
        titles = [t for t in titles if t]
        print(f"  {label}: {len(titles)} nyheter")
        return titles
    except Exception as e:
        print(f"  {label}: N/A ({e})")
        return []


def _finnhub(endpoint: str, params: dict = None):
    if not FINNHUB_KEY:
        return {}
    try:
        r = SESSION.get(
            f"https://finnhub.io/api/v1/{endpoint}",
            params={"token": FINNHUB_KEY, **(params or {})},
            timeout=10,
        )
        return r.json()
    except Exception as e:
        print(f"  Finnhub /{endpoint}: {e}")
        return {}


def _fred(series_id: str):
    if not FRED_KEY:
        return None
    try:
        r = SESSION.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key":   FRED_KEY,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 3,
            },
            timeout=10,
        )
        obs = [o for o in r.json().get("observations", []) if o["value"] != "."]
        return float(obs[0]["value"]) if obs else None
    except Exception as e:
        print(f"  FRED {series_id}: {e}")
        return None


# Kva subreddits vi overvaker og kva "type" dei representerer
_REDDIT_SUBS = {
    "wallstreetbets": "momentum",   # hype, kortsiktig
    "stocks":         "balanced",   # generell marknad
    "investing":      "balanced",   # medium-sikt
    "valueinvesting": "value",      # fundamentalt, langsiktig
}

# Mønster for kjøps- og salssignal i titlar
_BUY_RE  = re.compile(
    r"\b(buy|long|bull(?:ish)?|DD|loading|undervalued|bargain|"
    r"price.?target|moon|calls?|entry|accumulate|adding)\b",
    re.IGNORECASE,
)
_SELL_RE = re.compile(
    r"\b(sell|short|bear(?:ish)?|overvalued|puts?|crash|dump|"
    r"avoid|exit|trim|warning|danger)\b",
    re.IGNORECASE,
)


def _reddit_sentiment(limit: int = 50) -> dict:
    """
    Hentar hot- og new-innlegg frå fire subreddits.
    Returnerer dict: symbol -> {mentions, buy, sell, hype, value, sentiment, subs}
    """
    watchset = set(config.WATCHLIST)
    raw: dict = {}   # sym -> {mentions, buy, sell, subs: set, types: set}

    def _process(sub: str, sub_type: str, posts: list) -> None:
        for post in posts:
            p        = post.get("data", {})
            title    = p.get("title", "")
            selftext = p.get("selftext", "")[:400]
            flair    = (p.get("link_flair_text") or "").lower()
            text     = f"{title} {selftext}"

            found = re.findall(r"\$([A-Z]{2,5})\b|\b([A-Z]{2,5})\b", text)
            post_syms = {(g1 or g2) for g1, g2 in found if (g1 or g2) in watchset}
            if not post_syms:
                continue

            # DD-flair teller som buy-signal uansett ordval
            is_buy  = bool(_BUY_RE.search(title)) or flair in ("dd", "due diligence", "bullish")
            is_sell = bool(_SELL_RE.search(title))

            for sym in post_syms:
                if sym not in raw:
                    raw[sym] = {"mentions": 0, "buy": 0, "sell": 0,
                                "subs": set(), "types": set()}
                raw[sym]["mentions"] += 1
                raw[sym]["subs"].add(sub)
                raw[sym]["types"].add(sub_type)
                if is_buy:
                    raw[sym]["buy"] += 1
                if is_sell:
                    raw[sym]["sell"] += 1

    # wallstreetbets: hot + new (mest relevant for hype-signal)
    # dei andre: berre hot
    feeds = {
        "wallstreetbets": ("hot", "new"),
        "stocks":         ("hot",),
        "investing":      ("hot",),
        "valueinvesting": ("hot",),
    }
    for sub, sub_type in _REDDIT_SUBS.items():
        for feed in feeds.get(sub, ("hot",)):
            try:
                r = requests.get(
                    f"https://www.reddit.com/r/{sub}/{feed}.json",
                    params={"limit": limit},
                    headers={"User-Agent": "bullbot/1.0 (research)"},
                    timeout=12,
                )
                posts = r.json()["data"]["children"]
                _process(sub, sub_type, posts)
                print(f"  r/{sub}/{feed}: {len(posts)} innlegg")
            except Exception as e:
                print(f"  Reddit r/{sub}/{feed}: {e}")

    # Bygg endeleg resultat
    result = {}
    for sym, d in raw.items():
        buy, sell = d["buy"], d["sell"]
        if buy > sell * 2:
            sentiment = "BULLISH"
        elif sell > buy * 2 and sell > 0:
            sentiment = "BEARISH"
        else:
            sentiment = "NOEYTRAL"
        result[sym] = {
            "mentions":  d["mentions"],
            "buy":       buy,
            "sell":      sell,
            "sentiment": sentiment,
            "hype":      "momentum" in d["types"],
            "value":     "value"    in d["types"],
            "subs":      sorted(d["subs"]),
        }
    return result


def _hold_period(rec: str, upside: float, mom: float, reddit: dict) -> str:
    """Estimert haldetid basert på handelstype og signal-styrke."""
    mentions = reddit.get("mentions", 0)
    is_hype  = reddit.get("hype", False)
    buy_sigs = reddit.get("buy", 0)

    if abs(mom) >= config.MOMENTUM_MIN_DAY_PCT:
        return "1-3 dagar (momentum)"
    if is_hype and mentions >= 5 and buy_sigs >= 2 and upside < 15:
        return "1-3 dagar (WSB hype)"
    if buy_sigs >= 3 and reddit.get("value", False):
        return "2-4 veker (Reddit value pick)"
    if "strong_buy" in rec and upside > 20:
        return "1-3 veker (fundamentalt)"
    if "strong_buy" in rec or upside > 20:
        return "5-10 dagar"
    if "buy" in rec and upside > 10:
        return "3-7 dagar"
    return "3-5 dagar"


def _build_grunn(rec: str, upside: float, sb: int, mom: float,
                 reddit: dict, news: list) -> str:
    """Bygg kort grunngjeving frå tilgjengelege signal."""
    mentions = reddit.get("mentions", 0)
    buy_sigs = reddit.get("buy", 0)
    is_hype  = reddit.get("hype", False)
    is_value = reddit.get("value", False)

    parts = []
    if "strong_buy" in rec:
        parts.append("konsensus STRONG BUY")
    elif "buy" in rec:
        parts.append("analytikar: BUY")
    if upside > 5:
        parts.append(f"+{upside:.0f}% analytikarmål")
    if sb >= 5:
        parts.append(f"{sb} SB-analytik.")
    if abs(mom) >= config.MOMENTUM_MIN_DAY_PCT:
        parts.append(f"momentum {mom:+.1f}%")
    if buy_sigs >= 2:
        label = "WSB buy" if is_hype else ("value-pick" if is_value else "Reddit buy")
        parts.append(f"{label} x{buy_sigs}")
    elif mentions >= 5:
        parts.append(f"Reddit x{mentions} nemn.")
    if news and len(parts) < 4:
        parts.append(f'"{news[0][:45]}"')
    return " | ".join(parts)


def _alpaca_portfolio(per_symbol: dict, upcoming: list, scores: dict) -> list:
    """Hentar nåverande posisjonar frå Alpaca og vurderer kvar enkelt."""
    try:
        from alpaca.trading.client import TradingClient
        tc = TradingClient(
            os.getenv("ALPACA_API_KEY", ""),
            os.getenv("ALPACA_SECRET_KEY", ""),
            paper=os.getenv("ALPACA_MODE", "paper").lower() in ("paper", "true", "1"),
        )
        positions = tc.get_all_positions()
    except Exception as e:
        print(f"  Alpaca portfolio: {e}")
        return []

    result = []
    for p in positions:
        sym    = p.symbol
        pl_pct = float(p.unrealized_plpc) * 100
        pl_usd = float(p.unrealized_pl)
        qty    = int(float(p.qty))
        d      = per_symbol.get(sym, {})
        rec    = d.get("rec", "").lower()
        upside = d.get("upside_pct", 0)
        news   = d.get("news", [])
        score  = scores.get(sym, 0)

        if sym in upcoming:
            action = "SELG"
            grunn  = "Earnings snart — unngå kvartalssurprise-risiko"
        elif pl_pct >= 5 and score < 0:
            action = "VURDER SAL"
            grunn  = f"God gevinst ({pl_pct:.1f}%) men svak score — sikre noko av gevinsten"
        elif pl_pct >= 0 and ("strong_buy" in rec or "buy" in rec):
            action = "HALD"
            g_parts = [f"{rec.replace('_',' ').upper()}"]
            if upside > 5:
                g_parts.append(f"+{upside:.0f}% analytikarmål")
            if news:
                g_parts.append(f'"{news[0][:40]}"')
            grunn = " | ".join(g_parts)
        elif pl_pct <= -1.5:
            action = "MONITOR"
            grunn  = "Nærmar seg stop-loss — følg nøye"
        elif pl_pct >= 0:
            action = "HALD"
            grunn  = "Stabil posisjon — ingen klart exit-signal"
        else:
            action = "HALD"
            grunn  = "Ventar på betring eller stop-loss-utløysing"

        result.append({
            "symbol": sym,
            "qty":    qty,
            "pl_pct": round(pl_pct, 2),
            "pl_usd": round(pl_usd, 2),
            "action": action,
            "grunn":  grunn,
        })

    return sorted(result, key=lambda x: x["pl_pct"], reverse=True)


# Sektor-ETF kart — grøn energi (XLU, ICLN, TAN) er bevisst ekskludert
_SEKTOR_ETF = {
    "Teknologi":          "XLK",
    "Finans":             "XLF",
    "Helse":              "XLV",
    "Konsum (syklisk)":   "XLY",
    "Konsum (defensiv)":  "XLP",
    "Energi (olje/gass)": "XLE",
    "Industri":           "XLI",
    "Materialar":         "XLB",
    "Kommunikasjon":      "XLC",
    "Eigedom":            "XLRE",
    "Krypto-relatert":    "BITO",
}

_SEKTOR_AKSJAR = {
    "XLK":  ["NVDA", "MSFT", "AAPL", "AVGO", "AMD", "QCOM", "ARM", "MU"],
    "XLF":  ["JPM", "GS", "MS", "BLK", "V", "MA", "COIN", "HOOD"],
    "XLV":  ["LLY", "UNH", "ISRG", "ABBV", "MRNA", "HIMS", "TDOC"],
    "XLY":  ["AMZN", "TSLA", "BKNG", "ABNB", "SHOP", "ETSY", "DUOL"],
    "XLP":  ["WMT", "COST", "PG", "KO", "CELH"],
    "XLE":  ["XOM", "CVX", "COP", "SLB", "EOG"],
    "XLI":  ["CAT", "GE", "RTX", "DE", "UPS", "RKLB"],
    "XLB":  ["FCX", "NEM", "LIN", "APD", "ALB"],
    "XLC":  ["META", "GOOGL", "NFLX", "SNAP", "PINS", "SPOT"],
    "XLRE": ["EQIX", "AMT", "PLD", "SPG"],
    "BITO": ["MSTR", "COIN", "RIOT", "MARA", "HUT", "CLSK"],
}


def _scan_sectors() -> list:
    """
    Scorar kvar sektor basert på ETF-momentum (1V, 1M, 3M).
    Returnerer liste sortert etter score (beste øvst).
    Score = 0.5*w1 + 0.3*m1 + 0.2*m3 (vekta mot kortsiktig)
    """
    print("\n=== SEKTORANALYSE ===")
    results = []
    etfs = list(_SEKTOR_ETF.values())
    try:
        data = yf.download(etfs, period="3mo", auto_adjust=True, progress=False)["Close"]
    except Exception as e:
        print(f"  Sektordata: N/A ({e})")
        return []

    for namn, etf in _SEKTOR_ETF.items():
        try:
            hist = data[etf].dropna()
            if len(hist) < 5:
                continue
            p_now = float(hist.iloc[-1])
            p_1w  = float(hist.iloc[-6])  if len(hist) >= 6  else p_now
            p_1m  = float(hist.iloc[-22]) if len(hist) >= 22 else float(hist.iloc[0])
            p_3m  = float(hist.iloc[0])

            w1 = (p_now / p_1w - 1) * 100
            m1 = (p_now / p_1m - 1) * 100
            m3 = (p_now / p_3m - 1) * 100
            score = 0.5 * w1 + 0.3 * m1 + 0.2 * m3

            top_sym = _SEKTOR_AKSJAR.get(etf, [])[:4]
            results.append({
                "namn":    namn,
                "etf":     etf,
                "score":   round(score, 2),
                "w1_pct":  round(w1, 2),
                "m1_pct":  round(m1, 2),
                "m3_pct":  round(m3, 2),
                "aksjar":  top_sym,
            })
            trend = "+" if score > 0 else ""
            print(f"  {namn:22s} {etf}: score={trend}{score:.1f}  1V={w1:+.1f}%  1M={m1:+.1f}%")
        except Exception as e:
            print(f"  {namn}: {e}")

    return sorted(results, key=lambda x: x["score"], reverse=True)


def _generate_strategy(knowledge: dict, per_symbol: dict,
                        momentum_candidates: list, upcoming: list,
                        reddit_data: dict, upcoming_dates: dict = None) -> dict:
    fg    = knowledge.get("fear_greed", {}).get("score", 50)
    vix   = knowledge.get("vix", 20)
    spy   = knowledge.get("spy", {}).get("day_pct", 0)
    macro = knowledge.get("macro", {})

    # Overordna marknadsvurdering
    if fg >= 60 and vix < 20 and spy >= -0.5:
        market = "BULLISH"
    elif fg <= 35 or vix > 28 or spy < -1.5:
        market = "BEARISH"
    else:
        market = "NOEYTRAL"

    scores:      dict = {}
    neg_reasons: dict = {}

    for sym, d in per_symbol.items():
        s  = 0.0
        rp = []

        rec = d.get("rec", "").lower()
        if "strong_buy" in rec:
            s += 3; rp.append("strong buy")
        elif "buy" in rec:
            s += 2; rp.append("buy")
        elif "sell" in rec or "underperform" in rec:
            s -= 2; rp.append("sell-signal")

        upside = d.get("upside_pct", 0)
        if upside > 20:
            s += 2
        elif upside > 10:
            s += 1
        elif upside < -5:
            s -= 1; rp.append(f"negativ upside {upside:.0f}%")

        sb = d.get("finnhub_strong_buy", 0)
        if sb >= 5:
            s += 1

        mom = d.get("momentum_dag_pct", 0)
        if mom >= config.MOMENTUM_MIN_DAY_PCT:
            s += 2
        elif mom <= -config.MOMENTUM_MIN_DAY_PCT:
            s -= 2; rp.append(f"ned {mom:+.1f}% i dag")

        if sym in upcoming:
            # Tillat pre-earnings kjøp om signalane er sterkt bullish
            rec_e   = d.get("rec", "").lower()
            up_e    = d.get("upside_pct", 0)
            sb_e    = d.get("finnhub_strong_buy", 0)
            r_buy_e = reddit_data.get(sym, {}).get("buy", 0)
            if "strong_buy" in rec_e and up_e > 10 and sb_e >= 8:
                s -= 1; rp.append("pre-earnings bullish")
            elif "buy" in rec_e and (up_e > 5 or r_buy_e >= 2):
                s -= 2; rp.append("pre-earnings (kjøpsrisiko)")
            else:
                s -= 4; rp.append("earnings — usikker rapport")

        # Reddit-signal: buy-signal veg tyngre enn reine nemningar
        r = reddit_data.get(sym, {})
        r_buy  = r.get("buy", 0)
        r_sell = r.get("sell", 0)
        r_men  = r.get("mentions", 0)
        if r_buy >= 2:
            s += min(2.5, r_buy * 0.7)
        elif r_men >= 5:
            s += min(1.0, r_men * 0.15)
        if r_sell >= 3:
            s -= min(1.5, r_sell * 0.5); rp.append(f"Reddit sell x{r_sell}")

        if market == "BEARISH":
            s -= 1

        scores[sym]      = round(s, 1)
        neg_reasons[sym] = ", ".join(rp) if rp else "låg score"

    sorted_syms = sorted(scores, key=lambda x: scores[x], reverse=True)

    kjoep:    list = []
    unngaa:   list = []
    momentum: list = []

    _dates = upcoming_dates or {}

    for sym in sorted_syms:
        d               = per_symbol.get(sym, {})
        rec_l           = d.get("rec", "").lower()
        upside          = d.get("upside_pct", 0)
        sb              = d.get("finnhub_strong_buy", 0)
        mom             = d.get("momentum_dag_pct", 0)
        reddit          = reddit_data.get(sym, {})
        news            = d.get("news", [])
        is_pre_earnings = sym in upcoming
        ed_date         = _dates.get(sym, "snart")

        if scores[sym] >= 3 and len(kjoep) < 6:
            grunn_str = _build_grunn(rec_l, upside, sb, mom, reddit, news)
            if is_pre_earnings:
                grunn_str += f" | Rapport {ed_date} — tar sjansen"
            kjoep.append({
                "symbol":       sym,
                "rec":          d.get("rec", "N/A").upper(),
                "upside_pct":   round(upside, 1),
                "grunn":        grunn_str,
                "hald":         f"Selje etter rapport {ed_date}" if is_pre_earnings
                                else _hold_period(rec_l, upside, mom, reddit),
                "score":        scores[sym],
                "pre_earnings": is_pre_earnings,
            })
        elif is_pre_earnings and scores[sym] < 3 and len(unngaa) < 6:
            unngaa.append({
                "symbol": sym,
                "grunn":  f"Earnings {ed_date} — ikkje nok bullish signal",
            })
        elif scores[sym] <= -3 and len(unngaa) < 6:
            unngaa.append({
                "symbol": sym,
                "grunn":  neg_reasons[sym],
            })

    for m in momentum_candidates:
        if m["symbol"] not in upcoming:
            momentum.append({
                "symbol":  m["symbol"],
                "day_pct": m["day_pct"],
                "grunn":   f"Intradag hopp {m['day_pct']:+.1f}% — kortsiktig momentum-handel",
                "hald":    "1-2 dagar",
            })

    # Reddit-radar: topp-aksjar frå Reddit som ikkje er i kjøp-lista
    kjoep_syms   = {item["symbol"] for item in kjoep}
    radar_sorted = sorted(
        [(s, d) for s, d in reddit_data.items() if s not in kjoep_syms],
        key=lambda x: x[1]["buy"] * 3 + x[1]["mentions"],
        reverse=True,
    )
    reddit_radar = [
        {
            "symbol":    sym,
            "mentions":  d["mentions"],
            "buy":       d["buy"],
            "sell":      d["sell"],
            "sentiment": d["sentiment"],
            "hype":      d["hype"],
            "value":     d["value"],
        }
        for sym, d in radar_sorted[:8]
        if d["buy"] >= 1 or d["mentions"] >= 3
    ]

    # Marknadsnote: makro + toppnyheit + Reddit hot picks
    note_parts = []
    if macro.get("fedfunds"):
        note_parts.append(f"Fed Funds: {macro['fedfunds']:.2f}%")
    if macro.get("dgs10"):
        note_parts.append(f"10Y: {macro['dgs10']:.2f}%")
    market_news = knowledge.get("market_news", [])
    if market_news:
        note_parts.append(market_news[0][:80])
    top_radar = [r["symbol"] for r in reddit_radar[:3]]
    if top_radar:
        note_parts.append(f"Reddit: {', '.join(top_radar)}")

    # Portefølje-vurdering frå Alpaca
    print("\n=== NÅVERANDE PORTEFOLJE ===")
    portfolio = _alpaca_portfolio(per_symbol, upcoming, scores)
    for item in portfolio:
        bar = "▲" if item["pl_pct"] >= 0 else "▼"
        print(f"  {bar} {item['symbol']}: {item['pl_pct']:+.1f}%  →  {item['action']}")
    if not portfolio:
        print("  Ingen opne posisjonar")

    sektorar     = knowledge.get("sektorar", [])
    topp_sekt    = sektorar[:3] if sektorar else []
    bunn_sekt    = sektorar[-2:] if len(sektorar) >= 5 else []

    return {
        "marknad":      market,
        "fear_greed":   fg,
        "vix":          vix,
        "portfolio":    portfolio,
        "kjoep":        kjoep,
        "unngaa":       unngaa,
        "momentum":     momentum,
        "reddit_radar": reddit_radar,
        "marknadsnote": "  |  ".join(note_parts[:3]),
        "er_kveld":     datetime.now(timezone.utc).hour >= 20,
        "topp_sektorar": topp_sekt,
        "svake_sektorar": bunn_sekt,
    }


# ── MARKNADSSENTIMENT ────────────────────────────────────────────────────────
print("=== MARKNADSSENTIMENT ===")

try:
    resp     = SESSION.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", timeout=10)
    fg_data  = resp.json()["fear_and_greed"]
    fg_score = float(fg_data["score"])
    print(f"CNN Fear & Greed: {fg_score:.0f}/100 ({fg_data['rating']})")
    knowledge["fear_greed"] = {"score": fg_score, "rating": fg_data["rating"]}
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
    spy_chg  = (float(spy_hist.iloc[-1]) / float(spy_hist.iloc[-2]) - 1) * 100
    spy_w    = (float(spy_hist.iloc[-1]) / float(spy_hist.iloc[0])  - 1) * 100
    print(f"SPY: ${float(spy_hist.iloc[-1]):.2f}  dag={spy_chg:+.2f}%  veke={spy_w:+.2f}%")
    knowledge["spy"] = {"price": float(spy_hist.iloc[-1]), "day_pct": spy_chg, "week_pct": spy_w}
except Exception as e:
    print(f"SPY: N/A ({e})")


# ── MAKRODATA (FRED) ─────────────────────────────────────────────────────────
print("\n=== MAKRODATA (FRED) ===")
macro: dict = {}
for series_id, label in [
    ("FEDFUNDS", "Fed Funds Rate"),
    ("DGS10",    "10-åring Treasury"),
    ("CPIAUCSL", "CPI (siste)"),
    ("UNRATE",   "Arbeidsløyse"),
]:
    val = _fred(series_id)
    if val is not None:
        print(f"  {label}: {val:.2f}%")
        macro[series_id.lower()] = val
knowledge["macro"] = macro


# ── MARKNADSNYHETER ───────────────────────────────────────────────────────────
print("\n=== MARKNADSNYHETER ===")

reuters_news = _rss_headlines("https://feeds.reuters.com/reuters/businessNews", "Reuters")
mw_news      = _rss_headlines("https://feeds.marketwatch.com/marketwatch/topstories/", "MarketWatch")
yf_news      = _rss_headlines("https://finance.yahoo.com/news/rssindex", "Yahoo Finance")

fh_news: list = []
fh_data = _finnhub("news", {"category": "general"})
if isinstance(fh_data, list):
    for item in fh_data[:6]:
        t = item.get("headline", "")
        if t:
            fh_news.append(t)
    print(f"  Finnhub news: {len(fh_news)} nyheter")

all_market_news = reuters_news + mw_news + yf_news + fh_news
knowledge["market_news"] = all_market_news[:12]
for h in all_market_news[:5]:
    print(f"  • {h[:90]}")

# Alpha Vantage — overordna marknadsentiment (1 kall)
if AV_KEY:
    try:
        r = SESSION.get(
            "https://www.alphavantage.co/query",
            params={"function": "NEWS_SENTIMENT", "apikey": AV_KEY,
                    "sort": "LATEST", "limit": 10},
            timeout=15,
        )
        av_feed = r.json().get("feed", [])
        scores_av = [float(i.get("overall_sentiment_score", 0)) for i in av_feed if i.get("title")]
        if scores_av:
            avg = sum(scores_av) / len(scores_av)
            direction = "BULLISH" if avg > 0.1 else ("BEARISH" if avg < -0.1 else "NOEYTRAL")
            print(f"  Alpha Vantage sentiment: {avg:.3f} ({direction})")
            knowledge["av_sentiment"] = {"score": round(avg, 4), "direction": direction}
    except Exception as e:
        print(f"  Alpha Vantage: {e}")


# ── REDDIT SENTIMENT ─────────────────────────────────────────────────────────
print("\n=== REDDIT SENTIMENT (4 subreddits) ===")
reddit_data = _reddit_sentiment(limit=50)

if reddit_data:
    sorted_reddit = sorted(
        reddit_data.items(),
        key=lambda x: x[1]["buy"] * 2 + x[1]["mentions"],
        reverse=True,
    )
    for sym, d in sorted_reddit[:12]:
        tags = []
        if d["hype"]:  tags.append("WSB-hype")
        if d["value"]: tags.append("value-pick")
        senti_icon = {"BULLISH": "+", "BEARISH": "-", "NOEYTRAL": "~"}[d["sentiment"]]
        buy_str  = f"  {d['buy']} buy"  if d["buy"]  else ""
        sell_str = f"  {d['sell']} sell" if d["sell"] else ""
        tag_str  = f"  [{', '.join(tags)}]" if tags else ""
        print(f"  {senti_icon} {sym}: {d['mentions']} nemn.{buy_str}{sell_str}{tag_str}")
else:
    print("  Ingen watchlist-aksjar funne i dag")

knowledge["reddit"] = reddit_data


# ── EARNINGS KALENDER ────────────────────────────────────────────────────────
print("\n=== EARNINGS NESTE 7 DAGAR ===")
upcoming_dates: dict = {}   # sym -> date string
today = date.today()

fh_cal = _finnhub("calendar/earnings", {
    "from": str(today),
    "to":   str(today + timedelta(days=7)),
})
if isinstance(fh_cal, dict):
    for item in fh_cal.get("earningsCalendar", []):
        sym = item.get("symbol", "")
        if sym in config.WATCHLIST and sym not in upcoming_dates:
            ed_str = item.get("date", "?")
            upcoming_dates[sym] = ed_str
            print(f"  {sym}: {ed_str} (Finnhub)")

# yfinance-fallback for symbol Finnhub mista
for sym in config.WATCHLIST:
    if sym in upcoming_dates:
        continue
    try:
        cal = yf.Ticker(sym).calendar
        if cal is not None and hasattr(cal, "columns") and "Earnings Date" in cal.columns:
            ed = cal["Earnings Date"].iloc[0]
            if hasattr(ed, "date"):
                days = (ed.date() - today).days
                if 0 <= days <= 7:
                    upcoming_dates[sym] = str(ed.date())
                    print(f"  {sym}: {ed.date()} (yf, om {days} dagar)")
    except Exception:
        pass

upcoming = list(upcoming_dates.keys())
if not upcoming:
    print("  Ingen i watchlisten")
knowledge["ikke_kjoep"]     = upcoming
knowledge["upcoming_dates"] = upcoming_dates


# ── MOMENTUM-SCAN ─────────────────────────────────────────────────────────────
print("\n=== MOMENTUM-KANDIDATAR (>4% i dag) ===")
momentum_candidates: list = []

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


# ── PER SYMBOL ────────────────────────────────────────────────────────────────
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

        raw_news    = t.news[:5] if t.news else []
        news_titles = [_news_title(n) for n in raw_news]
        news_titles = [h for h in news_titles if h]

        # Finnhub analytikar-konsensus
        finnhub_strong_buy = 0
        fh_rec = _finnhub("stock/recommendation", {"symbol": sym})
        if isinstance(fh_rec, list) and fh_rec:
            finnhub_strong_buy = fh_rec[0].get("strongBuy", 0)
        time.sleep(0.05)  # stay under Finnhub rate limit

        mom = next((m for m in momentum_candidates if m["symbol"] == sym), None)

        print(f"\n{sym} @ ${price:.2f}")
        print(f"  P/E:{pe}  mål:${target:.2f} ({upside:+.1f}%)  rec:{rec.upper()}"
              + (f"  SB:{finnhub_strong_buy}" if finnhub_strong_buy else ""))
        print(f"  52V: ${w52l:.2f}–${w52h:.2f}  (frå topp: {pct_h:.1f}%)")
        rd = reddit_data.get(sym, {})
        if rd.get("mentions", 0) >= 2:
            tags = []
            if rd.get("hype"):  tags.append("WSB-hype")
            if rd.get("value"): tags.append("value-pick")
            print(f"  [Reddit] {rd['mentions']} nemn. | {rd['sentiment']}"
                  + (f" | {', '.join(tags)}" if tags else "")
                  + (f" | {rd['buy']} buy" if rd.get("buy") else ""))
        if mom:
            print(f"  🚀 MOMENTUM: {mom['day_pct']:+.1f}% i dag")
        if sym in upcoming_dates:
            print(f"  ⚠️  EARNINGS: {upcoming_dates[sym]}")
        for h in news_titles[:2]:
            print(f"  • {h[:80]}")

        per_symbol[sym] = {
            "price":              price,
            "pe":                 pe,
            "target":             target,
            "upside_pct":         round(upside, 1),
            "pct_from_52h":       round(pct_h, 1),
            "rec":                rec,
            "news":               news_titles,
            "momentum_dag_pct":   mom["day_pct"] if mom else 0.0,
            "finnhub_strong_buy": finnhub_strong_buy,
            "reddit":             reddit_data.get(sym, {}),
        }
    except Exception as e:
        print(f"{sym}: feil — {e}")

knowledge["per_symbol"] = per_symbol


# ── SEKTORANALYSE ─────────────────────────────────────────────────────────────
sektorar = _scan_sectors()
knowledge["sektorar"] = sektorar


# ── STRATEGI ──────────────────────────────────────────────────────────────────
print("\n=== DAGSSTRATEGI ===")
strategy = _generate_strategy(knowledge, per_symbol, momentum_candidates, upcoming, reddit_data, upcoming_dates)
knowledge["strategi"] = strategy

print(f"Marknad:   {strategy['marknad']}  (F&G={strategy['fear_greed']:.0f}  VIX={strategy['vix']:.1f})")
print(f"Kjøp ({len(strategy['kjoep'])}):    {strategy['kjoep']}")
print(f"Unngå ({len(strategy['unngaa'])}):  {strategy['unngaa']}")
print(f"Momentum ({len(strategy['momentum'])}): {strategy['momentum']}")
print(f"Note: {strategy['marknadsnote']}")

try:
    script  = Path(__file__).parent / "scripts" / "send_strategy.py"
    payload = json.dumps(strategy)
    result  = subprocess.run(
        [sys.executable, str(script), payload],
        capture_output=True, text=True, timeout=30,
    )
    print(result.stdout.strip() or result.stderr.strip())
except Exception as e:
    print(f"Discord strategi: feil — {e}")


# ── LAGRE ─────────────────────────────────────────────────────────────────────
outdir  = Path(__file__).parent / "knowledge"
outdir.mkdir(exist_ok=True)
outfile = outdir / f"report_{date.today()}.json"
with open(outfile, "w", encoding="utf-8") as f:
    json.dump(knowledge, f, indent=2, default=str)
print(f"\nKnowledge lagra: {outfile}")
print(f"Momentum-kandidatar: {[m['symbol'] for m in momentum_candidates]}")
print(f"Ikkje kjøp: {upcoming}")


# ── GIT COMMIT ────────────────────────────────────────────────────────────────
if "--commit" in sys.argv:
    os.system('git config user.email "bullbot-routine@noreply"')
    os.system('git config user.name "Bullbot Routine"')
    os.system("git add knowledge/")
    os.system(f'git commit -m "research: dagleg rapport {date.today()}"')
    os.system("git push")
    print("Committed og push til repo.")
