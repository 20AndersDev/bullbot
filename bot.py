"""
bullbot — regelbasert aksjehande (paper trading)
Kjør: python bot.py
"""
import time
import logging
from alpaca.trading.client import TradingClient

import config
from data.fetcher import get_bars
from strategy.ema_rsi import analyze, Signal
from risk.manager import position_size, stop_loss_price, take_profit_price
from executor.alpaca_broker import (
    get_account,
    get_open_positions,
    buy,
    sell_all,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bullbot")


# ---------------------------------------------------------------------------
# Guardrail-funksjonar
# ---------------------------------------------------------------------------

def _daily_loss_exceeded(equity: float, last_equity: float) -> bool:
    """Returner True om dagstapet overstig MAX_DAILY_LOSS_PCT."""
    if last_equity <= 0:
        return False
    return (equity - last_equity) / last_equity < -config.MAX_DAILY_LOSS_PCT


def _position_too_large(market_value: float, equity: float) -> bool:
    """Returner True om ei posisjon utgjer meir enn MAX_POSITION_PCT."""
    return (market_value / equity) > config.MAX_POSITION_PCT


def _sell_or_hold(pl_pct: float, reason: str) -> str:
    """
    Avgjør om vi skal selge eller halde basert på urealisert P&L.

    P&L >= 3%:  Selg alltid — sikre gevinst
    P&L 1-3%:   Selg på EMA-kryss, hald på RSI-exit åleine
    P&L < 1%:   Hald — stop-loss-ordren tek seg av nedsida
    """
    if pl_pct >= 3.0:
        return "SELG"
    if pl_pct >= 1.0:
        return "SELG" if "krysset" in reason else "HALD"
    return "HALD"


# ---------------------------------------------------------------------------
# Hovud-syklus
# ---------------------------------------------------------------------------

def is_market_open() -> bool:
    client = TradingClient(config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY, paper=config.PAPER)
    return client.get_clock().is_open


def run_cycle() -> None:
    if not is_market_open():
        log.info("Markedet er stengt, venter...")
        return

    acct = get_account()
    equity = float(acct.equity)
    last_equity = float(acct.last_equity)

    daily_pl_pct = (equity - last_equity) / last_equity * 100 if last_equity > 0 else 0
    log.info(f"Porteføljeverdi: ${equity:,.2f} | Dag P&L: {daily_pl_pct:+.2f}%")

    # Guardrail 1: dagleg tapgrense
    buys_allowed = True
    if _daily_loss_exceeded(equity, last_equity):
        log.warning(
            f"⚠️  Dagleg tapgrense nådd ({daily_pl_pct:.2f}% < "
            f"-{config.MAX_DAILY_LOSS_PCT*100:.0f}%) — berre salssignal aktive"
        )
        buys_allowed = False

    open_positions = get_open_positions()
    n_open = len(open_positions)

    for symbol in config.WATCHLIST:
        try:
            bars = get_bars(symbol)
            if bars.empty:
                log.warning(f"{symbol}: ingen data")
                continue

            result = analyze(bars)
            price = float(bars["close"].iloc[-1])

            log.info(
                f"{symbol} | {result.signal.value:4s} | "
                f"EMA{config.EMA_FAST}={result.ema_fast:.2f} "
                f"EMA{config.EMA_SLOW}={result.ema_slow:.2f} "
                f"RSI={result.rsi:.1f} | {result.reason}"
            )

            position = open_positions.get(symbol)
            already_in = position is not None

            # Guardrail 2: sjekk om eksisterande posisjon er for stor (>10%)
            if already_in:
                pos_pct = float(position.market_value) / equity * 100
                if _position_too_large(float(position.market_value), equity):
                    log.warning(
                        f"{symbol}: posisjon er {pos_pct:.1f}% av portefølje "
                        f"(maks {config.MAX_POSITION_PCT*100:.0f}%) — sel for å kome under grensa"
                    )
                    sell_all(symbol)
                    n_open -= 1
                    open_positions.pop(symbol)
                    already_in = False

            if result.signal == Signal.BUY and not already_in and buys_allowed:
                if n_open >= config.MAX_OPEN_POSITIONS:
                    log.info(f"{symbol}: maks posisjoner nådd ({config.MAX_OPEN_POSITIONS})")
                    continue

                qty = position_size(equity, price)
                invest_pct = qty * price / equity * 100
                sl = stop_loss_price(price)
                tp = take_profit_price(price)

                log.info(
                    f"{symbol}: KJØPER {qty} aksjer @ ~${price:.2f} "
                    f"({invest_pct:.1f}% av portefølje) | SL=${sl} TP=${tp}"
                )
                buy(symbol, qty, sl, tp)
                n_open += 1

            elif result.signal == Signal.SELL and already_in:
                pl_pct = float(position.unrealized_plpc) * 100
                decision = _sell_or_hold(pl_pct, result.reason)
                log.info(
                    f"{symbol}: SELL-signal | P&L={pl_pct:+.2f}% | "
                    f"Beslutning={decision} | {result.reason}"
                )
                if decision == "SELG":
                    sell_all(symbol)
                    n_open -= 1

        except Exception as e:
            log.error(f"{symbol}: feil — {e}")

    log.info(f"Syklus ferdig. Opne posisjonar: {n_open}/{config.MAX_OPEN_POSITIONS}")


def main() -> None:
    log.info("bullbot starter")
    interval_seconds = 60 * 60  # 1 time

    while True:
        try:
            run_cycle()
        except Exception as e:
            log.error(f"Uventet feil i syklus: {e}")

        log.info(f"Venter {interval_seconds // 60} min til neste syklus...")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
