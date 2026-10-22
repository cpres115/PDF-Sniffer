"""Optional user settings from settings.ini in the program folder."""
import configparser
import os

from . import paths

DEFAULT_ADVISORY_PHRASES = ("GENERAL ADVISORY",)
SETTINGS_FILE = paths.APP_ROOT / "settings.ini"


def load(path=None):
    """-> {'name_pattern': str, 'advisory_phrases': tuple or None (None = use the default)}."""
    path = str(path or SETTINGS_FILE)
    out = {"name_pattern": "", "advisory_phrases": None}
    if not os.path.isfile(path):
        return out
    cp = configparser.ConfigParser(interpolation=None, delimiters=("=",), inline_comment_prefixes=None)
    cp.read(path, encoding="utf-8-sig")
    if cp.has_option("revisions", "name_pattern"):
        out["name_pattern"] = cp.get("revisions", "name_pattern").strip()
    if cp.has_option("advisory", "phrases"):
        out["advisory_phrases"] = tuple(p.strip() for p in cp.get("advisory", "phrases").split(";") if p.strip())
    return out
