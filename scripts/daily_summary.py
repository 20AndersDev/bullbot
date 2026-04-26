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
bp      = float(acct.buying_power)

today  = date.today()
start  = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
orders = tc.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=start, limit=200))
filled = [o for o in orders if o.status.value == "filled"]
buys   = [o for o in filled if o.side.value == "buy"]
sells  = [o for o in filled if o.side.value == "sell"]

positions = tc.get_all_positions()
upl = sum(float(p.unrealized_pl) for p in positions)

# Ordrar med emoji-farge
ord_lines = []
for o in filled[:15]:
    is_buy = o.side.value == "buy"
    icon   = "🟢" if is_buy else "🔴"
    label  = "KJØP" if is_buy else " SAL"
    price  = float(o.filled_avg_price) if o.filled_avg_price else 0
    ord_lines.append(f"{icon} `{label}` **{o.symbol}** × {o.qty} @ ${price:.2f}")

# Posisjonar sortert etter P&L (beste øvst)
pos_lines = []
for p in sorted(positions, key=lambda x: float(x.unrealized_plpc), reverse=True):
    pct     = float(p.unrealized_plpc) * 100
    pl_usd  = float(p.unrealized_pl)
    bar     = "▲" if pct >= 0 else "▼"
    pos_lines.append(
        f"{bar} **{p.symbol}** {p.qty} stk  `{pct:+.2f}%`  (${pl_usd:+,.0f})"
    )

pl_icon  = "📈" if pl >= 0 else "📉"
upl_icon = "💹" if upl >= 0 else "🔻"

fields = [
    # Tre inline topprader
    {
        "name":   "💰 Porteføljeverdi",
        "value":  f"**${equity:,.2f}**",
        "inline": True,
    },
    {
        "name":   f"{pl_icon} Dag P&L",
        "value":  f"**${pl:+,.2f}**\n`{pl_pct:+.2f}%`",
        "inline": True,
    },
    {
        "name":   f"{upl_icon} Urealisert P&L",
        "value":  f"**${upl:+,.2f}**",
        "inline": True,
    },
    # Ordrar
    {
        "name":   f"📋 Dagens ordrar  ({len(filled)} totalt  |  {len(buys)} kjøp  {len(sells)} sal)",
        "value":  "\n".join(ord_lines) or "Ingen ordrar i dag",
        "inline": False,
    },
    # Posisjonar
    {
        "name":   f"📁 Opne posisjonar ({len(positions)})",
        "value":  "\n".join(pos_lines) or "Ingen opne posisjonar",
        "inline": False,
    },
    # Cash / buying power inline
    {
        "name":   "💵 Cash",
        "value":  f"${cash:,.2f}",
        "inline": True,
    },
    {
        "name":   "⚡ Buying Power",
        "value":  f"${bp:,.2f}",
        "inline": True,
    },
]

embed = {
    "title":  f"📊 Bullbot Dagsoppsummering  —  {today.strftime('%d.%m.%Y')}",
    "color":  0x2ECC71 if pl >= 0 else 0xE74C3C,
    "fields": fields,
    "footer": {"text": f"Bullbot  •  {today.strftime('%A %d. %B %Y')}"},
}

resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=10)
print(f"Discord dagsoppsummering sendt: HTTP {resp.status_code}")
