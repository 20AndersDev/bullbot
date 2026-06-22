import json, requests, os
from pathlib import Path
from datetime import date

DISCORD = os.environ.get("DISCORD_STRATEGY_WEBHOOK", "")
if not DISCORD:
    print("DISCORD_STRATEGY_WEBHOOK ikkje sett")
    raise SystemExit(1)

reports = sorted(Path("knowledge").glob("report_*.json"), reverse=True)
with open(reports[0]) as f:
    k = json.load(f)
s = k.get("strategi", {})

sentiment  = s.get("marknad", "BEARISH")
fear_greed = s.get("fear_greed", 35)
vix        = s.get("vix", 17.3)
portfolio  = s.get("portfolio", [])
kjoep      = s.get("kjoep", [])
unngaa     = s.get("unngaa", [])
momentum   = s.get("momentum", [])[:12]

fg_score = fear_greed if isinstance(fear_greed, (int, float)) else fear_greed.get("score", 35)
fg_icon  = "\U0001f628" if fg_score < 40 else ("\U0001f610" if fg_score < 60 else "\U0001f60f")

COLOR_MAP  = {"BULLISH": 0x2ECC71, "BEARISH": 0xE74C3C, "NOEYTRAL": 0xF1C40F}
SENTI_ICON = {"BULLISH": "\U0001f7e2", "BEARISH": "\U0001f534", "NOEYTRAL": "\U0001f7e1"}

color = COLOR_MAP.get(sentiment, 0xF1C40F)
icon  = SENTI_ICON.get(sentiment, "\U0001f7e1")
tittel = "\U0001f305 Dagsstrategi  —  " + date.today().strftime("%d.%m.%Y")

def fmt_portfolio(items):
    lines = []
    for p in items:
        sym    = p.get("symbol", "?")
        pl     = p.get("pl_pct", 0)
        action = p.get("action", "HALD")
        if action == "SELG":
            a_icon = "\U0001f534"
        elif action == "MONITOR":
            a_icon = "⚠️"
        elif pl >= 0:
            a_icon = "✅"
        else:
            a_icon = "\U0001f536"
        lines.append(f"{a_icon} **{sym}** `{pl:+.1f}%` → {action}")
    return "\n".join(lines) or "Tom"

def fmt_kjoep(items):
    lines = []
    for item in items:
        sym    = item.get("symbol", "?")
        upside = item.get("upside_pct", 0)
        rec    = item.get("rec", "").replace("_", " ")
        hald   = item.get("hald", "")
        lines.append(f"\U0001f7e2 **{sym}** `{rec}` +{upside:.0f}% ⏱ {hald}")
    return "\n".join(lines) or "Ingen signal"

def fmt_momentum(items):
    lines = []
    for m in items:
        sym = m.get("symbol", "?")
        pct = m.get("day_pct", 0)
        arr = "\U0001f680" if pct > 0 else "\U0001f4c9"
        lines.append(f"{arr} **{sym}** {pct:+.1f}%")
    return "\n".join(lines) or "Ingen"

def fmt_unngaa(items):
    lines = []
    for u in items:
        sym   = u.get("symbol", "?")
        grunn = u.get("grunn", "")
        lines.append(f"⚠️ **{sym}** — {grunn}")
    return "\n".join(lines) or "Ingen"

mom_total = len(s.get("momentum", []))
fields = [
    {"name": "Marknad",             "value": f"{icon} **{sentiment}**",         "inline": True},
    {"name": f"{fg_icon} Fear & Greed", "value": f"**{fg_score:.0f}** / 100",  "inline": True},
    {"name": "\U0001f4ca VIX",      "value": f"**{vix:.1f}**",                  "inline": True},
    {"name": f"\U0001f4c1 Portefølje ({len(portfolio)})", "value": fmt_portfolio(portfolio)[:1000], "inline": False},
    {"name": f"\U0001f6d2 Kjøpskandidatar ({len(kjoep)})", "value": fmt_kjoep(kjoep)[:1000],       "inline": False},
    {"name": f"\U0001f680 Momentum ({mom_total})",  "value": fmt_momentum(momentum)[:1000],             "inline": False},
    {"name": f"\U0001f6ab Unngå ({len(unngaa)})", "value": fmt_unngaa(unngaa)[:500],               "inline": False},
]

embed = {
    "title":  tittel,
    "color":  color,
    "fields": fields,
    "footer": {"text": "Bullbot  •  " + date.today().strftime("%A %d. %B %Y")},
}

resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=10)
print(f"HTTP {resp.status_code}")
if resp.status_code not in (200, 204):
    print(resp.text[:400])
