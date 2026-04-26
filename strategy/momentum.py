"""
Momentum / gap-strategi.
Kjøper aksjar som hoppar mykje på ein dag og tek raskt ut att gevinst.

Logikk:
  BUY  : dagleg hopp > MOMENTUM_MIN_DAY_PCT OG RSI ikkje overkjøpt
  HOLD : alt anna
"""
from dataclasses import dataclass
import pandas as pd
import pandas_ta as ta
import config


@dataclass
class MomentumResult:
    signal: str          # "BUY" eller "HOLD"
    day_change_pct: float
    rsi: float
    reason: str


def analyze(bars_daily: pd.DataFrame, bars_intraday: pd.DataFrame) -> MomentumResult:
    if len(bars_daily) < 2:
        return MomentumResult("HOLD", 0.0, 0.0, "ikkje nok dagsdata")

    prev_close = float(bars_daily["close"].iloc[-2])
    curr_price = float(bars_daily["close"].iloc[-1])
    day_chg    = (curr_price / prev_close - 1) * 100

    rsi_series = ta.rsi(bars_intraday["close"], length=config.RSI_PERIOD) if len(bars_intraday) >= config.RSI_PERIOD + 1 else None
    rsi = float(rsi_series.iloc[-1]) if rsi_series is not None else 50.0

    if day_chg >= config.MOMENTUM_MIN_DAY_PCT and rsi < config.MOMENTUM_RSI_MAX:
        return MomentumResult(
            "BUY", day_chg, rsi,
            f"Dagleg hopp +{day_chg:.1f}% | RSI={rsi:.1f} — momentum-kjøp"
        )

    return MomentumResult("HOLD", day_chg, rsi, f"Dagleg endring {day_chg:+.1f}%")
