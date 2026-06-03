"""
Dip-buy / mean-reversion på mega-cap.
Store kvalitetsselskap som fell mykje på 1-2 dagar hentar seg ofte inn att over tid.
Kjøp på oversold dropp, HALD til recovery-target eller hard stop (ingen stale/trailing).

Logikk:
  BUY  : fall <= -DIPBUY_MIN_DROP_PCT over DIPBUY_LOOKBACK_DAYS dagar
         OG RSI <= DIPBUY_RSI_MAX (oversold)
  HOLD : alt anna

Merk: scanninga i bot.py filtrerer til berre mega-cap (sektor='mega_cap').
"""
from dataclasses import dataclass
import pandas as pd
import pandas_ta as ta
import config


@dataclass
class DipResult:
    signal: str          # "BUY" eller "HOLD"
    drop_pct: float
    rsi: float
    reason: str


def analyze(bars_daily: pd.DataFrame, bars_intraday: pd.DataFrame) -> DipResult:
    n = config.DIPBUY_LOOKBACK_DAYS
    if len(bars_daily) < n + 1:
        return DipResult("HOLD", 0.0, 0.0, "ikkje nok dagsdata")

    ref_close  = float(bars_daily["close"].iloc[-(n + 1)])
    curr_price = float(bars_daily["close"].iloc[-1])
    drop       = (curr_price / ref_close - 1) * 100   # negativ ved fall

    rsi_series = ta.rsi(bars_intraday["close"], length=config.RSI_PERIOD) if len(bars_intraday) >= config.RSI_PERIOD + 1 else None
    rsi = float(rsi_series.iloc[-1]) if rsi_series is not None else 50.0

    if drop <= -config.DIPBUY_MIN_DROP_PCT and rsi <= config.DIPBUY_RSI_MAX:
        return DipResult(
            "BUY", drop, rsi,
            f"Dipp {drop:.1f}% over {n}d | RSI={rsi:.1f} oversold — mean-reversion kjøp"
        )

    return DipResult("HOLD", drop, rsi, f"Endring {drop:+.1f}% over {n}d")
