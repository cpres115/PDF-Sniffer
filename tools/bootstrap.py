"""First-time setup: install the bundled libraries into ./runtime (no internet, no admin rights).

Run by "Run PDF Sniffer.bat" with the *bundled* Python, after it has unpacked vendor/python-*.zip
into runtime/python.  Uses the standard library only.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
RUNTIME = ROOT / "runtime"
PYDIR = RUNTIME / "python"
SITE = RUNTIME / "site-packages"
VC_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"


def fail(msg):
    print("\nSETUP FAILED: " + msg)
    sys.exit(1)


def verify_vendor_files():
    sums = VENDOR / "SHA256SUMS.txt"
    if not sums.is_file():
        fail("vendor/SHA256SUMS.txt is missing - the download is incomplete.")
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        name = name.strip().lstrip("*")
        f = VENDOR / name
        if not f.is_file():
            fail(f"vendor/{name} is missing - the download is incomplete. Re-download the program folder.")
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            fail(f"vendor/{name} is corrupt (checksum mismatch). Re-download the program folder.")
    print("  checksums OK")


def install_wheels():
    SITE.mkdir(parents=True, exist_ok=True)
    for whl in sorted((VENDOR / "wheels").glob("*.whl")):
        print("  installing", whl.name)
        with zipfile.ZipFile(whl) as z:
            z.extractall(SITE)


def write_pth():
    stem = f"python{sys.version_info.major}{sys.version_info.minor}"
    pth = PYDIR / f"{stem}._pth"
    # paths are relative to this file: the standard library zip, the python folder itself,
    # the installed libraries, and the program folder (so `-m pdf_sniffer` is importable)
    pth.write_text(f"{stem}.zip\n.\n..\\site-packages\n..\\..\n", encoding="ascii")


def add_cpp_runtime():
    """PyMuPDF needs msvcp140.dll, which the embeddable Python does not include.

    numpy ships a private copy; place it next to python.exe so no Visual C++ Redistributable
    has to be installed on the machine.
    """
    if os.name != "nt" and not (PYDIR / "python.exe").exists():
        return
    found = sorted((SITE / "numpy.libs").glob("msvcp140*.dll"))
    if found:
        shutil.copyfile(found[0], PYDIR / "msvcp140.dll")
        print("  added app-local", "msvcp140.dll")


def check_imports():
    code = "import numpy, pymupdf, openpyxl, pdf_sniffer; print('  libraries import OK: PyMuPDF', pymupdf.__version__)"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print(r.stderr.rstrip()[-1500:])
        fail("the bundled libraries could not be loaded.\n"
             "If the message above mentions a missing DLL, install the Microsoft Visual C++ "
             f"Redistributable (x64) from {VC_URL} and run this program again.")


def main():
    if not (PYDIR / "python.exe").exists():
        fail("runtime/python/python.exe not found - run 'Run PDF Sniffer.bat' instead of this file.")
    print("Verifying bundled files ...")
    verify_vendor_files()
    print("Installing libraries into", SITE)
    install_wheels()
    write_pth()
    add_cpp_runtime()
    print("Testing the installation ...")
    check_imports()
    (RUNTIME / ".installed").write_text("ok\n", encoding="ascii")
    print("Setup complete.")


if __name__ == "__main__":
    main()
