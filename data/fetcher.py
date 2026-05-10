import math
import pandas as pd
from datetime import datetime, timezone, timedelta
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
import config


def _make_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY)


_BAR_MINUTES = {"1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60, "1Day": 1440}


def get_bars(symbol: str, limit: int = config.BARS_LOOKBACK) -> pd.DataFrame:
    """Hent OHLCV-bars for et symbol. Returnerer DataFrame med DatetimeIndex."""
    client = _make_client()

    end = datetime.now(timezone.utc)
    # Berekn start ut frå timeframe — unngå å hente fleire månader tilbake
    minutes = _BAR_MINUTES.get(config.BAR_TIMEFRAME, 5)
    trading_min_per_day = 390  # 6.5 timar
    days_needed = math.ceil(limit * minutes / trading_min_per_day * 3)  # 3x buffer for helger
    start = end - timedelta(days=max(days_needed, 3))

    tf_map = {
        "1Min": TimeFrame(1, TimeFrameUnit.Minute),
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
        "1Day": TimeFrame(1, TimeFrameUnit.Day),
    }
    timeframe = tf_map.get(config.BAR_TIMEFRAME, TimeFrame(5, TimeFrameUnit.Minute))

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=limit,
        feed="iex",  # gratis for paper-kontoer
    )
    bars = client.get_stock_bars(request).df

    if bars.empty:
        return pd.DataFrame()

    # alpaca-py returnerer MultiIndex (symbol, timestamp) — behold bare timestamp
    if isinstance(bars.index, pd.MultiIndex):
        bars = bars.xs(symbol, level="symbol")

    bars.index = pd.to_datetime(bars.index, utc=True)
    return bars[["open", "high", "low", "close", "volume"]].tail(limit)


def get_latest_price(symbol: str) -> float:
    """Hent siste handelskurs for et symbol."""
    bars = get_bars(symbol, limit=1)
    if bars.empty:
        raise ValueError(f"Ingen data for {symbol}")
    return float(bars["close"].iloc[-1])
