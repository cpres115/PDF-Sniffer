# PDF Sniffer

Scans folders of PDF drawings and documents and sorts every file by the **EAR / ITAR export-control logo**
(a red circle containing red "ITAR" or "EAR" text, usually with an ECCN beside it) it carries.

| Group | Meaning |
|---|---|
| `Non-Controlled` | no EAR/ITAR logo found on any page |
| `ITAR Controlled` | an ITAR logo was found on at least one page |
| `EAR Controlled (No Provided ECCN)` | an EAR logo was found, no ECCN next to it |
| `EAR Controlled - ECCN 9A610` (one per ECCN) | an EAR logo with that ECCN, e.g. `9A610`, `3A001`, `5D002`, `EAR99` |
| `Needs Review` | a red ring with letters was found but could not be read as ITAR or EAR |
| `Unreadable` | the PDF is damaged or password-protected, so it could not be scanned |

`Needs Review` and `Unreadable` are not in your original list. They exist so that a file the program
could not judge is never silently reported as `Non-Controlled`.

## Install (Windows 10 / 11, 64-bit)

1. Download this repository as a ZIP (green **Code** button, then **Download ZIP**) and extract it to the
   drive and folder you want, for example `D:\Tools\PDF-Sniffer`. The path may contain spaces. A network
   drive also works.
2. Double-click **`Run PDF Sniffer.bat`**. The first run unpacks the bundled Python and libraries into
   the `runtime` folder (about 15 seconds, no internet, no administrator rights). Nothing is installed on
   the computer itself and nothing is needed beforehand, not even Python.

Everything the program needs is already in the `vendor` folder (Python 3.13, PyMuPDF, NumPy, openpyxl,
OCR data). To move the program, copy the whole folder.

**Check it works on your computer:** double-click **`Run Self-Test.bat`**. It builds 19 sample PDFs (vector,
picture and "scanned" logos, a large E-size drawing, a rotated page, look-alike decoys, a corrupt file,
an encrypted file, ...) and confirms each is classified correctly. You should see `Self-test PASSED`.

## Run

Any of these:

* **Double-click `Run PDF Sniffer.bat`** and type or paste a folder path (use `;` between several folders).
* **Drag one or more folders onto `Run PDF Sniffer.bat`.**
* **List the folders in `folders.txt`** (one per line); they are used whenever you start without dragging folders.
* From a command prompt: `"Run PDF Sniffer.bat" "D:\Drawings" "\\server\PLM\Released" --copy-to "D:\Sorted"`

All sub-folders are searched. Only `.pdf` files are scanned; the summary says how many other files were ignored.
Original files are never modified or moved.

### Results

Each run creates `output\run_<date>_<time>\` inside the program folder:

* `classification_report.xlsx` - sheet **Summary** (counts per group), **All Files** (filterable, colour-coded),
  **Needs Attention** (everything flagged `REVIEW` or `ERROR`)
* `classification_report.csv` - the same list for other tools
* `evidence\` - a picture of every logo found, with its ECCN area. Use it to verify any result at a glance;
  the Excel report links to it.
* `summary.txt` - the counts shown at the end of the run
* `results.jsonl`, `run_info.json` - raw results and the settings used

Each report row gives the group, file, folder, ECCN as written (e.g. `9A610.x`), pages with a logo, how the logo
was recognised, and notes. Files with different paragraph suffixes (`9A610.x`, `9A610.y.1`) share one ECCN group.

### Useful options

| Option | Effect |
|---|---|
| `--copy-to DIR` | also **copy** every PDF into `DIR\<group>\...` (ECCN groups become `DIR\EAR Controlled\9A610\...`) |
| `--resume "output\run_..."` | continue an interrupted run; files already done are skipped |
| `--workers N` | parallel processes (default: CPU cores - 1, at most 8) |
| `--full-page` / `--zone X0,Y0,X1,Y1` | search the whole page / a custom area (fractions of the page, y downward) |
| `--no-ocr` | text-layer and shape detection only (faster, less able to read picture-only logos) |
| `--no-evidence` | don't save logo pictures |
| `--no-subfolders` | only the folders given |

Linux / macOS: `./run_pdf_sniffer.sh <folders>` (needs Python 3.10+ and internet once to install into `runtime/`).

## How it decides

For **every page**, the program looks at the lower 55% of the page as the person sees it (this covers a
document footer and the lower-right corner above a drawing's title block, and respects page rotation):

1. **Find red circles.** The area is rendered to pixels, red ink is isolated and thin, closed circle outlines of
   plausible logo size (0.2 - 2.5 in) are located. This works the same for vector drawings, embedded logo pictures
   and scanned pages. Filled discs, squares, red text and red rectangles are ignored.
2. **Read the text inside the circle** from the PDF text layer when there is one; otherwise by OCR of just the red
   ink. The letter shapes (four letters starting with a thin "I" = ITAR; three = EAR) are a second opinion that
   upgrades confidence but can never confirm a logo alone. A ring containing other text (for example a revision
   bubble with "12" or a stamp) is ignored when it is clearly not ITAR/EAR.
3. **For EAR logos, look for an ECCN** (`9A610`, `9A610.x`, `3A001.a.2`, `5D002`, `EAR99`) beside the logo, first in the
   text layer, then by OCR of the neighbourhood.
4. **Classify the file.** ITAR on any page wins; EAR groups by ECCN; a file with both is filed under ITAR and flagged.

### Flags (Status `REVIEW`) - check these by eye

A file is flagged, but still placed in its best group, when: a red ring with unreadable text was found; ITAR and EAR
both appear; several different ECCNs appear (the group is then e.g. `EAR Controlled - ECCN 3A001 + 9A610`);
the ECCN was not labelled "ECCN"; the logo text was confirmed by OCR only; the footer *text* mentions ITAR/EAR/ECCN but
no logo was found; a page was mostly red or could not be analysed; or not every page was scanned (time limit).

## Please verify on your own files first

The program was developed and tested on **synthetic logos** drawn to your description (vector, picture and noisy
"scanned" versions in several fonts and sizes, on letter pages and 44 x 34 in sheets). It has not been run on your real
drawings. Before relying on it for compliance decisions:

1. Run it on a folder where you already know the answers and compare, including drawings from different CAD systems and
   old scans.
2. Open `Needs Attention` and a handful of `evidence` images from each group.
3. If a real logo is missed or misread, send me an example (or the evidence image) and the thresholds can be tuned.

Limits to be aware of: a logo cut off by the page edge, drawn outside the lower 55% of the page (use `--full-page`),
smaller than 0.2 in, filled solid red, or smudged beyond recognition will not be recognised (the footer-text check and
`Needs Review` catch some, not all). Only English letters/digits are read. An ECCN that is far from the logo (for
example only in the title block) is found only if it is written "ECCN ...".

## Troubleshooting

* **"The bundled libraries could not be loaded ... missing DLL"** - install the Microsoft Visual C++ Redistributable
  (x64) from <https://aka.ms/vs/17/release/vc_redist.x64.exe> and run again. (Normally not needed: the required runtime
  file is bundled.)
* **Antivirus or SmartScreen blocks the .bat or python.exe** - the program only reads PDFs and writes into its own
  `output` folder; ask IT to allow the program folder.
* **Slow on a very large database** - each file takes 0.1 - 4 s (large scanned drawings are the slowest). Results are
  saved as it goes; if it stops, rerun with `--resume`.
* **Reset the installation** - delete the `runtime` folder and start again.

## For developers

```
pdf_sniffer/      imaging.py (red mask, components, circle fit)   logo_reader.py (ITAR/EAR reading)
                  scanner.py (per page / per file)   eccn.py   classify.py   runner.py (parallel, resume)
                  report.py   selftest.py (sample PDFs)   __main__.py (CLI)
tools/bootstrap.py   first-run installer used by the .bat files
vendor/              bundled Python, wheels, OCR data, SHA256SUMS.txt, LICENSES.md
tests/               python -m unittest discover -s tests -t .
```

Third-party components and licenses are listed in `vendor/LICENSES.md`. PyMuPDF is AGPL-3.0 (or commercial from Artifex):
fine for internal use; review it before redistributing the bundle outside your organisation.
