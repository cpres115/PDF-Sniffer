# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""End-to-end checks on the synthetic sample PDFs (the same ones `--selftest` uses)."""
import os
import shutil
import tempfile
import unittest

from pdf_sniffer import runner, selftest
from pdf_sniffer.selftest import E_NONE
from pdf_sniffer.config import ScanConfig
from pdf_sniffer.scanner import scan_file


class SampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pdf_sniffer_test_")
        cls.expected = selftest.build_samples(os.path.join(cls.tmp, "samples"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_each_sample(self):
        for name, (category, status) in sorted(self.expected.items()):
            with self.subTest(name):
                res = scan_file(os.path.join(self.tmp, "samples", name), ScanConfig())
                self.assertEqual((res.category, res.status), (category, status), res.notes)

    def test_evidence_picture_always_shows_the_eccn(self):
        evidence_dir = os.path.join(self.tmp, "evidence")
        os.makedirs(evidence_dir, exist_ok=True)
        cfg = ScanConfig(evidence_dir=evidence_dir)
        for name in ("04_document_ear_eccn_9A610x.pdf", "20_mwi_advisory_table_plus_ear_footer_5D002.pdf",
                     "23_document_eccn_far_above_logo.pdf", "24_document_eccn_far_right_and_above.pdf",
                     "25_drawing_scanned_eccn_far_above_logo.pdf", "07_drawing_rotated90_ear_3A001.pdf"):
            with self.subTest(name):
                res = scan_file(os.path.join(self.tmp, "samples", name), cfg)
                self.assertEqual(len(res.hits), 1, res.notes)
                hit = res.hits[0]
                ex0, ey0, ex1, ey1 = hit["eccn_box"]
                bx0, by0, bx1, by1 = hit["evidence_box"]
                self.assertTrue(bx0 <= ex0 and by0 <= ey0 and ex1 <= bx1 and ey1 <= by1,
                                f"ECCN {hit['eccn_box']} outside evidence {hit['evidence_box']}")
                self.assertTrue(os.path.isfile(os.path.join(evidence_dir, hit["evidence"])))

    def test_advisory_table_logos_are_ignored_but_reported_as_info(self):
        mwi = os.path.join(self.tmp, "samples", "19_mwi_advisory_table_only.pdf")
        res = scan_file(mwi, ScanConfig())
        self.assertEqual((res.category, res.status), (E_NONE, "OK"))
        self.assertTrue(any("2 explanatory logo(s)" in i for i in res.info), res.info)
        # with the filter switched off the same file is (wrongly) seen as controlled - proves the filter works
        off = scan_file(mwi, ScanConfig(advisory_phrases=()))
        self.assertEqual(off.category, selftest.E_ITAR)
        self.assertEqual(off.status, "REVIEW")

    def advisory_page(self, name, title_lines):
        doc, _ = selftest._letter("MWI footer")
        selftest._advisory_table(doc[0], 430, title="")
        for i, line in enumerate(title_lines):
            doc[0].insert_text((68, 439 + 9 * i), line, fontname="hebo", fontsize=8)
        path = os.path.join(self.tmp, name)
        doc.save(path)
        return scan_file(path, ScanConfig())

    def test_advisory_heading_may_wrap_and_must_match_in_full(self):
        wrapped = self.advisory_page("wrapped.pdf", ["General Symbol", "Advisory"])
        self.assertEqual((wrapped.category, wrapped.status), (E_NONE, "OK"))
        # only the full "General Symbol Advisory" heading marks the explanatory table
        other = self.advisory_page("other.pdf", ["GENERAL ADVISORY"])
        self.assertNotEqual(other.category, E_NONE)
        self.assertEqual(self.advisory_page("partial.pdf", ["Symbol Advisory"]).category, other.category)

    def test_real_footer_logo_is_still_found_on_an_advisory_page(self):
        res = scan_file(os.path.join(self.tmp, "samples", "21_mwi_advisory_pictures_plus_itar_footer.pdf"),
                        ScanConfig())
        self.assertEqual([h["label"] for h in res.hits], ["ITAR"])

    def test_no_ocr_still_reads_text_layer_logos(self):
        res = scan_file(os.path.join(self.tmp, "samples", "04_document_ear_eccn_9A610x.pdf"),
                        ScanConfig(use_ocr=False))
        self.assertEqual(res.category, selftest.ear_cat("9A610"))

    def test_parallel_run_matches_serial_and_resumes(self):
        files, skipped, _ = runner.discover([os.path.join(self.tmp, "samples")])
        self.assertEqual(len(files), len(self.expected))
        run_dir = os.path.join(self.tmp, "run")
        os.makedirs(run_dir)
        results = runner.run_scan(files, ScanConfig(), run_dir, workers=2)
        got = {os.path.basename(r["path"]): (r["category"], r["status"]) for r in results}
        self.assertEqual(got, self.expected)
        again = runner.run_scan(files, ScanConfig(), run_dir, workers=2, resume=True)
        self.assertEqual(len(again), len(files))

    @unittest.skipIf(os.name == "nt", "crash injection relies on fork()")
    def test_worker_crash_only_marks_the_crashing_file(self):
        folder = os.path.join(self.tmp, "crash")
        os.makedirs(folder)
        for i in range(6):
            shutil.copy(os.path.join(self.tmp, "samples", "01_document_plain.pdf"), os.path.join(folder, f"ok{i}.pdf"))
        shutil.copy(os.path.join(self.tmp, "samples", "02_document_itar_footer_vector.pdf"),
                    os.path.join(folder, "CRASHME.pdf"))
        real = runner.scan_file

        def crashing(path, cfg, root=""):
            if "CRASHME" in path:
                os._exit(9)
            return real(path, cfg, root)

        runner.scan_file = crashing
        try:
            files, _, _ = runner.discover([folder])
            run_dir = os.path.join(self.tmp, "crashrun")
            os.makedirs(run_dir)
            results = runner.run_scan(files, ScanConfig(), run_dir, workers=3)
        finally:
            runner.scan_file = real
        got = {os.path.basename(r["path"]): r["category"] for r in results}
        self.assertEqual(got.pop("CRASHME.pdf"), "Unreadable")
        self.assertEqual(set(got.values()), {"Non-Controlled"})


if __name__ == "__main__":
    unittest.main()
