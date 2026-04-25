"""Bullbot dagsoppsummering — sender Discord-embed."""
import os, requests
from datetime import datetime, timezone, date
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

DISCORD = os.environ["DISCORD_WEBHOOK"]
tc = TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=True)

acct    = tc.get_account()
equity  = float(acct.equity)
last_eq = float(acct.last_equity)
pl      = equity - last_eq
pl_pct  = pl / last_eq * 100 if last_eq else 0
cash    = float(acct.cash)

today = date.today()
start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=start, limit=200))
filled = [o for o in orders if o.status.value == "filled"]
buys   = [o for o in filled if o.side.value == "buy"]
sells  = [o for o in filled if o.side.value == "sell"]

positions = tc.get_all_positions()
upl = sum(float(p.unrealized_pl) for p in positions)

ord_lines = []
for o in filled[:12]:
    side  = "KJØP" if o.side.value == "buy" else " SAL"
    price = float(o.filled_avg_price) if o.filled_avg_price else 0
    ord_lines.append(f"{side}  {o.symbol} x{o.qty} @ ${price:.2f}")

pos_lines = []
for p in sorted(positions, key=lambda x: float(x.unrealized_plpc), reverse=True):
    pct = float(p.unrealized_plpc) * 100
    pos_lines.append(f"{p.symbol}: {p.qty}stk  {pct:+.2f}%  (${float(p.unrealized_pl):+,.0f})")

embed = {
    "title": f"📊 Bullbot Dagsoppsummering — {today.strftime('%d.%m.%Y')}",
    "color": 0x2ECC71 if pl >= 0 else 0xE74C3C,
    "fields": [
        {"name": "💰 Porteføljeverdi", "value": f"${equity:,.2f}",                      "inline": True},
        {"name": "📈 Dag P&L",         "value": f"${pl:+,.2f} ({pl_pct:+.2f}%)",        "inline": True},
        {"name": "⏳ Urealisert P&L",  "value": f"${upl:+,.2f}",                         "inline": True},
        {"name": f"📋 Ordrar ({len(filled)} | kjøp:{len(buys)} sal:{len(sells)})",
         "value": "\n".join(ord_lines) or "Ingen ordrar i dag",                          "inline": False},
        {"name": f"📁 Opne posisjonar ({len(positions)})",
         "value": "\n".join(pos_lines) or "Ingen opne posisjonar",                       "inline": False},
    ],
}
resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=10)
print(f"Discord dagsoppsummering sendt: HTTP {resp.status_code}")
