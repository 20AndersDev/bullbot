import math
import config


def position_size(equity: float, price: float) -> int:
    """
    Beregn antall aksjer basert på risikoprosent, avgrensa av MAX_POSITION_PCT.

    Risiko-basert formel gir tal aksjar der eit STOP_LOSS_PCT-fall
    kostar akkurat RISK_PER_TRADE av eigenkapitalen. Men dette investerer
    nesten heile eigenkapitalen (100% eksponering), så vi capper hardt
    på MAX_POSITION_PCT (10%) for å halde posisjonen konsentrasjonsikker.
    """
    risk_amount = equity * config.RISK_PER_TRADE
    risk_per_share = price * config.STOP_LOSS_PCT
    if risk_per_share <= 0:
        return 0
    risk_based_qty = math.floor(risk_amount / risk_per_share)
    max_qty = math.floor((equity * config.MAX_POSITION_PCT) / price)
    return max(min(risk_based_qty, max_qty), 1)


def stop_loss_price(entry: float) -> float:
    return round(entry * (1 - config.STOP_LOSS_PCT), 4)


def take_profit_price(entry: float) -> float:
    return round(entry * (1 + config.TAKE_PROFIT_PCT), 4)
