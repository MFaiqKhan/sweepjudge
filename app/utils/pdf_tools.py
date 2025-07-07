"""Utility helpers for downloading/storing PDFs."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

import aiohttp

DEFAULT_DIR = Path("data/corpus")
DEFAULT_DIR.mkdir(parents=True, exist_ok=True)


async def fetch_pdf(url: str, dest_dir: Path = DEFAULT_DIR) -> Path:
    """Download *url* into *dest_dir* if not already cached.

    File name is SHA256(url).pdf to avoid collisions.
    Returns absolute Path to the file.
    """

    name = hashlib.sha256(url.encode()).hexdigest()[:24] + ".pdf"
    dest = dest_dir / name
    if dest.exists():
        return dest

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.read()
            dest.write_bytes(data)
    return dest 