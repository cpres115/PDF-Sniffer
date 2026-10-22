"""Drawing number / revision parsing and the "old revisions left on the server" check.

In a version-controlled location the file name is <drawing number> + <revision>, and when a new
revision is saved the old one should be removed.  This module reads the drawing number and the
revision from each file name, groups files by drawing number, and reports every drawing that is
present in more than one revision (or more than once).

Recognised names (case-insensitive; separators may be space, underscore, hyphen or dot):
    12345-678 Rev B.pdf   12345-678_REV_02.pdf   MWI-1042_RevC_2025-03-04.pdf   (revision keyword)
    12345-678-B.pdf       12345_B.pdf            12345.B.pdf                      (trailing letter(s))
    12345-678_02.pdf                                                              (trailing 1-2 digits)
Windows copy markers such as "12345_B - Copy.pdf" or "12345_B (1).pdf" are ignored so such copies
are grouped with the original.  A different naming scheme can be supplied as a regular expression
with the named groups ``number`` and ``rev`` (see settings.ini).
"""
import os
import re
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass

STATUS_NEWEST = "Newest - keep"
STATUS_OLDER = "Older revision - remove?"
STATUS_COPY = "Same revision - extra copy"
STATUS_UNORDERED = "Revisions cannot be ordered - verify"

METHOD_KEYWORD = "Rev keyword"
METHOD_TRAILING = "Trailing letter/number (guess)"
METHOD_CUSTOM = "Custom pattern"

_COPY_SUFFIX = re.compile(r"(?:\s*[-_]?\s*copy(?:\s*\(\d+\))?|\s*\(\d+\))\s*$", re.IGNORECASE)
# "Rev B", "REV_02", "Revision-C"; without a separator only a short token is accepted so that
# words such as "Review" or "Revised" are not mistaken for a revision.
_REV_KEYWORD = re.compile(
    r"(?<![A-Za-z])REV(?:ISION)?(?:[\s_.\-]+([A-Z]{1,3}|\d{1,3})|([A-Z]{1,2}|\d{1,3}))(?![A-Za-z0-9])",
    re.IGNORECASE)
_SEPARATORS = r"[\s_.\-]+"
_TRAILING_REV = re.compile(r"^(?:[A-Za-z]{1,2}|\d{1,2})$")


@dataclass
class NameInfo:
    number: str   # drawing number as written, e.g. "12345-678"
    rev: str      # revision as written, upper-cased, e.g. "B" or "02"
    key: str      # normalised drawing number used for grouping
    method: str


def compile_pattern(text):
    """Compile a custom file-name pattern; it must define the groups ``number`` and ``rev``."""
    if not text:
        return None
    try:
        pattern = re.compile(text, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"name pattern is not a valid regular expression: {exc}")
    if not {"number", "rev"} <= set(pattern.groupindex):
        raise ValueError("name pattern must contain the named groups (?P<number>...) and (?P<rev>...)")
    return pattern


def _key(number):
    return re.sub(_SEPARATORS, "", number).upper()


def parse_name(filename, pattern=None):
    """NameInfo for a file name, or None when no drawing number + revision can be recognised."""
    stem = os.path.basename(filename)
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = _COPY_SUFFIX.sub("", stem).strip()
    if pattern is not None:
        m = pattern.search(stem)
        if m and m.group("number") and m.group("rev"):
            return NameInfo(m.group("number").strip(), m.group("rev").strip().upper(),
                            _key(m.group("number")), METHOD_CUSTOM)
        return None

    m = _REV_KEYWORD.search(stem)
    if m:
        number = stem[:m.start()].rstrip(" _-.([")
        if re.search(r"\d", number):
            return NameInfo(number, (m.group(1) or m.group(2)).upper(), _key(number), METHOD_KEYWORD)

    tokens = [t for t in re.split(_SEPARATORS, stem) if t]
    if len(tokens) >= 2 and _TRAILING_REV.match(tokens[-1]):
        number = stem[:stem.rfind(tokens[-1])].rstrip(" _-.")
        if re.search(r"\d", number):
            return NameInfo(number, tokens[-1].upper(), _key(number), METHOD_TRAILING)
    return None


def _norm_rev(rev):
    """Revisions that mean the same compare equal: '02' == '2', 'b' == 'B'."""
    return (rev.lstrip("0") or "0") if rev.isdigit() else rev.upper()


def _rank(rev):
    """Sort key within one kind of revision: numbers numerically, letters A < B < ... < Z < AA < AB."""
    return (int(rev),) if rev.isdigit() else (len(rev), rev)


def _kind(rev):
    return "number" if rev.isdigit() else "letter"


def _natural(text):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def analyze(files, pattern=None):
    """Find drawings present in more than one revision (or more than once).

    `files` are dicts with 'path', 'size', 'mtime' and optionally 'category'.  Each dict also gets
    'drawing_number' and 'revision' keys.  Returns (rows, stats) where rows are the files to look at.
    """
    groups = defaultdict(list)
    unparsed = 0
    for f in files:
        info = parse_name(f["path"], pattern)
        f["drawing_number"], f["revision"] = (info.number, info.rev) if info else ("", "")
        if info:
            groups[info.key].append((f, info))
        else:
            unparsed += 1

    stats = {"files": len(files), "parsed": len(files) - unparsed, "unparsed": unparsed,
             "drawings": len(groups), "multi_revision": 0, "older": 0, "extra_copies": 0, "unordered": 0}
    rows = []
    for key in sorted(groups, key=_natural):
        members = groups[key]
        if len(members) < 2:
            continue
        by_rev = defaultdict(list)
        for f, info in members:
            by_rev[_norm_rev(info.rev)].append((f, info))
        distinct = list(by_rev)
        kinds = {_kind(r) for r in distinct}
        status_of, notes_of = {}, {}
        if len(distinct) == 1:
            for f, _ in members:
                status_of[f["path"]] = STATUS_COPY
                notes_of[f["path"]] = f"{len(members)} files share this drawing number and revision"
            stats["extra_copies"] += len(members) - 1
            order = distinct
        elif len(kinds) > 1:
            for f, _ in members:
                status_of[f["path"]] = STATUS_UNORDERED
                notes_of[f["path"]] = "revisions mix letters and numbers"
            stats["unordered"] += 1
            order = sorted(distinct)
        else:
            order = sorted(distinct, key=_rank)
            newest = order[-1]
            stats["multi_revision"] += 1
            stats["extra_copies"] += len(by_rev[newest]) - 1
            for rev, items in by_rev.items():
                for f, _ in items:
                    if rev == newest:
                        status_of[f["path"]] = STATUS_NEWEST
                        if len(items) > 1:
                            notes_of[f["path"]] = f"{len(items)} copies of the newest revision exist"
                    else:
                        status_of[f["path"]] = STATUS_OLDER
                        stats["older"] += 1
        rev_list = ", ".join(by_rev[r][0][1].rev for r in order)
        rank_of = {r: i for i, r in enumerate(order)}

        def sort_key(item):
            f, info = item
            return (-rank_of[_norm_rev(info.rev)], -f.get("mtime", 0), f["path"].lower())

        for f, info in sorted(members, key=sort_key):
            mtime = f.get("mtime") or 0
            rows.append(OrderedDict([
                ("Drawing Number", info.number), ("Revision", info.rev),
                ("Status", status_of[f["path"]]), ("File Name", os.path.basename(f["path"])),
                ("Folder", os.path.dirname(f["path"])),
                ("Last Modified", time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else ""),
                ("Size (KB)", round(f.get("size", 0) / 1024, 1)),
                ("Revisions On Server", rev_list), ("Export Control Group", f.get("category", "")),
                ("Notes", notes_of.get(f["path"], "")), ("Name Read By", info.method),
                ("Full Path", f["path"]),
            ]))
    return rows, stats


REVISION_COLUMNS = ["Drawing Number", "Revision", "Status", "File Name", "Folder", "Last Modified",
                    "Size (KB)", "Revisions On Server", "Export Control Group", "Notes",
                    "Name Read By", "Full Path"]
