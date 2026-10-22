# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""Command-line entry point:  python -m pdf_sniffer [folders...]"""
import argparse
import multiprocessing
import os
import sys
import time
from pathlib import Path

from . import __version__, namecheck, ocr, paths, report, revisions, runner, settings
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


def _revisions_only(files, folders, run_dir, name_pattern, redline_re, skipped_dirs):
    items = []
    for _root, path in files:
        try:
            st = os.stat(path)
            items.append({"path": path, "size": st.st_size, "mtime": st.st_mtime})
        except OSError:
            items.append({"path": path, "size": 0, "mtime": 0})
    rev = revisions.analyze(items, name_pattern, redline_re)
    report.write_revision_csvs(rev, run_dir)
    try:
        report.write_revision_xlsx(rev, run_dir / "revision_check.xlsx", folders, skipped_dirs)
    except Exception as exc:
        print(f"(Excel report could not be written: {exc})")
    text = "\n".join(["PDF SNIFFER - REVISION CHECK", "=" * 60, "Folders scanned:"] + [f"  {f}" for f in folders]
                      + ["", f"PDF files checked: {len(files)}"] + report.skipped_dir_lines(skipped_dirs) + [""]
                      + report.revision_summary_lines(rev.stats) + ["", f"Reports saved in: {run_dir}"])
    (run_dir / "summary.txt").write_text(text + "\n", encoding="utf-8")
    print("\n" + text)
    return 0


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
    p.add_argument("--revisions-only", action="store_true",
                   help="only check file names for several revisions of the same drawing (fast; no content scan)")
    p.add_argument("--name-pattern", metavar="REGEX",
                   help="regular expression with groups (?P<number>..) and (?P<rev>..) for reading drawing "
                        "number and revision from file names (overrides settings.ini)")
    p.add_argument("--skip-folder", metavar="NAME", action="append", default=[],
                   help='extra folder name to skip everywhere (repeatable; "- Engineering Release" is always skipped)')
    p.add_argument("--redline-word", metavar="WORD", action="append", default=[],
                   help="extra word that marks a redline in a file name (repeatable; built in: REDLINE / red line)")
    p.add_argument("--advisory-phrase", metavar="TEXT", action="append", default=[],
                   help="extra heading of an explanatory logo table to ignore (repeatable; default: 'General Symbol Advisory')")
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

    user = settings.load()
    try:
        name_pattern = revisions.compile_pattern(args.name_pattern or user["name_pattern"])
    except ValueError as exc:
        print(exc)
        return 2
    phrases = user["advisory_phrases"] if user["advisory_phrases"] is not None else settings.DEFAULT_ADVISORY_PHRASES
    skip_folders = tuple(user["skip_folders"] if user["skip_folders"] is not None
                         else settings.DEFAULT_SKIP_FOLDERS) + tuple(args.skip_folder)
    redline_words = tuple(user["redline_words"] if user["redline_words"] is not None
                          else revisions.DEFAULT_REDLINE_WORDS) + tuple(args.redline_word)
    redline_re = revisions.compile_redline_words(redline_words)
    cfg = ScanConfig(use_ocr=not args.no_ocr, full_page=args.full_page, max_pages=args.max_pages,
                     advisory_phrases=tuple(phrases) + tuple(args.advisory_phrase))
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
        prefix = "revisions" if args.revisions_only else "run"
        run_dir = Path(args.out) / time.strftime(f"{prefix}_%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_evidence and not args.revisions_only:
        cfg.evidence_dir = str(run_dir / "evidence")
        os.makedirs(cfg.evidence_dir, exist_ok=True)

    print(f"PDF Sniffer {__version__}")
    print("Looking for PDF files ...")
    files, skipped, skipped_dirs = runner.discover(folders, recursive=not args.no_subfolders,
                                                   skip_folders=skip_folders)
    print(f"Found {len(files)} PDF file(s)" + (f" ({sum(skipped.values())} other files ignored)." if skipped else "."))
    if skipped_dirs:
        print(f"Skipped {len(skipped_dirs)} folder(s) by name ({', '.join(skip_folders)}).")
    if not files:
        return 0
    if args.revisions_only:
        return _revisions_only(files, folders, run_dir, name_pattern, redline_re, skipped_dirs)
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

    rev = revisions.analyze(results, name_pattern, redline_re)  # also adds drawing number / revision
    names = namecheck.check(results, redline_re)                # also flags files whose name and logo disagree
    report.write_csv(results, run_dir / "classification_report.csv")
    report.write_revision_csvs(rev, run_dir)
    report.write_name_csv(names, run_dir)
    try:
        report.write_xlsx(results, run_dir / "classification_report.xlsx", folders, skipped, rev, skipped_dirs, names)
    except Exception as exc:  # the CSV files are already written
        print(f"(Excel report could not be written: {exc})")
    text = report.summary_text(results, folders, skipped, seconds, run_dir, rev, skipped_dirs, names)
    (run_dir / "summary.txt").write_text(text + "\n", encoding="utf-8")
    print("\n" + text)
    if args.copy_to:
        n = report.copy_sorted(results, args.copy_to)
        print(f"\nCopied {n} file(s) into category folders under {args.copy_to}")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
