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
    def test_names_from_the_first_examples(self):
        self.assertEqual(read("A10-000-5660_B-EAR.pdf"), ("A10-000-5660", "B", False))
        self.assertEqual(read("DOC-000-746_C-EAR.pdf"), ("DOC-000-746", "C", False))
        self.assertEqual(read("TST-010-600_A Redline.pdf"), ("TST-010-600", "A", True))
        self.assertEqual(read("TST-010-600.pdf"), ("TST-010-600", "", False))

    # Synthetic names (invented numbers) that mimic every shape found in the ~6,100 real library names.
    LIBRARY_SHAPES = {
        # main form: number_revision, optional classification / tags
        "ASM-000-007_B.pdf": ("ASM-000-007", "B", False),
        "A10-000-009_G.pdf": ("A10-000-009", "G", False),
        "ASM-000-002-X_A.pdf": ("ASM-000-002-X", "A", False),
        "A10-000-8780-11_D.pdf": ("A10-000-8780-11", "D", False),
        "A10-000-7215-MOD_A Redline.pdf": ("A10-000-7215-MOD", "A", True),
        "MWI-A10-8875-10_B-EAR.pdf": ("MWI-A10-8875-10", "B", False),
        "FLX-02A-057-2_B.pdf": ("FLX-02A-057-2", "B", False),
        "T01-017-005-874_A.pdf": ("T01-017-005-874", "A", False),
        "ZU-S 708 Z054-007_B.pdf": ("ZU-S 708 Z054-007", "B", False),
        "E1 701.729DD_A.pdf": ("E1 701.729DD", "A", False),
        "T01-000-771-XXXL_M.pdf": ("T01-000-771-XXXL", "M", False),
        "fischer_pcb-000-079_a.pdf": ("fischer_pcb-000-079", "A", False),
        # revision shapes: numbers, dotted numbers, letter+digit, two letters
        "A10-000-7052_1.pdf": ("A10-000-7052", "1", False),
        "A10-000-5936_2.0.pdf": ("A10-000-5936", "2.0", False),
        "A10-000-1143_1.1.pdf": ("A10-000-1143", "1.1", False),
        "A10-000-5034 K-S_1_0.pdf": ("A10-000-5034 K-S", "1_0", False),
        "A10-000-7797_1-0 Redline.pdf": ("A10-000-7797", "1-0", True),
        "CBL-000-911_A0.pdf": ("CBL-000-911", "A0", False),
        "A10-000-9256_A1-EAR.pdf": ("A10-000-9256", "A1", False),
        "A10-000-7647-X_AB-EAR.pdf": ("A10-000-7647-X", "AB", False),
        "A10-000-9815 K-S_1.0.pdf": ("A10-000-9815 K-S", "1.0", False),
        # underscores inside the drawing number: the revision is the last short token
        "A10-000-809_X_A_ITAR Blocked.pdf": ("A10-000-809_X", "A", False),
        "T01-U08-008_X_1.pdf": ("T01-U08-008_X", "1", False),
        "T01-000-732_L_A.pdf": ("T01-000-732_L", "A", False),
        "T01-000-979_755-740-L_A.pdf": ("T01-000-979_755-740-L", "A", False),
        "T01-000-979_870-870_U & L_A.pdf": ("T01-000-979_870-870_U & L", "A", False),
        "T01-000-915__A.PDF": ("T01-000-915", "A", False),
        "DOC-000-534 _A.pdf": ("DOC-000-534", "A", False),
        # classification before the revision, tags and initials after it
        "A10-000-5410-X-EAR_B.pdf": ("A10-000-5410-X", "B", False),
        "A10-000-7099_1_In Change QRS.pdf": ("A10-000-7099", "1", False),
        "A10-000-7084_A-ITAR_ In Change_ QRS1.pdf": ("A10-000-7084", "A", False),
        "A10-000-168_B_In Change _ QTS.pdf": ("A10-000-168", "B", False),
        "A10-000-7852_A-ITAR Blocked QAC.pdf": ("A10-000-7852", "A", False),
        "A10-000-561-X_A_Removed.pdf": ("A10-000-561-X", "A", False),
        "ASM-000-068-X_B(OBSOLETE).pdf": ("ASM-000-068-X", "B", False),
        "A10-000-7079_A_Obsolete.pdf": ("A10-000-7079", "A", False),
        "DOC-000-961_A in ECO process.pdf": ("DOC-000-961", "A", False),
        "A10-000-8820_1 -ITAR PRELIM.pdf": ("A10-000-8820", "1", False),
        "S10-700-817-X_A-Deviation.pdf": ("S10-700-817-X", "A", False),
        "A10-000-8830_E_(786528).pdf": ("A10-000-8830", "E", False),
        "CHM-000-773_A_Internal Use Only.pdf": ("CHM-000-773", "A", False),
        "A10-000-1826_B-X.PDF": ("A10-000-1826", "B", False),
        "A10-000-1173_A..pdf": ("A10-000-1173", "A", False),
        "CBL-000-060_B .PDF": ("CBL-000-060", "B", False),
        "A10-000-5170-X_1.0 EAR .pdf": ("A10-000-5170-X", "1.0", False),
        "A10-000-5935_A REDLINE - BLOCKED - QJ 7-12-23.pdf": ("A10-000-5935", "A", True),
        "A10-000-9760_A K-S REDLINE.pdf": ("A10-000-9760", "A", True),
        "MWI-A10-5585-X_6-EAR_REDLINE.pdf": ("MWI-A10-5585-X", "6", True),
        "DOC-000-528_B_Redline.pdf": ("DOC-000-528", "B", True),
        "A10-000-7865_1_redline.pdf": ("A10-000-7865", "1", True),
        # older styles without an underscore
        "T01-000-863 A.pdf": ("T01-000-863", "A", False),
        "A10-000-481-B.pdf": ("A10-000-481", "B", False),
        "HDW-000-087-X-B.pdf": ("HDW-000-087-X", "B", False),
        "HDC-000-704-B-ITAR.pdf": ("HDC-000-704", "B", False),
        "A10-000-9722 K-S 1.0 redline.pdf": ("A10-000-9722 K-S", "1.0", True),
        "C70854 R6.pdf": ("C70854", "R6", False),
        "103213-Rev1.pdf": ("103213", "1", False),
        "105388-RevNA.pdf": ("105388", "", False),
        # no revision at all
        "CHM-000-074.pdf": ("CHM-000-074", "", False),
        "A10-000-7040-X.pdf": ("A10-000-7040-X", "", False),
        "MWI-A10-5229-EAR.pdf": ("MWI-A10-5229", "", False),
        "DOC-000-110 PRELIM.pdf": ("DOC-000-110", "", False),
        "DOC-000-186-prelim.pdf": ("DOC-000-186", "", False),
        "CHM-000-053.Internal Use Only.pdf": ("CHM-000-053", "", False),
        "A30-000-002_HAND DRAWN.pdf": ("A30-000-002", "", False),
        "SDW-A15-077 (upon request).pdf": ("SDW-A15-077", "", False),
        "Ex_VA-000-007.pdf": ("Ex_VA-000-007", "", False),
        "T01-708-002-1.pdf": ("T01-708-002-1", "", False),
        "DOC-000-914_A YELLOW.pdf": ("DOC-000-914", "A", False),   # colours are not redlines
        "DOC-000-913_A RED.pdf": ("DOC-000-913", "A", False),
    }

    def test_every_library_shape(self):
        for name, expected in self.LIBRARY_SHAPES.items():
            got = read(name)
            self.assertEqual(got and (got[0], revisions._norm_rev(got[1]), got[2]),
                             (expected[0], revisions._norm_rev(expected[1]), expected[2]), name)

    def test_status_words_are_tags_not_revisions(self):
        tags = {n: set(revisions.parse_name(n).tags) for n in (
            "A10-000-7099_1_In Change QRS.pdf", "A10-000-7056_1 Blocked.pdf", "A10-000-561-X_A_Removed.pdf",
            "ASM-000-068-X_B(OBSOLETE).pdf", "A10-000-8820_1 -ITAR PRELIM.pdf", "A10-000-9256_A1-EAR.pdf",
            "A10-000-5935_A REDLINE - BLOCKED - QJ 7-12-23.pdf", "A10-000-7076-X_D.pdf")}
        self.assertEqual(tags["A10-000-7099_1_In Change QRS.pdf"], {"In Change"})
        self.assertEqual(tags["A10-000-7056_1 Blocked.pdf"], {"Blocked"})
        self.assertEqual(tags["A10-000-561-X_A_Removed.pdf"], {"Removed"})
        self.assertEqual(tags["ASM-000-068-X_B(OBSOLETE).pdf"], {"Obsolete"})
        self.assertEqual(tags["A10-000-8820_1 -ITAR PRELIM.pdf"], {"ITAR", "Prelim"})
        self.assertEqual(tags["A10-000-9256_A1-EAR.pdf"], {"EAR"})
        self.assertEqual(tags["A10-000-5935_A REDLINE - BLOCKED - QJ 7-12-23.pdf"], {"Redline", "Blocked"})
        self.assertEqual(tags["A10-000-7076-X_D.pdf"], set())

    def test_revisions_that_mean_the_same_thing(self):
        norm = revisions._norm_rev
        self.assertEqual(norm("1"), norm("1.0")), self.assertEqual(norm("1-0"), norm("1_0"))
        self.assertEqual(norm("A"), norm("a0")), self.assertEqual(norm("02"), norm("2"))
        self.assertNotEqual(norm("1.1"), norm("1")), self.assertNotEqual(norm("A1"), norm("A"))
        rank = lambda r: revisions._rank(norm(r))
        self.assertLess(rank("1"), rank("1.1")), self.assertLess(rank("1.1"), rank("2"))
        self.assertLess(rank("9"), rank("10")), self.assertLess(rank("A"), rank("A1"))
        self.assertLess(rank("A1"), rank("B")), self.assertLess(rank("Z"), rank("AA"))

    def test_redline_variants(self):
        for name in ("TST-010-600_A Redline.pdf", "TST-010-600_A REDLINE.pdf", "TST-010-600_A_redline.pdf",
                     "TST-010-600_A Red Line.pdf", "TST-010-600_A-Red-Line.pdf", "TST-010-600_A Redlined.pdf",
                     "TST-010-600_A REDLINES.pdf", "TST-010-600_A Redline 2.pdf", "TST-010-600_A-EAR Redline.pdf",
                     "TST-010-600_A (REDLINE).pdf"):
            self.assertEqual(read(name), ("TST-010-600", "A", True), name)
        self.assertEqual(read("TST-010-600_Redline.pdf"), ("TST-010-600", "", True))
        # only REDLINE is a redline unless more words are configured
        for name in ("TST-010-600_A.pdf", "TST-010-600_A Markup.pdf", "TST-010-600_A_RL.pdf", "Sherlock-123_A.pdf"):
            self.assertEqual(revisions.find_redline(name), "", name)

    def test_custom_redline_words(self):
        more = revisions.compile_redline_words(revisions.DEFAULT_REDLINE_WORDS + ("markup", "mark up", "rl"))
        for name in ("TST-010-600_A Markup.pdf", "TST-010-600_A Mark-Up.pdf", "TST-010-600_A_RL.pdf"):
            self.assertEqual(read(name, redline_re=more), ("TST-010-600", "A", True), name)
        self.assertEqual(revisions.find_redline("TST-010-600_ARL.pdf", more), "")      # whole token only
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
        for name in ("Review.pdf", "Datasheet.pdf", "Procedure Review.pdf", "readme.pdf", "DOC.pdf"):
            self.assertIsNone(read(name), name)
        self.assertEqual(read("Doc123 Review.pdf"), ("Doc123 Review", "", False))  # no revision, but has a number

    def test_custom_pattern(self):
        pattern = revisions.compile_pattern(r"^(?P<number>\d{5}-\d{3})_(?P<rev>[A-Z])$")
        self.assertEqual(read("12345-678_B-EAR.pdf", pattern=pattern), ("12345-678", "B", False))
        self.assertEqual(read("12345-678_B Redline.pdf", pattern=pattern), ("12345-678", "B", True))
        self.assertIsNone(read("12345-678-B.pdf", pattern=pattern))

    def test_bad_patterns_are_rejected(self):
        for bad in ("(", r"^(\d+)_([A-Z])$"):
            with self.assertRaises(ValueError):
                revisions.compile_pattern(bad)

    def test_windows_and_posix_paths(self):
        for path in (r"S:\Library\Drawings - Fischer US\A10\A10-000-5660_B-EAR.pdf",
                     "/srv/library/A10/A10-000-5660_B-EAR.pdf"):
            self.assertEqual(read(path), ("A10-000-5660", "B", False))


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


class LibraryScenarioTests(unittest.TestCase):
    """Situations seen in the real library (with invented numbers)."""

    def test_same_drawing_in_both_libraries_with_different_tagging(self):
        rep = revisions.analyze([
            item(r"S:\Library\Drawings - Fischer US ITAR\ITAR\TST-000-455_F-ITAR.pdf"),
            item(r"S:\Library\Drawings - Fischer US\TST\TST-000-455_F.pdf"),
            item(r"S:\Library\Drawings - Fischer US ITAR\ITAR\TST-000-005_B-ITAR.PDF"),
            item(r"S:\Library\Drawings - Fischer US\TST\TST-000-005_A.pdf"),
            item(r"S:\Library\Drawings - Fischer US ITAR\ITAR\TST-000-746_C-EAR.pdf"),
            item(r"S:\Library\Drawings - Fischer US ITAR\ITAR\TST-000-746_B-EAR.pdf")])
        self.assertEqual(rep.stats["tag_conflicts"], 2)
        notes = {r["File Name"]: r["Notes"] for r in rep.rows}
        self.assertIn("ITAR vs no tag", notes["TST-000-455_F.pdf"])
        self.assertIn("ITAR vs no tag", notes["TST-000-005_A.pdf"])
        self.assertNotIn("disagree", notes["TST-000-746_B-EAR.pdf"])       # both EAR: no conflict
        self.assertEqual({r["File Name"]: r["Status"] for r in rep.rows}["TST-000-005_A.pdf"], STATUS_OLDER)
        self.assertEqual({r["File Name"]: r["Status"] for r in rep.rows}["TST-000-455_F.pdf"], STATUS_COPY)

    def test_dotted_and_letter_digit_revisions_are_ordered(self):
        s = statuses(revisions.analyze([item("/a/X-1_1.pdf"), item("/a/X-1_1.1.pdf"), item("/a/X-1_2.0.pdf"),
                                        item("/a/Y-1_A.pdf"), item("/a/Y-1_A1.pdf"), item("/a/Y-1_B.pdf")]))
        self.assertEqual((s["X-1_1.pdf"], s["X-1_1.1.pdf"], s["X-1_2.0.pdf"]),
                         (STATUS_OLDER, STATUS_OLDER, STATUS_NEWEST))
        self.assertEqual((s["Y-1_A.pdf"], s["Y-1_A1.pdf"], s["Y-1_B.pdf"]),
                         (STATUS_OLDER, STATUS_OLDER, STATUS_NEWEST))

    def test_equivalent_revision_spellings_are_the_same_revision(self):
        rep = revisions.analyze([item("/a/X-2_1.pdf"), item("/b/X-2_1.0.pdf"), item("/a/Y-2_A.pdf"), item("/b/Y-2_A0.pdf")])
        self.assertEqual({r["Status"] for r in rep.rows}, {STATUS_COPY})

    def test_files_already_marked_blocked_are_noted(self):
        rep = revisions.analyze([item("/a/Z-1_A Blocked.pdf"), item("/a/Z-1_B.pdf"), item("/a/Z-2_A_Removed.pdf"),
                                 item("/a/Z-2_C.pdf")])
        notes = {r["File Name"]: r["Notes"] for r in rep.rows}
        self.assertIn("already marked Blocked", notes["Z-1_A Blocked.pdf"])
        self.assertIn("already marked Removed", notes["Z-2_A_Removed.pdf"])
        self.assertEqual({r["File Name"]: r["Name Tags"] for r in rep.rows}["Z-1_A Blocked.pdf"], "Blocked")

    def test_prelim_without_revision_is_older_than_the_release(self):
        s = statuses(revisions.analyze([item("/a/D-1 PRELIM.pdf"), item("/a/D-1_A.pdf")]))
        self.assertEqual((s["D-1 PRELIM.pdf"], s["D-1_A.pdf"]), (STATUS_OLDER, STATUS_NEWEST))

    def test_k_s_and_x_variants_are_separate_drawings(self):
        rep = revisions.analyze([item("/a/K-1 K-S_1.0.pdf"), item("/a/K-1_A.pdf"), item("/a/K-2-X_A.pdf"),
                                 item("/a/K-2_A.pdf")])
        self.assertEqual(rep.rows, [])

    def test_lone_redlines_are_listed(self):
        rep = revisions.analyze([item("/a/R-1_1.0 REDLINE.pdf"), item("/a/R-2_A Redline.pdf"), item("/a/R-3_1.pdf")])
        self.assertEqual((rep.rows, rep.stats["redlines"]), ([], 2))
        self.assertEqual({r["Status"] for r in rep.redlines}, {"Only file of this drawing on the server"})


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
                          "[advisory]\nphrases = GENERAL SYMBOL ADVISORY; Export Notice\n[folders]\nskip = - Engineering Release; Old\n")
        got = settings.load(path)
        self.assertEqual(got["name_pattern"], "^(?P<number>\\d+)%(?P<rev>[A-Z])$")
        self.assertEqual(got["redline_words"], ("redline", "rev marked"))
        self.assertEqual(got["advisory_phrases"], ("GENERAL SYMBOL ADVISORY", "Export Notice"))
        self.assertEqual(got["skip_folders"], ("- Engineering Release", "Old"))

    def test_empty_values_turn_things_off(self):
        got = settings.load(self.write("[advisory]\nphrases =\n[folders]\nskip =\n"))
        self.assertEqual((got["advisory_phrases"], got["skip_folders"]), ((), ()))


if __name__ == "__main__":
    unittest.main()
