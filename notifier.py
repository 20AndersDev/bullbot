"""
Discord-varsel for bullbot.
Bruk: send(content="tekst") eller send(embeds=[...])
"""
import requests
import config

_WEBHOOK = config.DISCORD_WEBHOOK
_GREEN = 0x2ECC71
_RED   = 0xE74C3C
_BLUE  = 0x3498DB
_GOLD  = 0xF1C40F


def send(content: str = "", embeds: list = None) -> None:
    if not _WEBHOOK:
        return
    payload: dict = {}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds
    try:
        requests.post(_WEBHOOK, json=payload, timeout=10)
    except Exception as e:
        print(f"Discord-varsel feila: {e}")


def trade_embed(action: str, symbol: str, qty: int, price: float,
                sl: float, tp: float, invest_pct: float, reason: str) -> dict:
    is_buy = action.upper() == "KJOEP"
    return {
        "title": f"{'🟢 KJØP' if is_buy else '🔴 SAL'} {symbol}",
        "color": _GREEN if is_buy else _RED,
        "fields": [
            {"name": "Antal",     "value": str(qty),              "inline": True},
            {"name": "Pris",      "value": f"${price:.2f}",        "inline": True},
            {"name": "Storleik",  "value": f"{invest_pct:.1f}% av portefølje", "inline": True},
            {"name": "Stop loss", "value": f"${sl:.2f}",           "inline": True},
            {"name": "Take profit","value": f"${tp:.2f}",          "inline": True},
            {"name": "Signal",    "value": reason,                 "inline": False},
        ],
    }


def sell_embed(symbol: str, pl_pct: float, reason: str) -> dict:
    return {
        "title": f"{'🟢' if pl_pct >= 0 else '🔴'} SAL {symbol}  ({pl_pct:+.2f}%)",
        "color": _GREEN if pl_pct >= 0 else _RED,
        "fields": [
            {"name": "P&L",    "value": f"{pl_pct:+.2f}%", "inline": True},
            {"name": "Grunn",  "value": reason,              "inline": False},
        ],
    }
