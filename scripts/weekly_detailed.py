"""Bullbot laurdag-rapport — detaljert dagleg og vekeoppsummering til Discord."""
import os, requests, yfinance as yf
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest, GetPortfolioHistoryRequest
from alpaca.trading.enums import QueryOrderStatus
import config

DISCORD = os.environ["DISCORD_WEBHOOK"]
tc = TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=config.PAPER)

acct   = tc.get_account()
equity = float(acct.equity)
cash   = float(acct.cash)

today  = date.today()
monday = today - timedelta(days=today.weekday())
week_days = [monday + timedelta(days=i) for i in range(5)]  # Man-fre

# ── Porteføljehistorikk ──────────────────────────────────────────────────────
try:
    hist = tc.get_portfolio_history(GetPortfolioHistoryRequest(period="1W", timeframe="1D"))
    eq_by_date = {}
    for ts, eq_val in zip(hist.timestamp, hist.equity):
        if ts and eq_val and eq_val > 0:
            d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
            eq_by_date[d] = eq_val
    week_base = min(eq_by_date.values()) if eq_by_date else None
    week_pl   = equity - week_base if week_base else 0
    week_pct  = week_pl / week_base * 100 if week_base else 0
except Exception:
    eq_by_date = {}
    week_pl = week_pct = 0

try:
    hist1m   = tc.get_portfolio_history(GetPortfolioHistoryRequest(period="1M", timeframe="1D"))
    start_eq = next((v for v in hist1m.equity if v and v > 0), None)
    total_pl  = equity - start_eq if start_eq else 0
    total_pct = total_pl / start_eq * 100 if start_eq else 0
except Exception:
    total_pl = total_pct = 0

# ── Ordrar for heile veka ────────────────────────────────────────────────────
week_start_dt = datetime.combine(monday, datetime.min.time()).replace(tzinfo=timezone.utc)
orders  = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=week_start_dt, limit=500))
filled  = [o for o in orders if o.status.value == "filled"]
buys    = [o for o in filled if o.side.value == "buy"]
sells   = [o for o in filled if o.side.value == "sell"]

orders_by_day = defaultdict(list)
for o in filled:
    if o.filled_at:
        orders_by_day[o.filled_at.date()].append(o)

# ── Posisjonar ───────────────────────────────────────────────────────────────
positions  = list(tc.get_all_positions())
sorted_pos = sorted(positions, key=lambda x: float(x.unrealized_plpc), reverse=True)
upl        = sum(float(p.unrealized_pl) for p in positions)

def pos_line(p):
    pct    = float(p.unrealized_plpc) * 100
    pl_usd = float(p.unrealized_pl)
    icon   = "▲" if pct >= 0 else "▼"
    return f"{icon} **{p.symbol}** `{pct:+.2f}%` (${pl_usd:+,.0f})"

# ── Dagleg aksjeperformance frå yfinance ─────────────────────────────────────
syms = config.WATCHLIST
daily_best  = {}  # date -> (symbol, pct)
daily_worst = {}  # date -> (symbol, pct)
try:
    raw = yf.download(
        syms,
        start=monday,
        end=today + timedelta(days=1),
        progress=False,
        auto_adjust=True,
        group_by="ticker",
    )
    # Støttar både single og multi-ticker-format
    import pandas as pd
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw.xs("Close", axis=1, level=1)
    else:
        close = raw[["Close"]].rename(columns={"Close": syms[0]}) if len(syms) == 1 else raw["Close"]

    dates_sorted = sorted(close.index)
    for i in range(1, len(dates_sorted)):
        d     = dates_sorted[i].date()
        d_prev = dates_sorted[i - 1].date()
        changes = {}
        for sym in syms:
            try:
                prev = close.loc[dates_sorted[i - 1], sym]
                curr = close.loc[dates_sorted[i], sym]
                if prev and prev > 0:
                    changes[sym] = (curr - prev) / prev * 100
            except Exception:
                pass
        if changes:
            daily_best[d]  = max(changes.items(), key=lambda x: x[1])
            daily_worst[d] = min(changes.items(), key=lambda x: x[1])
except Exception as e:
    print(f"yfinance-feil: {e}")

# ── Bygg Discord-embeds ───────────────────────────────────────────────────────
embeds = []
veke_nr  = today.isocalendar()[1]
pl_icon  = "📈" if week_pl >= 0 else "📉"
upl_icon = "💹" if upl >= 0 else "🔻"

top3 = "\n".join(pos_line(p) for p in sorted_pos[:3])  if sorted_pos else "—"
bot3 = "\n".join(pos_line(p) for p in sorted_pos[-3:]) if len(sorted_pos) >= 3 else "—"

# 1) Vekeoppsummering
weekly_embed = {
    "title": f"{pl_icon} Veke {veke_nr} — {monday.strftime('%d.%m')}–{today.strftime('%d.%m.%Y')}",
    "color": 0x2ECC71 if week_pl >= 0 else 0xE74C3C,
    "fields": [
        {"name": "💰 Porteføljeverdi",        "value": f"**${equity:,.2f}**",                          "inline": True},
        {"name": f"{pl_icon} Vekes-P&L",      "value": f"**${week_pl:+,.2f}** `{week_pct:+.2f}%`",   "inline": True},
        {"name": "🚀 Total P&L",              "value": f"**${total_pl:+,.2f}** `{total_pct:+.2f}%`",  "inline": True},
        {"name": f"{upl_icon} Urealisert P&L","value": f"**${upl:+,.2f}**",                            "inline": True},
        {"name": "💵 Cash",                   "value": f"${cash:,.2f}",                               "inline": True},
        {"name": "📊 Opne posisjonar",         "value": str(len(positions)),                            "inline": True},
        {"name": "🏆 Beste aksjar",            "value": top3,                                          "inline": False},
        {"name": "📉 Svakaste aksjar",         "value": bot3,                                          "inline": False},
        {"name": "🔄 Handel",                  "value": f"{len(buys)} kjøp  |  {len(sells)} sal  |  {len(filled)} totalt", "inline": False},
    ],
    "footer": {"text": f"Bullbot  •  Laurdag {today.strftime('%d.%m.%Y')}  •  Ha ei god helg! 🎯"},
}
embeds.append(weekly_embed)

# 2) Dagleg breakdown (Man-Fre)
day_names = ["Måndag", "Tysdag", "Onsdag", "Torsdag", "Fredag"]
sorted_dates = sorted(eq_by_date.keys())

for i, day in enumerate(week_days):
    if day > today:
        break

    day_orders = orders_by_day.get(day, [])
    day_buys   = [o for o in day_orders if o.side.value == "buy"]
    day_sells  = [o for o in day_orders if o.side.value == "sell"]

    day_eq = eq_by_date.get(day)
    # Finn forrige handelsdag
    prev_dates = [d for d in sorted_dates if d < day]
    prev_eq    = eq_by_date.get(prev_dates[-1]) if prev_dates else None

    day_pl  = (day_eq - prev_eq) if (day_eq and prev_eq) else None
    day_pct = (day_pl / prev_eq * 100) if (day_pl is not None and prev_eq) else None

    best  = daily_best.get(day)
    worst = daily_worst.get(day)

    d_icon = "📈" if (day_pl is not None and day_pl >= 0) else "📉"
    color  = 0x2ECC71 if (day_pl and day_pl >= 0) else (0xE74C3C if day_pl is not None else 0x95A5A6)

    fields = []

    if day_pl is not None:
        fields.append({"name": f"{d_icon} Dag P&L", "value": f"**${day_pl:+,.2f}** `{day_pct:+.2f}%`", "inline": True})
    if day_eq:
        fields.append({"name": "💰 Eigenkapital", "value": f"${day_eq:,.2f}", "inline": True})

    if best:
        fields.append({"name": "🏆 Beste aksje", "value": f"**{best[0]}** `{best[1]:+.2f}%`", "inline": True})
    if worst:
        fields.append({"name": "📉 Svakaste aksje", "value": f"**{worst[0]}** `{worst[1]:+.2f}%`", "inline": True})

    trade_txt = f"{len(day_buys)} kjøp  |  {len(day_sells)} sal" if day_orders else "Ingen handler"
    fields.append({"name": "🔄 Handler", "value": trade_txt, "inline": True})

    if day_orders:
        lines = []
        for o in day_orders[:6]:
            side  = "🟢" if o.side.value == "buy" else "🔴"
            qty   = float(o.filled_qty or 0)
            price = float(o.filled_avg_price or 0)
            lines.append(f"{side} **{o.symbol}** {qty:.0f}x @ ${price:.2f}")
        fields.append({"name": "📋 Detaljar", "value": "\n".join(lines), "inline": False})

    embeds.append({
        "title":  f"{d_icon} {day_names[i]} {day.strftime('%d.%m.%Y')}",
        "color":  color,
        "fields": fields or [{"name": "—", "value": "Ingen data", "inline": False}],
    })

# ── Send til Discord (maks 10 embeds per melding) ────────────────────────────
for i in range(0, len(embeds), 10):
    batch = embeds[i:i + 10]
    resp  = requests.post(DISCORD, json={"embeds": batch}, timeout=10)
    print(f"Discord batch {i // 10 + 1} sendt: HTTP {resp.status_code}")
    if resp.status_code not in (200, 204):
        print(f"Feil: {resp.text}")
