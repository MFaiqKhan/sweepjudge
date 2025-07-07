"""Helpers to build Markdown comparison tables from metric lists."""

from __future__ import annotations

from collections import defaultdict
from typing import List, Dict, Any


def metrics_to_markdown(metrics_lists: List[List[Dict[str, Any]]]) -> str:
    """Combine metrics from many papers into a markdown table.

    Each element in *metrics_lists* is the metrics_json produced by Metrician
    for one paper.
    """

    rows = []
    for idx, metrics in enumerate(metrics_lists, 1):
        for m in metrics:
            rows.append(
                {
                    "Paper": f"P{idx}",
                    "Metric": m["metric"],
                    "Value": m["value"],
                    "Dataset": m.get("dataset") or "-",
                }
            )

    if not rows:
        return "No comparable metrics found."

    # build markdown
    header = "| Paper | Metric | Value | Dataset |\n|---|---|---|---|"
    lines = [header]
    for r in rows:
        lines.append(f"| {r['Paper']} | {r['Metric']} | {r['Value']} | {r['Dataset']} |")
    return "\n".join(lines) 