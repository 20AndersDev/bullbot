from dataclasses import dataclass
from enum import Enum
import pandas as pd
import pandas_ta as ta
import config


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyResult:
    signal: Signal
    reason: str
    ema_fast: float
    ema_slow: float
    rsi: float


def analyze(bars: pd.DataFrame) -> StrategyResult:
    """
    EMA crossover + RSI-filter.

    Kjøp:  EMA(9) krysser over EMA(21) OG RSI < RSI_BUY_MAX
    Selg:  EMA(9) krysser under EMA(21) ELLER RSI > RSI_SELL_MIN
    """
    if len(bars) < config.EMA_SLOW + 5:
        return StrategyResult(Signal.HOLD, "ikke nok data", 0, 0, 0)

    close = bars["close"]

    ema_fast = ta.ema(close, length=config.EMA_FAST)
    ema_slow = ta.ema(close, length=config.EMA_SLOW)
    rsi = ta.rsi(close, length=config.RSI_PERIOD)

    if ema_fast is None or ema_slow is None or rsi is None:
        return StrategyResult(Signal.HOLD, "indikatorberegning feilet", 0, 0, 0)

    ef_now  = float(ema_fast.iloc[-1])
    ef_prev = float(ema_fast.iloc[-2])
    es_now  = float(ema_slow.iloc[-1])
    es_prev = float(ema_slow.iloc[-2])
    rsi_now = float(rsi.iloc[-1])

    bullish_cross = ef_prev <= es_prev and ef_now > es_now
    bearish_cross = ef_prev >= es_prev and ef_now < es_now
    overbought    = rsi_now > config.RSI_SELL_MIN

    if bullish_cross and rsi_now < config.RSI_BUY_MAX:
        return StrategyResult(
            Signal.BUY,
            f"EMA{config.EMA_FAST} krysset over EMA{config.EMA_SLOW}, RSI={rsi_now:.1f}",
            ef_now, es_now, rsi_now,
        )

    if bearish_cross or overbought:
        reason = (
            f"EMA{config.EMA_FAST} krysset under EMA{config.EMA_SLOW}"
            if bearish_cross
            else f"RSI overkjøpt ({rsi_now:.1f})"
        )
        return StrategyResult(Signal.SELL, reason, ef_now, es_now, rsi_now)

    return StrategyResult(Signal.HOLD, "ingen kryssing", ef_now, es_now, rsi_now)
