"""
Les siste knowledge-rapport frå knowledge/-mappa.
Returnerer dict med sentiment, ikkje_kjoep, per_symbol osv.
"""
import json
from pathlib import Path
from datetime import date


def load() -> dict:
    knowledge_dir = Path(__file__).parent.parent / "knowledge"
    reports = sorted(knowledge_dir.glob("report_*.json"), reverse=True)
    if not reports:
        return {}
    with open(reports[0], encoding="utf-8") as f:
        data = json.load(f)
    print(f"Knowledge lasta frå {reports[0].name}")
    return data


def summary(knowledge: dict) -> str:
    if not knowledge:
        return "Ingen knowledge tilgjengeleg."
    lines = [f"Knowledge-dato: {knowledge.get('dato', 'ukjend')}"]
    fg = knowledge.get("fear_greed", {})
    if fg:
        lines.append(f"Fear&Greed: {fg.get('score', '?')}/100 ({fg.get('rating', '?')})")
    if knowledge.get("vix"):
        lines.append(f"VIX: {knowledge['vix']:.1f}")
    ikkje = knowledge.get("ikke_kjoep", [])
    if ikkje:
        lines.append(f"Ikkje kjøp (earnings/risiko): {', '.join(ikkje)}")
    return "\n".join(lines)
