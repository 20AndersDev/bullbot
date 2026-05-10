from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
import config


def _client() -> TradingClient:
    return TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.PAPER)


def get_account():
    return _client().get_account()


def get_equity() -> float:
    return float(get_account().equity)


def get_open_positions() -> dict[str, object]:
    """Returnerer dict symbol -> posisjon."""
    positions = _client().get_all_positions()
    return {p.symbol: p for p in positions}


def has_position(symbol: str) -> bool:
    return symbol in get_open_positions()


def open_position_count() -> int:
    return len(get_open_positions())


def buy(symbol: str, qty: int, stop_loss: float, take_profit: float) -> None:
    """Kjøp med bracket-ordre (stop loss + take profit i én ordre)."""
    order = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        order_class=OrderClass.BRACKET,
        stop_loss=StopLossRequest(stop_price=round(stop_loss, 2)),
        take_profit=TakeProfitRequest(limit_price=round(take_profit, 2)),
    )
    _client().submit_order(order)


def sell_all(symbol: str) -> None:
    """Lukk heile posisjonen for eit symbol via Alpaca close_position."""
    _client().close_position(symbol)


def sell_partial(symbol: str, qty: int) -> None:
    """Sel eit gitt antal aksjar (partiell lukking)."""
    order = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    _client().submit_order(order)


def cancel_all_orders() -> None:
    _client().cancel_orders()
