"""
bullbot — regelbasert aksjehande (paper trading)
Kjør: python bot.py
"""
import time
import logging
from alpaca.trading.client import TradingClient

import config
import notifier
from data.fetcher import get_bars
from strategy.ema_rsi import analyze, Signal
from strategy import momentum as mom_strat
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


def _load_knowledge() -> dict:
    """Les siste knowledge-rapport frå knowledge/-mappa."""
    import json
    from pathlib import Path
    reports = sorted((Path(__file__).parent / "knowledge").glob("report_*.json"), reverse=True)
    if not reports:
        return {}
    try:
        with open(reports[0], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _build_buy_reason(technical_reason: str, symbol: str, knowledge: dict) -> str:
    """Bygg rik grunngjeving for kjøp frå teknisk signal + knowledge."""
    parts = [f"📈 Teknisk: {technical_reason}"]
    sym_data = knowledge.get("per_symbol", {}).get(symbol, {})
    rec = sym_data.get("rec", "")
    if rec and rec not in ("N/A", "none"):
        parts.append(f"👥 Analytikar: {rec.upper()}")
    upside = sym_data.get("upside_pct", 0)
    if upside and upside > 0:
        parts.append(f"🎯 Analytikarmål: +{upside:.1f}% upside")
    news = [n for n in sym_data.get("news", []) if n]
    if news:
        parts.append(f"📰 Nyheit: {news[0][:80]}")
    mom = sym_data.get("momentum_dag_pct", 0)
    if abs(mom) >= config.MOMENTUM_MIN_DAY_PCT:
        parts.append(f"🚀 Dagleg momentum: {mom:+.1f}%")
    return "\n".join(parts)


def _build_sell_reason(technical_reason: str, symbol: str, pl_pct: float,
                       pl_dollar: float, knowledge: dict) -> str:
    """Bygg rik grunngjeving for sal frå teknisk signal + P&L + knowledge."""
    pl_emoji = "✅" if pl_dollar >= 0 else "❌"
    parts = [
        f"{pl_emoji} P&L: {pl_pct:+.2f}% (${pl_dollar:+,.2f})",
        f"📉 Signal: {technical_reason}",
    ]
    sym_data = knowledge.get("per_symbol", {}).get(symbol, {})
    news = [n for n in sym_data.get("news", []) if n]
    if news:
        parts.append(f"📰 Nyheit: {news[0][:80]}")
    return "\n".join(parts)


def run_cycle() -> None:
    if not is_market_open():
        log.info("Markedet er stengt, venter...")
        return

    knowledge = _load_knowledge()

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
                buy_reason = _build_buy_reason(result.reason, symbol, knowledge)
                buy(symbol, qty, sl, tp)
                n_open += 1
                notifier.send_trade(embeds=[notifier.buy_embed(
                    symbol, qty, price, sl, tp, invest_pct, equity, buy_reason
                )])

            elif result.signal == Signal.SELL and already_in:
                pl_pct    = float(position.unrealized_plpc) * 100
                pl_dollar = float(position.unrealized_pl)
                avg_entry = float(position.avg_entry_price)
                qty_held  = int(float(position.qty))
                decision  = _sell_or_hold(pl_pct, result.reason)
                log.info(
                    f"{symbol}: SELL-signal | P&L={pl_pct:+.2f}% | "
                    f"Beslutning={decision} | {result.reason}"
                )
                if decision == "SELG":
                    sell_reason = _build_sell_reason(result.reason, symbol,
                                                     pl_pct, pl_dollar, knowledge)
                    sell_all(symbol)
                    n_open -= 1
                    notifier.send_trade(embeds=[notifier.sell_embed(
                        symbol, qty_held, avg_entry, price,
                        pl_dollar, pl_pct, sell_reason
                    )])

        except Exception as e:
            log.error(f"{symbol}: feil — {e}")

    log.info(f"Syklus ferdig. Opne posisjonar: {n_open}/{config.MAX_OPEN_POSITIONS}")

    # ── MOMENTUM-SCAN ──────────────────────────────────────────────────────
    if buys_allowed and n_open < config.MAX_OPEN_POSITIONS:
        _run_momentum_scan(equity, open_positions, n_open, buys_allowed)


def _run_momentum_scan(equity: float, open_positions: dict, n_open: int, buys_allowed: bool) -> None:
    """Skanner watchlisten for store dagleg hopp og kjøper momentum-aksjar."""
    import yfinance as yf
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    log.info("--- Momentum-scan ---")
    for symbol in config.WATCHLIST:
        if symbol in open_positions:
            continue
        if n_open >= config.MAX_OPEN_POSITIONS:
            break
        try:
            # Dagsdata for % endring
            daily = yf.Ticker(symbol).history(period="3d")[["Open","High","Low","Close","Volume"]]
            daily.columns = [c.lower() for c in daily.columns]
            daily.index.name = "timestamp"

            # Intradag bars for RSI
            intra = get_bars(symbol, limit=30)

            result = mom_strat.analyze(daily, intra)

            if result.signal != "BUY":
                continue

            log.info(f"{symbol}: MOMENTUM {result.day_change_pct:+.1f}% | RSI={result.rsi:.1f}")
            price = float(daily["close"].iloc[-1])
            qty   = position_size(equity, price)
            sl    = round(price * (1 - config.MOMENTUM_STOP_LOSS), 2)
            tp    = round(price * (1 + config.MOMENTUM_TAKE_PROFIT), 2)
            invest_pct = qty * price / equity * 100

            buy(symbol, qty, sl, tp)
            n_open += 1
            notifier.send_trade(embeds=[notifier.buy_embed(
                symbol, qty, price, sl, tp, invest_pct, equity,
                result.reason
            )])
        except Exception as e:
            log.error(f"Momentum {symbol}: {e}")


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
    import sys
    if "--once" in sys.argv:
        run_cycle()
    else:
        main()
