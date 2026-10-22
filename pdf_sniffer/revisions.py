# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""Drawing number / revision / REDLINE handling and the "out-of-date files on the server" check.

In a version-controlled location the file name is <drawing number>_<revision>, optionally followed by tags,
for example ``A10-000-5660_B-EAR.pdf`` or ``A10-000-1059_1 Blocked.pdf``.  When a new revision is saved the
old one should be removed, and when a REDLINE is shared (``TST-010-600_A REDLINE.pdf``) the plain file of
that drawing is out of date.  This module reads those parts from each name, groups files by drawing number
and reports

* older revisions that are still on the server,
* plain files made out of date by a shared redline (and redlines that are themselves out of date),
* extra copies of the same revision,
* and a list of every redline on the server.

How a name is read (case-insensitive) - built from the ~6,300 real file names of the library:
  * Copy markers (" - Copy", " (1)"), the extension and trailing dots/spaces are ignored.
  * The revision is the last short token after an underscore:  _B  _C  _AB  _2  _1.0  _1_0  _1-0  _A0  _B1.
    Tag words that follow it (EAR, ITAR, REDLINE, Blocked, Removed, Obsolete, In Change SJS, PRELIM, ...)
    are not revisions; the drawing number is everything before the underscore (it may itself contain
    underscores:  A10-000-204_X_A  ->  number A10-000-204_X, revision A).
  * Older names without an underscore are read too:  "T01-000-297 A",  "CBL-000-238-B",  "305722-RevNA".
  * Without a revision the whole name is the drawing number ("CHM-000-016.pdf").
  * Tags are collected for the reports: classification (EAR / ITAR / EAR99), REDLINE and status words.
A different scheme can be given as a regular expression with the named groups ``number`` and ``rev``.
"""
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
METHOD_LEGACY = "Older style (space / hyphen before revision)"
METHOD_NONE = "No revision in name"
METHOD_CUSTOM = "Custom pattern"

# Words that mark a redline.  Spaces/hyphens inside a word are optional ("red line" = "redline" = "red-line"),
# words of 5+ letters also match longer forms ("redlines", "redlined"), shorter ones only as a whole token.
# The library only ever uses REDLINE; add more (markup, rl, ...) in settings.ini if your team does.
DEFAULT_REDLINE_WORDS = ("redline", "red line")

_SEP = r"[\s_.\-]"
_COPY_SUFFIX = re.compile(r"(?:\s*[-_]?\s*copy(?:\s*\(\d+\))?|\s*\(\d+\))\s*$", re.IGNORECASE)

# ---- tags found in the name after the drawing number: (label, regex).  Status words are the ones seen
# in the library; "RETIRED" ones mean the file has already been marked as not to be used.
CLASSIFICATION_TAGS = (("ITAR", r"itar"), ("EAR99", r"ear99"), ("EAR", r"ear"))
STATUS_TAGS = (
    ("Blocked", r"block(?:ed)?"),
    ("Removed", r"removed"),
    ("Obsolete", r"obsolete[d]?"),
    ("Do Not Use", r"do" + _SEP + r"*not" + _SEP + r"*use"),
    ("In Change", r"in" + _SEP + r"*(?:change|eco)(?:" + _SEP + r"*process)?"),
    ("Prelim", r"prelim(?:inary)?"),
    ("Deviation", r"deviation"),
    ("Internal Use Only", r"internal" + _SEP + r"*use" + _SEP + r"*only"),
    ("Hand Drawn", r"hand" + _SEP + r"*drawn"),
)
RETIRED_TAGS = {"Blocked", "Removed", "Obsolete", "Do Not Use"}
_TAG_PATTERNS = [(label, re.compile(r"(?<![A-Za-z])(?:" + rx + r")(?![A-Za-z])", re.IGNORECASE))
                 for label, rx in CLASSIFICATION_TAGS + STATUS_TAGS]
# classification words / an ECCN at the end of a drawing number:  A10-000-5630-X-EAR_B  ->  A10-000-5630-X
_CLASSIFICATION_TAIL = re.compile(
    r"(?:[\s_.\-]+(?:ITAR|EAR99|EAR|[0-9][A-E][0-9]{3}(?:\.[A-Za-z0-9]+)*))+$", re.IGNORECASE)
# tag phrases (and "(anything)") at the very end of a name that has no revision
_TRAILING_TAG = re.compile(
    r"[\s_.\-]*(?:\([^)]*\)|(?<![A-Za-z])(?:" + "|".join(rx for _, rx in CLASSIFICATION_TAGS + STATUS_TAGS)
    + r")(?![A-Za-z]))[\s_.\-]*$", re.IGNORECASE)

# A revision token: 7  12  1.0  1_0  1-0  |  A0  B1  R6  |  A  AB.   Not followed by more letters/digits.
_REV_TOKEN = re.compile(r"(?P<rev>\d{1,2}(?:[._\-]\d{1,2})?|[A-Za-z]\d{1,2}|[A-Za-z]{1,2})(?![A-Za-z0-9])")
_NOT_REV = {"IN", "ON", "NO", "OF", "TO", "DO", "AT", "BY", "OR", "AN", "AS", "IS", "IT", "US", "UP"}
# "Rev B", "REV_02", "Revision-C", "RevNA"; without a separator only a short token is accepted so that
# words such as "Review" or "Revised" are not mistaken for a revision.
_REV_KEYWORD = re.compile(
    r"(?<![A-Za-z])REV(?:ISION)?(?:[\s_.\-]+([A-Z]{1,3}|\d{1,3})|([A-Z]{1,2}|\d{1,3}))(?![A-Za-z0-9])",
    re.IGNORECASE)
# older names: "T01-000-297 A", "C10256 R6", "A10-000-4188 K-S 1.0"   and   "CBL-000-238-B", "HDW-000-021-X-B"
_SPACE_REV = re.compile(r"^(?P<number>.*\d.*?)\s+(?P<rev>[A-Za-z]{1,2}|[A-Za-z]\d{1,2}|\d{1,2}(?:\.\d{1,2})?)$")
_HYPHEN_REV = re.compile(r"^(?P<number>.*\d.*?)-(?P<rev>[A-WYZa-wyz]{1,2})$")  # "-X" is a variant of the number, not a revision


@dataclass
class NameInfo:
    number: str    # drawing number as written, e.g. "A10-000-5660"
    rev: str       # revision as written, upper-cased, e.g. "B", "02" or "1.0"; "" when the name has none
    key: str       # normalised drawing number used for grouping
    method: str
    redline: str = ""                       # the REDLINE word found in the name ("" = not a redline)
    tags: tuple = ()                        # labels found in the name: EAR, ITAR, Redline, Blocked, In Change, ...


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


def _basename(path):
    """File name of a Windows or POSIX path (works on any OS)."""
    return re.split(r"[\\/]", path)[-1]


def _dirname(path):
    parts = re.split(r"[\\/]", path)
    return path[:len(path) - len(parts[-1]) - 1] if len(parts) > 1 else ""


def _stem(filename):
    stem = _basename(filename)
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    stem = stem.rstrip(" .")            # "A10-000-3317_A..pdf"  and  "CBL-000-090_B .PDF"
    return _COPY_SUFFIX.sub("", stem).strip()


def find_redline(filename, redline_re=_DEFAULT_REDLINE_RE):
    """The REDLINE word found in a file name ('' if there is none)."""
    m = redline_re.search(_stem(filename)) if redline_re is not None else None
    return m.group(0) if m else ""


def _find_tags(text, redline_re):
    found = []
    if redline_re is not None:
        m = redline_re.search(text)
        if m:
            found.append((m.start(), "Redline"))
    for label, rx in _TAG_PATTERNS:
        m = rx.search(text)
        if m:
            found.append((m.start(), label))
    return tuple(label for _, label in sorted(found))


def _key(number):
    return re.sub(_SEP + "+", "", number).upper()


def _clean_number(text):
    text = text.strip(" _-.([")
    while True:
        new = _CLASSIFICATION_TAIL.sub("", text).strip(" _-.([")
        if new == text:
            return re.sub(r"\s+", " ", text)
        text = new


def _without_tail_tags(stem, redline_re):
    """The name without trailing tag phrases (EAR, Blocked, "(anything)") and without the REDLINE word and
    whatever follows it."""
    core = stem
    while True:
        shorter = _TRAILING_TAG.sub("", core)
        if redline_re is not None:
            m = redline_re.search(shorter)
            if m:
                shorter = shorter[:m.start()]
        shorter = shorter.strip(" _-.")
        if shorter == core:
            return core
        core = shorter


def _underscore_revision(stem):
    """(position of the underscore, revision) of the revision token after an underscore, or None.

    Every underscore followed by a short token is a candidate; tag words (In, Blocked, SJS, ...) are
    not revision-shaped, and a two-letter token (could be initials) only wins if no simpler candidate
    exists.  Among the rest the rightmost one wins:  A10-000-204_X_A_ITAR Blocked -> A.
    """
    candidates, consumed = [], -1
    for m in re.finditer(r"_+\s*", stem):
        if m.start() < consumed:       # the underscore in "1_0" belongs to the revision token before it
            continue
        t = _REV_TOKEN.match(stem, m.end())
        if t and t.group("rev").upper() not in _NOT_REV:
            candidates.append((m.start(), t.group("rev")))
            consumed = t.end()
    simple = [c for c in candidates if not re.fullmatch(r"[A-Za-z]{2}", c[1])]
    pool = simple or candidates
    return pool[-1] if pool else None


def parse_name(filename, pattern=None, redline_re=_DEFAULT_REDLINE_RE):
    """NameInfo for a file name, or None when it contains no drawing number."""
    stem = _stem(filename)
    tags = _find_tags(stem, redline_re)
    m = redline_re.search(stem) if redline_re is not None else None
    redline = m.group(0) if m else ""

    def info(number, rev, method):
        number = _clean_number(number)
        if not re.search(r"\d", number):
            return None
        rev = "" if rev.upper() in ("NA", "N/A") else rev     # "305722-RevNA" = not applicable
        return NameInfo(number, rev.upper(), _key(number), method, redline, tags)

    if pattern is not None:
        m = pattern.search(_without_tail_tags(stem, redline_re))
        return info(m.group("number"), m.group("rev").strip(), METHOD_CUSTOM) if m and m.group("number") and m.group("rev") else None

    m = _REV_KEYWORD.search(stem)      # "Rev B", "REV_02", "-RevNA" win over everything else
    if m:
        result = info(stem[:m.start()], m.group(1) or m.group(2), METHOD_KEYWORD)
        if result:
            return result
    found = _underscore_revision(stem)
    if found:
        result = info(stem[:found[0]], found[1], METHOD_UNDERSCORE)
        if result:
            return result

    # no underscore revision: drop tag phrases from the end, then try the older styles
    core = _clean_number(_without_tail_tags(stem, redline_re))
    for rx in (_SPACE_REV, _HYPHEN_REV):
        m = rx.match(core)
        if m and m.group("rev").upper() not in _NOT_REV:
            result = info(m.group("number"), m.group("rev"), METHOD_LEGACY)
            if result:
                return result
    return info(core, "", METHOD_NONE)


# ------------------------------------------------------------------------------ ordering
def _norm_rev(rev):
    """Revisions that mean the same compare equal: '02' == '2', '1.0' == '1', 'A0' == 'A', 'b' == 'B'.

    '' = no revision.  Numbers become dotted ints ('1.1'); letters stay letters (+ minor digit if non-zero).
    """
    rev = rev.strip().upper()
    if not rev:
        return ""
    if rev[0].isdigit():
        parts = [int(p) for p in re.split(r"[._\-]", rev)]
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()
        return ".".join(str(p) for p in parts)
    letters, digits = re.fullmatch(r"([A-Z]+)(\d*)", rev).groups()
    return letters + (str(int(digits)) if digits and int(digits) else "")


def _rank(norm):
    """Sort key within one kind of revision: numbers numerically (1 < 1.1 < 2), letters A < B < ... < Z < AA."""
    if norm[0].isdigit():
        return tuple(int(p) for p in norm.split("."))
    letters, digits = re.fullmatch(r"([A-Z]+)(\d*)", norm).groups()
    return (len(letters), letters, int(digits or 0))


def _kind(norm):
    return "number" if norm[0].isdigit() else "letter"


_CLASS_ORDER = {"": 0, "EAR99": 1, "EAR": 2, "ITAR": 3}


def _classification(info):
    """The strictest classification written in the name: ITAR > EAR > EAR99 > '' (no tag)."""
    return max((t for t in info.tags if t in _CLASS_ORDER), key=_CLASS_ORDER.get, default="")


def classification_in_name(filename, redline_re=_DEFAULT_REDLINE_RE):
    """The classification tag written in a file name: 'ITAR', 'EAR' (EAR99 counts as EAR) or '' (no tag)."""
    tags = _find_tags(_stem(filename), redline_re)
    strictest = max((t for t in tags if t in _CLASS_ORDER), key=_CLASS_ORDER.get, default="")
    return "EAR" if strictest == "EAR99" else strictest


def _natural(text):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


@dataclass
class RevisionReport:
    rows: list = field(default_factory=list)       # files to look at, grouped by drawing number
    stats: dict = field(default_factory=dict)
    redlines: list = field(default_factory=list)   # every redline on the server


REVISION_COLUMNS = ["Drawing Number", "Revision", "Status", "File Name", "Name Tags", "Folder",
                    "Last Modified", "Size (KB)", "Revisions On Server", "Export Control Group", "Notes",
                    "Name Read By", "Full Path"]
REDLINE_COLUMNS = ["Drawing Number", "Revision", "Redline File", "Name Tags", "Folder", "Last Modified",
                   "Size (KB)", "Redline Word", "Status", "Plain File(s) It Makes Out Of Date",
                   "Export Control Group", "Full Path"]


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
             "outdated_by_redline": 0, "old_redlines": 0, "tag_conflicts": 0,
             "redlines": sum(1 for f in files if f["redline"])}
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
                                _basename(rf["path"]) for rf in covering)
                            stats["outdated_by_redline"] += 1
                            for rf in covering:
                                outdates[rf["path"]].append(_basename(f["path"]))
                        else:
                            status = STATUS_NEWEST
                    status_of[f["path"]] = status
                if len(items) > 1:
                    stats["extra_copies"] += len(items) - 1
                    for f, _ in items:
                        prior = notes_of.get(f["path"])
                        notes_of[f["path"]] = (prior + "; " if prior else "") + f"{len(items)} copies of this file"
        classes = {_classification(info) for _, info in members}
        conflict = ""
        if len(classes) > 1:   # e.g. one copy tagged -ITAR in the ITAR library, another untagged elsewhere
            stats["tag_conflicts"] += 1
            conflict = "copies disagree on classification in the file name: " + " vs ".join(
                (c or "no tag") for c in sorted(classes, key=_CLASS_ORDER.get, reverse=True))
        for f, info in members:
            extra = [conflict] if conflict else []
            retired = [t for t in info.tags if t in RETIRED_TAGS]
            if retired:
                extra.append("already marked " + "/".join(retired))
            if extra:
                prior = notes_of.get(f["path"])
                notes_of[f["path"]] = "; ".join(([prior] if prior else []) + extra)
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
                ("Status", status_of[f["path"]]), ("File Name", _basename(f["path"])),
                ("Name Tags", ", ".join(info.tags)), ("Folder", _dirname(f["path"])),
                ("Last Modified", _when(f.get("mtime"))),
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
            ("Redline File", _basename(f["path"])), ("Name Tags", ", ".join(info.tags) if info else ""),
            ("Folder", _dirname(f["path"])),
            ("Last Modified", _when(f.get("mtime"))), ("Size (KB)", round(f.get("size", 0) / 1024, 1)),
            ("Redline Word", f["redline"]), ("Status", status),
            ("Plain File(s) It Makes Out Of Date", "; ".join(sorted(set(outdates.get(f["path"], []))))),
            ("Export Control Group", f.get("category", "")), ("Full Path", f["path"]),
        ]))
    return RevisionReport(rows, stats, redlines)

