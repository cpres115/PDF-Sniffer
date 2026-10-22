# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""Locations of bundled resources (everything lives inside the program folder)."""
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = APP_ROOT / "vendor"
DEFAULT_OUTPUT_DIR = APP_ROOT / "output"


def tessdata_dir():
    """Folder holding eng.traineddata, or None when OCR data cannot be found."""
    candidates = []
    if os.environ.get("PDF_SNIFFER_TESSDATA"):
        candidates.append(Path(os.environ["PDF_SNIFFER_TESSDATA"]))
    candidates.append(VENDOR_DIR / "tessdata")
    for c in candidates:
        if (c / "eng.traineddata").is_file():
            return str(c)
    try:  # last resort: a system-wide Tesseract install
        import pymupdf
        td = pymupdf.get_tessdata()
        if td and (Path(td) / "eng.traineddata").is_file():
            return str(td)
    except Exception:
        pass
    return None
