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

def _sector_count(symbol: str, open_positions: dict) -> int:
    """Tel kor mange opne posisjonar vi har i same sektor som symbol."""
    sector = config.SECTOR_MAP.get(symbol, "other")
    if sector == "other":
        return 0
    return sum(
        1 for sym in open_positions
        if config.SECTOR_MAP.get(sym, "other") == sector
    )


def _daily_loss_exceeded(equity: float, last_equity: float) -> bool:
    """Returner True om dagstapet overstig MAX_DAILY_LOSS_PCT."""
    if last_equity <= 0:
        return False
    return (equity - last_equity) / last_equity < -config.MAX_DAILY_LOSS_PCT


def _position_too_large(market_value: float, equity: float) -> bool:
    """Returner True om ei posisjon utgjer meir enn MAX_POSITION_PCT."""
    return (market_value / equity) > config.MAX_POSITION_PCT


def _sell_decision(pl_pct: float, price: float, recent_high: float,
                   rsi: float, tech_sell: bool) -> tuple:
    """
    Avgjer om vi skal selje basert på trailing stop og teknisk signal.

    Returnerer (decision, grunn) der decision er "SELG" eller "HALD".

    Logikk:
    - Trailing stop: om prisen fell 2% frå nyleg topp OG vi har gevinst → SELG
    - Teknisk SELL + RSI overkjøpt → SELG (kursen er sannsynleg på veg ned)
    - Teknisk SELL men framleis i pluss → HALD (let vinnaren løpe)
    - Tap + teknisk SELL → SELG (kutt tapet)
    """
    drawdown_from_high = (recent_high - price) / recent_high * 100

    if pl_pct < -(config.STOP_LOSS_PCT * 100):
        return "SELG", f"hard stop-loss ({pl_pct:+.2f}%) — ingen signal kravd"

    if pl_pct > 0.5 and drawdown_from_high >= 2.0:
        return "SELG", f"trailing stop — fall {drawdown_from_high:.1f}% frå topp ${recent_high:.2f}"

    if tech_sell and rsi > config.RSI_SELL_MIN:
        return "SELG", f"EMA-kryss + RSI overkjøpt ({rsi:.1f})"

    if tech_sell and pl_pct < -0.5:
        return "SELG", f"teknisk SELL på tap ({pl_pct:+.2f}%) — kuttar tap"

    if tech_sell and pl_pct > 0:
        return "HALD", f"teknisk svakt men let vinnaren løpe (P&L={pl_pct:+.2f}%)"

    return "HALD", ""


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


def _conviction_score(symbol: str, knowledge: dict, technical_reason: str = "") -> float:
    """
    Berekn overtydingsscore (0–10) for eit kjøp.
    Skalaen styrer kor stor posisjon vi tek (2%–10% av portefølja).

    Prioritet 1: bruk score frå dagens strategi om tilgjengeleg.
    Prioritet 2: bygg score frå per_symbol-data.
    """
    # Hent ferdigrekna score frå dagsstrategi
    for item in knowledge.get("strategi", {}).get("kjoep", []):
        if isinstance(item, dict) and item.get("symbol") == symbol:
            return min(10.0, float(item.get("score", 5.0)))

    # Fallback: bygg score frå per_symbol
    d     = knowledge.get("per_symbol", {}).get(symbol, {})
    score = 5.0

    rec = str(d.get("rec", "")).lower()
    if "strong_buy" in rec:
        score += 2.0
    elif "buy" in rec:
        score += 1.0
    elif "sell" in rec or "underperform" in rec:
        score -= 2.0

    upside = d.get("upside_pct", 0)
    if upside > 20:
        score += 1.5
    elif upside > 10:
        score += 0.75
    elif upside < -5:
        score -= 1.0

    sb = d.get("finnhub_strong_buy", 0)
    if sb >= 10:
        score += 1.0
    elif sb >= 5:
        score += 0.5

    reddit = d.get("reddit", {})
    r_buy  = reddit.get("buy", 0)
    if r_buy >= 3:
        score += 1.0
    elif r_buy >= 1:
        score += 0.5

    mom = d.get("momentum_dag_pct", 0)
    if abs(mom) >= config.MOMENTUM_MIN_DAY_PCT:
        score += 1.0

    return max(0.0, min(10.0, score))


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
    equity        = float(acct.equity)
    last_equity   = float(acct.last_equity)
    buying_power  = float(acct.non_marginable_buying_power)

    daily_pl_pct = (equity - last_equity) / last_equity * 100 if last_equity > 0 else 0
    log.info(f"Porteføljeverdi: ${equity:,.2f} | Dag P&L: {daily_pl_pct:+.2f}% | Buying power: ${buying_power:,.2f}")

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

                sector    = config.SECTOR_MAP.get(symbol, "other")
                sec_count = _sector_count(symbol, open_positions)
                if n_open > 0 and sector != "other":
                    sec_pct = (sec_count + 1) / (n_open + 1) * 100
                    if sec_pct > 50:
                        log.warning(f"{symbol}: høg sektorkonsentrasjon ({sector}: {sec_count+1}/{n_open+1} = {sec_pct:.0f}%) — kjøper likevel")

                conviction     = _conviction_score(symbol, knowledge, result.reason)
                qty            = position_size(equity, price, conviction)
                invest_amount  = qty * price
                invest_pct     = invest_amount / equity * 100
                sl             = stop_loss_price(price)
                tp             = take_profit_price(price)

                # Sjekk at det finst nok buying power
                if invest_amount > buying_power:
                    log.info(
                        f"{symbol}: ikkje nok buying power "
                        f"(treng ${invest_amount:,.0f}, har ${buying_power:,.0f})"
                    )
                    continue

                log.info(
                    f"{symbol}: KJØPER {qty} aksjer @ ~${price:.2f} "
                    f"({invest_pct:.1f}% av portefølje, conviction={conviction:.1f}) "
                    f"| SL=${sl} TP=${tp}"
                )
                buy_reason = _build_buy_reason(result.reason, symbol, knowledge)
                buy(symbol, qty, sl, tp)
                buying_power -= invest_amount
                n_open += 1
                notifier.send_trade(embeds=[notifier.buy_embed(
                    symbol, qty, price, sl, tp, invest_pct, equity, buy_reason
                )])

            if already_in:
                pl_pct    = float(position.unrealized_plpc) * 100
                pl_dollar = float(position.unrealized_pl)
                avg_entry = float(position.avg_entry_price)
                qty_held  = int(float(position.qty))

                # Trailing stop: siste 12 bars (~1 time) eller det som finst
                lookback    = min(12, len(bars))
                recent_high = float(bars["close"].tail(lookback).max())
                tech_sell   = result.signal == Signal.SELL

                decision, sell_note = _sell_decision(
                    pl_pct, price, recent_high, result.rsi, tech_sell
                )
                log.info(
                    f"{symbol}: {decision} | P&L={pl_pct:+.2f}% | "
                    f"RSI={result.rsi:.1f} | topp=${recent_high:.2f} | "
                    + (sell_note or result.reason)
                )
                if decision == "SELG":
                    full_reason = result.reason + (f" | {sell_note}" if sell_note else "")
                    sell_reason = _build_sell_reason(
                        full_reason, symbol, pl_pct, pl_dollar, knowledge
                    )
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
        _run_momentum_scan(equity, open_positions, n_open, buys_allowed, buying_power)


def _run_momentum_scan(equity: float, open_positions: dict, n_open: int,
                       buys_allowed: bool, buying_power: float = 0) -> None:
    """Skanner watchlisten for store dagleg hopp og kjøper momentum-aksjar."""
    import yfinance as yf

    log.info("--- Momentum-scan ---")
    for symbol in config.WATCHLIST:
        if symbol in open_positions:
            continue
        if n_open >= config.MAX_OPEN_POSITIONS:
            break
        try:
            daily = yf.Ticker(symbol).history(period="3d")[["Open","High","Low","Close","Volume"]]
            daily.columns = [c.lower() for c in daily.columns]
            daily.index.name = "timestamp"

            intra  = get_bars(symbol, limit=30)
            result = mom_strat.analyze(daily, intra)

            if result.signal != "BUY":
                continue

            log.info(f"{symbol}: MOMENTUM {result.day_change_pct:+.1f}% | RSI={result.rsi:.1f}")
            price      = float(daily["close"].iloc[-1])
            # Conviction skalerer med styrken på hoppet, maks 8 (momentum = kortsiktig)
            conviction = min(8.0, 5.0 + abs(result.day_change_pct) * 0.25)
            qty           = position_size(equity, price, conviction)
            invest_amount = qty * price
            invest_pct    = invest_amount / equity * 100
            sl            = round(price * (1 - config.MOMENTUM_STOP_LOSS), 2)
            tp            = round(price * (1 + config.MOMENTUM_TAKE_PROFIT), 2)

            if invest_amount > buying_power:
                log.info(f"{symbol}: ikkje nok buying power for momentum-kjøp")
                break  # resten vil heller ikkje ha nok

            buy(symbol, qty, sl, tp)
            buying_power -= invest_amount
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
