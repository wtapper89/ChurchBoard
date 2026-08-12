from __future__ import annotations

import csv
import html
import io
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SPLReportStore:
    """Append-only, local SPL samples and Planning Center item summaries."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        measurement: dict[str, Any],
        service: dict[str, Any],
        item: dict[str, Any] | None,
        metric_key: str = "a_fast",
        metric_label: str = "A-weighted Fast",
    ) -> None:
        value = measurement.get(metric_key, measurement.get("laeq"))
        if not isinstance(value, (int, float)):
            return
        event = {
            "timestamp": measurement.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "service_id": str(service.get("id") or "unassigned"),
            "service_title": str(service.get("title") or service.get("service_type_name") or "Unassigned service"),
            "item_id": str((item or {}).get("id") or "unassigned"),
            "item_title": str((item or {}).get("title") or "Unassigned"),
            "value": float(value),
            "metric_key": metric_key,
            "metric_label": metric_label,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")

    def events(self, service_id: str) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        result = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(event.get("service_id")) == str(service_id):
                result.append(event)
        return result

    def services(self) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            grouped[str(event.get("service_id"))] = {"id": str(event.get("service_id")), "title": event.get("service_title"), "last_sample_at": event.get("timestamp")}
        return sorted(grouped.values(), key=lambda entry: str(entry["last_sample_at"]), reverse=True)

    def csv(self, service_id: str) -> str:
        rows = self.events(service_id)
        groups: dict[tuple[str, str], list[float]] = defaultdict(list)
        for row in rows:
            groups[(row["item_id"], row["item_title"])].append(float(row.get("value", row.get("laeq"))))
        output = io.StringIO()
        writer = csv.writer(output)
        label = str(rows[0].get("metric_label") or "A-weighted Fast") if rows else "A-weighted Fast"
        writer.writerow(["Planning Center item", "Samples", f"Average {label} (dB)", f"Minimum {label} (dB)", f"Maximum {label} (dB)"])
        for (_, title), values in groups.items():
            writer.writerow([title, len(values), f"{sum(values) / len(values):.1f}", f"{min(values):.1f}", f"{max(values):.1f}"])
        return output.getvalue()

    def graph_html(self, service_id: str) -> str:
        rows = self.events(service_id)
        points = json.dumps([[row["timestamp"], row.get("value", row.get("laeq")), row["item_title"]] for row in rows])
        title = html.escape(rows[0]["service_title"] if rows else "ChurchBoard SPL report")
        label = html.escape(str(rows[0].get("metric_label") or "A-weighted Fast") if rows else "A-weighted Fast")
        return f'''<!doctype html><meta charset="utf-8"><title>{title} · SPL report</title><style>body{{font:16px system-ui;margin:2rem;background:#0a0d12;color:#f5f7fb}}svg{{width:100%;height:420px;background:#121721;border-radius:12px}}.muted{{color:#93a0b5}}</style><h1>{title}</h1><p class="muted">{label} samples correlated to the active Planning Center LIVE item.</p><svg viewBox="0 0 1000 420" aria-label="SPL graph"></svg><script>const p={points},s=document.querySelector('svg');if(!p.length)s.outerHTML='<p>No samples were recorded.</p>';else{{const v=p.map(x=>x[1]),lo=Math.floor(Math.min(...v)-3),hi=Math.ceil(Math.max(...v)+3),path=p.map((x,i)=>`${{i?'L':'M'}}${{i/(p.length-1||1)*940+30}},${{390-(x[1]-lo)/(hi-lo||1)*340}}`).join('');s.innerHTML=`<path d="${{path}}" fill="none" stroke="#55e6a5" stroke-width="3"/><text x="30" y="25" fill="#93a0b5">${{hi}} dB</text><text x="30" y="410" fill="#93a0b5">${{lo}} dB</text>`}}</script>'''
