"""Tiny helper to split large text into token-constrained chunks.

Avoids pulling in LangChain; relies on tiktoken for GPT-4 encoder.
"""

from __future__ import annotations

from typing import Iterator, List

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(ENC.encode(text))


def chunk_text(text: str, max_tokens: int = 3000, overlap: int = 200) -> List[str]:
    """Yield chunks of *text* where each chunk has <= max_tokens.

    Uses sliding window with *overlap* tokens for context retention.
    """

    tokens = ENC.encode(text)
    chunks: List[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(ENC.decode(chunk_tokens))
        start = end - overlap  # slide window with overlap
        if start < 0:
            start = 0
    return chunks 