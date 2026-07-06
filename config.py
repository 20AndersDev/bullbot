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
_wl_data: dict = {}
if _wl_file.exists():
    _wl_data = json.loads(_wl_file.read_text())
    WATCHLIST = _wl_data.get("symbols", [])
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

    # ── Elektriske køyretøy ───────────────────────────────────────────────────
    "TSLA", "RIVN", "LCID", "NIO", "XPEV", "LI",

    # ── Ad-tech / Enterprise SaaS / MedTech ──────────────────────────────────
    "TTD", "WDAY", "ISRG",

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

# Sektorkarting for diversifisering — ukjende symbol får "other"
SECTOR_MAP: dict = {
    # Mega-cap tech
    "AAPL": "mega_cap",  "MSFT": "mega_cap",  "NVDA": "mega_cap",
    "AMZN": "mega_cap",  "META": "mega_cap",  "GOOGL": "mega_cap",
    "ORCL": "mega_cap",  "AVGO": "mega_cap",  "CRM": "mega_cap",  "ADBE": "mega_cap",
    # Halvleiarar
    "AMD":  "chips",  "QCOM": "chips",  "SMCI": "chips", "ARM":  "chips",
    "AMAT": "chips",  "LRCX": "chips",  "MRVL": "chips",  "ON":   "chips", "TSM":  "chips", "WOLF": "chips",
    # Minne / Lagring (NAND/DRAM) — korrelert syklisk sektor
    "MU":   "memory", "SNDK": "memory",
    # AI / Cloud / SaaS
    "PLTR": "ai_cloud", "NOW":  "ai_cloud", "DDOG": "ai_cloud", "MDB":  "ai_cloud",
    "SNOW": "ai_cloud", "NET":  "ai_cloud", "GTLB": "ai_cloud", "PATH": "ai_cloud",
    "BILL": "ai_cloud", "ZM":   "ai_cloud", "TWLO": "ai_cloud", "AI":   "ai_cloud",
    "WDAY": "ai_cloud", "HUBS": "ai_cloud",
    # Cybersikkerheit
    "CRWD": "cyber", "PANW": "cyber", "ZS": "cyber", "OKTA": "cyber", "FTNT": "cyber", "S": "cyber",
    # Fintech / Betalingar
    "V":    "fintech", "SQ":   "fintech", "PYPL": "fintech", "COIN": "fintech", "SOFI": "fintech",
    "AFRM": "fintech", "HOOD": "fintech", "MELI": "fintech", "NU":   "fintech", "UPST": "fintech",
    # Bank / Investering
    "JPM": "banking", "GS": "banking", "MS": "banking", "BAC": "banking", "BLK": "banking",
    # Strøyming / Media
    "NFLX": "media", "SPOT": "media", "ROKU": "media", "DIS": "media",
    # E-handel / Annonsering / Consumer
    "SHOP": "consumer", "ETSY": "consumer", "CHWY": "consumer", "PINS": "consumer",
    "SNAP": "consumer", "APP":  "consumer", "DUOL": "consumer", "TOST": "consumer",
    "TTD":  "consumer",
    # Transport
    "UBER": "transport", "LYFT": "transport", "DASH": "transport",
    # Livsstil
    "ABNB": "lifestyle", "DKNG": "lifestyle", "CELH": "lifestyle",
    # Elektriske køyretøy
    "TSLA": "ev", "RIVN": "ev", "LCID": "ev", "NIO": "ev", "XPEV": "ev", "LI": "ev",
    # Krypto-relatert
    "MSTR": "crypto", "MARA": "crypto", "RIOT": "crypto", "CLSK": "crypto", "HUT": "crypto",
    # Gaming
    "RBLX": "gaming", "U": "gaming",
    # Rom / Quantum
    "RKLB": "space", "LUNR": "space", "IONQ": "space",
    # Helse / Biotech / MedTech
    "MRNA": "health", "HIMS": "health", "TDOC": "health",
    "BNTX": "health", "DOCS": "health", "ISRG": "health",
    # Globalt vekst
    "SE": "global", "GRAB": "global", "GLBE": "global", "PTON": "global",
}

# Sektorar frå watchlist.json (bygde av scripts/update_watchlist.py via yfinance)
# overstyrer/utvidar den hardkoda lista — held SECTOR_MAP i takt med watchlista.
SECTOR_MAP.update(_wl_data.get("sectors", {}))

# Strategi-parametere
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
RSI_BUY_MAX = 65     # ikke kjøp hvis RSI er over dette
RSI_SELL_MIN = 68    # selg om EMA-kryss + RSI over dette (senka frå 72)
CROSS_LOOKBACK_BARS = 4  # godta EMA-kryss opptil så mange barar tilbake (botten
                         # køyrer kvar time på 15-min barar — eksakt siste-bar-kryss
                         # blir elles nesten alltid bomma)

# Risikostyring — opptil 15 posisjonar, storleik styrt av overtydingsscore (0-10)
#   conviction=0  → ~2% per posisjon
#   conviction=5  → ~6% per posisjon
#   conviction=10 → 10% per posisjon (hardt tak)
STOP_LOSS_PCT = 0.02        # 2% stop loss
TAKE_PROFIT_PCT = 0.04      # 4% take profit (2:1 R/R)
MAX_OPEN_POSITIONS = 15

# Guardrails
MAX_POSITION_PCT = 0.10     # hardt tak: aldri meir enn 10% av portefølje i éin aksje
MIN_POSITION_PCT = 0.02     # minste posisjon: 2% (ikkje verdt bryet under)
MAX_DAILY_LOSS_PCT = 0.05   # stopp nye kjøp om dagstap overstig 5%

# Tidsramme for bars (15 minutters candles — betre signal/støy)
BAR_TIMEFRAME = "15Min"
BARS_LOOKBACK = 50          # 50 x 15min = ~12.5t historikk

# Momentum/gap-strategi
MOMENTUM_MIN_DAY_PCT  = 4.0   # kjøp om aksjen er opp > 4% i dag
MOMENTUM_RSI_MAX      = 74    # ikkje kjøp om RSI er for høg
MOMENTUM_STOP_LOSS    = 0.015 # 1.5% SL (tettare enn vanleg)
MOMENTUM_TAKE_PROFIT  = 0.025 # 2.5% TP (rask exit)

# Dip-buy / mean-reversion (berre mega-cap)
# Store kvalitetsselskap som fell mykje på 1-2 dagar hentar seg ofte inn att.
# Kjøp på oversold dropp, HALD til recovery-target eller hard stop (ingen stale/trailing).
DIPBUY_MIN_DROP_PCT  = 5.0    # kjøp om mega-cap er ned >= 5% over vindauget
DIPBUY_LOOKBACK_DAYS = 2      # vindauge for fallet (1-2 dagar)
DIPBUY_RSI_MAX       = 35     # berre om RSI oversold (mean-reversion sannsynleg)
DIPBUY_STOP_LOSS     = 0.06   # 6% stop — breiare, gjev recovery rom
DIPBUY_TARGET_PCT    = 0.08   # +8% recovery-target → ut
