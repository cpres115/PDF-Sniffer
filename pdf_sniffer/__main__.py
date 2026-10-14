"""Command-line entry point:  python -m pdf_sniffer [folders...]"""
import argparse
import multiprocessing
import os
import sys
import time
from pathlib import Path

from . import __version__, ocr, paths, report, runner
from .config import SCANNER_VERSION, ScanConfig


def _read_folders_file(path):
    folders = []
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip().strip('"')
                if line and not line.startswith("#"):
                    folders.append(line)
    return folders


def _ask_folders():
    print("Enter the folder(s) to scan. Separate several folders with a semicolon (;).")
    print("Tip: you can paste a path copied from File Explorer.")
    raw = input("Folder(s): ").strip()
    return [p.strip().strip('"') for p in raw.split(";") if p.strip()]


def build_parser():
    p = argparse.ArgumentParser(
        prog="pdf_sniffer",
        description="Classify PDFs by the EAR / ITAR export-control logo (red circle) they carry.")
    p.add_argument("folders", nargs="*", help="folders to scan (searched recursively)")
    p.add_argument("--folders-file", default=str(paths.APP_ROOT / "folders.txt"),
                   help="text file listing folders, one per line (default: folders.txt in the program folder)")
    p.add_argument("--out", default=str(paths.DEFAULT_OUTPUT_DIR), help="where result folders are created")
    p.add_argument("--workers", type=int, default=0, help="parallel worker processes (default: automatic)")
    p.add_argument("--no-subfolders", action="store_true", help="do not descend into sub-folders")
    p.add_argument("--resume", metavar="RUN_FOLDER", help="continue an interrupted run (skips files already done)")
    p.add_argument("--copy-to", metavar="DIR", help="also COPY each PDF into category folders under DIR")
    p.add_argument("--no-evidence", action="store_true", help="do not save crops of detected logos")
    p.add_argument("--no-ocr", action="store_true", help="disable OCR (text-layer and shape detection only)")
    p.add_argument("--full-page", action="store_true", help="search the whole page instead of the lower part")
    p.add_argument("--zone", metavar="X0,Y0,X1,Y1",
                   help="search area as page fractions, y downward (default 0,0.45,1,1)")
    p.add_argument("--max-pages", type=int, default=0, help="scan at most this many pages per file")
    p.add_argument("--selftest", action="store_true", help="verify the installation on built-in sample PDFs")
    p.add_argument("--version", action="version", version=f"PDF Sniffer {__version__}")
    return p


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)

    if args.selftest:
        from .selftest import run_selftest
        return 0 if run_selftest() else 1

    cfg = ScanConfig(use_ocr=not args.no_ocr, full_page=args.full_page, max_pages=args.max_pages)
    if args.zone:
        try:
            cfg.zone = tuple(float(v) for v in args.zone.split(","))
            assert len(cfg.zone) == 4 and 0 <= cfg.zone[0] < cfg.zone[2] <= 1 and 0 <= cfg.zone[1] < cfg.zone[3] <= 1
        except Exception:
            print("--zone must be four fractions between 0 and 1: X0,Y0,X1,Y1 (e.g. 0,0.45,1,1)")
            return 2

    folders = list(args.folders) or _read_folders_file(args.folders_file)
    if args.resume:
        run_dir = Path(args.resume)
        info_file = run_dir / "run_info.json"
        if not info_file.is_file():
            print(f"{run_dir} is not a PDF Sniffer run folder (no run_info.json).")
            return 2
        import json
        info = json.loads(info_file.read_text(encoding="utf-8"))
        if info.get("scanner_version") != SCANNER_VERSION:
            print("That run was made with a different scanner version; start a new run instead.")
            return 2
        cfg = ScanConfig.from_dict(info["config"])
        folders = folders or info["folders"]
    if not folders:
        if not sys.stdin or not sys.stdin.isatty():
            print("No folders given. Pass folder paths, or list them in folders.txt.")
            return 2
        folders = _ask_folders()
    missing = [f for f in folders if not os.path.isdir(f)]
    if missing:
        print("These folders do not exist or are not reachable:\n  " + "\n  ".join(missing))
        return 2
    if not folders:
        return 2

    if not args.resume:
        run_dir = Path(args.out) / time.strftime("run_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_evidence:
        cfg.evidence_dir = str(run_dir / "evidence")
        os.makedirs(cfg.evidence_dir, exist_ok=True)

    print(f"PDF Sniffer {__version__}")
    print("Looking for PDF files ...")
    files, skipped = runner.discover(folders, recursive=not args.no_subfolders)
    print(f"Found {len(files)} PDF file(s)" + (f" ({sum(skipped.values())} other files ignored)." if skipped else "."))
    if not files:
        return 0
    if cfg.use_ocr and not ocr.available():
        print(f"WARNING: OCR is unavailable ({ocr.error()}); picture-only logos may be flagged for review.")

    workers = args.workers or max(1, min((os.cpu_count() or 2) - 1, 8))
    if not args.resume:
        runner.write_run_info(run_dir, folders, cfg, workers)
    print(f"Scanning with {workers} worker process(es). Results are saved as it goes, "
          f"so an interrupted run can be continued with --resume \"{run_dir}\"")
    t0 = time.time()
    results = runner.run_scan(files, cfg, run_dir, workers=workers, resume=bool(args.resume))
    seconds = time.time() - t0

    report.write_csv(results, run_dir / "classification_report.csv")
    try:
        report.write_xlsx(results, run_dir / "classification_report.xlsx", folders, skipped)
    except Exception as exc:  # the CSV is already written
        print(f"(Excel report could not be written: {exc})")
    text = report.summary_text(results, folders, skipped, seconds, run_dir)
    (run_dir / "summary.txt").write_text(text + "\n", encoding="utf-8")
    print("\n" + text)
    if args.copy_to:
        n = report.copy_sorted(results, args.copy_to)
        print(f"\nCopied {n} file(s) into category folders under {args.copy_to}")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
