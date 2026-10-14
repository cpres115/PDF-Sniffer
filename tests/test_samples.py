"""End-to-end checks on the synthetic sample PDFs (the same ones `--selftest` uses)."""
import os
import shutil
import tempfile
import unittest

from pdf_sniffer import runner, selftest
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

    def test_no_ocr_still_reads_text_layer_logos(self):
        res = scan_file(os.path.join(self.tmp, "samples", "04_document_ear_eccn_9A610x.pdf"),
                        ScanConfig(use_ocr=False))
        self.assertEqual(res.category, selftest.ear_cat("9A610"))

    def test_parallel_run_matches_serial_and_resumes(self):
        files, skipped = runner.discover([os.path.join(self.tmp, "samples")])
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
            files, _ = runner.discover([folder])
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
