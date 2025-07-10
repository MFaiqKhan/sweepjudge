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

    if overlap >= max_tokens:
        raise ValueError("overlap must be smaller than max_tokens to guarantee progress")

    tokens = ENC.encode(text)
    n_tokens = len(tokens)
    chunks: List[str] = []
    start = 0

    while start < n_tokens:
        end = min(start + max_tokens, n_tokens)
        chunk_tokens = tokens[start:end]
        chunks.append(ENC.decode(chunk_tokens))

        if end == n_tokens:
            # Reached the end; exit to avoid infinite loop when remaining tokens < overlap
            break

        # Advance the window keeping the desired overlap
        start = end - overlap

    return chunks 