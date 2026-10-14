"""ECCN (Export Control Classification Number) parsing.

An ECCN is <digit 0-9><letter A-E><3 digits>, e.g. 9A610, optionally followed by a
paragraph reference such as ".x", ".a.2" or ".y.1".  "EAR99" is the catch-all
designation for items subject to the EAR but not on the Commerce Control List; it is
reported as its own ECCN type.
"""
import re
from dataclasses import dataclass

_CODE = r"[0-9][A-E][0-9]{3}"
_SUFFIX = r"(?:\.[A-Za-z0-9]{1,3}){0,3}"
_EDGE_L = r"(?<![A-Za-z0-9])"
_EDGE_R = r"(?![A-Za-z0-9])"

ECCN_RE = re.compile(_EDGE_L + r"(" + _CODE + _SUFFIX + r")" + _EDGE_R, re.IGNORECASE)
EAR99_RE = re.compile(_EDGE_L + r"EAR\s?99" + _EDGE_R, re.IGNORECASE)
LABELED_RE = re.compile(
    r"ECCN\W{0,3}\s*(" + _CODE + _SUFFIX + r"|EAR\s?99)" + _EDGE_R, re.IGNORECASE)
ECCN_WORD_RE = re.compile(r"\bECCN\b", re.IGNORECASE)

# Characters OCR commonly confuses with digits.
_TO_DIGIT = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "S": "5",
                           "B": "8", "Z": "2", "G": "6"})


@dataclass
class EccnMatch:
    text: str      # as written, e.g. "9A610.x"
    base: str      # grouping key, e.g. "9A610" or "EAR99"
    labeled: bool  # was it preceded by the word "ECCN"?


def _base(code):
    code = re.sub(r"\s", "", code).upper()
    return "EAR99" if code.startswith("EAR") else code[:5]


def _clean(code):
    code = re.sub(r"\s", "", code)
    return "EAR99" if code.upper().startswith("EAR") else code[:5].upper() + code[5:].lower()


def extract(text):
    """Return the ECCNs found in `text`, labelled ones first, de-duplicated."""
    found = {}
    for m in LABELED_RE.finditer(text):
        found.setdefault(_base(m.group(1)), EccnMatch(_clean(m.group(1)), _base(m.group(1)), True))
    for m in ECCN_RE.finditer(text):
        found.setdefault(_base(m.group(1)), EccnMatch(_clean(m.group(1)), _base(m.group(1)), False))
    for m in EAR99_RE.finditer(text):
        found.setdefault("EAR99", EccnMatch("EAR99", "EAR99", bool(ECCN_WORD_RE.search(text))))
    return sorted(found.values(), key=lambda e: (not e.labeled, e.base))


def extract_ocr(text):
    """Like extract(), but also repairs typical OCR digit/letter confusions."""
    found = extract(text)
    if found:
        return found
    for tok in re.findall(r"[A-Za-z0-9]{5}(?:\.[A-Za-z0-9]{1,3}){0,3}", text):
        head = tok[:5].upper()
        fixed = head[0].translate(_TO_DIGIT) + head[1] + head[2:].translate(_TO_DIGIT)
        if re.fullmatch(_CODE, fixed):
            labeled = bool(re.search(r"ECCN\W{0,3}\s*" + re.escape(tok), text, re.IGNORECASE))
            return [EccnMatch(fixed + tok[5:].lower(), fixed, labeled)]
    return []
