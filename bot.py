"""
bullbot — regelbasert aksjehande (paper trading)
Kjør: python bot.py
"""
import time
import logging
import json
import math
from datetime import datetime
from pathlib import Path
from alpaca.trading.client import TradingClient

import config
import notifier

_COOLDOWN_FILE = Path(__file__).parent / "data" / "cooldown.json"
_ENTRY_FILE    = Path(__file__).parent / "data" / "positions_opened.json"
_PARTIAL_FILE  = Path(__file__).parent / "data" / "partial_sold.json"
_DIP_FILE      = Path(__file__).parent / "data" / "dip_positions.json"
_COOLDOWN_DAYS = 3
_STALE_DAYS    = 5
_STALE_MAX_PL  = 3.0


def _load_json(filepath: Path) -> dict:
    try:
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(filepath: Path, data: dict) -> None:
    filepath.parent.mkdir(exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_cooldown() -> dict:
    return _load_json(_COOLDOWN_FILE)


def _save_cooldown(symbol: str, cooldown: dict) -> None:
    cooldown[symbol] = datetime.now().strftime("%Y-%m-%d")
    _save_json(_COOLDOWN_FILE, cooldown)


def _in_cooldown(symbol: str, cooldown: dict) -> bool:
    if symbol not in cooldown:
        return False
    return (datetime.now() - datetime.strptime(cooldown[symbol], "%Y-%m-%d")).days < _COOLDOWN_DAYS


def _load_entries() -> dict:
    return _load_json(_ENTRY_FILE)


def _save_entry(symbol: str, entries: dict) -> None:
    entries[symbol] = datetime.now().strftime("%Y-%m-%d")
    _save_json(_ENTRY_FILE, entries)


def _remove_entry(symbol: str, entries: dict) -> None:
    entries.pop(symbol, None)
    _save_json(_ENTRY_FILE, entries)


def _load_partial() -> dict:
    return _load_json(_PARTIAL_FILE)


def _save_partial(symbol: str, pct: int, partial: dict) -> None:
    partial[symbol] = pct
    _save_json(_PARTIAL_FILE, partial)


def _is_stale(symbol: str, pl_pct: float, entries: dict) -> bool:
    if symbol not in entries or pl_pct >= _STALE_MAX_PL:
        return False
    return (datetime.now() - datetime.strptime(entries[symbol], "%Y-%m-%d")).days >= _STALE_DAYS


def _load_dips() -> dict:
    return _load_json(_DIP_FILE)


def _save_dip(symbol: str, dips: dict) -> None:
    dips[symbol] = datetime.now().strftime("%Y-%m-%d")
    _save_json(_DIP_FILE, dips)


def _remove_dip(symbol: str, dips: dict) -> None:
    dips.pop(symbol, None)
    _save_json(_DIP_FILE, dips)


from data.fetcher import get_bars
from strategy.ema_rsi import analyze, Signal
from strategy import momentum as mom_strat
from strategy import dipbuy as dip_strat
from risk.manager import position_size, stop_loss_price, take_profit_price
from executor.alpaca_broker import (
    get_account,
    get_open_positions,
    buy,
    sell_all,
    sell_partial,
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
    Trailing stop startar IKKJE før +4% — let small-cap runners puste.

    Nivå:
      +4–8%:  3% trail, 12-bar topp
      +8–15%: 4% trail, 24-bar topp
      +15%+:  5% trail, 48-bar topp

    Under +4%: berre hard stop-loss og tap-kutt.
    Ingen trailing på < +4% — hindrar for tidleg exit på potensielle runners.
    """
    drawdown_from_high = (recent_high - price) / recent_high * 100

    # Hard stop — alltid
    if pl_pct < -(config.STOP_LOSS_PCT * 100):
        return "SELG", f"hard stop-loss ({pl_pct:+.2f}%) — ingen signal kravd"

    # Trailing stop — startar IKKJE før +4%
    if pl_pct >= 15:
        trail_pct = 5.0
    elif pl_pct >= 8:
        trail_pct = 4.0
    elif pl_pct >= 4:
        trail_pct = 3.0
    else:
        trail_pct = None  # ingen trailing på < +4%

    if trail_pct and drawdown_from_high >= trail_pct:
        return "SELG", f"trailing stop {trail_pct:.0f}% — fall {drawdown_from_high:.1f}% frå topp ${recent_high:.2f}"

    # RSI ekstremt overkjøpt — berre sel om allereie god gevinst (+5%+)
    if rsi > 80 and pl_pct >= 5:
        return "SELG", f"RSI ekstremt overkjøpt ({rsi:.1f}) ved gevinst {pl_pct:+.1f}%"

    # EMA-kryss + RSI bekreftar reversering
    if tech_sell and rsi > config.RSI_SELL_MIN and pl_pct >= 5:
        return "SELG", f"EMA-kryss + RSI overkjøpt ({rsi:.1f}) — ta gevinst"

    # Kutt tap på teknisk signal
    if tech_sell and pl_pct < -0.5:
        return "SELG", f"teknisk SELL på tap ({pl_pct:+.2f}%) — kuttar tap"

    # Alt anna: HALD — let posisjonen løpe
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

    # Sektorboost: symbol i topp-sektor → høgare conviction
    for sekt in knowledge.get("sektorar", [])[:3]:
        if symbol in sekt.get("aksjar", []):
            boost = min(1.5, sekt.get("score", 0) * 0.15)
            if boost > 0:
                score += boost
            break

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
    cooldown  = _load_cooldown()
    entries   = _load_entries()
    partial   = _load_partial()
    dips      = _load_dips()

    acct = get_account()
    equity        = float(acct.equity)
    last_equity   = float(acct.last_equity)
    buying_power  = max(0.0, float(acct.cash))

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

    # Rydd dip-register: bracket (target/stop) kan ha lukka posisjonar server-side
    for sym in list(dips):
        if sym not in open_positions:
            log.info(f"{sym}: dip-posisjon lukka av bracket (target/stop) — set cooldown")
            _save_cooldown(sym, cooldown)
            _remove_dip(sym, dips)

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
                f"RSI={result.rsi:.1f} MACD={result.macd_hist:+.4f} "
                f"Vol={result.vol_ratio:.1f}x | {result.reason}"
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

                if _in_cooldown(symbol, cooldown):
                    log.info(f"{symbol}: cooldown etter sal — ventar {_COOLDOWN_DAYS} dagar")
                    continue

                sector    = config.SECTOR_MAP.get(symbol, "other")
                sec_count = _sector_count(symbol, open_positions)
                if n_open > 0 and sector != "other":
                    sec_pct = (sec_count + 1) / (n_open + 1) * 100
                    if sec_pct > 50:
                        log.warning(f"{symbol}: høg sektorkonsentrasjon ({sector}: {sec_count+1}/{n_open+1} = {sec_pct:.0f}%) — kjøper likevel")

                conviction      = _conviction_score(symbol, knowledge, result.reason)
                conviction_qty  = position_size(equity, price, conviction)
                # Fullinvestert: fordel tilgjengeleg cash jamnt på ledige slot
                remaining_slots = max(1, config.MAX_OPEN_POSITIONS - n_open)
                deploy_qty      = math.floor(buying_power / remaining_slots / price)
                cap_qty         = math.floor(equity * config.MAX_POSITION_PCT / price)
                qty             = min(max(conviction_qty, deploy_qty), cap_qty)
                qty             = max(qty, 1)
                invest_amount   = qty * price
                invest_pct      = invest_amount / equity * 100
                sl             = stop_loss_price(price)
                tp             = take_profit_price(price)  # ref-mål for embed; OTO set ingen fast TP

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
                    f"| SL=${sl} (OTO — trailing styrer exit, ref-mål ${tp})"
                )
                buy_reason = _build_buy_reason(result.reason, symbol, knowledge)
                buy(symbol, qty, sl)  # OTO: berre stop-loss, trailing-logikk styrer exit
                _save_entry(symbol, entries)
                buying_power -= invest_amount
                n_open += 1
                notifier.send_trade(embeds=[notifier.buy_embed(
                    symbol, qty, price, sl, tp, invest_pct, equity, buy_reason
                )])

            # Dip-posisjonar: bracket styrer exit (target/stop). Hopp over stale/partial/trailing.
            if already_in and symbol in dips:
                pl_pct = float(position.unrealized_plpc) * 100
                log.info(
                    f"{symbol}: dip-posisjon | P&L={pl_pct:+.2f}% — bracket styrer exit "
                    f"(target +{config.DIPBUY_TARGET_PCT*100:.0f}% / stop -{config.DIPBUY_STOP_LOSS*100:.0f}%), ingen stale/trailing"
                )
                continue

            if already_in:
                pl_pct    = float(position.unrealized_plpc) * 100
                pl_dollar = float(position.unrealized_pl)
                avg_entry = float(position.avg_entry_price)
                qty_held  = int(float(position.qty))

                # Gradert lookback: store vinnerar treng lengre vindauge
                if pl_pct >= 15:
                    lookback = min(48, len(bars))
                elif pl_pct >= 5:
                    lookback = min(24, len(bars))
                else:
                    lookback = min(12, len(bars))
                recent_high = float(bars["close"].tail(lookback).max())
                tech_sell   = result.signal == Signal.SELL

                # Gevinstsikring: 50% ved +20%, heilt ut ved +35%
                already_partial = partial.get(symbol, 0)
                if pl_pct >= 35 and already_partial < 100:
                    # Sel alt — ingen stub-posisjonar att
                    sell_all(symbol)
                    _save_cooldown(symbol, cooldown)
                    _remove_entry(symbol, entries)
                    partial.pop(symbol, None)
                    n_open -= 1
                    log.info(f"{symbol}: FULLSALG ved +{pl_pct:.0f}% — gevinst sikra")
                    notifier.send_trade(embeds=[notifier.sell_embed(
                        symbol, qty_held, avg_entry, price,
                        pl_dollar, pl_pct,
                        f"Fullsalg ved +{pl_pct:.0f}% — gevinst sikra"
                    )])
                    continue
                elif pl_pct >= 20 and already_partial < 50 and qty_held >= 2:
                    partial_qty = max(1, qty_held // 2)
                    remaining   = qty_held - partial_qty
                    if remaining < 2:
                        # For lite att etter 50% — sel alt for å unngå stub
                        sell_all(symbol)
                        _save_cooldown(symbol, cooldown)
                        _remove_entry(symbol, entries)
                        partial.pop(symbol, None)
                        n_open -= 1
                        log.info(f"{symbol}: FULLSALG ved +{pl_pct:.0f}% (stub-unngåing)")
                        notifier.send_trade(embeds=[notifier.sell_embed(
                            symbol, qty_held, avg_entry, price,
                            pl_dollar, pl_pct,
                            f"Fullsalg ved +{pl_pct:.0f}% — for få aksjar att"
                        )])
                        continue
                    sell_partial(symbol, partial_qty)
                    _save_partial(symbol, 50, partial)
                    log.info(f"{symbol}: DELSELG 50% ({partial_qty} aksjar) — P&L={pl_pct:+.2f}%")
                    notifier.send_trade(embeds=[notifier.sell_embed(
                        symbol, partial_qty, avg_entry, price,
                        pl_dollar * 0.5, pl_pct,
                        f"Partialsalg 50% — sikrar gevinst ved +{pl_pct:.0f}%"
                    )])

                # Tidsbasert exit: stagnerande posisjon etter 5 dagar < +3%
                if _is_stale(symbol, pl_pct, entries):
                    decision   = "SELG"
                    sell_note  = f"stagnant {entries.get(symbol)} — {pl_pct:+.2f}% etter {_STALE_DAYS}d"
                else:
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
                    _save_cooldown(symbol, cooldown)
                    _remove_entry(symbol, entries)
                    partial.pop(symbol, None)
                    n_open -= 1
                    notifier.send_trade(embeds=[notifier.sell_embed(
                        symbol, qty_held, avg_entry, price,
                        pl_dollar, pl_pct, sell_reason
                    )])

        except Exception as e:
            log.error(f"{symbol}: feil — {e}")

    log.info(f"Syklus ferdig. Opne posisjonar: {n_open}/{config.MAX_OPEN_POSITIONS}")

    # ── MOMENTUM-SCAN ──────────────────────────────────────────────────────
    # Tråd buying_power + n_open vidare så scans ikkje dobbel-deployerer same cash
    if buys_allowed and n_open < config.MAX_OPEN_POSITIONS:
        buying_power, n_open = _run_momentum_scan(
            equity, open_positions, n_open, buys_allowed, buying_power
        )

    # ── DIP-SCAN (mega-cap mean-reversion, hald til target) ─────────────────
    if buys_allowed and n_open < config.MAX_OPEN_POSITIONS:
        buying_power, n_open = _run_dip_scan(
            equity, open_positions, n_open, buying_power, dips, cooldown
        )


def _run_momentum_scan(equity: float, open_positions: dict, n_open: int,
                       buys_allowed: bool, buying_power: float = 0) -> tuple[float, int]:
    """Skanner watchlisten for store dagleg hopp og kjøper momentum-aksjar.

    Returnerer (buying_power, n_open) etter scan så kallaren kan tråde resten
    av cash-budsjettet vidare — hindrar at neste scan brukar same pengar.
    """
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
                continue  # ein billegare kandidat seinare kan framleis passe

            buy(symbol, qty, sl, tp)
            buying_power -= invest_amount
            n_open += 1
            notifier.send_trade(embeds=[notifier.buy_embed(
                symbol, qty, price, sl, tp, invest_pct, equity,
                result.reason
            )])
        except Exception as e:
            log.error(f"Momentum {symbol}: {e}")

    return buying_power, n_open


def _run_dip_scan(equity: float, open_positions: dict, n_open: int,
                  buying_power: float, dips: dict, cooldown: dict) -> tuple[float, int]:
    """Skanner mega-cap for oversold dropp og kjøper mean-reversion (hald til target).

    Dip-posisjonar får breiare stop + recovery-target via bracket og handterast
    IKKJE av standard exit-logikk (sjå skip i run_cycle).

    Returnerer (buying_power, n_open) etter scan.
    """
    import yfinance as yf

    log.info("--- Dip-scan (mega-cap mean-reversion) ---")
    for symbol in config.WATCHLIST:
        if config.SECTOR_MAP.get(symbol) != "mega_cap":
            continue
        if symbol in open_positions or symbol in dips:
            continue
        if _in_cooldown(symbol, cooldown):
            continue
        if n_open >= config.MAX_OPEN_POSITIONS:
            break
        try:
            daily = yf.Ticker(symbol).history(period="5d")[["Open","High","Low","Close","Volume"]]
            daily.columns = [c.lower() for c in daily.columns]
            daily.index.name = "timestamp"

            intra  = get_bars(symbol, limit=30)
            result = dip_strat.analyze(daily, intra)

            if result.signal != "BUY":
                continue

            log.info(f"{symbol}: DIP {result.drop_pct:+.1f}% | RSI={result.rsi:.1f}")
            price          = float(daily["close"].iloc[-1])
            # Større fall = sterkare mean-reversion-case, men cap conviction (kvalitet, ikkje jakt)
            conviction     = min(7.0, 5.0 + abs(result.drop_pct) * 0.1)
            conviction_qty = position_size(equity, price, conviction)
            cap_qty        = math.floor(equity * config.MAX_POSITION_PCT / price)
            qty            = max(1, min(conviction_qty, cap_qty))
            invest_amount  = qty * price
            invest_pct     = invest_amount / equity * 100
            sl             = round(price * (1 - config.DIPBUY_STOP_LOSS), 2)
            tp             = round(price * (1 + config.DIPBUY_TARGET_PCT), 2)

            if invest_amount > buying_power:
                log.info(f"{symbol}: ikkje nok buying power for dip-kjøp")
                continue  # ein billegare kandidat seinare kan framleis passe

            buy(symbol, qty, sl, tp)
            _save_dip(symbol, dips)
            buying_power -= invest_amount
            n_open += 1
            log.info(
                f"{symbol}: DIP-KJØP {qty} aksjer @ ~${price:.2f} "
                f"({invest_pct:.1f}%, conviction={conviction:.1f}) | SL=${sl} target=${tp}"
            )
            notifier.send_trade(embeds=[notifier.buy_embed(
                symbol, qty, price, sl, tp, invest_pct, equity,
                f"💧 Dip-buy (hald til +{config.DIPBUY_TARGET_PCT*100:.0f}%): {result.reason}"
            )])
        except Exception as e:
            log.error(f"Dip {symbol}: {e}")

    return buying_power, n_open


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
    elif "--twice" in sys.argv:
        run_cycle()
        log.info("Ventar 30 min til neste syklus...")
        time.sleep(1800)
        run_cycle()
    else:
        main()
