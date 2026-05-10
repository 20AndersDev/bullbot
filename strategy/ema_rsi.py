from dataclasses import dataclass, field
from enum import Enum
import pandas as pd
import pandas_ta as ta
import config


class Signal(Enum):
    BUY  = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyResult:
    signal:    Signal
    reason:    str
    ema_fast:  float
    ema_slow:  float
    rsi:       float
    macd_hist: float = 0.0
    vol_ratio: float = 1.0


def analyze(bars: pd.DataFrame) -> StrategyResult:
    """
    Teknisk analyse: EMA-kryss bekrefta av MACD + volumfilter.

    KJØP:  EMA(9) krysser over EMA(21)
           OG RSI < RSI_BUY_MAX
           OG MACD-histogram > 0  (momentum er bullish)
           Volumbekreftelse gir sterkare signal men er ikkje krav.

    SELG:  EMA(9) krysser under EMA(21) (bot.py handterer RSI standalone)
           MACD-histogram < 0 = bekrefta, ≥ 0 = svakt (loggar men sel likevel)

    HALD:  EMA krysser BUY men MACD-histogram < 0 → falsk kryss, ikkje kjøp.
    """
    min_bars = max(config.EMA_SLOW + 5, 35)  # MACD treng 26+9 bars
    if len(bars) < min_bars:
        return StrategyResult(Signal.HOLD, "ikkje nok data", 0, 0, 0)

    close  = bars["close"]
    volume = bars["volume"] if "volume" in bars.columns else None

    ema_fast = ta.ema(close, length=config.EMA_FAST)
    ema_slow = ta.ema(close, length=config.EMA_SLOW)
    rsi      = ta.rsi(close, length=config.RSI_PERIOD)
    macd_df  = ta.macd(close, fast=12, slow=26, signal=9)

    if ema_fast is None or ema_slow is None or rsi is None:
        return StrategyResult(Signal.HOLD, "indikatorberekning feila", 0, 0, 0)

    ef_now  = float(ema_fast.iloc[-1])
    ef_prev = float(ema_fast.iloc[-2])
    es_now  = float(ema_slow.iloc[-1])
    es_prev = float(ema_slow.iloc[-2])
    rsi_now = float(rsi.iloc[-1])

    # MACD histogram
    macd_hist = 0.0
    if macd_df is not None and "MACDh_12_26_9" in macd_df.columns:
        raw = macd_df["MACDh_12_26_9"].iloc[-1]
        macd_hist = float(raw) if pd.notna(raw) else 0.0

    # Volumratio: siste bar vs 20-bar snitt
    vol_ratio = 1.0
    if volume is not None and len(volume) >= 20:
        avg_vol = float(volume.iloc[-20:].mean())
        cur_vol = float(volume.iloc[-1])
        vol_ratio = (cur_vol / avg_vol) if avg_vol > 0 else 1.0

    bullish_cross = ef_prev <= es_prev and ef_now > es_now
    bearish_cross = ef_prev >= es_prev and ef_now < es_now
    vol_ok        = vol_ratio >= 1.2

    # ── KJØP ──────────────────────────────────────────────────────────────────
    if bullish_cross and rsi_now < config.RSI_BUY_MAX:
        if macd_hist <= 0:
            # EMA kryssar men MACD ikkje einig — falsk kryss, ikkje kjøp
            return StrategyResult(
                Signal.HOLD,
                f"EMA-kryss AVVIST — MACD histogram negativt ({macd_hist:.4f})",
                ef_now, es_now, rsi_now, macd_hist, vol_ratio,
            )
        vol_tag = f" + vol {vol_ratio:.1f}x" if vol_ok else f" (volum svakt {vol_ratio:.1f}x)"
        return StrategyResult(
            Signal.BUY,
            f"EMA{config.EMA_FAST}x{config.EMA_SLOW} + MACD+{vol_tag}, RSI={rsi_now:.1f}",
            ef_now, es_now, rsi_now, macd_hist, vol_ratio,
        )

    # ── SELG ──────────────────────────────────────────────────────────────────
    if bearish_cross:
        if macd_hist < 0:
            reason = f"EMA{config.EMA_FAST}x{config.EMA_SLOW} ned + MACD- bekrefta, RSI={rsi_now:.1f}"
        else:
            reason = f"EMA-kryss ned (MACD svakt bekrefta: {macd_hist:.4f}), RSI={rsi_now:.1f}"
        return StrategyResult(Signal.SELL, reason, ef_now, es_now, rsi_now, macd_hist, vol_ratio)

    return StrategyResult(Signal.HOLD, "ingen kryssing", ef_now, es_now, rsi_now, macd_hist, vol_ratio)
