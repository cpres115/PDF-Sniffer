"""Turn the logos found in a file into one of the report categories."""
from .models import (EAR_NO_ECCN, EAR_PREFIX, ITAR, NEEDS_REVIEW, NON_CONTROLLED, STATUS_ERROR,
                     STATUS_OK, STATUS_REVIEW, UNREADABLE)


def category_for(hits, suspects, error=""):
    """Return (category, status, notes) from LogoHit dicts."""
    notes = []
    if error:
        return UNREADABLE, STATUS_ERROR, [error]

    itar = [h for h in hits if h["label"] == "ITAR"]
    ear = [h for h in hits if h["label"] == "EAR"]
    review = bool(suspects)
    if suspects:
        pages = sorted({s["page"] for s in suspects})
        notes.append("Unconfirmed red ring on page(s) " + ", ".join(map(str, pages)) + ": "
                     + "; ".join(sorted({s["detail"] for s in suspects if s["detail"]})))

    if itar:
        category = ITAR
        if ear:
            review = True
            notes.append("Also carries an EAR logo; classified as ITAR (the stricter regime).")
    elif ear:
        eccns = sorted({h["eccn_base"] for h in ear if h["eccn_base"]})
        category = EAR_PREFIX + " + ".join(eccns) if eccns else EAR_NO_ECCN
        if len(eccns) > 1:
            review = True
            notes.append("Multiple different ECCNs found: " + ", ".join(eccns))
        if any(h["eccn_base"] and not h["eccn_labeled"] for h in ear) and not any(
                h["eccn_labeled"] for h in ear):
            notes.append("ECCN was not preceded by the word 'ECCN' - verify.")
    elif suspects:
        category = NEEDS_REVIEW
    else:
        category = NON_CONTROLLED

    if any(h["confidence"] == "medium" for h in hits):
        notes.append("Logo text confirmed by OCR only - verify against the evidence image.")
    return category, (STATUS_REVIEW if review else STATUS_OK), notes
