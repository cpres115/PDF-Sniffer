"""Scan one PDF: find red-circle logos in the search zone of every page and read them."""
import contextlib
import hashlib
import io
import math
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


def _norm(text):
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _words_display(page, rect):
    """[(Rect, text)] for the text-layer words inside a displayed-page rectangle."""
    out = []
    for x0, y0, x1, y1, word, *_ in page.get_text("words", clip=rect * page.derotation_matrix):
        out.append((pymupdf.Rect(x0, y0, x1, y1) * page.rotation_matrix, word))
    return out


def _page_text(page, rect):
    """Text-layer text inside a displayed-page rectangle."""
    return page.get_text("text", clip=rect * page.derotation_matrix)


def _pick_eccn(found, words, cx, cy):
    """Choose the best ECCN: one written as 'ECCN ...' first, then the one nearest the logo.

    `words` are (Rect, text) in displayed-page points.  Returns (match, rect of its text or None).
    """
    scored = []
    for m in found:
        needle, best, best_d = _norm(m.base), None, None
        for rect, w in words:
            if needle in _norm(w):
                d = math.hypot((rect.x0 + rect.x1) / 2 - cx, (rect.y0 + rect.y1) / 2 - cy)
                if best is None or d < best_d:
                    best, best_d = rect, d
        scored.append((not m.labeled, best_d if best is not None else 1e12, m.base, m, best))
    scored.sort(key=lambda t: t[:3])
    return scored[0][3], scored[0][4]


def _ocr_strips(page, win, cx, cy, r):
    """OCR the ECCN window in overlapping horizontal strips, nearest the logo first.

    A whole drawing corner confuses Tesseract (it locks onto the largest text), strips do not.
    Yields (EccnMatch list, words in displayed-page points) per strip that contains an ECCN.
    """
    zoom = float(np.clip(300 / 72.0, 1.0, 3000.0 / max(win.width, 1.0)))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=win,
                          colorspace=pymupdf.csRGB, alpha=False)
    # Blank out the logo itself so Tesseract only sees the text around it.
    # (Pixmap.set_rect works in absolute zoomed coordinates, not pixmap-local ones.)
    pad = 1.1
    box = pymupdf.IRect(int((cx - r * pad) * zoom), int((cy - r * pad) * zoom),
                        int((cx + r * pad) * zoom) + 1, int((cy + r * pad) * zoom) + 1)
    pix.set_rect(box & pix.irect, (255, 255, 255))
    arr = logo_reader.pixmap_to_array(pix)
    height = arr.shape[0]
    strip = max(int(2.5 * 2 * r * zoom), 150)
    step = max(strip // 2, 1)
    starts = list(range(0, max(height - strip, 0) + 1, step))
    if starts[-1] + strip < height:
        starts.append(height - strip)
    centre_px = cy * zoom - pix.y
    starts.sort(key=lambda y0: abs(y0 + strip / 2 - centre_px))
    for y0 in starts:
        sub = np.ascontiguousarray(arr[y0:y0 + strip])
        piece = pymupdf.Pixmap(pymupdf.csRGB, sub.shape[1], sub.shape[0], sub.tobytes(), False)
        piece.set_dpi(300, 300)
        text, words = ocr.read_words(piece)
        found = eccn.extract_ocr(text)
        if found:
            shown = [(pymupdf.Rect((x0 + pix.x) / zoom, (y0 + y + pix.y) / zoom,
                                   (x1 + pix.x) / zoom, (y0 + y1 + pix.y) / zoom), w)
                     for x0, y, x1, y1, w in words]
            yield found, shown


def find_eccn(page, cx, cy, r, cfg):
    """Look for an ECCN around the logo: text layer first, then OCR.

    -> (EccnMatch, source, rect of the ECCN text or None), or (None, '', None).
    """
    win = _window_rect(page, cx, cy, r, cfg)
    found = eccn.extract(_page_text(page, win))
    if found:
        m, rect = _pick_eccn(found, _words_display(page, win), cx, cy)
        return m, "text", rect
    if cfg.use_ocr and ocr.available():
        for found, words in _ocr_strips(page, win, cx, cy, r):
            m, rect = _pick_eccn(found, words, cx, cy)
            return m, "ocr", rect
    # fall back to an explicitly labelled ECCN anywhere in the search zone
    zone = _clip_for_zone(page, cfg)
    labelled = [m for m in eccn.extract(_page_text(page, zone)) if m.labeled]
    if labelled:
        m, rect = _pick_eccn(labelled, _words_display(page, zone), cx, cy)
        return m, "page-text", rect
    return None, "", None


# ------------------------------------------------------------ explanatory ("advisory") tables
def _phrase_rects(words, phrase):
    target = [_norm(t) for t in phrase.split()]
    toks = [_norm(w) for _, w in words]
    rects = []
    for i in range(len(words) - len(target) + 1):
        if toks[i:i + len(target)] == target:
            rect = pymupdf.Rect(words[i][0])
            for j in range(1, len(target)):
                rect |= words[i + j][0]
            rects.append(rect)
    return rects


def advisory_regions(page, cfg):
    """Areas of the page that only *explain* what the ITAR/EAR logos look like.

    Found from a heading such as "GENERAL ADVISORY" (see cfg.advisory_phrases): the table that
    holds or directly follows the heading.  If no table can be detected, everything below the
    heading down to the footer band counts, so a real logo in the footer is never skipped.
    """
    if not cfg.advisory_phrases:
        return []
    words = _words_display(page, page.rect)
    heads = [rect for phrase in cfg.advisory_phrases for rect in _phrase_rects(words, phrase)]
    if not heads:
        return []
    tables = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # PyMuPDF prints an advert on first use
            found = page.find_tables().tables
        tables = [pymupdf.Rect(t.bbox) * page.rotation_matrix for t in found]
    except Exception:
        pass
    footer_top = page.rect.y1 - cfg.footer_fraction * page.rect.height
    regions = []
    for h in heads:
        centre = pymupdf.Point((h.x0 + h.x1) / 2, (h.y0 + h.y1) / 2)
        holding = [t for t in tables if pymupdf.Rect(t.x0 - 2, t.y0 - 2, t.x1 + 2, t.y1 + 2).contains(centre)]
        following = [t for t in tables if -4 <= t.y0 - h.y1 <= max(40.0, 3 * h.height)
                     and t.x0 <= h.x1 and t.x1 >= h.x0]
        chosen = holding or following
        if chosen:
            regions.append(min(chosen, key=lambda t: t.width * t.height))
        elif h.y0 < footer_top:
            regions.append(pymupdf.Rect(page.rect.x0, h.y0, page.rect.x1, footer_top))
    return regions


# ------------------------------------------------------------------------------- evidence
def _draw_box(arr, box, color, thickness=3):
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = box
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 <= x0 or y1 <= y0:
        return
    arr[y0:min(y0 + thickness, h), x0:x1] = color
    arr[max(y1 - thickness, 0):y1, x0:x1] = color
    arr[y0:y1, x0:min(x0 + thickness, w)] = color
    arr[y0:y1, max(x1 - thickness, 0):x1] = color


def _save_evidence(page, logo, eccn_rect, cfg, path, page_no, tag=""):
    """Save a picture of the logo and its surroundings.  -> (file name, box on the page) or ('', ()).

    The picture always covers the whole ECCN search window and the ECCN text itself, so the
    ECCN is visible wherever it sits.  The logo is outlined in green and the ECCN in blue.
    """
    if not cfg.evidence_dir:
        return "", ()
    cx, cy, r = logo
    try:
        d = 2 * r
        logo_rect = pymupdf.Rect(cx - r, cy - r, cx + r, cy + r)
        box = _window_rect(page, cx, cy, r, cfg) | logo_rect
        if eccn_rect is not None:
            box = box | eccn_rect
        box = pymupdf.Rect(box.x0 - 0.5 * d, box.y0 - 0.5 * d, box.x1 + 0.5 * d, box.y1 + 0.5 * d) & page.rect
        zoom = float(np.clip(200 / 72.0, 0.4, min(2400.0 / max(box.width, 1.0), 2000.0 / max(box.height, 1.0))))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=box, colorspace=pymupdf.csRGB, alpha=False)
        arr = logo_reader.pixmap_to_array(pix).copy()

        def to_px(rect, grow=4):
            return (int(rect.x0 * zoom - pix.x) - grow, int(rect.y0 * zoom - pix.y) - grow,
                    int(rect.x1 * zoom - pix.x) + grow, int(rect.y1 * zoom - pix.y) + grow)

        _draw_box(arr, to_px(logo_rect, 6), (0, 170, 0))
        if eccn_rect is not None:
            _draw_box(arr, to_px(eccn_rect), (0, 90, 255))
        out = pymupdf.Pixmap(pymupdf.csRGB, arr.shape[1], arr.shape[0], arr.tobytes(), False)
        digest = hashlib.sha1(path.encode("utf-8", "replace")).hexdigest()[:8]
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(path).stem)[:40]
        name = f"{stem}_{digest}_p{page_no}_{int(cx)}x{int(cy)}{'_' + tag if tag else ''}.png"
        out.save(os.path.join(cfg.evidence_dir, name))
        return name, tuple(round(v, 1) for v in box)
    except Exception:
        return "", ()


def scan_page(page, page_no, cfg, path):
    """-> (hits, suspects, notes, infos) for one page."""
    hits, suspects, notes, infos = [], [], [], []
    try:
        candidates = find_candidate_rings(page, cfg)
    except imaging.TooMuchInk as exc:
        return hits, suspects, [f"page {page_no}: {exc}; logo search skipped - verify manually"], infos

    regions = None

    def advisory():
        nonlocal regions
        if regions is None:
            regions = advisory_regions(page, cfg)
        return regions

    ignored = 0
    for cx, cy, r in candidates:
        if any(reg.contains(pymupdf.Point(cx, cy)) for reg in advisory()):
            ignored += 1
            _save_evidence(page, (cx, cy, r), None, cfg, path, page_no, tag="ignored")
            continue
        rd = logo_reader.read_ring(page, cx, cy, r, use_ocr=cfg.use_ocr)
        if rd is None or not (rd.is_hit or rd.is_suspect):
            continue
        hit = LogoHit(page=page_no, label=rd.label if rd.is_hit else "", method=rd.method,
                      confidence=rd.confidence, center_pt=(round(rd.cx, 1), round(rd.cy, 1)),
                      diameter_pt=round(2 * rd.r, 1), detail=rd.detail)
        eccn_rect = None
        if rd.is_hit and rd.label == "EAR":
            m, src, eccn_rect = find_eccn(page, rd.cx, rd.cy, rd.r, cfg)
            if m:
                hit.eccn, hit.eccn_base, hit.eccn_source, hit.eccn_labeled = m.text, m.base, src, m.labeled
                if eccn_rect is not None:
                    hit.eccn_box = tuple(round(v, 1) for v in eccn_rect)
        hit.evidence, hit.evidence_box = _save_evidence(page, (rd.cx, rd.cy, rd.r), eccn_rect, cfg, path, page_no)
        (hits if rd.is_hit else suspects).append(asdict(hit))
    if ignored:
        infos.append(f"page {page_no}: {ignored} explanatory logo(s) in the advisory table were ignored")
    if not hits and not suspects:
        band_top = page.rect.y1 - cfg.footer_fraction * page.rect.height
        band = pymupdf.Rect(page.rect.x0, band_top, page.rect.x1, page.rect.y1)
        words = [w for rect, w in _words_display(page, band)
                 if not any(reg.contains(pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2))
                            for reg in advisory())]
        word = _FOOTER_MENTION.search(" ".join(words))
        if word:
            notes.append(f"page {page_no}: footer text mentions '{word.group(0)}' but no logo was found - verify")
    return hits, suspects, notes, infos


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

    hits, suspects, notes, infos, page_errors = [], [], [], [], 0
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
                h, s, n, f = scan_page(doc.load_page(i), i + 1, cfg, str(path))
                hits += h
                suspects += s
                notes += n
                infos += f
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
    res.info = infos
    if res.pages_scanned < res.pages:
        res.status = STATUS_REVIEW
        res.notes.append(f"only {res.pages_scanned} of {res.pages} pages were scanned")
    if (notes or page_errors) and res.status == STATUS_OK:
        res.status = STATUS_REVIEW
    if not ocr.available() and cfg.use_ocr:
        res.notes.append("OCR unavailable: " + ocr.error())
    res.seconds = round(time.time() - t0, 2)
    return res
