"""Bullbot morgonrapport — køyrast av morning-research-rutinen etter analyse."""
import os, sys, requests
from datetime import date

DISCORD = os.environ["DISCORD_WEBHOOK"]

# Argument: sentiment|vix|fg|topp1;topp2;topp3|blokkert1;blokkert2|oppdagingar1;oppdagingar2
# Eks: python scripts/morning_report.py "BULLISH|18.5|62|NVDA-sterk AI-momentum;COIN-crypto medvind|META-earnings 2d|HOOD-breakout"
if len(sys.argv) < 2:
    print("Bruk: python scripts/morning_report.py 'SENTIMENT|VIX|FG|TOPP1;TOPP2|BLOKKERT|OPPDAG'")
    sys.exit(1)

parts      = sys.argv[1].split("|")
sentiment  = parts[0] if len(parts) > 0 else "UKJEND"
vix_val    = float(parts[1]) if len(parts) > 1 else 0
fg_score   = float(parts[2]) if len(parts) > 2 else 0
topp_list  = parts[3].split(";") if len(parts) > 3 and parts[3] else []
blokk_list = parts[4].split(";") if len(parts) > 4 and parts[4] else []
oppdg_list = parts[5].split(";") if len(parts) > 5 and parts[5] else []

color = 0x2ECC71 if sentiment == "BULLISH" else (0xE74C3C if sentiment == "BEARISH" else 0xF1C40F)

embed = {
    "title": f"🌅 Bullbot Morgonrapport — {date.today().strftime('%d.%m.%Y')}",
    "color": color,
    "fields": [
        {"name": "📊 Marknad",
         "value": f"**{sentiment}**  |  VIX: {vix_val:.1f}  |  Fear&Greed: {fg_score:.0f}/100",
         "inline": False},
        {"name": "🎯 Topp moglegheiter i dag",
         "value": "\n".join(f"• {t}" for t in topp_list) or "Ingen",
         "inline": False},
        {"name": "🚫 Ikkje kjøp (earnings/risiko)",
         "value": "\n".join(f"• {b}" for b in blokk_list) or "Ingen",
         "inline": True},
        {"name": "🔍 Oppdagingar utanfor watchlist",
         "value": "\n".join(f"• {o}" for o in oppdg_list) or "Ingen",
         "inline": True},
    ],
}
resp = requests.post(DISCORD, json={"embeds": [embed]}, timeout=10)
print(f"Discord morgonrapport sendt: HTTP {resp.status_code}")
