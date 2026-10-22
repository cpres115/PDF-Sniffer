# Author:  Corey Preston
# Company: Fischer Connectors, Inc
# Date:    October 2026
"""Walk folders, scan every PDF (in parallel) and stream results to a JSON-lines file."""
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from .config import SCANNER_VERSION, ScanConfig
from .models import FileResult, STATUS_ERROR, UNREADABLE
from .scanner import scan_file

_CFG = None
_INFLIGHT = None


# ------------------------------------------------------------------ discovery
def _norm_dir(name):
    """Folder-name comparison key: ignores case, repeated spaces and the kind of dash used."""
    name = re.sub("[\u2010-\u2015\u2212]", "-", name)
    return re.sub(r"\s+", " ", name.strip()).casefold()


def discover(folders, recursive=True, skip_folders=()):
    """Find the PDFs under `folders`.

    Any folder whose name is in `skip_folders` (e.g. "- Engineering Release") is skipped together with
    everything inside it, wherever it is - even when it is one of the folders given.
    Returns (list of (root, pdf_path), Counter of ignored non-PDF extensions, list of skipped folder paths).
    """
    skip = {_norm_dir(n) for n in skip_folders if n.strip()}
    seen, files, ignored, skipped_dirs = set(), [], Counter(), []
    for root in folders:
        root = os.path.abspath(root)
        if _norm_dir(os.path.basename(root.rstrip("\\/"))) in skip:
            skipped_dirs.append(root)
            continue
        if recursive:
            walker = os.walk(root)
        else:
            walker = [(root, [], [n for n in os.listdir(root) if os.path.isfile(os.path.join(root, n))])]
        for dirpath, dirnames, names in walker:
            kept = []
            for d in dirnames:
                if _norm_dir(d) in skip:
                    skipped_dirs.append(os.path.join(dirpath, d))
                else:
                    kept.append(d)
            dirnames[:] = kept  # os.walk does not descend into the skipped folders
            for name in names:
                full = os.path.join(dirpath, name)
                if name.lower().endswith(".pdf"):
                    key = os.path.normcase(full)
                    if key not in seen and not name.startswith("~$"):
                        seen.add(key)
                        files.append((root, full))
                else:
                    ignored[os.path.splitext(name)[1].lower() or "(no extension)"] += 1
    files.sort(key=lambda t: os.path.normcase(t[1]))
    return files, ignored, sorted(set(skipped_dirs), key=os.path.normcase)


# ---------------------------------------------------------------- worker side
def _init_worker(cfg_dict, inflight_dir):
    global _CFG, _INFLIGHT
    _CFG = ScanConfig.from_dict(cfg_dict)
    _INFLIGHT = inflight_dir


def _work(item):
    root, path = item
    marker = os.path.join(_INFLIGHT, f"{os.getpid()}.txt") if _INFLIGHT else None
    if marker:  # lets the parent identify a file that crashes its worker process
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(path)
    try:
        return scan_file(path, _CFG, root).to_dict()
    finally:
        if marker and os.path.exists(marker):
            os.remove(marker)


def _scan_isolated(root, path, cfg_dict):
    """Re-run one file alone in a throw-away worker; only a real crasher stays marked as one."""
    try:
        with ProcessPoolExecutor(1, initializer=_init_worker, initargs=(cfg_dict, None)) as ex:
            return ex.submit(_work, (root, path)).result()
    except BrokenProcessPool:
        return _crash_result(root, path)


def _crash_result(root, path):
    res = FileResult(path=path, root=root, category=UNREADABLE, status=STATUS_ERROR,
                     notes=["the scanner crashed on this file (it may be damaged)"])
    try:
        st = os.stat(path)
        res.size, res.mtime = st.st_size, st.st_mtime
    except OSError:
        pass
    return res.to_dict()


# ------------------------------------------------------------------ resume I/O
def load_results(jsonl):
    out = {}
    if os.path.isfile(jsonl):
        with open(jsonl, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        d = json.loads(line)
                        out[os.path.normcase(d["path"])] = d
                    except (ValueError, KeyError):
                        pass  # a half-written last line from an interrupted run
    return out


def _unchanged(prev, path):
    try:
        st = os.stat(path)
    except OSError:
        return False
    return prev.get("size") == st.st_size and abs(prev.get("mtime", 0) - st.st_mtime) < 1e-3


# --------------------------------------------------------------------- driver
class Progress:
    def __init__(self, total, already=0):
        self.total, self.done, self.t0 = total, 0, time.time()
        self.already = already
        self.tty = sys.stdout.isatty()

    def tick(self, path):
        self.done += 1
        if not self.tty and self.done % 25 and self.done != self.total:
            return
        elapsed = time.time() - self.t0
        eta = elapsed / self.done * (self.total - self.done)
        name = os.path.basename(path)
        line = (f"[{self.done + self.already}/{self.total + self.already}] "
                f"{100 * (self.done + self.already) / max(self.total + self.already, 1):5.1f}%  "
                f"ETA {int(eta // 3600)}:{int(eta % 3600 // 60):02d}:{int(eta % 60):02d}  {name[:50]}")
        if self.tty:
            sys.stdout.write("\r" + line.ljust(100)[:100])
            sys.stdout.flush()
        else:
            print(line, flush=True)

    def finish(self):
        if self.tty:
            sys.stdout.write("\r" + " " * 100 + "\r")


def run_scan(files, cfg, run_dir, workers=1, resume=False):
    """Scan `files` [(root, path)], appending results to run_dir/results.jsonl.

    Returns all results (including ones carried over from a resumed run) as dicts.
    """
    run_dir = Path(run_dir)
    jsonl = run_dir / "results.jsonl"
    previous = load_results(str(jsonl)) if resume else {}
    todo, kept = [], []
    for root, path in files:
        prev = previous.get(os.path.normcase(path))
        if prev and _unchanged(prev, path):
            kept.append(prev)
        else:
            todo.append((root, path))
    if resume and kept:
        print(f"Resuming: {len(kept)} file(s) already scanned, {len(todo)} to go.")

    results = list(kept)
    mode = "a" if resume else "w"
    progress = Progress(len(todo), already=len(kept))
    inflight = run_dir / ".inflight"
    inflight.mkdir(exist_ok=True)
    for stale in inflight.glob("*.txt"):
        stale.unlink()

    with open(jsonl, mode, encoding="utf-8") as out:
        def record(d):
            out.write(json.dumps(d, ensure_ascii=False) + "\n")
            out.flush()
            results.append(d)
            progress.tick(d["path"])

        if workers <= 1 or len(todo) <= 1:
            _init_worker(cfg.to_dict(), None)
            for item in todo:
                record(_work(item))
        else:
            pending = list(todo)
            retries = 0
            while pending:
                done = set()
                try:
                    with ProcessPoolExecutor(workers, initializer=_init_worker,
                                             initargs=(cfg.to_dict(), str(inflight))) as ex:
                        futs = {ex.submit(_work, it): it for it in pending}
                        for fut in as_completed(futs):
                            record(fut.result())
                            done.add(futs[fut])
                    pending = []
                except BrokenProcessPool:
                    pending = [it for it in pending if it not in done]
                    # Every worker that was mid-file died with the pool, so the in-flight files are
                    # only suspects: re-scan each alone to find which one really crashes.
                    suspects = set()
                    for marker in inflight.glob("*.txt"):
                        try:
                            suspects.add(os.path.normcase(marker.read_text(encoding="utf-8")))
                            marker.unlink()
                        except OSError:
                            pass
                    for root, path in list(pending):
                        if os.path.normcase(path) in suspects:
                            record(_scan_isolated(root, path, cfg.to_dict()))
                            pending.remove((root, path))
                    if not suspects:
                        retries += 1
                        workers = max(1, workers // 2)
                        if retries > 3:
                            for root, path in pending:
                                record(_crash_result(root, path))
                            pending = []
    progress.finish()
    try:
        inflight.rmdir()
    except OSError:
        pass
    by_path = {os.path.normcase(d["path"]): d for d in results}
    return [by_path[os.path.normcase(p)] for _r, p in files if os.path.normcase(p) in by_path]


def write_run_info(run_dir, folders, cfg, workers, extra=None):
    info = {"scanner_version": SCANNER_VERSION, "folders": [str(f) for f in folders],
            "config": cfg.to_dict(), "workers": workers,
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    info.update(extra or {})
    with open(Path(run_dir) / "run_info.json", "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2)
