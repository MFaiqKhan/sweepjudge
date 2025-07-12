"""Utility to heuristically extract PEFT metrics from text.

Looks for table-like lines and common keywords such as BLEU, ROUGE, perplexity,
accuracy, etc. Produces list of (metric_name, value, dataset).
"""

from __future__ import annotations

import re
from typing import List, Tuple

# A list of (name, regex_pattern) tuples for easy extension and configuration.
# Each pattern should have 'value' and optional 'dataset' capture groups.
METRIC_PATTERNS = [
    ("Accuracy", re.compile(r"accuracy of (?P<value>\d+\.\d+)%", re.IGNORECASE)),
    ("BLEU", re.compile(r"BLEU score of (?P<value>\d+\.\d+)", re.IGNORECASE)),
    ("ROUGE-L", re.compile(r"ROUGE-L\s*:\s*(?P<value>\d+\.\d+)", re.IGNORECASE)),
    # A more generic pattern to catch table-like formats
    ("Generic", re.compile(
        r"(?P<metric>BLEU(?:-[1-4])?|ROUGE(?:-[LF])?(?:-[1-2])?|METEOR|perplexity|accuracy|precision|recall|F1(?:-score)?|F-?score|loss|WER|CER|MAPE|MAE|MSE|RMSE)"
        r"[\s:=-]*"
        r"(?P<value>\d+(?:\.\d+)?%?)"
        r"(?:\s*(?:on|for|in|using|with)\s*(?P<dataset>[A-Za-z0-9_\-\.]+))?",
        re.IGNORECASE
    )),
]


def extract_metrics(
    text: str, patterns: List[Tuple[str, re.Pattern]] = METRIC_PATTERNS
) -> List[Tuple[str, float, str | None]]:
    """Extract metrics from text using a provided list of regex patterns."""
    results: List[Tuple[str, float, str | None]] = []
    
    for metric_name, pattern in patterns:
        for match in pattern.finditer(text):
            try:
                # Use the provided metric name, but allow override if pattern captures it
                captured_metric = match.groupdict().get("metric", metric_name).lower()
                
                value_str = match.group("value").replace("%", "")
                value = float(value_str)
                
                dataset = match.groupdict().get("dataset")
                
                results.append((captured_metric, value, dataset))
            except (ValueError, IndexError):
                # This can happen if a pattern has a bad 'value' group
                continue

    # Simple deduplication
    return list(set(results)) 