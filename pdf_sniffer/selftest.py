# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""Synthetic sample PDFs with known answers, used by `--selftest` and the unit tests.

Nothing here is real export-controlled data: the logos are drawn on the fly as a red
circle containing red text, in vector form, as embedded pictures and as noisy "scans".
"""
import os
import tempfile

import numpy as np
import pymupdf

from . import models
from .config import ScanConfig
from .scanner import scan_file

RED = (0.85, 0.05, 0.05)
E_ITAR = models.ITAR
E_NONE = models.NON_CONTROLLED
E_EAR = models.EAR_NO_ECCN
E_UNREADABLE = models.UNREADABLE


def ear_cat(*eccns):
    return models.EAR_PREFIX + " + ".join(eccns)


def draw_logo(page, cx, cy, r, word, font="hebo", color=RED):
    page.draw_circle((cx, cy), r, color=color, width=r * 0.09)
    fs = r * 0.62
    tw = pymupdf.get_text_length(word, fontname=font, fontsize=fs)
    page.insert_text((cx - tw / 2, cy + fs * 0.35), word, fontname=font, fontsize=fs, color=color)


def _scan_copy(doc, dpi, quality, noise=6.0, seed=1):
    """Replace every page by a noisy JPEG picture of itself (a stand-in for a scanned drawing)."""
    rng = np.random.default_rng(seed)
    out = pymupdf.open()
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width * 3]
        arr = arr.reshape(pix.height, pix.width, 3).astype(np.float32)
        arr = np.clip(arr + rng.normal(0, noise, arr.shape), 0, 255).astype(np.uint8)
        noisy = pymupdf.Pixmap(pymupdf.csRGB, pix.width, pix.height, arr.tobytes(), False)
        newp = out.new_page(width=page.rect.width, height=page.rect.height)
        newp.insert_image(newp.rect, stream=noisy.tobytes("jpeg", jpg_quality=quality))
    return out


def _picture_logo(page, cx, cy, r, word, font="hebo"):
    """Insert the logo as an embedded PNG image (no text layer)."""
    tmp = pymupdf.open()
    tp = tmp.new_page(width=2 * r + 8, height=2 * r + 8)
    draw_logo(tp, r + 4, r + 4, r, word, font)
    png = tp.get_pixmap(dpi=300, alpha=False).tobytes("png")
    page.insert_image(pymupdf.Rect(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4), stream=png)


def _letter(footer_text=""):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    for i in range(6):
        page.insert_text((72, 90 + i * 16), "Lorem ipsum dolor sit amet, consectetur adipiscing elit.", fontsize=10)
    page.insert_text((72, 770), footer_text or "Company confidential - page 1", fontsize=8)
    return doc, page


def _drawing(width, height, title="DRAWING"):
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=height)
    page.draw_rect(pymupdf.Rect(30, 30, width - 30, height - 30), width=2)
    page.draw_rect(pymupdf.Rect(width - 560, height - 200, width - 30, height - 30), width=1.5)
    page.insert_text((width - 540, height - 100), title, fontsize=40)
    page.draw_circle((width * 0.4, height * 0.4), 120, width=1.5)       # black part outline
    page.draw_line((width * 0.2, height * 0.5), (width * 0.7, height * 0.3), width=1.0)
    return doc, page


def _advisory_table(page, top, borders=True, pictures=False, title="GENERAL SYMBOL ADVISORY"):
    """A 'General Symbol Advisory' table that shows what the ITAR / EAR logos look like (as in MWI files)."""
    x0, x1, xm = 60, 552, 168
    if borders:
        page.draw_rect(pymupdf.Rect(x0, top, x1, top + 134), width=0.8)
        page.draw_line((x0, top + 22), (x1, top + 22), width=0.8)
        page.draw_line((x0, top + 78), (x1, top + 78), width=0.8)
        page.draw_line((xm, top + 22), (xm, top + 134), width=0.8)
    page.insert_text((x0 + 8, top + 15), title, fontname="hebo", fontsize=11)
    for word, row_top, text in (("ITAR", top + 22, "This logo marks documents controlled under the ITAR."),
                                ("EAR", top + 78, "This logo marks documents controlled under the EAR.")):
        cy = row_top + 28
        (_picture_logo if pictures else draw_logo)(page, x0 + 54, cy, 18, word)
        page.insert_text((xm + 10, cy + 3), text, fontsize=9)


def build_samples(folder):
    """Create the sample PDFs in `folder`; return {file name: (expected category, expected status)}."""
    os.makedirs(folder, exist_ok=True)
    expected = {}

    def save(name, doc, category, status=models.STATUS_OK, **kw):
        doc.save(os.path.join(folder, name), **kw)
        expected[name] = (category, status)

    doc, page = _letter()
    save("01_document_plain.pdf", doc, E_NONE)

    doc, page = _letter("Company confidential")
    draw_logo(page, 300, 755, 20, "ITAR")
    save("02_document_itar_footer_vector.pdf", doc, E_ITAR)

    doc, page = _letter()
    _picture_logo(page, 520, 750, 20, "EAR")
    save("03_document_ear_no_eccn_picture.pdf", doc, E_EAR)

    doc, page = _letter()
    draw_logo(page, 80, 752, 18, "EAR")
    page.insert_text((110, 756), "ECCN: 9A610.x", fontsize=10)
    save("04_document_ear_eccn_9A610x.pdf", doc, ear_cat("9A610"))

    doc, page = _drawing(3168, 2448, "ASSEMBLY, MOTOR")
    draw_logo(page, 3168 - 300, 2448 - 260, 34, "ITAR")
    save("05_drawing_E_size_itar_vector.pdf", doc, E_ITAR)

    doc, page = _drawing(1224, 792, "BRACKET")
    draw_logo(page, 1224 - 140, 792 - 250, 26, "EAR")
    page.insert_text((1224 - 250, 792 - 245), "ECCN 5D002", fontsize=12)
    scan = _scan_copy(doc, dpi=150, quality=55)
    save("06_drawing_D_size_ear_5D002_scanned.pdf", scan, ear_cat("5D002"))

    for name, place, rot, eccn_txt, cat in (
            ("07_drawing_rotated90_ear_3A001.pdf", 90, 90, "ECCN: 3A001.a", ear_cat("3A001")),
            ("07b_drawing_rotated270_ear_3A001.pdf", -90, 270, "ECCN: 3A001.a", ear_cat("3A001"))):
        src = pymupdf.open()
        sp = src.new_page(width=792, height=612)
        sp.draw_rect(pymupdf.Rect(480, 540, 780, 600))
        draw_logo(sp, 700, 500, 24, "EAR")
        sp.insert_text((560, 505), eccn_txt, fontsize=10)
        doc = pymupdf.open()
        raw = doc.new_page(width=612, height=792)
        raw.show_pdf_page(raw.rect, src, 0, rotate=place)
        raw.set_rotation(rot)
        save(name, doc, cat)

    doc, _ = _letter()
    for _ in range(5):
        p = doc.new_page(width=612, height=792)
        p.insert_text((72, 100), "continued", fontsize=10)
    draw_logo(doc[3], 520, 745, 22, "ITAR")
    save("08_document_6pages_itar_on_page4.pdf", doc, E_ITAR)

    doc, page = _letter("Rev B  -  see sheet 2")
    draw_logo(page, 60, 740, 14, "3")
    draw_logo(page, 120, 740, 14, "12")
    page.draw_circle((180, 740), 14, color=RED, fill=RED)
    page.draw_rect(pymupdf.Rect(220, 725, 260, 755), color=RED, fill=RED)
    page.insert_text((280, 745), "REV A", fontsize=12, color=RED)
    page.draw_sector((400, 740), (420, 740), 120, color=RED, fill=RED)
    save("09_document_red_decoys.pdf", doc, E_NONE)

    doc, page = _letter("This document is subject to the ITAR")
    save("10_document_text_mention_only.pdf", doc, E_NONE, models.STATUS_REVIEW)

    doc, page = _letter()
    draw_logo(page, 200, 750, 18, "ITAR")
    draw_logo(page, 400, 750, 18, "EAR")
    save("11_document_itar_and_ear.pdf", doc, E_ITAR, models.STATUS_REVIEW)

    doc, page = _letter()
    draw_logo(page, 300, 750, 18, "EAR")
    page.insert_text((330, 754), "ECCN: EAR99", fontsize=10)
    save("12_document_ear99.pdf", doc, ear_cat("EAR99"))

    doc, page = _letter()
    draw_logo(page, 100, 750, 18, "EAR")
    page.insert_text((130, 754), "ECCN: 9A610.x", fontsize=10)
    p2 = doc.new_page(width=612, height=792)
    draw_logo(p2, 100, 750, 18, "EAR")
    p2.insert_text((130, 754), "ECCN: 3A001", fontsize=10)
    save("13_document_two_different_eccns.pdf", doc, ear_cat("3A001", "9A610"), models.STATUS_REVIEW)

    with open(os.path.join(folder, "14_corrupt.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.7\n" + os.urandom(2000))
    expected["14_corrupt.pdf"] = (E_UNREADABLE, models.STATUS_ERROR)

    doc, page = _letter()
    draw_logo(page, 300, 750, 18, "ITAR")
    save("15_encrypted.pdf", doc, E_UNREADABLE, models.STATUS_ERROR,
         encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")

    doc, page = _drawing(792, 612, "SPACER")
    draw_logo(page, 792 - 120, 612 - 120, 18, "EAR", font="tibo")
    scan = _scan_copy(doc, dpi=100, quality=40, noise=8.0, seed=3)
    save("16_drawing_B_size_ear_scanned_low_quality.pdf", scan, E_EAR)

    doc, page = _letter()
    draw_logo(page, 306, 752, 16, "EAR", font="tibo")
    save("17_document_ear_times_font.pdf", doc, E_EAR)

    doc, page = _letter()
    draw_logo(page, 300, 750, 22, "ABCD")
    save("18_document_red_ring_other_text.pdf", doc, models.NEEDS_REVIEW, models.STATUS_REVIEW)

    # --- MWI-style pages: the General Symbol Advisory table shows both logos but they must not count
    doc, page = _letter("MWI-1042 Rev C - page 1")
    page.insert_text((72, 60), "MWI-1042  Assemble connector housing", fontname="hebo", fontsize=14)
    _advisory_table(page, 430)
    save("19_mwi_advisory_table_only.pdf", doc, E_NONE)

    doc, page = _letter("MWI-2210 Rev A - page 1")
    _advisory_table(page, 430)
    draw_logo(page, 306, 748, 18, "EAR")
    page.insert_text((330, 752), "ECCN: 5D002", fontsize=10)
    save("20_mwi_advisory_table_plus_ear_footer_5D002.pdf", doc, ear_cat("5D002"))

    doc, page = _letter("MWI-3305 Rev B - page 1")
    _advisory_table(page, 430, pictures=True)
    draw_logo(page, 520, 748, 18, "ITAR")
    save("21_mwi_advisory_pictures_plus_itar_footer.pdf", doc, E_ITAR)

    doc, page = _letter("MWI-4410 Rev A - page 1")
    bold_title = "General Symbol Advisory"  # as the real MWI files write it
    _advisory_table(page, 430, borders=False, title=bold_title)
    save("22_mwi_advisory_without_table_lines.pdf", doc, E_NONE)

    # --- ECCN well away from the logo (vertical / horizontal offset)
    doc, page = _letter()
    draw_logo(page, 306, 750, 18, "EAR")
    page.insert_text((330, 642), "ECCN: 9A610.x", fontsize=10)
    save("23_document_eccn_far_above_logo.pdf", doc, ear_cat("9A610"))

    doc, page = _letter()
    draw_logo(page, 120, 750, 18, "EAR")
    page.insert_text((354, 640), "ECCN: 3A001.a", fontsize=10)
    save("24_document_eccn_far_right_and_above.pdf", doc, ear_cat("3A001"))

    doc, page = _drawing(1224, 792, "HOUSING")
    draw_logo(page, 1224 - 140, 792 - 250, 28, "EAR")
    page.insert_text((1224 - 330, 792 - 250 - 3 * 56), "ECCN 6A002", fontsize=12)
    save("25_drawing_scanned_eccn_far_above_logo.pdf", _scan_copy(doc, dpi=150, quality=55), ear_cat("6A002"))

    return expected


def run_selftest(verbose=True):
    """Build the samples, scan them and compare with the known answers.  Returns True on success."""
    from . import ocr
    work = tempfile.mkdtemp(prefix="pdf_sniffer_selftest_")
    expected = build_samples(work)
    cfg = ScanConfig(evidence_dir="")
    failures = 0
    print(f"Self-test: scanning {len(expected)} synthetic PDFs "
          f"(OCR {'available' if ocr.available() else 'NOT available: ' + ocr.error()})")
    for name in sorted(expected):
        want_cat, want_status = expected[name]
        res = scan_file(os.path.join(work, name), cfg)
        ok = res.category == want_cat and res.status == want_status
        failures += not ok
        if verbose or not ok:
            mark = "PASS" if ok else "FAIL"
            line = f"  [{mark}] {name}"
            if not ok:
                line += f"\n         expected {want_cat!r} / {want_status}\n         got      {res.category!r} / {res.status} {res.notes}"
            print(line)
    print("Self-test " + ("PASSED" if not failures else f"FAILED ({failures} problem(s))"))
    try:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
    except Exception:
        pass
    return failures == 0
