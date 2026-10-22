"""Optional user settings from settings.ini in the program folder."""
import configparser
import os

from . import paths

DEFAULT_ADVISORY_PHRASES = ("GENERAL SYMBOL ADVISORY",)
DEFAULT_SKIP_FOLDERS = ("- Engineering Release",)
SETTINGS_FILE = paths.APP_ROOT / "settings.ini"


def _split(value):
    return tuple(p.strip() for p in value.split(";") if p.strip())


def load(path=None):
    """Settings from settings.ini.  A value of None means "not set: use the built-in default"."""
    path = str(path or SETTINGS_FILE)
    out = {"name_pattern": "", "advisory_phrases": None, "skip_folders": None, "redline_words": None}
    if not os.path.isfile(path):
        return out
    cp = configparser.ConfigParser(interpolation=None, delimiters=("=",), inline_comment_prefixes=None)
    cp.read(path, encoding="utf-8-sig")
    if cp.has_option("revisions", "name_pattern"):
        out["name_pattern"] = cp.get("revisions", "name_pattern").strip()
    if cp.has_option("revisions", "redline_words"):
        out["redline_words"] = _split(cp.get("revisions", "redline_words"))
    if cp.has_option("advisory", "phrases"):
        out["advisory_phrases"] = _split(cp.get("advisory", "phrases"))
    if cp.has_option("folders", "skip"):
        out["skip_folders"] = _split(cp.get("folders", "skip"))
    return out
