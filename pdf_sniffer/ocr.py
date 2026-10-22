# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""Thin wrapper around PyMuPDF's built-in Tesseract OCR (English data is bundled)."""
import contextlib
import os

import numpy as np
import pymupdf

from . import paths

_state = {"checked": False, "dir": None, "error": ""}


def available():
    if not _state["checked"]:
        _state["checked"] = True
        _state["dir"] = paths.tessdata_dir()
        if _state["dir"] is None:
            _state["error"] = "eng.traineddata not found (expected in vendor/tessdata)"
    return _state["dir"] is not None


def error():
    return _state["error"]


@contextlib.contextmanager
def _quiet_stderr():
    """Tesseract prints harmless warnings straight to the C-level stderr; hide them."""
    try:
        saved = os.dup(2)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
    except OSError:
        yield
        return
    try:
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)


def read_words(pix):
    """OCR a Pixmap -> (text, words); each word is (x0, y0, x1, y1, text) in the pixmap's pixel coordinates.

    Returns ('', []) when nothing is recognised or OCR is unavailable.
    """
    if not available():
        return "", []
    try:
        with _quiet_stderr():
            data = pix.pdfocr_tobytes(language="eng", tessdata=_state["dir"])
        doc = pymupdf.open("pdf", data)
        try:
            page = doc[0]
            scale = pix.width / page.rect.width
            words = [(x0 * scale, y0 * scale, x1 * scale, y1 * scale, w)
                     for x0, y0, x1, y1, w, *_ in page.get_text("words")]
            return page.get_text(), words
        finally:
            doc.close()
    except Exception as exc:  # OCR must never abort a scan
        _state["dir"] = None
        _state["error"] = f"OCR failed: {exc}"
        return "", []


def read(pix):
    """OCR a Pixmap and return its text ('' when nothing is recognised or OCR is unavailable)."""
    return read_words(pix)[0]


def gray_pixmap(gray):
    """numpy uint8 (H, W) array -> PyMuPDF RGB Pixmap.

    (Tesseract through PyMuPDF returns nothing for grayscale pixmaps, so use RGB.)
    """
    h, w = gray.shape
    rgb = np.repeat(gray[..., None], 3, axis=2)
    pix = pymupdf.Pixmap(pymupdf.csRGB, w, h, rgb.tobytes(), False)
    pix.set_dpi(300, 300)
    return pix
