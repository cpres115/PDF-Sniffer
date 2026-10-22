# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
import unittest

from pdf_sniffer import eccn


class EccnTests(unittest.TestCase):
    def first(self, text, fn=eccn.extract):
        found = fn(text)
        return (found[0].base, found[0].text, found[0].labeled) if found else None

    def test_valid_forms(self):
        self.assertEqual(self.first("ECCN: 9A610.x"), ("9A610", "9A610.x", True))
        self.assertEqual(self.first("EAR ECCN 3A001.a.2 foo"), ("3A001", "3A001.a.2", True))
        self.assertEqual(self.first("export 5D002"), ("5D002", "5D002", False))
        self.assertEqual(self.first("ECCN: EAR99"), ("EAR99", "EAR99", True))
        self.assertEqual(self.first("EAR99"), ("EAR99", "EAR99", False))
        self.assertEqual(self.first("9a610.X")[0], "9A610")

    def test_rejects_lookalikes(self):
        for text in ("part 12345 rev 9F610", "ABC9A6100", "9A61", "no code here", ""):
            self.assertIsNone(self.first(text), text)

    def test_groups_by_base_code(self):
        found = eccn.extract("9A610.x and 9A610.y.1 and 3A001")
        self.assertEqual(sorted(m.base for m in found), ["3A001", "9A610"])

    def test_ocr_repair(self):
        self.assertEqual(self.first("ECCN: 9A6lO.x", eccn.extract_ocr)[0], "9A610")
        self.assertEqual(self.first("ECCN 5D0O2", eccn.extract_ocr)[0], "5D002")


if __name__ == "__main__":
    unittest.main()
