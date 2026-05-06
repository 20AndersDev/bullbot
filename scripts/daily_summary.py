"""Bullbot dagsoppsummering — sender Discord-embed."""
import os, requests
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone, date
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

import config
DISCORD = os.environ["DISCORD_WEBHOOK"]
tc = TradingClient(os.environ["ALPACA_API_KEY"], os.environ["ALPACA_SECRET_KEY"], paper=config.PAPER)

acct    = tc.get_account()
equity  = float(acct.equity)
last_eq = float(acct.last_equity)
pl      = equity - last_eq
pl_pct  = pl / last_eq * 100 if last_eq else 0
cash    = float(acct.cash)

from alpaca.trading.requests import GetPortfolioHistoryRequest
try:
    hist       = tc.get_portfolio_history(GetPortfolioHistoryRequest(period="1M", timeframe="1D"))
    start_eq   = next((v for v in hist.equity if v and v > 0), None)
    total_pl   = equity - start_eq if start_eq else 0
    total_pct  = total_pl / start_eq * 100 if start_eq else 0
except Exception:
    total_pl = total_pct = 0

today  = date.today()
start  = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=start, limit=200))
filled = [o for o in orders if o.status.value == "filled"]
buys   = [o for o in filled if o.side.value == "buy"]
sells  = [o for o in filled if o.side.value == "sell"]

positions = list(tc.get_all_positions())
upl       = sum(float(p.unrealized_pl) for p in positions)
sorted_pos = sorted(positions, key=lambda x: float(x.unrealized_plpc), reverse=True)

def _pos_line(p):
    pct    = float(p.unrealized_plpc) * 100
    pl_usd = float(p.unrealized_pl)
    icon   = "▲" if pct >= 0 else "▼"
    return f"{icon} **{p.symbol}**  `{pct:+.2f}%`  (${pl_usd:+,.0f})"

top3  = "\n".join(_pos_line(p) for p in sorted_pos[:3])  if sorted_pos else "—"
bot3  = "\n".join(_pos_line(p) for p in sorted_pos[-3:]) if len(sorted_pos) >= 3 else "—"

pl_icon  = "📈" if pl >= 0 else "📉"
upl_icon = "💹" if upl >= 0 else "🔻"
res_txt  = "POSITIV DAG" if pl >= 0 else "NEGATIV DAG"

fields = [
    {"name": "💰 Porteføljeverdi",          "value": f"**${equity:,.2f}**",                        "inline": True},
    {"name": f"{pl_icon} Dag P&L",          "value": f"**${pl:+,.2f}**  `{pl_pct:+.2f}%`",      "inline": True},
    {"name": "🚀 Total P&L",               "value": f"**${total_pl:+,.2f}**  `{total_pct:+.2f}%`", "inline": True},
    {"name": "🏆 Beste aksjar i dag",       "value": top3,                                     "inline": False},
    {"name": "📉 Svakaste aksjar i dag",    "value": bot3,                                     "inline": False},
    {"name": "🔄 Handel i dag",
     "value": f"{len(buys)} kjøp  |  {len(sells)} sal  |  {len(filled)} totalt",              "inline": True},
    {"name": "💵 Tilgjengeleg cash",        "value": f"${cash:,.2f}",                          "inline": True},
]

embed = {
    "title":  f"{'📈' if pl >= 0 else '📉'} {res_txt}  —  {today.strftime('%d.%m.%Y')}",
    "color":  0x2ECC71 if pl >= 0 else 0xE74C3C,
    "fields": fields,
    "footer": {"text": f"Bullbot  •  {today.strftime('%A %d. %B %Y')}  •  {len(positions)} opne posisjonar"},
}

resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=10)
print(f"Discord dagsoppsummering sendt: HTTP {resp.status_code}")
