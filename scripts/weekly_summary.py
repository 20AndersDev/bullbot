"""Bullbot vekesoppsummering — sender Discord-embed."""
import os, requests
from datetime import datetime, timezone, timedelta, date
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest, GetPortfolioHistoryRequest
from alpaca.trading.enums import QueryOrderStatus

DISCORD = os.environ["DISCORD_WEBHOOK"]
tc = TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=True)

acct   = tc.get_account()
equity = float(acct.equity)
cash   = float(acct.cash)

today      = date.today()
start_week = today - timedelta(days=today.weekday())
start_dt   = datetime.combine(start_week, datetime.min.time()).replace(tzinfo=timezone.utc)

orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=start_dt, limit=500))
filled = [o for o in orders if o.status.value == "filled"]
buys   = [o for o in filled if o.side.value == "buy"]
sells  = [o for o in filled if o.side.value == "sell"]

try:
    hist     = tc.get_portfolio_history(GetPortfolioHistoryRequest(period="1W", timeframe="1D"))
    week_pl  = equity - hist.equity[0] if hist.equity and hist.equity[0] else 0
    week_pct = week_pl / hist.equity[0] * 100 if hist.equity and hist.equity[0] else 0
except Exception:
    week_pl = week_pct = 0

positions = tc.get_all_positions()
upl = sum(float(p.unrealized_pl) for p in positions)

sym_cnt = {}
for o in filled:
    sym_cnt[o.symbol] = sym_cnt.get(o.symbol, 0) + 1
topp      = sorted(sym_cnt.items(), key=lambda x: -x[1])[:5]
topp_text = "\n".join(f"{s}: {c} ordrar" for s, c in topp) if topp else "Ingen"

pos_lines = []
for p in sorted(positions, key=lambda x: float(x.unrealized_plpc), reverse=True):
    pct = float(p.unrealized_plpc) * 100
    pos_lines.append(f"{p.symbol}: {p.qty}stk  {pct:+.2f}%  (${float(p.unrealized_pl):+,.0f})")

embed = {
    "title": f"📅 Bullbot Vekesoppsummering — Veke {today.isocalendar()[1]}  "
             f"({start_week.strftime('%d.%m')} – {today.strftime('%d.%m.%Y')})",
    "color": 0x2ECC71 if week_pl >= 0 else 0xE74C3C,
    "fields": [
        {"name": "💰 Porteføljeverdi", "value": f"${equity:,.2f}",                        "inline": True},
        {"name": "📈 Vekes-P&L",       "value": f"${week_pl:+,.2f} ({week_pct:+.2f}%)",   "inline": True},
        {"name": "⏳ Urealisert P&L",  "value": f"${upl:+,.2f}",                           "inline": True},
        {"name": "💵 Kontantar",       "value": f"${cash:,.2f}",                           "inline": True},
        {"name": "🔄 Handel",          "value": f"{len(filled)} ordrar  (kjøp:{len(buys)} sal:{len(sells)})", "inline": True},
        {"name": "🏆 Mest handla",     "value": topp_text,                                 "inline": False},
        {"name": f"📁 Opne posisjonar ({len(positions)})",
         "value": "\n".join(pos_lines) or "Ingen opne posisjonar",                         "inline": False},
    ],
    "footer": {"text": "Ha ei god helg! 🎯"},
}
resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=10)
print(f"Discord vekesoppsummering sendt: HTTP {resp.status_code}")
