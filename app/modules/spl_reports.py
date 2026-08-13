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
    """Append-only, local audio samples correlated to Planning Center items."""

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
        *,
        timing: dict[str, Any] | None = None,
        source: str = "Open Sound Meter",
        unit: str = "dB",
    ) -> None:
        metrics = measurement.get("metrics") if isinstance(measurement.get("metrics"), dict) else {}
        value = measurement.get(metric_key, metrics.get(metric_key, measurement.get("laeq")))
        if not isinstance(value, (int, float)):
            return
        plan_id = str(service.get("id") or "unassigned")
        service_time_id = str((timing or {}).get("service_time_id") or "")
        service_id = f"{plan_id}--{service_time_id}" if service_time_id else plan_id
        service_time_name = str((timing or {}).get("service_time_name") or "")
        service_title = str(service.get("title") or service.get("service_type_name") or "Unassigned service")
        if service_time_name:
            service_title = f"{service_title} · {service_time_name}"
        event = {
            "timestamp": measurement.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "service_id": service_id,
            "plan_id": plan_id,
            "service_time_id": service_time_id,
            "service_time_name": service_time_name,
            "service_title": service_title,
            "item_id": str((item or {}).get("id") or "unassigned"),
            "item_title": str((item or {}).get("title") or "Unassigned"),
            "value": float(value),
            "metric_key": metric_key,
            "metric_label": metric_label,
            "source": source,
            "unit": unit,
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
            grouped[str(event.get("service_id"))] = {
                "id": str(event.get("service_id")), "plan_id": str(event.get("plan_id") or event.get("service_id")),
                "service_time_id": str(event.get("service_time_id") or ""), "title": event.get("service_title"),
                "last_sample_at": event.get("timestamp"), "source": event.get("source") or "Open Sound Meter",
            }
        return sorted(grouped.values(), key=lambda entry: str(entry["last_sample_at"]), reverse=True)

    def report(self, service_id: str) -> dict[str, Any]:
        rows = self.events(service_id)
        grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[(str(row.get("item_id")), str(row.get("item_title")), str(row.get("source") or "Audio"), str(row.get("metric_label") or "Level"))].append(row)
        items = []
        for (item_id, title, source, metric_label), samples in grouped.items():
            values = [float(sample.get("value", 0)) for sample in samples]
            items.append({
                "id": item_id, "title": title, "source": source, "metric_label": metric_label,
                "unit": str(samples[0].get("unit") or "dB"), "samples": len(values),
                "average": round(sum(values) / len(values), 1), "minimum": round(min(values), 1), "maximum": round(max(values), 1),
                "points": [[sample.get("timestamp"), float(sample.get("value", 0))] for sample in samples],
            })
        return {
            "id": service_id, "title": rows[0].get("service_title") if rows else "Audio history",
            "last_sample_at": rows[-1].get("timestamp") if rows else None, "items": items,
        }

    def csv(self, service_id: str) -> str:
        rows = self.events(service_id)
        groups: dict[tuple[str, str, str, str, str], list[float]] = defaultdict(list)
        for row in rows:
            groups[(row["item_id"], row["item_title"], str(row.get("source") or "Open Sound Meter"), str(row.get("metric_label") or "Level"), str(row.get("unit") or "dB"))].append(float(row.get("value", row.get("laeq"))))
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Planning Center item", "Source", "Measurement", "Unit", "Samples", "Average", "Minimum", "Maximum"])
        for (_, title, source, metric_label, unit), values in groups.items():
            writer.writerow([title, source, metric_label, unit, len(values), f"{sum(values) / len(values):.1f}", f"{min(values):.1f}", f"{max(values):.1f}"])
        return output.getvalue()

    def graph_html(self, service_id: str) -> str:
        rows = self.events(service_id)
        points = json.dumps([[row["timestamp"], row.get("value", row.get("laeq")), row["item_title"]] for row in rows])
        title = html.escape(rows[0]["service_title"] if rows else "ChurchBoard SPL report")
        label = html.escape(str(rows[0].get("metric_label") or "A-weighted Fast") if rows else "A-weighted Fast")
        return f'''<!doctype html><meta charset="utf-8"><title>{title} · SPL report</title><style>body{{font:16px system-ui;margin:2rem;background:#0a0d12;color:#f5f7fb}}svg{{width:100%;height:420px;background:#121721;border-radius:12px}}.muted{{color:#93a0b5}}</style><h1>{title}</h1><p class="muted">{label} samples correlated to the active Planning Center LIVE item.</p><svg viewBox="0 0 1000 420" aria-label="SPL graph"></svg><script>const p={points},s=document.querySelector('svg');if(!p.length)s.outerHTML='<p>No samples were recorded.</p>';else{{const v=p.map(x=>x[1]),lo=Math.floor(Math.min(...v)-3),hi=Math.ceil(Math.max(...v)+3),path=p.map((x,i)=>`${{i?'L':'M'}}${{i/(p.length-1||1)*940+30}},${{390-(x[1]-lo)/(hi-lo||1)*340}}`).join('');s.innerHTML=`<path d="${{path}}" fill="none" stroke="#55e6a5" stroke-width="3"/><text x="30" y="25" fill="#93a0b5">${{hi}} dB</text><text x="30" y="410" fill="#93a0b5">${{lo}} dB</text>`}}</script>'''
