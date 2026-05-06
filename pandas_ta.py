"""Lightweight pandas_ta shim providing ema() and rsi()."""
import pandas as pd


def ema(series: pd.Series, length: int = 20):
    if series is None or len(series) < length:
        return None
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14):
    if series is None or len(series) < length + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))
