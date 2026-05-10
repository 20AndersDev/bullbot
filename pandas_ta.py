"""Lightweight pandas_ta shim providing ema(), rsi(), macd()."""
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


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD = EMA(fast) - EMA(slow). Histogram = MACD - Signal line."""
    if series is None or len(series) < slow + signal:
        return None
    macd_line   = series.ewm(span=fast, adjust=False).mean() - series.ewm(span=slow, adjust=False).mean()
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram   = macd_line - signal_line
    col_m = f"MACD_{fast}_{slow}_{signal}"
    col_s = f"MACDs_{fast}_{slow}_{signal}"
    col_h = f"MACDh_{fast}_{slow}_{signal}"
    return pd.DataFrame({col_m: macd_line, col_s: signal_line, col_h: histogram})
