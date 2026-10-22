import os
import tempfile
import unittest

from pdf_sniffer import revisions, runner, settings
from pdf_sniffer.revisions import (STATUS_COPY, STATUS_NEWEST, STATUS_OLDER, STATUS_OUTDATED,
                                   STATUS_REDLINE_CURRENT, STATUS_REDLINE_OLD, STATUS_UNORDERED)


def read(name, **kw):
    info = revisions.parse_name(name, **kw)
    return (info.number, info.rev, bool(info.redline)) if info else None


class ParseNameTests(unittest.TestCase):
    def test_names_from_the_real_library(self):
        self.assertEqual(read("A10-000-5660_B-EAR.pdf"), ("A10-000-5660", "B", False))
        self.assertEqual(read("A10-000-5660_C-EAR.pdf"), ("A10-000-5660", "C", False))
        self.assertEqual(read("DOC-000-746_B-EAR.pdf"), ("DOC-000-746", "B", False))
        self.assertEqual(read("DOC-000-746_C-EAR.pdf"), ("DOC-000-746", "C", False))
        self.assertEqual(read("TST-010-600_A Redline.pdf"), ("TST-010-600", "A", True))
        self.assertEqual(read("TST-010-600.pdf"), ("TST-010-600", "", False))

    def test_other_classification_suffixes(self):
        for name in ("TST-010-600_A-ITAR.pdf", "TST-010-600_A-EAR99.pdf", "TST-010-600_A-EAR-9A610.x.pdf",
                     "TST-010-600_A.pdf", "tst-010-600_a-ear.PDF", "TST-010-600_A - Copy.pdf", "TST-010-600_A (1).pdf"):
            self.assertEqual(read(name), ("TST-010-600" if name[0] == "T" else "tst-010-600", "A", False), name)
        self.assertEqual(read("TST-010-600-EAR.pdf"), ("TST-010-600", "", False))

    def test_redline_variants(self):
        for name in ("TST-010-600_A Redline.pdf", "TST-010-600_A REDLINE.pdf", "TST-010-600_A_redline.pdf",
                     "TST-010-600_A Red Line.pdf", "TST-010-600_A-Red-Line.pdf", "TST-010-600_A Redlined.pdf",
                     "TST-010-600_A Redline 2.pdf", "TST-010-600_A-EAR Redline.pdf", "TST-010-600_A Markup.pdf",
                     "TST-010-600_A Mark-Up.pdf", "TST-010-600_A_RL.pdf", "TST-010-600_A (REDLINE).pdf"):
            self.assertEqual(read(name), ("TST-010-600", "A", True), name)
        self.assertEqual(read("TST-010-600_Redline.pdf"), ("TST-010-600", "", True))
        for name in ("TST-010-600_A.pdf", "TST-010-600_ARL.pdf", "Sherlock-123_A.pdf", "TST-010-600_A-EAR.pdf"):
            self.assertEqual(revisions.find_redline(name), "", name)

    def test_custom_redline_words(self):
        only = revisions.compile_redline_words(("rev-marked",))
        self.assertEqual(revisions.find_redline("X-1_A rev marked.pdf", only), "rev marked")
        self.assertEqual(revisions.find_redline("X-1_A Redline.pdf", only), "")

    def test_revision_keyword_forms(self):
        cases = {"12345-678 Rev B.pdf": ("12345-678", "B"), "12345-678_REV_02.pdf": ("12345-678", "02"),
                 "MWI-1042_RevC_2025-03-04.pdf": ("MWI-1042", "C"), "12345REVB.pdf": ("12345", "B"),
                 "12345_Revision_E.pdf": ("12345", "E"), "12345 rev b.PDF": ("12345", "B")}
        for name, (number, rev) in cases.items():
            self.assertEqual(read(name), (number, rev, False), name)

    def test_names_that_are_not_drawings(self):
        for name in ("Review.pdf", "Datasheet.pdf", "Procedure Review.pdf", "readme.pdf"):
            self.assertIsNone(read(name), name)
        self.assertEqual(read("Doc123 Review.pdf"), ("Doc123 Review", "", False))  # no revision, but has a number

    def test_custom_pattern(self):
        pattern = revisions.compile_pattern(r"^(?P<number>\d{5}-\d{3})_(?P<rev>[A-Z])$")
        self.assertEqual(read("12345-678_B-EAR.pdf", pattern=pattern), ("12345-678", "B", False))
        self.assertIsNone(read("12345-678-B.pdf", pattern=pattern))

    def test_bad_patterns_are_rejected(self):
        for bad in ("(", r"^(\d+)_([A-Z])$"):
            with self.assertRaises(ValueError):
                revisions.compile_pattern(bad)


def item(path, mtime=1.0, category=""):
    return {"path": path, "size": 2048, "mtime": mtime, "category": category}


def statuses(report):
    return {r["File Name"]: r["Status"] for r in report.rows}


class AnalyzeTests(unittest.TestCase):
    def test_duplicates_from_the_real_library(self):
        rep = revisions.analyze([item("/lib/" + n) for n in (
            "A10-000-5660_B-EAR.pdf", "A10-000-5660_C-EAR.pdf", "DOC-000-746_B-EAR.pdf", "DOC-000-746_C-EAR.pdf",
            "TST-010-600_A Redline.pdf", "TST-010-600.pdf", "UNIQ-001-100_A-EAR.pdf")])
        self.assertEqual(statuses(rep), {
            "A10-000-5660_B-EAR.pdf": STATUS_OLDER, "A10-000-5660_C-EAR.pdf": STATUS_NEWEST,
            "DOC-000-746_B-EAR.pdf": STATUS_OLDER, "DOC-000-746_C-EAR.pdf": STATUS_NEWEST,
            "TST-010-600_A Redline.pdf": STATUS_REDLINE_CURRENT, "TST-010-600.pdf": STATUS_OUTDATED})
        self.assertEqual((rep.stats["older"], rep.stats["outdated_by_redline"], rep.stats["redlines"]), (2, 1, 1))
        self.assertEqual([r["Redline File"] for r in rep.redlines], ["TST-010-600_A Redline.pdf"])
        self.assertEqual(rep.redlines[0]["Plain File(s) It Makes Out Of Date"], "TST-010-600.pdf")

    def one_drawing(self, *names):
        return statuses(revisions.analyze([item("/lib/" + n) for n in names]))

    def test_redline_scenarios(self):
        self.assertEqual(self.one_drawing("X-1_A.pdf", "X-1_A REDLINE.pdf"),
                         {"X-1_A.pdf": STATUS_OUTDATED, "X-1_A REDLINE.pdf": STATUS_REDLINE_CURRENT})
        self.assertEqual(self.one_drawing("X-2_B.pdf", "X-2_C Redline.pdf"),
                         {"X-2_B.pdf": STATUS_OUTDATED, "X-2_C Redline.pdf": STATUS_REDLINE_CURRENT})
        self.assertEqual(self.one_drawing("X-3_B.pdf", "X-3_A Redline.pdf"),
                         {"X-3_B.pdf": STATUS_NEWEST, "X-3_A Redline.pdf": STATUS_REDLINE_OLD})
        self.assertEqual(self.one_drawing("X-4_A.pdf", "X-4_B.pdf", "X-4_B Redline.pdf"),
                         {"X-4_A.pdf": STATUS_OLDER, "X-4_B.pdf": STATUS_OUTDATED,
                          "X-4_B Redline.pdf": STATUS_REDLINE_CURRENT})
        self.assertEqual(self.one_drawing("X-5_A Redline.pdf", "X-5_B Redline.pdf"),
                         {"X-5_A Redline.pdf": STATUS_REDLINE_OLD, "X-5_B Redline.pdf": STATUS_REDLINE_CURRENT})
        self.assertEqual(self.one_drawing("X-7.pdf", "X-7 Redline.pdf"),
                         {"X-7.pdf": STATUS_OUTDATED, "X-7 Redline.pdf": STATUS_REDLINE_CURRENT})

    def test_every_redline_is_listed_even_when_alone_or_unrecognised(self):
        rep = revisions.analyze([item("/lib/X-6_A Redline.pdf"), item("/lib/Redline notes.pdf"),
                                 item("/lib/Y-1_B-ITAR.pdf", category="ITAR Controlled")])
        self.assertEqual(rep.rows, [])
        self.assertEqual(rep.stats["redlines"], 2)
        self.assertEqual({r["Redline File"]: r["Status"] for r in rep.redlines},
                         {"X-6_A Redline.pdf": "Only file of this drawing on the server",
                          "Redline notes.pdf": "Drawing number not recognised"})

    def test_older_revisions_and_ordering(self):
        rep = revisions.analyze([item("/srv/12345-678_RevA.pdf"), item("/srv/12345-678_B.pdf"),
                                 item("/srv/12345-678_C-EAR.pdf"), item("/srv/99999_A.pdf"), item("/srv/readme.pdf")])
        self.assertEqual(sum(1 for r in rep.rows if r["Status"] == STATUS_OLDER), 2)
        self.assertEqual((rep.rows[0]["Revision"], rep.rows[0]["Revisions On Server"]), ("C", "A, B, C"))
        self.assertEqual(self.one_drawing("30002_REV_9.pdf", "30002_REV_10.pdf")["30002_REV_10.pdf"], STATUS_NEWEST)
        self.assertEqual(self.one_drawing("50004_Z.pdf", "50004_AA.pdf")["50004_AA.pdf"], STATUS_NEWEST)

    def test_same_drawing_in_different_folders_and_punctuation(self):
        rep = revisions.analyze([item("/Released/12345-678_A.pdf"), item("/Archive/12345_678 Rev B.pdf")])
        self.assertEqual(len(rep.rows), 2)

    def test_copies_and_mixed_revisions(self):
        rep = revisions.analyze([item("/a/20001_A.pdf"), item("/a/20001_A - Copy.pdf"),
                                 item("/a/40003_A.pdf"), item("/a/40003_01.pdf"),
                                 item("/a/10_A.pdf"), item("/a/10_B.pdf"), item("/b/10_B (1).pdf")])
        s = statuses(rep)
        self.assertEqual(s["20001_A - Copy.pdf"], STATUS_COPY)
        self.assertEqual(s["40003_A.pdf"], STATUS_UNORDERED)
        self.assertEqual(s["10_B (1).pdf"], STATUS_NEWEST)
        self.assertEqual((rep.stats["unordered"], rep.stats["extra_copies"]), (1, 2))

    def test_single_files_and_leading_zeros(self):
        self.assertEqual(revisions.analyze([item("/a/60005_B.pdf")]).rows, [])
        rep = revisions.analyze([item("/a/70_02.pdf"), item("/b/70_2.pdf")])
        self.assertEqual({r["Status"] for r in rep.rows}, {STATUS_COPY})  # 02 == 2

    def test_results_are_annotated(self):
        files = [item("/a/A10-000-5660_B-EAR.pdf"), item("/a/TST-010-600_A Redline.pdf")]
        revisions.analyze(files)
        self.assertEqual([(f["drawing_number"], f["revision"], f["redline"]) for f in files],
                         [("A10-000-5660", "B", ""), ("TST-010-600", "A", "Redline")])


class DiscoverTests(unittest.TestCase):
    def test_skipped_folders(self):
        with tempfile.TemporaryDirectory() as root:
            tree = ["Released/A-1_A.pdf", "Released/- Engineering Release/B-1_A.pdf",
                    "Released/- Engineering Release/Deep/C-1_A.pdf", "Other/- engineering  release/D-1_A.pdf",
                    "Other/Engineering Release/E-1_A.pdf", "Other/Release - Engineering/F-1_A.pdf",
                    "Other/notes.txt"]
            for rel in tree:
                path = os.path.join(root, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "wb").close()
            files, ignored, skipped = runner.discover([root], skip_folders=("- Engineering Release",))
            self.assertEqual(sorted(os.path.basename(p) for _, p in files), ["A-1_A.pdf", "E-1_A.pdf", "F-1_A.pdf"])
            self.assertEqual(len(skipped), 2)           # the folder is matched at any depth, ignoring case/spacing
            self.assertEqual(sum(ignored.values()), 1)
            # off by default when no names are given
            self.assertEqual(len(runner.discover([root])[0]), 6)
            # also skipped when it is one of the folders given, and with --no-subfolders
            given = os.path.join(root, "Released", "- Engineering Release")
            files, _, skipped = runner.discover([given], skip_folders=("- Engineering Release",))
            self.assertEqual((files, skipped), ([], [given]))
            files, _, _ = runner.discover([os.path.join(root, "Released")], recursive=False,
                                          skip_folders=("- Engineering Release",))
            self.assertEqual([os.path.basename(p) for _, p in files], ["A-1_A.pdf"])


class SettingsTests(unittest.TestCase):
    def write(self, text):
        fd, path = tempfile.mkstemp(suffix=".ini")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_defaults_when_missing_or_commented_out(self):
        unset = {"name_pattern": "", "advisory_phrases": None, "skip_folders": None, "redline_words": None}
        self.assertEqual(settings.load("/no/such/file.ini"), unset)
        path = self.write("[revisions]\n# name_pattern = x\n# redline_words = y\n[advisory]\n# phrases = Y\n"
                          "[folders]\n# skip = Z\n")
        self.assertEqual(settings.load(path), unset)

    def test_values(self):
        path = self.write("[revisions]\nname_pattern = ^(?P<number>\\d+)%(?P<rev>[A-Z])$\nredline_words = redline; rev marked\n"
                          "[advisory]\nphrases = GENERAL ADVISORY; Export Notice\n[folders]\nskip = - Engineering Release; Old\n")
        got = settings.load(path)
        self.assertEqual(got["name_pattern"], "^(?P<number>\\d+)%(?P<rev>[A-Z])$")
        self.assertEqual(got["redline_words"], ("redline", "rev marked"))
        self.assertEqual(got["advisory_phrases"], ("GENERAL ADVISORY", "Export Notice"))
        self.assertEqual(got["skip_folders"], ("- Engineering Release", "Old"))

    def test_empty_values_turn_things_off(self):
        got = settings.load(self.write("[advisory]\nphrases =\n[folders]\nskip =\n"))
        self.assertEqual((got["advisory_phrases"], got["skip_folders"]), ((), ()))


if __name__ == "__main__":
    unittest.main()
