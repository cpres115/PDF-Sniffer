"""Scan one PDF: find red-circle logos in the search zone of every page and read them."""
import hashlib
import os
import re
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pymupdf

from . import eccn, imaging, logo_reader, ocr
from .classify import category_for
from .config import ScanConfig
from .models import FileResult, LogoHit, STATUS_ERROR, STATUS_OK, STATUS_REVIEW, UNREADABLE

pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

_FOOTER_MENTION = re.compile(r"\b(?:ITAR|EAR|ECCN)\b")
_BIG_FILE = 400 * 1024 * 1024


def _long_path(path):
    """Windows needs the \\\\?\\ prefix for paths over 260 characters."""
    if os.name == "nt" and not path.startswith("\\\\?\\"):
        path = os.path.abspath(path)
        return ("\\\\?\\UNC" + path[1:]) if path.startswith("\\\\") else "\\\\?\\" + path
    return path


def _open(path):
    lp = _long_path(path)
    if os.path.getsize(lp) <= _BIG_FILE:
        with open(lp, "rb") as fh:
            return pymupdf.open(stream=fh.read(), filetype="pdf")
    return pymupdf.open(lp)


def _clip_for_zone(page, cfg):
    rect = page.rect
    x0, y0, x1, y1 = (0.0, 0.0, 1.0, 1.0) if cfg.full_page else cfg.zone
    return pymupdf.Rect(rect.x0 + x0 * rect.width, rect.y0 + y0 * rect.height,
                        rect.x0 + x1 * rect.width, rect.y0 + y1 * rect.height)


def _scan_dpi(clip, cfg):
    area_in2 = (clip.width / 72.0) * (clip.height / 72.0)
    return max(40.0, min(float(cfg.max_scan_dpi), (cfg.pixel_budget / max(area_in2, 1e-6)) ** 0.5))


def find_candidate_rings(page, cfg):
    """First pass: low-resolution render of the search zone -> list of (cx, cy, r) in points."""
    clip = _clip_for_zone(page, cfg)
    dpi = _scan_dpi(clip, cfg)
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip,
                          colorspace=pymupdf.csRGB, alpha=False)
    mask = imaging.red_mask(logo_reader.pixmap_to_array(pix))
    if mask.sum() < 20:
        return []
    if mask.mean() > 0.40:
        raise imaging.TooMuchInk("search zone is mostly red")
    rings = imaging.find_rings(mask, cfg.min_logo_in * dpi, cfg.max_logo_in * dpi)
    return [((g.cx + pix.x) / zoom, (g.cy + pix.y) / zoom, g.r_out / zoom) for g in rings]


def _window_rect(page, cx, cy, r, cfg):
    left, right, up, down = cfg.eccn_window
    d = 2 * r
    return pymupdf.Rect(cx - left * d, cy - up * d, cx + right * d, cy + down * d) & page.rect


def _page_text(page, rect):
    """Text-layer text inside a displayed-page rectangle."""
    return page.get_text("text", clip=rect * page.derotation_matrix)


def find_eccn(page, cx, cy, r, cfg):
    """Look for an ECCN beside the logo: text layer first, then OCR.  -> (EccnMatch, source) or (None, '')."""
    win = _window_rect(page, cx, cy, r, cfg)
    found = eccn.extract(_page_text(page, win))
    if found:
        return found[0], "text"
    if cfg.use_ocr and ocr.available():
        zoom = float(np.clip(300 / 72.0, 1.0, 3000.0 / max(win.width, 1.0)))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=win,
                              colorspace=pymupdf.csRGB, alpha=False)
        # Blank out the logo itself so Tesseract only sees the text around it.
        # (Pixmap.set_rect works in absolute zoomed coordinates, not pixmap-local ones.)
        pad = 1.1
        box = pymupdf.IRect(int((cx - r * pad) * zoom), int((cy - r * pad) * zoom),
                            int((cx + r * pad) * zoom) + 1, int((cy + r * pad) * zoom) + 1)
        pix.set_rect(box & pix.irect, (255, 255, 255))
        found = eccn.extract_ocr(ocr.read(pix))
        if found:
            return found[0], "ocr"
    # fall back to an explicitly labelled ECCN anywhere in the search zone
    for m in eccn.extract(_page_text(page, _clip_for_zone(page, cfg))):
        if m.labeled:
            return m, "page-text"
    return None, ""


def _save_evidence(page, cx, cy, r, cfg, path, page_no):
    if not cfg.evidence_dir:
        return ""
    try:
        win = _window_rect(page, cx, cy, r, cfg)
        zoom = float(np.clip(200 / 72.0, 1.0, 2000.0 / max(win.width, 1.0)))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=win, alpha=False)
        digest = hashlib.sha1(path.encode("utf-8", "replace")).hexdigest()[:8]
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(path).stem)[:40]
        name = f"{stem}_{digest}_p{page_no}_{int(cx)}x{int(cy)}.png"
        pix.save(os.path.join(cfg.evidence_dir, name))
        return name
    except Exception:
        return ""


def scan_page(page, page_no, cfg, path):
    """-> (hits, suspects, notes) for one page."""
    hits, suspects, notes = [], [], []
    try:
        candidates = find_candidate_rings(page, cfg)
    except imaging.TooMuchInk as exc:
        return hits, suspects, [f"page {page_no}: {exc}; logo search skipped - verify manually"]
    for cx, cy, r in candidates:
        rd = logo_reader.read_ring(page, cx, cy, r, use_ocr=cfg.use_ocr)
        if rd is None or not (rd.is_hit or rd.is_suspect):
            continue
        hit = LogoHit(page=page_no, label=rd.label if rd.is_hit else "", method=rd.method,
                      confidence=rd.confidence, center_pt=(round(rd.cx, 1), round(rd.cy, 1)),
                      diameter_pt=round(2 * rd.r, 1), detail=rd.detail)
        if rd.is_hit and rd.label == "EAR":
            m, src = find_eccn(page, rd.cx, rd.cy, rd.r, cfg)
            if m:
                hit.eccn, hit.eccn_base, hit.eccn_source, hit.eccn_labeled = m.text, m.base, src, m.labeled
        hit.evidence = _save_evidence(page, rd.cx, rd.cy, rd.r, cfg, path, page_no)
        (hits if rd.is_hit else suspects).append(asdict(hit))
    if not hits and not suspects:
        band_top = page.rect.y1 - cfg.footer_fraction * page.rect.height
        text = _page_text(page, pymupdf.Rect(page.rect.x0, band_top, page.rect.x1, page.rect.y1))
        word = _FOOTER_MENTION.search(text)
        if word:
            notes.append(f"page {page_no}: footer text mentions '{word.group(0)}' but no logo was found - verify")
    return hits, suspects, notes


def scan_file(path, cfg=None, root=""):
    """Scan one PDF and return a FileResult.  Never raises."""
    cfg = cfg or ScanConfig()
    t0 = time.time()
    res = FileResult(path=str(path), root=str(root))
    try:
        st = os.stat(_long_path(str(path)))
        res.size, res.mtime = st.st_size, st.st_mtime
        doc = _open(str(path))
    except Exception as exc:
        res.category, res.status, res.notes = UNREADABLE, STATUS_ERROR, [f"cannot open: {exc}"]
        res.seconds = round(time.time() - t0, 2)
        return res

    hits, suspects, notes, page_errors = [], [], [], 0
    try:
        if doc.needs_pass and not doc.authenticate(""):
            raise RuntimeError("password protected")
        res.pages = doc.page_count
        limit = res.pages if not cfg.max_pages else min(res.pages, cfg.max_pages)
        for i in range(limit):
            if time.time() - t0 > cfg.max_seconds_per_file:
                notes.append(f"time limit reached after {i} of {res.pages} pages")
                break
            try:
                h, s, n = scan_page(doc.load_page(i), i + 1, cfg, str(path))
                hits += h
                suspects += s
                notes += n
            except Exception as exc:
                page_errors += 1
                notes.append(f"page {i + 1} could not be analysed: {exc}")
            res.pages_scanned += 1
        if res.pages_scanned == 0 and res.pages:
            raise RuntimeError("no pages could be scanned")
        if page_errors == res.pages_scanned and res.pages_scanned:
            raise RuntimeError("every page failed to render; the file may be damaged")
    except Exception as exc:
        res.category, res.status, res.notes = UNREADABLE, STATUS_ERROR, [str(exc)] + notes
        res.seconds = round(time.time() - t0, 2)
        return res
    finally:
        doc.close()

    res.hits, res.suspects = hits, suspects
    res.category, res.status, extra = category_for(hits, suspects)
    res.notes = extra + notes
    if res.pages_scanned < res.pages:
        res.status = STATUS_REVIEW
        res.notes.append(f"only {res.pages_scanned} of {res.pages} pages were scanned")
    if (notes or page_errors) and res.status == STATUS_OK:
        res.status = STATUS_REVIEW
    if not ocr.available() and cfg.use_ocr:
        res.notes.append("OCR unavailable: " + ocr.error())
    res.seconds = round(time.time() - t0, 2)
    return res
