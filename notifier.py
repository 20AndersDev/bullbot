"""
Discord-varsel for bullbot.
- DISCORD_WEBHOOK:       oppsummering (dagsrapport, vekesrapport, morgonrapport)
- DISCORD_TRADE_WEBHOOK: kvart enkelt kjøp og sal
"""
import requests
from datetime import datetime, timezone
import config

_SUMMARY_URL = config.DISCORD_WEBHOOK
_TRADE_URL   = config.DISCORD_TRADE_WEBHOOK
_GREEN = 0x2ECC71
_RED   = 0xE74C3C
_GOLD  = 0xF1C40F

_NAMES: dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "AMZN": "Amazon",
    "META": "Meta",
    "GOOGL": "Alphabet",
    "TSLA": "Tesla",
    "AMD": "AMD",
    "NFLX": "Netflix",
    "JPM": "JPMorgan Chase",
    "V": "Visa",
    "CRWD": "CrowdStrike",
    "PLTR": "Palantir",
    "COIN": "Coinbase",
    "UBER": "Uber",
    "SOFI": "SoFi",
    "AFRM": "Affirm",
    "HOOD": "Robinhood",
    "RBLX": "Roblox",
    "DASH": "DoorDash",
    "RIVN": "Rivian",
    "MSTR": "MicroStrategy",
    "NET": "Cloudflare",
    "SNOW": "Snowflake",
}


def _company_name(symbol: str) -> str:
    if symbol in _NAMES:
        return _NAMES[symbol]
    try:
        import yfinance as yf
        name = yf.Ticker(symbol).info.get("shortName") or yf.Ticker(symbol).info.get("longName")
        if name:
            _NAMES[symbol] = name
            return name
    except Exception:
        pass
    return symbol


def _post(url: str, payload: dict) -> None:
    if not url:
        return
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Discord-varsel feila: {e}")


def send(content: str = "", embeds: list = None) -> None:
    """Send til oppsummerings-kanalen."""
    payload: dict = {}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds
    _post(_SUMMARY_URL, payload)


def send_trade(embeds: list) -> None:
    """Send til handels-kanalen."""
    _post(_TRADE_URL, {"embeds": embeds})


def buy_embed(symbol: str, qty: int, price: float, sl: float, tp: float,
              invest_pct: float, equity: float, reason: str) -> dict:
    invest_kr = qty * price
    ts   = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    name = _company_name(symbol)
    return {
        "title": f"🟢  KJØP  {symbol} — {name}",
        "color": _GREEN,
        "fields": [
            {"name": "Aksje",         "value": symbol,                          "inline": True},
            {"name": "Antal",         "value": f"{qty} aksjar",                 "inline": True},
            {"name": "Pris",          "value": f"${price:.2f}",                 "inline": True},
            {"name": "Investert",     "value": f"${invest_kr:,.2f}  ({invest_pct:.1f}%)",  "inline": True},
            {"name": "Stop loss",     "value": f"${sl:.2f}  (−2%)",             "inline": True},
            {"name": "Take profit",   "value": f"${tp:.2f}  (+4%)",             "inline": True},
            {"name": "Grunngjeving",  "value": reason,                          "inline": False},
            {"name": "Porteføljeverdi", "value": f"${equity:,.2f}",            "inline": True},
            {"name": "Tidspunkt",     "value": ts,                              "inline": True},
        ],
    }


def sell_embed(symbol: str, qty: int, entry_price: float, exit_price: float,
               pl_dollar: float, pl_pct: float, reason: str) -> dict:
    ts   = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    won  = pl_dollar >= 0
    name = _company_name(symbol)
    pl_display = f"{'🟢' if won else '🔴'}  ${pl_dollar:+,.2f}  ({pl_pct:+.2f}%)"
    return {
        "title": f"🔴  SAL  {symbol} — {name}",
        "color": _RED,
        "fields": [
            {"name": "Aksje",      "value": symbol,                "inline": True},
            {"name": "Antal",      "value": f"{qty} aksjar",       "inline": True},
            {"name": "Salpris",    "value": f"${exit_price:.2f}",  "inline": True},
            {"name": "Kjøpspris",  "value": f"${entry_price:.2f}", "inline": True},
            {"name": "P&L",        "value": pl_display,            "inline": True},
            {"name": "Resultat",   "value": "✅ Gevinst" if won else "❌ Tap", "inline": True},
            {"name": "Grunngjeving", "value": reason,               "inline": False},
            {"name": "Tidspunkt",  "value": ts,                    "inline": True},
        ],
    }
