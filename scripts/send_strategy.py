"""
Sender dagsstrategi-embed til Discord strategi-kanalen.

Bruk:
  python scripts/send_strategy.py '<json>'

JSON-format:
{
  "marknad":      "BULLISH",          # BULLISH | BEARISH | NOEYTRAL
  "fear_greed":   66,
  "vix":          18.7,
  "kjoep":        ["NVDA — strong_buy, +29% upside", "META — positiv nyheit"],
  "unngaa":       ["TSLA — earnings om 2 dagar"],
  "momentum":     ["COIN — opp +5.2% i dag"],
  "marknadsnote": "Fed-møte tysdag. Mega-cap earnings-sesong i gang.",
  "er_kveld":     false
}
"""
import os, sys, json, requests
from datetime import date
from dotenv import load_dotenv
load_dotenv()

DISCORD = os.environ.get("DISCORD_STRATEGY_WEBHOOK", "")
if not DISCORD:
    print("DISCORD_STRATEGY_WEBHOOK ikkje sett")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Bruk: python scripts/send_strategy.py '<json>'")
    sys.exit(1)

data = json.loads(sys.argv[1])

sentiment   = data.get("marknad", "NOEYTRAL")
fear_greed  = data.get("fear_greed", 0)
vix         = data.get("vix", 0)
kjoep       = data.get("kjoep", [])
unngaa      = data.get("unngaa", [])
momentum    = data.get("momentum", [])
note        = data.get("marknadsnote", "")
er_kveld    = data.get("er_kveld", False)

color_map = {"BULLISH": 0x2ECC71, "BEARISH": 0xE74C3C, "NOEYTRAL": 0xF1C40F}
color     = color_map.get(sentiment, 0xF1C40F)

tittel = f"{'🌙 Kveldstrategi' if er_kveld else '🌅 Dagsstrategi'}  —  {date.today().strftime('%d.%m.%Y')}"

fields = [
    {
        "name": "📊 Marknad",
        "value": (
            f"**{sentiment}**\n"
            f"Fear & Greed: {fear_greed:.0f}/100  |  VIX: {vix:.1f}"
        ),
        "inline": False,
    },
    {
        "name": f"🛒 Kjøp i dag ({len(kjoep)})",
        "value": "\n".join(f"• {k}" for k in kjoep) or "Ingen signal",
        "inline": False,
    },
    {
        "name": f"🚀 Momentum-radar ({len(momentum)})",
        "value": "\n".join(f"• {m}" for m in momentum) or "Ingen store hopp",
        "inline": False,
    },
    {
        "name": f"🚫 Unngå i dag ({len(unngaa)})",
        "value": "\n".join(f"• {u}" for u in unngaa) or "Ingen varslar",
        "inline": False,
    },
]

if note:
    fields.append({"name": "📅 Marknadsnote", "value": note, "inline": False})

embed = {"title": tittel, "color": color, "fields": fields}

resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=10)
print(f"Strategi sendt til Discord: HTTP {resp.status_code}")
