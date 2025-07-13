"""PDF utility functions for downloading, storing, and extracting content from PDFs."""

from __future__ import annotations

import hashlib
import io
import logging
import os
from pathlib import Path
from typing import List, Optional

import aiohttp
import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)

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


def extract_images_from_pdf(pdf_path: str, min_width: int = 100, min_height: int = 100) -> List[bytes]:
    """Extract images from a PDF file.
    
    Args:
        pdf_path: Path to the PDF file
        min_width: Minimum width of images to extract (to filter out tiny icons)
        min_height: Minimum height of images to extract
        
    Returns:
        List of image data as bytes
    """
    try:
        # Open the PDF
        doc = fitz.open(pdf_path)
        images = []
        
        # Iterate through each page
        for page_num in range(len(doc)):
            try:
                page = doc.load_page(page_num)
                image_list = page.get_images(full=True)
                
                # Process each image on the page
                for img_index, img_info in enumerate(image_list):
                    try:
                        xref = img_info[0]  # Get the image reference
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        
                        # Check image dimensions to filter out small icons
                        try:
                            img = Image.open(io.BytesIO(image_bytes))
                            width, height = img.size
                            
                            # Skip small images
                            if width < min_width or height < min_height:
                                continue
                                
                            # Convert to PNG for consistency
                            img_bytes = io.BytesIO()
                            img.save(img_bytes, format="PNG")
                            images.append(img_bytes.getvalue())
                            
                        except Exception as img_exc:
                            logger.warning(f"Failed to process image on page {page_num+1}: {img_exc}")
                            continue
                            
                    except Exception as xref_exc:
                        logger.warning(f"Failed to extract image {img_index} on page {page_num+1}: {xref_exc}")
                        continue
                        
            except Exception as page_exc:
                logger.warning(f"Failed to process page {page_num+1}: {page_exc}")
                continue
                
        logger.info(f"Extracted {len(images)} images from PDF")
        return images
        
    except ImportError:
        logger.warning("PyMuPDF (fitz) not available, falling back to PyPDF2")
        return _extract_images_with_pypdf2(pdf_path)
        
    except Exception as exc:
        logger.exception(f"Failed to extract images from PDF: {exc}")
        return []


def _extract_images_with_pypdf2(pdf_path: str) -> List[bytes]:
    """Fallback method to extract images using PyPDF2.
    
    This is less reliable than PyMuPDF but provided as a fallback.
    """
    try:
        import PyPDF2
        from PyPDF2.filters import _xobj_to_image
        
        images = []
        with open(pdf_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            
            for page_num, page in enumerate(reader.pages):
                try:
                    if "/Resources" in page and "/XObject" in page["/Resources"]:
                        xobjects = page["/Resources"]["/XObject"]
                        
                        for obj_name, obj in xobjects.items():
                            if "/Subtype" in obj and obj["/Subtype"] == "/Image":
                                try:
                                    img_data = _xobj_to_image(obj)
                                    if img_data:
                                        images.append(img_data)
                                except Exception as img_exc:
                                    logger.warning(f"Failed to extract image on page {page_num+1}: {img_exc}")
                except Exception as page_exc:
                    logger.warning(f"Failed to process page {page_num+1}: {page_exc}")
                    
        logger.info(f"Extracted {len(images)} images from PDF using PyPDF2")
        return images
        
    except Exception as exc:
        logger.exception(f"Failed to extract images with PyPDF2: {exc}")
        return [] 