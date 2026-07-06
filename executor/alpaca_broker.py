from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, QueryOrderStatus
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


def get_open_order_symbols() -> set[str]:
    """Symbol som har minst éin open ordre (t.d. aktiv stop-loss/target)."""
    orders = _client().get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
    return {o.symbol for o in orders}


def cancel_orders_for(symbol: str) -> None:
    """Kanseller alle opne ordrar for eit symbol.

    MÅ gjerast før sal: ein aktiv stop-loss/target held aksjane, og
    close_position/sell blir elles avvist med «insufficient qty available».
    """
    client = _client()
    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol]))
    for o in orders:
        try:
            client.cancel_order_by_id(o.id)
        except Exception:
            pass  # allereie fylt/kansellert i mellomtida


def buy(symbol: str, qty: int, stop_loss: float, take_profit: float | None = None) -> None:
    """Kjøp med stop-loss.

    take_profit=None  → OTO-ordre: berre hard stop-loss server-side, INGA fast take-profit.
                        Exit styrast av trailing-logikken i bot.py (let vinnarar løpe).
    take_profit satt  → BRACKET-ordre: stop-loss + fast take-profit (rask exit / hald-til-target).

    GTC, ikkje DAY: med DAY utløper stop/target ved børsstenging, og posisjonar
    haldne over natta står utan vern (jf. ORCL som fall 32% forbi 2%-stoppen).
    """
    if take_profit is None:
        order = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.OTO,
            stop_loss=StopLossRequest(stop_price=round(stop_loss, 2)),
        )
    else:
        order = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            order_class=OrderClass.BRACKET,
            stop_loss=StopLossRequest(stop_price=round(stop_loss, 2)),
            take_profit=TakeProfitRequest(limit_price=round(take_profit, 2)),
        )
    _client().submit_order(order)


def sell_all(symbol: str) -> None:
    """Lukk heile posisjonen for eit symbol via Alpaca close_position."""
    cancel_orders_for(symbol)
    _client().close_position(symbol)


def sell_partial(symbol: str, qty: int) -> None:
    """Sel eit gitt antal aksjar (partiell lukking)."""
    cancel_orders_for(symbol)
    order = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    _client().submit_order(order)


def cancel_all_orders() -> None:
    _client().cancel_orders()
