import os, json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
PAPER = os.getenv("ALPACA_MODE", "paper").lower() in ("paper", "true", "1")
DISCORD_WEBHOOK           = os.getenv("DISCORD_WEBHOOK", "")
DISCORD_TRADE_WEBHOOK     = os.getenv("DISCORD_TRADE_WEBHOOK", "")
DISCORD_STRATEGY_WEBHOOK  = os.getenv("DISCORD_STRATEGY_WEBHOOK", "")
DISCORD_WATCHLIST_WEBHOOK = os.getenv("DISCORD_WATCHLIST_WEBHOOK", "")

# Les watchlist frå watchlist.json om han finst, elles bruk hardkoda liste
_wl_file = Path(__file__).parent / "watchlist.json"
if _wl_file.exists():
    WATCHLIST = json.loads(_wl_file.read_text()).get("symbols", [])
else:
    # Fallback — 100 aksjar på tvers av alle sektorar
    WATCHLIST = [
    # ── Mega-cap (stabil base) ───────────────────────────────────────────────
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL",
    "ORCL", "AVGO", "CRM", "ADBE",

    # ── Halvleiarar / Chip ───────────────────────────────────────────────────
    "AMD", "QCOM", "MU", "SMCI", "ARM",
    "AMAT", "LRCX", "MRVL", "ON", "TSM", "WOLF",

    # ── AI / Cloud / SaaS ────────────────────────────────────────────────────
    "PLTR", "NOW", "DDOG", "MDB", "SNOW",
    "NET", "GTLB", "PATH", "BILL", "ZM", "TWLO", "AI",

    # ── Cybersikkerheit ──────────────────────────────────────────────────────
    "CRWD", "PANW", "ZS", "OKTA", "FTNT", "S",

    # ── Fintech / Betalingar ─────────────────────────────────────────────────
    "V", "SQ", "PYPL", "COIN", "SOFI",
    "AFRM", "HOOD", "MELI", "NU", "UPST",

    # ── Bank / Investering ───────────────────────────────────────────────────
    "JPM", "GS", "MS", "BAC", "BLK",

    # ── Strøyming / Media ────────────────────────────────────────────────────
    "NFLX", "SPOT", "ROKU", "DIS",

    # ── E-handel / Consumer Tech ─────────────────────────────────────────────
    "SHOP", "ETSY", "CHWY", "PINS", "SNAP", "APP", "DUOL", "TOST",

    # ── Transport / Mobilitet ────────────────────────────────────────────────
    "UBER", "LYFT", "DASH",

    # ── Reise / Livsstil ─────────────────────────────────────────────────────
    "ABNB", "DKNG", "CELH",

    # ── EV / Rein energi ─────────────────────────────────────────────────────
    "TSLA", "RIVN", "LCID", "NIO", "XPEV", "LI",
    "PLUG", "ENPH", "SEDG",

    # ── Krypto-relatert ──────────────────────────────────────────────────────
    "MSTR", "MARA", "RIOT", "CLSK", "HUT",

    # ── Gaming / Metaverse ───────────────────────────────────────────────────
    "RBLX", "U",

    # ── Rom / Quantum computing ──────────────────────────────────────────────
    "RKLB", "LUNR", "IONQ",

    # ── Helse / Biotech ──────────────────────────────────────────────────────
    "MRNA", "HIMS", "TDOC", "BNTX", "DOCS",

    # ── Globalt vekst ────────────────────────────────────────────────────────
    "SE", "GRAB", "GLBE", "PTON",
    ]

# Strategi-parametere
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_BUY_MAX = 65     # ikke kjøp hvis RSI er over dette
RSI_SELL_MIN = 72    # selg hvis RSI er over dette (overkjøpt exit)

# Risikostyring — opptil 20 posisjonar, storleik styrt av overtydingsscore (0-10)
#   conviction=0  → ~2% per posisjon
#   conviction=5  → ~6% per posisjon
#   conviction=10 → 10% per posisjon (hardt tak)
STOP_LOSS_PCT = 0.02        # 2% stop loss
TAKE_PROFIT_PCT = 0.04      # 4% take profit (2:1 R/R)
MAX_OPEN_POSITIONS = 20

# Guardrails
MAX_POSITION_PCT = 0.10     # hardt tak: aldri meir enn 10% av portefølje i éin aksje
MIN_POSITION_PCT = 0.02     # minste posisjon: 2% (ikkje verdt bryet under)
MAX_DAILY_LOSS_PCT = 0.05   # stopp nye kjøp om dagstap overstig 5%

# Tidsramme for bars (5 minutters candles)
BAR_TIMEFRAME = "5Min"
BARS_LOOKBACK = 50          # antall bars å hente for indikatorberegning

# Momentum/gap-strategi
MOMENTUM_MIN_DAY_PCT  = 4.0   # kjøp om aksjen er opp > 4% i dag
MOMENTUM_RSI_MAX      = 74    # ikkje kjøp om RSI er for høg
MOMENTUM_STOP_LOSS    = 0.015 # 1.5% SL (tettare enn vanleg)
MOMENTUM_TAKE_PROFIT  = 0.025 # 2.5% TP (rask exit)
