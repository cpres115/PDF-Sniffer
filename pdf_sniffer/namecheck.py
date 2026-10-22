# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""Name-versus-logo check.

In the library every controlled drawing carries its classification in the file name (``..._B-EAR.pdf``,
``..._A-ITAR.pdf``) and uncontrolled drawings carry no tag.  This module compares that tag with the logo
the scan actually found in the PDF and reports every disagreement:

  High    the logo is stricter than the name  (name has no tag / says EAR, but the file carries an ITAR logo;
          name has no tag, but the file carries an EAR logo)  - the file may be under-protected
  Medium  the name is stricter than the logo  (name says ITAR but the logo says EAR; name says ITAR/EAR but no
          logo was found - the logo may be missing, or the scan may have missed it)

Files whose scan ended in "Needs Review" or "Unreadable" cannot be compared.  EAR99 counts as EAR.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from . import models, revisions

MATCH = "Match"
NOT_COMPARED = "Could not compare"
HIGH, MEDIUM = "High", "Medium"

COLUMNS = ["Priority", "Mismatch", "File Name", "Classification In Name", "Classification From Logo",
           "ECCN (as written)", "Logo Pages", "Detection", "Evidence Image(s)", "Folder", "Notes", "Full Path"]

_STRICTNESS = {"": 0, "EAR": 1, "ITAR": 2}


@dataclass
class NameCheck:
    rows: list = field(default_factory=list)    # one per mismatch, High priority first
    stats: dict = field(default_factory=dict)


def logo_classification(result):
    """'ITAR', 'EAR' or '' (no logo) for a scan result; None when the scan could not decide."""
    if result["category"] in (models.UNREADABLE, models.NEEDS_REVIEW):
        return None
    labels = {h["label"] for h in result["hits"]}
    return "ITAR" if "ITAR" in labels else "EAR" if "EAR" in labels else ""


def verdict(name_class, logo_class):
    """-> (text, priority).  text is MATCH / NOT_COMPARED or a description of the mismatch."""
    if logo_class is None:
        return NOT_COMPARED, ""
    if name_class == logo_class:
        return MATCH, ""
    if not logo_class:
        text = f"Name says {name_class}, no ITAR/EAR logo found"
    elif not name_class:
        text = f"Name has no ITAR/EAR tag, but the file carries an {logo_class} logo"
    else:
        text = f"Name says {name_class}, logo says {logo_class}"
    return text, (HIGH if _STRICTNESS[logo_class] > _STRICTNESS[name_class] else MEDIUM)


def check(results, redline_re=revisions._DEFAULT_REDLINE_RE):
    """Compare every scanned file.  Annotates each result dict ('name_class', 'name_vs_logo'), marks mismatches
    for review (status + note) and returns a NameCheck."""
    stats = {"compared": 0, "match": 0, "mismatch": 0, "high": 0, "medium": 0, "not_compared": 0}
    rows = []
    for r in results:
        name_class = revisions.classification_in_name(r["path"], redline_re)
        logo_class = logo_classification(r)
        text, priority = verdict(name_class, logo_class)
        r["name_class"], r["name_vs_logo"] = name_class, text
        if text == NOT_COMPARED:
            stats["not_compared"] += 1
            continue
        stats["compared"] += 1
        if text == MATCH:
            stats["match"] += 1
            continue
        stats["mismatch"] += 1
        stats["high" if priority == HIGH else "medium"] += 1
        r["notes"] = list(r["notes"]) + [f"Name vs logo: {text}"]
        if r["status"] == models.STATUS_OK:
            r["status"] = models.STATUS_REVIEW
        hits = r["hits"]
        rows.append(OrderedDict([
            ("Priority", priority), ("Mismatch", text), ("File Name", Path(r["path"]).name),
            ("Classification In Name", name_class or "(none)"), ("Classification From Logo", r["category"]),
            ("ECCN (as written)", ", ".join(sorted({h["eccn"] for h in hits if h["eccn"]}))),
            ("Logo Pages", ", ".join(map(str, sorted({h["page"] for h in hits})))),
            ("Detection", "; ".join(sorted({f'{h["method"]} ({h["confidence"]})' for h in hits}))),
            ("Evidence Image(s)", "; ".join(h["evidence"] for h in hits if h["evidence"])),
            ("Folder", str(Path(r["path"]).parent)), ("Notes", ""), ("Full Path", r["path"]),
        ]))
    rows.sort(key=lambda row: (row["Priority"] != HIGH, row["Mismatch"], row["Full Path"].lower()))
    return NameCheck(rows, stats)
