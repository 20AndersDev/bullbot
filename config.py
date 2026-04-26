import os
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
PAPER = os.getenv("ALPACA_MODE", "paper") == "paper"
DISCORD_WEBHOOK          = os.getenv("DISCORD_WEBHOOK", "")
DISCORD_TRADE_WEBHOOK    = os.getenv("DISCORD_TRADE_WEBHOOK", "")
DISCORD_STRATEGY_WEBHOOK = os.getenv("DISCORD_STRATEGY_WEBHOOK", "")

# Aksjer å handle — mix av trygge store og vekstaksjar med potensiale
WATCHLIST = [
    # Mega-cap (stabil base)
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL",
    # Stor-cap vekst
    "TSLA", "AMD", "NFLX", "JPM", "V",
    # Mid-cap vekst / høgt potensiale
    "CRWD", "PLTR", "COIN", "UBER", "SOFI", "AFRM",
    # Mindre / høgare risiko / høgare potensiale
    "HOOD", "RBLX", "DASH", "RIVN", "MSTR", "NET", "SNOW",
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
