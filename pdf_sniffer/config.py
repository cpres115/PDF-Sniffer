"""Tunable settings.  Defaults suit US-letter documents and ANSI/ISO engineering drawings."""
from dataclasses import asdict, dataclass, fields

SCANNER_VERSION = "1.1"


@dataclass
class ScanConfig:
    # Part of each page that is searched for the logo, as fractions of the *displayed* page
    # (x0, y0, x1, y1; y grows downward).  Default = the bottom 55% of the page, full width:
    # that covers a document footer and the lower-right corner above a drawing's title block.
    zone: tuple = (0.0, 0.45, 1.0, 1.0)
    full_page: bool = False        # ignore `zone` and search the whole page
    max_scan_dpi: int = 150        # resolution of the first (find-the-circle) pass
    pixel_budget: int = 10_000_000  # cap on pixels rendered per page for the first pass
    min_logo_in: float = 0.20      # smallest logo diameter considered (inches)
    max_logo_in: float = 2.50      # largest logo diameter considered (inches)
    use_ocr: bool = True
    max_pages: int = 0             # 0 = every page
    max_seconds_per_file: int = 300
    # Where to look for an ECCN: left / right / above / below the logo, in logo diameters.  The
    # evidence picture always covers this whole window plus the ECCN itself.
    eccn_window: tuple = (8.0, 8.0, 4.0, 4.0)
    # Pages containing one of these phrases have an explanatory table (e.g. "General Symbol Advisory" in
    # MWI files) that shows what the ITAR/EAR logos look like.  Logos inside that table are ignored.
    advisory_phrases: tuple = ("GENERAL SYMBOL ADVISORY",)
    footer_fraction: float = 0.20  # bottom band checked for stray 'ITAR'/'EAR' text when no logo is found
    evidence_dir: str = ""         # where to save crops of detected logos ('' = don't)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        out = {k: v for k, v in d.items() if k in names}
        for k in ("zone", "eccn_window", "advisory_phrases"):
            if k in out:
                out[k] = tuple(out[k])
        return cls(**out)
