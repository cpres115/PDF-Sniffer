"""Drawing number / revision / REDLINE handling and the "out-of-date files on the server" check.

In a version-controlled location the file name is <drawing number>[_<revision>][-<classification>],
for example ``A10-000-5660_B-EAR.pdf``.  When a new revision is saved the old one should be removed,
and when a REDLINE is shared (``TST-010-600_A Redline.pdf``) the plain file of that drawing is out of
date.  This module reads those parts from each name, groups files by drawing number and reports

* older revisions that are still on the server,
* plain files made out of date by a shared redline (and redlines that are themselves out of date),
* extra copies of the same revision,
* and a list of every redline on the server.

How a name is read (case-insensitive):
  1. A REDLINE word (redline, red line, markup, ... - see DEFAULT_REDLINE_WORDS) cuts the name there:
     the word and anything after it are ignored, and the file is a redline.
  2. Windows copy markers (" - Copy", " (1)") and trailing classification words (-EAR, -ITAR, -EAR99,
     an ECCN such as -9A610) are ignored.
  3. A revision keyword ("Rev B", "REV_02") or, failing that, a short last token after an underscore
     (_B, _C, _02) is the revision; whatever precedes it is the drawing number.
  4. Without a revision the whole remaining name is the drawing number (``TST-010-600.pdf``).
A different scheme can be given as a regular expression with the named groups ``number`` and ``rev``.
"""
import os
import re
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field

STATUS_NEWEST = "Newest - keep"
STATUS_OLDER = "Older revision - remove?"
STATUS_COPY = "Same revision - extra copy"
STATUS_UNORDERED = "Revisions cannot be ordered - verify"
STATUS_REDLINE_CURRENT = "Current redline - keep"
STATUS_OUTDATED = "Out of date - a redline exists"
STATUS_REDLINE_OLD = "Old redline - remove?"

METHOD_KEYWORD = "Rev keyword"
METHOD_UNDERSCORE = "_Revision after underscore"
METHOD_NONE = "No revision in name"
METHOD_CUSTOM = "Custom pattern"

# Words that mark a redline.  Spaces/hyphens inside a word are optional ("red line" = "redline" = "red-line"),
# longer words also match when followed by more letters ("redlined", "redlines"), short ones only as a whole token.
DEFAULT_REDLINE_WORDS = ("redline", "red line", "markup", "mark up", "marked up", "redln", "rdln", "mkup", "rl")

_SEP = r"[\s_.\-]"
_COPY_SUFFIX = re.compile(r"(?:\s*[-_]?\s*copy(?:\s*\(\d+\))?|\s*\(\d+\))\s*$", re.IGNORECASE)
_CLASSIFICATION_TAIL = re.compile(
    r"(?:[\s_.\-]+(?:ITAR|EAR99|EAR|[0-9][A-E][0-9]{3}(?:\.[A-Za-z0-9]+)*))+$", re.IGNORECASE)
# "Rev B", "REV_02", "Revision-C"; without a separator only a short token is accepted so that
# words such as "Review" or "Revised" are not mistaken for a revision.
_REV_KEYWORD = re.compile(
    r"(?<![A-Za-z])REV(?:ISION)?(?:[\s_.\-]+([A-Z]{1,3}|\d{1,3})|([A-Z]{1,2}|\d{1,3}))(?![A-Za-z0-9])",
    re.IGNORECASE)
# 12345-678_B   or   12345-678_B-whatever   (the last underscore that is followed by a short token)
_UNDERSCORE_REV = re.compile(r"^(?P<number>.+)_(?P<rev>[A-Za-z]{1,2}|\d{1,3})(?:[\s\-_].*)?$")


@dataclass
class NameInfo:
    number: str    # drawing number as written, e.g. "A10-000-5660"
    rev: str       # revision as written, upper-cased, e.g. "B" or "02"; "" when the name has none
    key: str       # normalised drawing number used for grouping
    method: str
    redline: str = ""  # the REDLINE word found in the name ("" = not a redline)


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


def compile_redline_words(words=DEFAULT_REDLINE_WORDS):
    """One regular expression that finds any of the REDLINE words (None if the list is empty)."""
    parts = []
    for word in words:
        tokens = [t for t in re.split(_SEP + "+", word.strip()) if t]
        if not tokens:
            continue
        body = (_SEP + "?").join(re.escape(t) for t in tokens)
        letters = re.sub(r"[^A-Za-z]", "", word)
        parts.append(body + ("" if len(letters) >= 5 else r"(?![A-Za-z])"))
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(parts) + ")", re.IGNORECASE) if parts else None


_DEFAULT_REDLINE_RE = compile_redline_words()


def _stem(filename):
    stem = os.path.basename(filename)
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    return _COPY_SUFFIX.sub("", stem).strip()


def find_redline(filename, redline_re=_DEFAULT_REDLINE_RE):
    """The REDLINE word found in a file name ('' if there is none)."""
    m = redline_re.search(_stem(filename)) if redline_re is not None else None
    return m.group(0) if m else ""


def _key(number):
    return re.sub(_SEP + "+", "", number).upper()


def parse_name(filename, pattern=None, redline_re=_DEFAULT_REDLINE_RE):
    """NameInfo for a file name, or None when it contains no drawing number."""
    stem = _stem(filename)
    redline = ""
    m = redline_re.search(stem) if redline_re is not None else None
    if m:
        redline, stem = m.group(0), stem[:m.start()]
    stem = stem.strip(" _-.")
    stem = _CLASSIFICATION_TAIL.sub("", stem).strip(" _-.")

    def info(number, rev, method):
        number = _CLASSIFICATION_TAIL.sub("", number.strip(" _-.([")).strip(" _-.")
        if not re.search(r"\d", number):
            return None
        return NameInfo(number, rev.upper(), _key(number), method, redline)

    if pattern is not None:
        m = pattern.search(stem)
        return info(m.group("number"), m.group("rev").strip(), METHOD_CUSTOM) if m and m.group("number") and m.group("rev") else None
    m = _REV_KEYWORD.search(stem)
    if m:
        found = info(stem[:m.start()], m.group(1) or m.group(2), METHOD_KEYWORD)
        if found:
            return found
    m = _UNDERSCORE_REV.match(stem)
    if m:
        found = info(m.group("number"), m.group("rev"), METHOD_UNDERSCORE)
        if found:
            return found
    return info(stem, "", METHOD_NONE)


# ------------------------------------------------------------------------------ ordering
def _norm_rev(rev):
    """Revisions that mean the same compare equal: '02' == '2', 'b' == 'B'; '' = no revision."""
    return (rev.lstrip("0") or "0") if rev.isdigit() else rev.upper()


def _rank(rev):
    """Sort key within one kind of revision: numbers numerically, letters A < B < ... < Z < AA < AB."""
    return (int(rev),) if rev.isdigit() else (len(rev), rev)


def _kind(rev):
    return "number" if rev.isdigit() else "letter"


def _natural(text):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


@dataclass
class RevisionReport:
    rows: list = field(default_factory=list)       # files to look at, grouped by drawing number
    stats: dict = field(default_factory=dict)
    redlines: list = field(default_factory=list)   # every redline on the server


REVISION_COLUMNS = ["Drawing Number", "Revision", "Status", "File Name", "Folder", "Last Modified",
                    "Size (KB)", "Revisions On Server", "Export Control Group", "Notes",
                    "Name Read By", "Full Path"]
REDLINE_COLUMNS = ["Drawing Number", "Revision", "Redline File", "Folder", "Last Modified", "Size (KB)",
                   "Redline Word", "Status", "Plain File(s) It Makes Out Of Date", "Export Control Group",
                   "Full Path"]


def _when(mtime):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)) if mtime else ""


def analyze(files, pattern=None, redline_re=_DEFAULT_REDLINE_RE):
    """Find out-of-date files among `files` (dicts with 'path', 'size', 'mtime', optional 'category').

    Each dict also gets 'drawing_number', 'revision' and 'redline' keys.  Returns a RevisionReport.
    """
    groups = defaultdict(list)
    parsed, unparsed, no_revision = {}, 0, 0
    for f in files:
        info = parse_name(f["path"], pattern, redline_re)
        parsed[f["path"]] = info
        f["drawing_number"], f["revision"] = (info.number, info.rev) if info else ("", "")
        f["redline"] = info.redline if info else find_redline(f["path"], redline_re)
        if info:
            groups[info.key].append((f, info))
            no_revision += not info.rev
        else:
            unparsed += 1

    stats = {"files": len(files), "unparsed": unparsed, "no_revision": no_revision,
             "multi_revision": 0, "older": 0, "extra_copies": 0, "unordered": 0,
             "outdated_by_redline": 0, "old_redlines": 0, "redlines": sum(1 for f in files if f["redline"])}
    rows = []
    status_of = {}                 # path -> status
    outdates = defaultdict(list)   # redline path -> plain file names it makes out of date
    for key in sorted(groups, key=_natural):
        members = groups[key]
        if len(members) < 2:
            continue
        buckets = defaultdict(list)    # (normalised revision, is_redline) -> [(file, info)]
        shown = {"": "(none)"}         # normalised revision -> as written in a file name
        for f, info in members:
            buckets[(_norm_rev(info.rev), bool(info.redline))].append((f, info))
            shown.setdefault(_norm_rev(info.rev), info.rev)
        revs = sorted({r for r, _ in buckets if r})
        notes_of = {}

        if len(buckets) == 1:
            order = revs
            for f, _ in members:
                status_of[f["path"]] = STATUS_COPY
                notes_of[f["path"]] = f"{len(members)} files share this drawing number and revision"
            stats["extra_copies"] += len(members) - 1
        elif len({_kind(r) for r in revs}) > 1:
            order = sorted(revs)
            for f, _ in members:
                status_of[f["path"]] = STATUS_UNORDERED
                notes_of[f["path"]] = "revisions mix letters and numbers"
            stats["unordered"] += 1
        else:
            order = sorted(revs, key=_rank)
            rank = {"": -1, **{r: i for i, r in enumerate(order)}}
            newest = max(rank[r] for r, _ in buckets)
            newest_plain = max((rank[r] for r, red in buckets if not red), default=-2)
            redline_files = [(rank[r], f) for (r, red), items in buckets.items() if red for f, _ in items]
            newest_text = shown[order[-1]] if order else "(none)"
            plain_text = next((shown[r] for r in reversed(order) if (r, False) in buckets), "(none)")
            if len({r for r, _ in buckets}) > 1:
                stats["multi_revision"] += 1
            for (rev, is_redline), items in buckets.items():
                for f, _ in items:
                    if is_redline:
                        if rank[rev] == newest:
                            status = STATUS_REDLINE_CURRENT
                        else:
                            status = STATUS_REDLINE_OLD
                            notes_of[f["path"]] = f"revision {newest_text} is on the server"
                            stats["old_redlines"] += 1
                    elif rank[rev] < newest_plain:
                        status = STATUS_OLDER
                        notes_of[f["path"]] = f"revision {plain_text} is on the server"
                        stats["older"] += 1
                    else:
                        covering = [rf for rk, rf in redline_files if rk >= rank[rev]]
                        if covering:
                            status = STATUS_OUTDATED
                            notes_of[f["path"]] = "redline on the server: " + ", ".join(
                                os.path.basename(rf["path"]) for rf in covering)
                            stats["outdated_by_redline"] += 1
                            for rf in covering:
                                outdates[rf["path"]].append(os.path.basename(f["path"]))
                        else:
                            status = STATUS_NEWEST
                    status_of[f["path"]] = status
                if len(items) > 1:
                    stats["extra_copies"] += len(items) - 1
                    for f, _ in items:
                        prior = notes_of.get(f["path"])
                        notes_of[f["path"]] = (prior + "; " if prior else "") + f"{len(items)} copies of this file"
        rank_of = {"": -1, **{r: i for i, r in enumerate(order)}}
        revs_text = ", ".join((["(none)"] if ("", False) in buckets or ("", True) in buckets else [])
                              + [shown[r] for r in order])

        def sort_key(item):
            f, info = item
            return (-rank_of.get(_norm_rev(info.rev), -1), 0 if info.redline else 1,
                    -f.get("mtime", 0), f["path"].lower())

        for f, info in sorted(members, key=sort_key):
            rows.append(OrderedDict([
                ("Drawing Number", info.number), ("Revision", info.rev or "(none)"),
                ("Status", status_of[f["path"]]), ("File Name", os.path.basename(f["path"])),
                ("Folder", os.path.dirname(f["path"])), ("Last Modified", _when(f.get("mtime"))),
                ("Size (KB)", round(f.get("size", 0) / 1024, 1)), ("Revisions On Server", revs_text),
                ("Export Control Group", f.get("category", "")), ("Notes", notes_of.get(f["path"], "")),
                ("Name Read By", info.method), ("Full Path", f["path"]),
            ]))

    redlines = []
    for f in sorted((f for f in files if f["redline"]), key=lambda f: (_natural(f["drawing_number"].upper()), f["path"].lower())):
        info = parsed[f["path"]]
        if info is None:
            status = "Drawing number not recognised"
        else:
            status = status_of.get(f["path"], "Only file of this drawing on the server")
        redlines.append(OrderedDict([
            ("Drawing Number", f["drawing_number"]), ("Revision", (info.rev or "(none)") if info else ""),
            ("Redline File", os.path.basename(f["path"])), ("Folder", os.path.dirname(f["path"])),
            ("Last Modified", _when(f.get("mtime"))), ("Size (KB)", round(f.get("size", 0) / 1024, 1)),
            ("Redline Word", f["redline"]), ("Status", status),
            ("Plain File(s) It Makes Out Of Date", "; ".join(sorted(set(outdates.get(f["path"], []))))),
            ("Export Control Group", f.get("category", "")), ("Full Path", f["path"]),
        ]))
    return RevisionReport(rows, stats, redlines)

