"""Plain data containers shared by the scanner, classifier and reports."""
from dataclasses import asdict, dataclass, field, fields

# Category names (the groups requested)
NON_CONTROLLED = "Non-Controlled"
ITAR = "ITAR Controlled"
EAR_NO_ECCN = "EAR Controlled (No Provided ECCN)"
EAR_PREFIX = "EAR Controlled - ECCN "
NEEDS_REVIEW = "Needs Review"
UNREADABLE = "Unreadable"

STATUS_OK = "OK"
STATUS_REVIEW = "REVIEW"
STATUS_ERROR = "ERROR"


@dataclass
class LogoHit:
    """A red-circle logo found on one page."""
    page: int                    # 1-based
    label: str = ""              # 'ITAR', 'EAR' or '' when the logo could not be read
    method: str = ""             # text | ocr | shape | ocr+shape
    confidence: str = ""         # high | medium | low
    eccn: str = ""               # as written, e.g. '9A610.x'
    eccn_base: str = ""          # grouping key, e.g. '9A610'
    eccn_source: str = ""        # text | ocr | page-text
    eccn_labeled: bool = False   # was the ECCN preceded by the word 'ECCN'?
    center_pt: tuple = (0.0, 0.0)  # logo centre on the displayed page, in points
    diameter_pt: float = 0.0
    evidence: str = ""           # file name of the saved crop
    detail: str = ""             # why a suspect could not be resolved


@dataclass
class FileResult:
    path: str
    root: str = ""
    size: int = 0
    mtime: float = 0.0
    pages: int = 0
    pages_scanned: int = 0
    category: str = ""
    status: str = STATUS_OK
    hits: list = field(default_factory=list)      # list[LogoHit as dict]
    suspects: list = field(default_factory=list)  # list[LogoHit as dict]
    notes: list = field(default_factory=list)
    seconds: float = 0.0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})
