"""
Sender dagsstrategi-embed til Discord strategi-kanalen.

Bruk:
  python scripts/send_strategy.py '<json>'

JSON-format (kjoep/unngaa/momentum er lister av dict-objekt):
{
  "marknad":      "BULLISH",
  "fear_greed":   66,
  "vix":          18.7,
  "kjoep":        [{"symbol":"NVDA","rec":"STRONG_BUY","upside_pct":29,"grunn":"...","hald":"3-7 dagar"}],
  "unngaa":       [{"symbol":"TSLA","grunn":"earnings om 2 dagar"}],
  "momentum":     [{"symbol":"AMD","day_pct":13.9,"grunn":"...","hald":"1-2 dagar"}],
  "marknadsnote": "Fed Funds: 3.64%  |  10Y: 4.34%",
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

sentiment  = data.get("marknad", "NOEYTRAL")
fear_greed = data.get("fear_greed", 0)
vix        = data.get("vix", 0)
kjoep        = data.get("kjoep", [])
unngaa       = data.get("unngaa", [])
momentum     = data.get("momentum", [])
reddit_radar = data.get("reddit_radar", [])
note         = data.get("marknadsnote", "")
er_kveld     = data.get("er_kveld", False)

color_map = {"BULLISH": 0x2ECC71, "BEARISH": 0xE74C3C, "NOEYTRAL": 0xF1C40F}
color     = color_map.get(sentiment, 0xF1C40F)

tittel = (
    f"{'Kveldstrategi' if er_kveld else 'Dagsstrategi'}"
    f"  —  {date.today().strftime('%d.%m.%Y')}"
)


def _fmt_kjoep(items: list) -> str:
    """Formater kjøpsliste kompakt (maks ~160 teikn per rad for å halde seg under 1024)."""
    lines = []
    for item in items:
        if isinstance(item, dict):
            sym    = item.get("symbol", "?")
            rec    = item.get("rec", "").upper()
            upside = item.get("upside_pct", 0)
            grunn  = item.get("grunn", "")
            hald   = item.get("hald", "")
            pre_e  = item.get("pre_earnings", False)

            warn = "⚠️ " if pre_e else ""
            head = f"{warn}**{sym}**"
            if rec not in ("N/A", "NONE", ""):
                head += f" {rec}"
            if upside and upside > 0:
                head += f" +{upside:.0f}%"

            # Hald og truncated grunn på same linje
            detail = ""
            if hald:
                detail += f"Hald: {hald}"
            if grunn:
                detail += (" | " if detail else "") + grunn[:75]

            lines.append(head + (f"\n  {detail}" if detail else ""))
        else:
            lines.append(f"• {item}")
    return "\n".join(lines) or "Ingen signal"


def _fmt_reddit_radar(items: list) -> str:
    """Formater Reddit-radar med sentiment og type."""
    if not items:
        return "Ingen Reddit-aktivitet i dag"
    lines = []
    for item in items:
        if isinstance(item, dict):
            sym      = item.get("symbol", "?")
            mentions = item.get("mentions", 0)
            buy      = item.get("buy", 0)
            sell     = item.get("sell", 0)
            senti    = item.get("sentiment", "NOEYTRAL")
            tags     = []
            if item.get("hype"):  tags.append("WSB")
            if item.get("value"): tags.append("value")

            icon  = {"BULLISH": "+", "BEARISH": "-", "NOEYTRAL": "~"}.get(senti, "~")
            line  = f"{icon} **{sym}** — {mentions} nemn."
            if buy:  line += f"  {buy} buy"
            if sell: line += f"  {sell} sell"
            if tags: line += f"  [{', '.join(tags)}]"
            lines.append(line)
    return "\n".join(lines) or "Ingen aktivitet"


def _fmt_unngaa(items: list) -> str:
    """Formater unngå-liste med grunngjeving."""
    lines = []
    for item in items:
        if isinstance(item, dict):
            sym   = item.get("symbol", "?")
            grunn = item.get("grunn", "")
            line  = f"• **{sym}**"
            if grunn:
                line += f" — {grunn}"
            lines.append(line)
        else:
            lines.append(f"• {item}")
    return "\n".join(lines) or "Ingen varslar"


def _fmt_momentum(items: list) -> str:
    """Formater momentum-radar med haldetid."""
    lines = []
    for item in items:
        if isinstance(item, dict):
            sym  = item.get("symbol", "?")
            pct  = item.get("day_pct", 0)
            hald = item.get("hald", "")
            line = f"• **{sym}** {pct:+.1f}% i dag"
            if hald:
                line += f"  —  Hald: {hald}"
            lines.append(line)
        else:
            lines.append(f"• {item}")
    return "\n".join(lines) or "Ingen store hopp"


fields = [
    {
        "name": "Marknad",
        "value": (
            f"**{sentiment}**\n"
            f"Fear & Greed: {fear_greed:.0f}/100  |  VIX: {vix:.1f}"
        ),
        "inline": False,
    },
    {
        "name": f"Kjop i dag ({len(kjoep)})",
        "value": _fmt_kjoep(kjoep),
        "inline": False,
    },
    {
        "name": f"Momentum-radar ({len(momentum)})",
        "value": _fmt_momentum(momentum),
        "inline": False,
    },
    {
        "name": f"Unnga i dag ({len(unngaa)})",
        "value": _fmt_unngaa(unngaa),
        "inline": False,
    },
    {
        "name": f"Reddit-radar ({len(reddit_radar)})",
        "value": _fmt_reddit_radar(reddit_radar),
        "inline": False,
    },
]

if note:
    fields.append({"name": "Marknadsnote", "value": note, "inline": False})

embed = {"title": tittel, "color": color, "fields": fields}

resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=10)
print(f"Strategi sendt til Discord: HTTP {resp.status_code}")
