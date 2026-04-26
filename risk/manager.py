import math
import config


def position_size(equity: float, price: float, conviction: float = 5.0) -> int:
    """
    Berekn antal aksjar basert på overtydingsscore (0–10).

    conviction=0  → MIN_POSITION_PCT  (~2% av eigenkapital)
    conviction=5  → midtpunkt          (~6% av eigenkapital)
    conviction=10 → MAX_POSITION_PCT  (10% av eigenkapital, hardt tak)

    Høg overtyding = sterke signal (STRONG_BUY + høg upside + Reddit-buzz).
    Lav overtyding = svakare signal, invest litt men ikkje for mykje.
    """
    conviction = max(0.0, min(10.0, conviction))
    span = config.MAX_POSITION_PCT - config.MIN_POSITION_PCT
    pct  = config.MIN_POSITION_PCT + (conviction / 10.0) * span
    qty  = math.floor(equity * pct / price)
    return max(qty, 1)


def stop_loss_price(entry: float) -> float:
    return round(entry * (1 - config.STOP_LOSS_PCT), 4)


def take_profit_price(entry: float) -> float:
    return round(entry * (1 + config.TAKE_PROFIT_PCT), 4)
