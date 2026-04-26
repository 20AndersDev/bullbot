"""
Sender dagsstrategi-embed til Discord strategi-kanalen.
Bruk: python scripts/send_strategy.py '<json>'
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

sentiment    = data.get("marknad", "NOEYTRAL")
fear_greed   = data.get("fear_greed", 0)
vix          = data.get("vix", 0)
kjoep        = data.get("kjoep", [])
unngaa       = data.get("unngaa", [])
momentum     = data.get("momentum", [])
reddit_radar = data.get("reddit_radar", [])
note         = data.get("marknadsnote", "")
er_kveld     = data.get("er_kveld", False)

COLOR_MAP  = {"BULLISH": 0x2ECC71, "BEARISH": 0xE74C3C, "NOEYTRAL": 0xF1C40F}
SENTI_ICON = {"BULLISH": "🟢", "BEARISH": "🔴", "NOEYTRAL": "🟡"}
FG_ICON    = lambda s: "😱" if s < 25 else ("😨" if s < 40 else ("😐" if s < 60 else ("😏" if s < 75 else "🤑")))

color  = COLOR_MAP.get(sentiment, 0xF1C40F)
icon   = SENTI_ICON.get(sentiment, "🟡")
tittel = f"{'🌙 Kveldstrategi' if er_kveld else '🌅 Dagsstrategi'}  —  {date.today().strftime('%d.%m.%Y')}"


def _fmt_kjoep(items: list) -> str:
    if not items:
        return "Ingen signal i dag"
    lines = []
    for item in items:
        if isinstance(item, dict):
            sym    = item.get("symbol", "?")
            rec    = item.get("rec", "").replace("_", " ")
            upside = item.get("upside_pct", 0)
            grunn  = item.get("grunn", "")
            hald   = item.get("hald", "")
            pre_e  = item.get("pre_earnings", False)

            prefix = "⚠️" if pre_e else "🟢"
            head   = f"{prefix} **{sym}**"
            if rec and rec not in ("N/A", "NONE"):
                head += f"  `{rec}`"
            if upside and upside > 0:
                head += f"  +{upside:.0f}%"

            details = []
            if hald:
                details.append(f"⏱ {hald}")
            if grunn:
                details.append(grunn[:80])
            detail_str = "  |  ".join(details)

            lines.append(head + (f"\n  {detail_str}" if detail_str else ""))
        else:
            lines.append(f"🟢 {item}")
    return "\n".join(lines)


def _fmt_unngaa(items: list) -> str:
    if not items:
        return "Ingen aksjar å unngå i dag"
    lines = []
    for item in items:
        if isinstance(item, dict):
            sym   = item.get("symbol", "?")
            grunn = item.get("grunn", "")
            icon  = "⚠️" if "earnings" in grunn.lower() else "🚫"
            line  = f"{icon} **{sym}**"
            if grunn:
                line += f" — {grunn}"
            lines.append(line)
        else:
            lines.append(f"🚫 {item}")
    return "\n".join(lines)


def _fmt_momentum(items: list) -> str:
    if not items:
        return "Ingen store dagleg hopp"
    lines = []
    for item in items:
        if isinstance(item, dict):
            sym  = item.get("symbol", "?")
            pct  = item.get("day_pct", 0)
            hald = item.get("hald", "")
            arrow = "🚀" if pct > 0 else "📉"
            line  = f"{arrow} **{sym}** {pct:+.1f}%"
            if hald:
                line += f"  —  ⏱ {hald}"
            lines.append(line)
        else:
            lines.append(f"🚀 {item}")
    return "\n".join(lines)


def _fmt_reddit(items: list) -> str:
    if not items:
        return "Ingen aktivitet i dag"
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

            r_icon = {"BULLISH": "📈", "BEARISH": "📉", "NOEYTRAL": "➡️"}.get(senti, "➡️")
            line   = f"{r_icon} **{sym}** — {mentions} nemn."
            if buy:  line += f"  ✅ {buy} buy"
            if sell: line += f"  ❌ {sell} sell"
            if tags: line += f"  `{', '.join(tags)}`"
            lines.append(line)
    return "\n".join(lines)


fields = [
    # Tre inline-felt øvst: sentiment, F&G, VIX
    {
        "name":   "Marknad",
        "value":  f"{icon} **{sentiment}**",
        "inline": True,
    },
    {
        "name":   f"{FG_ICON(fear_greed)} Fear & Greed",
        "value":  f"**{fear_greed:.0f}** / 100",
        "inline": True,
    },
    {
        "name":   "📊 VIX",
        "value":  f"**{vix:.1f}**",
        "inline": True,
    },
    # Kjøpsliste
    {
        "name":   f"🛒 Kjøp i dag ({len(kjoep)})",
        "value":  _fmt_kjoep(kjoep),
        "inline": False,
    },
    # Momentum
    {
        "name":   f"🚀 Momentum-radar ({len(momentum)})",
        "value":  _fmt_momentum(momentum),
        "inline": False,
    },
    # Unngå
    {
        "name":   f"🚫 Unngå i dag ({len(unngaa)})",
        "value":  _fmt_unngaa(unngaa),
        "inline": False,
    },
    # Reddit
    {
        "name":   f"📱 Reddit-radar ({len(reddit_radar)})",
        "value":  _fmt_reddit(reddit_radar),
        "inline": False,
    },
]

if note:
    fields.append({
        "name":   "📅 Marknadsnote",
        "value":  note,
        "inline": False,
    })

embed = {
    "title":  tittel,
    "color":  color,
    "fields": fields,
    "footer": {"text": f"Bullbot  •  {date.today().strftime('%A %d. %B %Y')}"},
}

resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=10)
print(f"Strategi sendt til Discord: HTTP {resp.status_code}")
