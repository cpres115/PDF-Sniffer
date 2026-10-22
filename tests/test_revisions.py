import os
import tempfile
import unittest

from pdf_sniffer import revisions, settings


class ParseNameTests(unittest.TestCase):
    CASES = {
        "12345-678_RevB.pdf": ("12345-678", "B"), "12345-678 Rev B.pdf": ("12345-678", "B"),
        "12345-678_REV_02.pdf": ("12345-678", "02"), "MWI-1042 Rev C.pdf": ("MWI-1042", "C"),
        "MWI-1042_RevC_2025-03-04.pdf": ("MWI-1042", "C"), "12345-678-B.pdf": ("12345-678", "B"),
        "12345_B.pdf": ("12345", "B"), "12345.B.pdf": ("12345", "B"), "12345-678_02.pdf": ("12345-678", "02"),
        "12345_B - Copy.pdf": ("12345", "B"), "12345_B (1).pdf": ("12345", "B"),
        "12345_B - Copy (2).pdf": ("12345", "B"), "12345REVB.pdf": ("12345", "B"),
        "A12345-REV-C.pdf": ("A12345", "C"), "12345 rev b.PDF": ("12345", "B"),
        "12345-678-AB.pdf": ("12345-678", "AB"), "12345_Revision_E.pdf": ("12345", "E"),
        # not drawing numbers with a revision
        "Review.pdf": None, "Procedure Review.pdf": None, "Doc123 Review.pdf": None, "12345 Revised.pdf": None,
        "12345.pdf": None, "Datasheet.pdf": None, "Revision-D 12345.pdf": None,
    }

    def test_default_recognition(self):
        for name, expected in self.CASES.items():
            info = revisions.parse_name(name)
            self.assertEqual((info.number, info.rev) if info else None, expected, name)

    def test_custom_pattern(self):
        pattern = revisions.compile_pattern(r"^(?P<number>\d{5}-\d{3})_(?P<rev>[A-Z])$")
        self.assertEqual(revisions.parse_name("12345-678_B.pdf", pattern).rev, "B")
        self.assertIsNone(revisions.parse_name("12345-678-B.pdf", pattern))

    def test_bad_patterns_are_rejected(self):
        for bad in ("(", r"^(\d+)_([A-Z])$"):
            with self.assertRaises(ValueError):
                revisions.compile_pattern(bad)


def item(path, mtime=1.0, category=""):
    return {"path": path, "size": 2048, "mtime": mtime, "category": category}


class AnalyzeTests(unittest.TestCase):
    def status(self, rows):
        return {r["File Name"]: r["Status"] for r in rows}

    def test_older_revisions_are_reported(self):
        rows, stats = revisions.analyze([
            item("/srv/12345-678_RevA.pdf"), item("/srv/12345-678_RevB.pdf"), item("/srv/12345-678_RevC.pdf"),
            item("/srv/99999_A.pdf"), item("/srv/readme.pdf")])
        self.assertEqual(self.status(rows), {
            "12345-678_RevA.pdf": revisions.STATUS_OLDER, "12345-678_RevB.pdf": revisions.STATUS_OLDER,
            "12345-678_RevC.pdf": revisions.STATUS_NEWEST})
        self.assertEqual((stats["multi_revision"], stats["older"], stats["unparsed"]), (1, 2, 1))
        self.assertEqual(rows[0]["Revision"], "C")  # newest listed first
        self.assertEqual(rows[0]["Revisions On Server"], "A, B, C")

    def test_ordering_rules(self):
        rows, _ = revisions.analyze([item("/a/30002_REV_9.pdf"), item("/a/30002_REV_10.pdf"),
                                     item("/a/50004_Z.pdf"), item("/a/50004_AA.pdf")])
        s = self.status(rows)
        self.assertEqual(s["30002_REV_10.pdf"], revisions.STATUS_NEWEST)   # numbers compare numerically
        self.assertEqual(s["50004_AA.pdf"], revisions.STATUS_NEWEST)       # Z < AA

    def test_same_drawing_in_different_folders_and_punctuation(self):
        rows, _ = revisions.analyze([item("/Released/12345-678_RevA.pdf"), item("/Archive/12345_678 Rev B.pdf")])
        self.assertEqual(len(rows), 2)

    def test_copies_and_mixed_revisions(self):
        rows, stats = revisions.analyze([item("/a/20001_A.pdf"), item("/a/20001_A - Copy.pdf"),
                                         item("/a/40003_A.pdf"), item("/a/40003_01.pdf"),
                                         item("/a/10_A.pdf"), item("/a/10_B.pdf"), item("/b/10_B (1).pdf")])
        s = self.status(rows)
        self.assertEqual(s["20001_A - Copy.pdf"], revisions.STATUS_COPY)
        self.assertEqual(s["40003_A.pdf"], revisions.STATUS_UNORDERED)
        self.assertEqual(s["10_B (1).pdf"], revisions.STATUS_NEWEST)
        self.assertEqual((stats["unordered"], stats["extra_copies"]), (1, 2))

    def test_single_files_and_leading_zeros(self):
        rows, _ = revisions.analyze([item("/a/60005_B.pdf")])
        self.assertEqual(rows, [])
        rows, _ = revisions.analyze([item("/a/70_02.pdf"), item("/b/70_2.pdf")])
        self.assertEqual({r["Status"] for r in rows}, {revisions.STATUS_COPY})  # 02 == 2

    def test_results_are_annotated_with_number_and_revision(self):
        files = [item("/a/12345-678_RevB.pdf")]
        revisions.analyze(files)
        self.assertEqual((files[0]["drawing_number"], files[0]["revision"]), ("12345-678", "B"))


class SettingsTests(unittest.TestCase):
    def write(self, text):
        fd, path = tempfile.mkstemp(suffix=".ini")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_defaults_when_missing_or_commented_out(self):
        self.assertEqual(settings.load("/no/such/file.ini"), {"name_pattern": "", "advisory_phrases": None})
        path = self.write("[revisions]\n# name_pattern = x\n[advisory]\n# phrases = Y\n")
        self.assertEqual(settings.load(path), {"name_pattern": "", "advisory_phrases": None})

    def test_values(self):
        path = self.write("[revisions]\nname_pattern = ^(?P<number>\\d+)%(?P<rev>[A-Z])$\n"
                          "[advisory]\nphrases = GENERAL ADVISORY; Export Notice\n")
        got = settings.load(path)
        self.assertEqual(got["name_pattern"], "^(?P<number>\\d+)%(?P<rev>[A-Z])$")
        self.assertEqual(got["advisory_phrases"], ("GENERAL ADVISORY", "Export Notice"))

    def test_empty_phrases_turns_the_filter_off(self):
        self.assertEqual(settings.load(self.write("[advisory]\nphrases =\n"))["advisory_phrases"], ())


if __name__ == "__main__":
    unittest.main()
