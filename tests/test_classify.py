# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
import unittest

from pdf_sniffer import models
from pdf_sniffer.classify import category_for


def hit(label, eccn="", labeled=True, conf="high", page=1):
    return {"label": label, "eccn": eccn, "eccn_base": eccn[:5], "eccn_labeled": labeled,
            "confidence": conf, "page": page, "detail": ""}


class ClassifyTests(unittest.TestCase):
    def test_categories(self):
        cases = [
            (([], []), models.NON_CONTROLLED, "OK"),
            (([hit("ITAR")], []), models.ITAR, "OK"),
            (([hit("EAR")], []), models.EAR_NO_ECCN, "OK"),
            (([hit("EAR", "9A610.x")], []), models.EAR_PREFIX + "9A610", "OK"),
            (([hit("EAR", "9A610.x"), hit("EAR", "9A610.y", page=2)], []), models.EAR_PREFIX + "9A610", "OK"),
            (([hit("EAR", "9A610"), hit("EAR", "3A001", page=2)], []), models.EAR_PREFIX + "3A001 + 9A610", "REVIEW"),
            (([hit("EAR", "9A610"), hit("EAR", page=2)], []), models.EAR_PREFIX + "9A610", "OK"),
            (([hit("ITAR"), hit("EAR", "9A610", page=2)], []), models.ITAR, "REVIEW"),
            (([], [{"page": 2, "detail": "x"}]), models.NEEDS_REVIEW, "REVIEW"),
            (([hit("ITAR")], [{"page": 2, "detail": "x"}]), models.ITAR, "REVIEW"),
        ]
        for (hits, suspects), cat, status in cases:
            got = category_for(hits, suspects)
            self.assertEqual((got[0], got[1]), (cat, status), (hits, suspects))

    def test_error(self):
        cat, status, notes = category_for([], [], error="password protected")
        self.assertEqual((cat, status), (models.UNREADABLE, "ERROR"))


if __name__ == "__main__":
    unittest.main()
