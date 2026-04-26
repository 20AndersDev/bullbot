"""
Bullbot Watchlist Optimizer
Køyrer kvar kveld etter US-børsstenging.

- Scorar alle aksjar på watchlisten frå knowledge-rapporten
- Fjernar aksjar med vedvarande svake signal (score < -3)
- Legg til nye lovande aksjar frå Reddit, Yahoo Finance gainers/most-active
- Validerer nye kandidatar med yfinance
- Committar endringar til GitHub og varslar Discord
"""
import json, os, sys, re
from pathlib import Path
from datetime import date
from dotenv import load_dotenv
load_dotenv()

import yfinance as yf
import requests

# ── KONFIGURASJON ─────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent.parent
WATCHLIST_FILE = BASE_DIR / "watchlist.json"
KNOWLEDGE_DIR  = BASE_DIR / "knowledge"
MAX_SIZE        = 100
REMOVE_MAX      = 8
ADD_MAX         = 8
REMOVE_SCORE    = -3.0   # score under dette = kandidat for fjerning
ADD_SCORE       = 2.0    # min score for å bli lagt til

# Desse fjernast aldri uansett signal
CORE = {
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL",
    "TSLA", "AMD", "JPM", "V", "CRWD", "PLTR", "COIN",
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; bullbot/1.0)"})

# ── LAST KNOWLEDGE ────────────────────────────────────────────────────────
reports = sorted(KNOWLEDGE_DIR.glob("report_*.json"), reverse=True)
if not reports:
    print("Ingen knowledge-rapport funne — avsluttar")
    sys.exit(0)

with open(reports[0]) as f:
    knowledge = json.load(f)

knowledge_date = knowledge.get("dato", "?")
print(f"=== WATCHLIST OPTIMIZER ===")
print(f"Brukar knowledge frå: {knowledge_date}")

# ── LAST WATCHLIST ────────────────────────────────────────────────────────
if WATCHLIST_FILE.exists():
    wl_data  = json.loads(WATCHLIST_FILE.read_text())
    current  = wl_data.get("symbols", [])
else:
    sys.path.insert(0, str(BASE_DIR))
    import config
    current = list(config.WATCHLIST)

current_set = set(current)
print(f"Nåverande watchlist: {len(current)} aksjar")


# ── SCORINGSFUNKSJON ──────────────────────────────────────────────────────
def score_sym(sym: str) -> float:
    d = knowledge.get("per_symbol", {}).get(sym, {})
    if not d:
        return 0.0
    s = 0.0
    rec = d.get("rec", "").lower()
    if "strong_buy" in rec:                     s += 3
    elif "buy" in rec:                          s += 2
    elif "sell" in rec or "underperform" in rec: s -= 2

    upside = d.get("upside_pct", 0)
    if upside > 20:   s += 2
    elif upside > 10: s += 1
    elif upside < -5: s -= 1

    if d.get("finnhub_strong_buy", 0) >= 8: s += 1

    mom = d.get("momentum_dag_pct", 0)
    if mom >= 4:    s += 2
    elif mom <= -4: s -= 1

    r = d.get("reddit", {})
    if r.get("buy", 0) >= 2:       s += 1
    elif r.get("mentions", 0) >= 5: s += 0.5

    return s


# ── SCORE ALLE OG FINN KANDIDATAR FOR FJERNING ───────────────────────────
scores = {sym: score_sym(sym) for sym in current}

sorted_by_score = sorted(
    [(sym, sc) for sym, sc in scores.items() if sym not in CORE],
    key=lambda x: x[1],
)

to_remove = []
for sym, sc in sorted_by_score:
    if len(to_remove) >= REMOVE_MAX:
        break
    d   = knowledge.get("per_symbol", {}).get(sym, {})
    rec = d.get("rec", "?").upper()
    if sc < REMOVE_SCORE:
        to_remove.append((sym, sc, rec))

print(f"\n--- Svake aksjar (score < {REMOVE_SCORE}) ---")
if to_remove:
    for sym, sc, rec in to_remove:
        print(f"  {sym}: score={sc:.1f}  {rec}")
else:
    print("  Ingen aksjar kvalifiserer for fjerning")


# ── FINN NYE KANDIDATAR ───────────────────────────────────────────────────
print("\n--- Søker etter nye kandidatar ---")
candidates = {}   # sym -> grunn

# 1. Reddit buy-signal utanfor watchlist
reddit_data = knowledge.get("reddit", {})
for sym, d in reddit_data.items():
    if sym not in current_set and d.get("buy", 0) >= 2:
        subs = ", ".join(d.get("subs", [])[:2])
        candidates[sym] = f"Reddit buy ×{d['buy']} ({subs})"

# 2. Yahoo Finance gainers og most-active
for scrId in ("day_gainers", "most_actives"):
    try:
        r = SESSION.get(
            "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved",
            params={"scrIds": scrId, "count": 25, "formatted": "false"},
            timeout=10,
        )
        quotes = r.json()["finance"]["result"][0]["quotes"]
        added_from_screen = 0
        for q in quotes:
            sym  = q.get("symbol", "")
            prc  = q.get("regularMarketPrice", 0)
            mkt  = q.get("marketCap", 0)
            chg  = q.get("regularMarketChangePercent", 0)
            if (sym and "." not in sym and len(sym) <= 5
                    and prc > 5 and mkt > 1_000_000_000
                    and sym not in current_set
                    and sym not in candidates):
                candidates[sym] = f"Yahoo {scrId}: {chg:+.1f}%"
                added_from_screen += 1
        print(f"  Yahoo {scrId}: {len(quotes)} henta, {added_from_screen} nye kandidatar")
    except Exception as e:
        print(f"  Yahoo {scrId}: {e}")

print(f"Totalt {len(candidates)} potensielle kandidatar")


# ── VALIDER NYE KANDIDATAR MED YFINANCE ──────────────────────────────────
def quick_score_new(sym: str):
    """Rask scoring av ein ny kandidat. Returnerer (score, detaljar) eller (None, grunn)."""
    try:
        info   = yf.Ticker(sym).info
        price  = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        mkt    = float(info.get("marketCap") or 0)
        rec    = str(info.get("recommendationKey", "")).lower()
        target = float(info.get("targetMeanPrice") or 0)
        upside = ((target / price) - 1) * 100 if price and target else 0
        n_anal = int(info.get("numberOfAnalystOpinions") or 0)

        if price < 5:
            return None, f"for billeg (${price:.2f})"
        if mkt < 500_000_000:
            return None, "mkt cap for liten"
        if "strong_sell" in rec:
            return None, "STRONG SELL konsensus"

        s = 0.0
        if "strong_buy" in rec: s += 3
        elif "buy" in rec:       s += 2
        if upside > 20:   s += 2
        elif upside > 10: s += 1
        if n_anal >= 10:  s += 1

        detail = f"${price:.0f}  {rec.upper()}  upside={upside:+.0f}%  {n_anal} analytik."
        return s, detail
    except Exception as e:
        return None, str(e)


print("\n--- Validerer kandidatar ---")
validated = []
checked   = 0
for sym, grunn in candidates.items():
    if checked >= 20:   # maks 20 API-kall for å halde farta
        break
    sc, detail = quick_score_new(sym)
    checked += 1
    if sc is not None and sc >= ADD_SCORE:
        validated.append((sym, sc, grunn, detail))
        print(f"  ✓ {sym}: score={sc:.1f}  {detail}")
    else:
        print(f"  ✗ {sym}: {detail}")

validated.sort(key=lambda x: x[1], reverse=True)
to_add = [(sym, grunn) for sym, sc, grunn, detail in validated[:ADD_MAX]]


# ── BYGG NY WATCHLIST ─────────────────────────────────────────────────────
remove_set = {sym for sym, _, _ in to_remove}
add_syms   = [sym for sym, _ in to_add]

new_watchlist = [sym for sym in current if sym not in remove_set] + add_syms
new_watchlist  = list(dict.fromkeys(new_watchlist))   # fjern duplikat, bevar rekkefølge
new_watchlist  = new_watchlist[:MAX_SIZE]             # hardt tak

print(f"\n=== RESULTAT ===")
print(f"  Fjerna:   {list(remove_set) or 'ingen'}")
print(f"  Lagt til: {add_syms or 'ingen'}")
print(f"  Ny storleik: {len(new_watchlist)}")


# ── LAGRE OG COMMIT ───────────────────────────────────────────────────────
if not remove_set and not add_syms:
    print("\nIngen endringar — watchlist er optimal i dag")
    sys.exit(0)

WATCHLIST_FILE.write_text(json.dumps({
    "updated": str(date.today()),
    "symbols": new_watchlist,
    "removed": list(remove_set),
    "added":   add_syms,
}, indent=2))
print(f"\nwatchlist.json oppdatert: {WATCHLIST_FILE}")

# Git commit
os.system("git config user.email 'bullbot-routine@noreply'")
os.system("git config user.name 'Bullbot Routine'")
os.system("git add watchlist.json")
os.system(f'git commit -m "watchlist: oppdatert {date.today()} (+{len(add_syms)} -{len(remove_set)})"')
os.system("git push")
print("Committed og push til GitHub")


# ── DISCORD-NOTIFIKASJON ──────────────────────────────────────────────────
discord_url = os.environ.get("DISCORD_WATCHLIST_WEBHOOK", "") or os.environ.get("DISCORD_WEBHOOK", "")
if not discord_url:
    sys.exit(0)

fields = []
if remove_set:
    lines = []
    for sym, sc, rec in to_remove:
        lines.append(f"🔴 **{sym}** score={sc:.1f}  {rec}")
    fields.append({"name": f"🗑️ Fjerna ({len(remove_set)})", "value": "\n".join(lines), "inline": False})

if add_syms:
    lines = []
    for sym, grunn in to_add:
        lines.append(f"🟢 **{sym}** — {grunn}")
    fields.append({"name": f"✅ Lagt til ({len(add_syms)})", "value": "\n".join(lines), "inline": False})

fields.append({
    "name": "📊 Watchlist-storleik", "value": f"{len(new_watchlist)} aksjar", "inline": True
})
fields.append({
    "name": "📅 Dato", "value": str(date.today()), "inline": True
})

embed = {
    "title":  f"📋 Watchlist oppdatert — {date.today().strftime('%d.%m.%Y')}",
    "color":  0x3498DB,
    "fields": fields,
    "footer": {"text": "Bullbot Watchlist Optimizer  •  køyrer kvar kveld etter børsstenging"},
}
try:
    requests.post(discord_url, json={"embeds": [embed]}, timeout=10)
    print("Discord-notifikasjon sendt")
except Exception as e:
    print(f"Discord: {e}")
