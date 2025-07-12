"""Utility for quickly extracting pages that likely contain metrics/result tables.

The goal is to *avoid* sending a full 100-page PDF to the LLM. We use cheap
heuristics (keywords + regex + optional table detection via pdfplumber) to rank
pages and then return the top-K pages' text concatenated.

If `pdfplumber` or `PyMuPDF` are not installed, we gracefully degrade to a
pure-PyPDF2 approach.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

import PyPDF2

logger = logging.getLogger(__name__)

# Default keywords that often appear near metric tables or result sections
DEFAULT_KEYWORDS = [
    "bleu", "rouge", "accuracy", "f1", "perplexity", "results", "table", "evaluation",
]

# Simple regex to spot number + optional percent sign, e.g. "93.4%" or "12.3"
_VALUE_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")


def _extract_page_texts(pdf_path: Path) -> List[str]:
    """Return a list of text strings, one per page."""
    reader = PyPDF2.PdfReader(str(pdf_path))
    texts: List[str] = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to extract text for a page: %s", exc)
            texts.append("")
    return texts


def _detect_tables_with_pdfplumber(pdf_path: Path) -> List[bool]:
    """Return a list[bool] indicating whether each page contains a table (best-effort)."""
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        logger.debug("pdfplumber not installed; skipping table detection.")
        return []

    table_flags: List[bool] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                table_flags.append(bool(page.find_tables()))
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("pdfplumber table detection failed: %s", exc)
        # Fallback: assume no tables
        table_flags = []
    return table_flags


def filter_metric_pages(
    pdf_path: Path,
    *,
    keywords: List[str] | None = None,
    max_pages: int = 8,
) -> str:
    """Return concatenated text of the *max_pages* pages most likely to contain metrics.

    Scoring heuristics:
    1. keyword frequency (case-insensitive)
    2. number of numeric values with optional % (\d+(?:\.\d+)?%?)
    3. +10 bonus if pdfplumber says the page has a table
    """
    if keywords is None:
        keywords = DEFAULT_KEYWORDS
    keywords_lower = [k.lower() for k in keywords]

    page_texts = _extract_page_texts(pdf_path)
    n_pages = len(page_texts)

    # Optional table detection
    table_flags = _detect_tables_with_pdfplumber(pdf_path)

    scores: List[float] = []
    for i, text in enumerate(page_texts):
        text_lower = text.lower()
        score = 0.0
        # keyword hits
        for kw in keywords_lower:
            score += text_lower.count(kw)
        # value hits
        score += len(_VALUE_RE.findall(text)) * 0.5
        # table bonus
        if i < len(table_flags) and table_flags[i]:
            score += 10
        scores.append(score)

    # Pick top-k indices
    top_indices = sorted(range(n_pages), key=lambda idx: scores[idx], reverse=True)[:max_pages]
    top_indices = sorted(top_indices)  # keep original order

    logger.info(
        "PDF filtering: selected pages %s (scores: %s)",
        top_indices,
        [scores[i] for i in top_indices],
    )

    filtered_text = "\n".join(page_texts[i] for i in top_indices)
    return filtered_text 