"""Utility to heuristically extract PEFT metrics from text.

Looks for table-like lines and common keywords such as BLEU, ROUGE, perplexity,
accuracy, etc. Produces list of (metric_name, value, dataset).
"""

from __future__ import annotations

import re
from typing import List, Tuple

METRIC_RE = re.compile(
    r"(?P<metric>BLEU|ROUGE|perplexity|accuracy|F1|F-?score|loss)"  # metric
    r"[\s:]*"  # separator
    r"(?P<value>\d+\.\d+|\d+)%?"  # value
    r"(?:\s*on\s*(?P<dataset>[A-Za-z0-9_\-]+))?",  # optional dataset
    flags=re.IGNORECASE,
)


def extract_metrics(text: str) -> List[Tuple[str, float, str | None]]:
    results: List[Tuple[str, float, str | None]] = []
    for match in METRIC_RE.finditer(text):
        metric = match.group("metric").lower()
        value = float(match.group("value"))
        dataset = match.group("dataset")
        results.append((metric, value, dataset))
    return results 