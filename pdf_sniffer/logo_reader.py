# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""Decide whether a red ring contains the word ITAR or EAR.

Three independent signals are combined:
  1. the PDF text layer (exact, when the logo text is real text),
  2. OCR of the isolated red ink (when the logo is a picture),
  3. glyph shape: how many letters, and whether the first one is a narrow 'I'.
"""
import re
from dataclasses import dataclass

import numpy as np
import pymupdf

from . import imaging, ocr

_ITAR = re.compile(r"^[I1L|!]TAR$")
_EAR = re.compile(r"^[E3]AR$")


def pixmap_to_array(pix):
    buf = np.frombuffer(pix.samples, dtype=np.uint8)
    return buf.reshape(pix.height, pix.stride)[:, :pix.width * pix.n].reshape(
        pix.height, pix.width, pix.n)


def match_label(text):
    """'ITAR' / 'EAR' / None for a piece of text read from (or around) the logo."""
    cleaned = [re.sub(r"[^A-Z0-9|!]", "", t.upper()) for t in text.split()]
    for cand in cleaned + ["".join(cleaned)]:
        if _ITAR.match(cand):
            return "ITAR"
        if _EAR.match(cand):
            return "EAR"
    return None


def _edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def near_label(text):
    """Label whose spelling is within one edit of the OCR text (e.g. 'FAR', 'ITA'), else None."""
    cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
    if len(cleaned) < 2:
        return None
    best = [(_edit_distance(cleaned, w), w) for w in ("ITAR", "EAR")]
    dist, word = min(best)
    return word if dist <= 1 else None


@dataclass
class Reading:
    cx: float                 # displayed-page coordinates (points)
    cy: float
    r: float
    label: str = ""           # '' = could not be read
    method: str = ""
    confidence: str = ""      # high | medium | low
    glyphs: int = 0
    texty: bool = False       # ink inside the ring looks like a word, not a digit or blank
    detail: str = ""

    @property
    def is_hit(self):
        return bool(self.label) and self.confidence in ("high", "medium")

    @property
    def is_suspect(self):
        """A ring with word-like text that could not be confirmed as ITAR or EAR."""
        return not self.is_hit and self.texty


def shape_vote(glyphs):
    """('ITAR'|'EAR', 'high'|'low') from letter count and first-letter width, or None."""
    n = len(glyphs)
    if n < 2 or n > 6:
        return None
    first = glyphs[0]
    narrow = (first.w / max(first.h, 1)) < 0.65     # 'I' is a thin stem; 'E' is wide
    itar = (2 if narrow else 0) + (1 if n == 4 else 0)
    ear = (0 if narrow else 2) + (1 if n == 3 else 0)
    if itar == ear:
        return None
    label = "ITAR" if itar > ear else "EAR"
    return label, ("high" if max(itar, ear) == 3 else "low")


def _text_in_circle(page, cx, cy, r):
    raw = pymupdf.Rect(cx - r, cy - r, cx + r, cy + r) * page.derotation_matrix
    found = []
    for x0, y0, x1, y1, word, *_ in page.get_text("words", clip=raw):
        rect = pymupdf.Rect(x0, y0, x1, y1) * page.rotation_matrix
        mx, my = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        if np.hypot(mx - cx, my - cy) <= r * 1.05:
            found.append((rect.x0, word))
    return " ".join(w for _, w in sorted(found))


def read_ring(page, cx, cy, r, use_ocr=True, hires_px=240):
    """Analyse one candidate ring (displayed-page coordinates, points).

    Returns a Reading, or None if the ring does not survive a high-resolution re-check.
    """
    margin = 1.15
    clip = pymupdf.Rect(cx - r * margin, cy - r * margin, cx + r * margin, cy + r * margin) & page.rect
    zoom = float(np.clip(hires_px / (2 * r), 2.0, 8.5))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip,
                          colorspace=pymupdf.csRGB, alpha=False)
    mask = imaging.red_mask(pixmap_to_array(pix))
    d_px = 2 * r * zoom
    rings = imaging.find_rings(mask, d_px * 0.7, d_px * 1.4, 0.80)
    if not rings:
        return None
    ex, ey = cx * zoom - pix.x, cy * zoom - pix.y
    ring = min(rings, key=lambda g: np.hypot(g.cx - ex, g.cy - ey))
    if np.hypot(ring.cx - ex, ring.cy - ey) > 0.3 * ring.r_out:
        return None

    # displayed-page geometry of the refined ring
    rd = Reading((ring.cx + pix.x) / zoom, (ring.cy + pix.y) / zoom, ring.r_out / zoom)

    h, w = mask.shape
    yy, xx = np.ogrid[:h, :w]
    rr = ring.r_in * 0.97
    ink = mask & (((xx - ring.cx) ** 2 + (yy - ring.cy) ** 2) <= rr * rr)
    min_area = max(10, 0.0015 * np.pi * rr * rr)
    glyphs = sorted((c for c in imaging.label_components(ink)
                     if c.area >= min_area and c.h >= 0.10 * rr), key=lambda c: c.x0)
    rd.glyphs = len(glyphs)
    if glyphs:
        gx0, gx1 = min(g.x0 for g in glyphs), max(g.x1 for g in glyphs)
        gy0, gy1 = min(g.y0 for g in glyphs), max(g.y1 for g in glyphs)
        # three or more letters, or one wide blob (letters fused together by a fat font / low res)
        rd.texty = len(glyphs) >= 3 or (gx1 - gx0) >= 1.6 * (gy1 - gy0)

    text_label = match_label(_text_in_circle(page, rd.cx, rd.cy, rd.r))
    shape = shape_vote(glyphs)

    ocr_text, ocr_label = "", None
    if text_label is None and use_ocr and rd.texty and ocr.available():
        pad = max(12, int(0.35 * (gy1 - gy0)))
        crop = ink[max(0, gy0 - pad):gy1 + pad, max(0, gx0 - pad):gx1 + pad]
        gray = np.pad(np.where(crop, 0, 255).astype(np.uint8), 30, constant_values=255)
        ocr_text = " ".join(ocr.read(ocr.gray_pixmap(gray)).split())
        ocr_label = match_label(ocr_text)
    near = near_label(ocr_text) if ocr_text and not ocr_label else None

    # Only the text layer or OCR can confirm a logo.  Letter shape alone is never trusted
    # (it cannot tell 'EAR' from any other three-letter word); it only upgrades OCR's confidence.
    if text_label:
        rd.label, rd.method, rd.confidence = text_label, "text", "high"
    elif ocr_label:
        agree = shape is not None and shape[0] == ocr_label
        rd.label, rd.confidence = ocr_label, ("high" if agree else "medium")
        rd.method = "ocr+shape" if agree else "ocr"
        if shape is not None and not agree:
            rd.detail = f"OCR read {ocr_label} but letter shapes suggest {shape[0]}"
    elif near and shape and shape[0] == near:
        rd.label, rd.method, rd.confidence = near, "ocr~+shape", "medium"
        rd.detail = f"OCR read '{ocr_text}'"
    elif shape:
        rd.label, rd.method, rd.confidence = shape[0], "shape", "low"
    if rd.is_suspect and not rd.detail:
        rd.detail = (f"ring text read as '{ocr_text}'" if ocr_text
                     else "ring contains letters that could not be read")
    return rd
