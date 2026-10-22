# PDF Sniffer

**Author:** Corey Preston  
**Company:** Fischer Connectors, Inc  
**Date:** October 2026

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

**Check it works on your computer:** double-click **`Run Self-Test.bat`**. It builds 26 sample PDFs (vector,
picture and "scanned" logos, a large E-size drawing, rotated pages, MWI-style pages with an explanatory logo table,
ECCNs placed far from the logo, look-alike decoys, a corrupt file, an encrypted file, ...) and confirms each is
classified correctly. You should see `Self-test PASSED`.

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
* `name_vs_logo.csv` / sheet **Name vs Logo** - files whose `-ITAR` / `-EAR` file-name tag disagrees with the logo (see below)
* `revision_check.csv` / sheet **Revision Check** - old revisions, redlines and copies left on the server (see below)
* `redlines.csv` / sheet **Redlines** - every REDLINE file with a count
* `evidence\` - a picture of every logo found. It always shows the whole area searched for the ECCN (8 logo
  diameters either side, 4 above and below) plus the ECCN itself, with the logo outlined in **green** and the ECCN in
  **blue**, so the ECCN is visible wherever it sits. Pictures ending in `_ignored` show explanatory logos that were
  deliberately skipped (see "MWI files"). The Excel report links to them.
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
| `--revisions-only` | only run the revision / redline check on the file names (takes seconds, no PDF content is read) |
| `--name-pattern REGEX` | how to read drawing number and revision from file names (see "Revision check") |
| `--redline-word WORD` | one more word that marks a redline (repeatable) |
| `--skip-folder NAME` | one more folder name to skip everywhere (repeatable; `- Engineering Release` is always skipped) |
| `--advisory-phrase TEXT` | one more heading that marks an explanatory logo table to ignore (repeatable) |

Linux / macOS: `./run_pdf_sniffer.sh <folders>` (needs Python 3.10+ and internet once to install into `runtime/`).

## Name vs logo check

In your library the classification is written into the file name (`..._B-EAR.pdf`, `..._A-ITAR.pdf`; untagged = not
controlled). After the scan, every PDF's name tag is compared with the logo actually found in it (the *All Files* sheet
shows **Classification In Name** and **Name vs Logo** for every file), and each disagreement is listed in the
**Name vs Logo** sheet / `name_vs_logo.csv`, with the evidence picture, and the file is flagged `REVIEW`:

| Priority | Mismatch | Meaning |
|---|---|---|
| **High** | name has no tag, but the file carries an ITAR or an EAR logo | possibly under-protected: controlled content filed as uncontrolled |
| **High** | name says EAR, but the logo says ITAR | the stricter regime applies |
| Medium | name says ITAR, but the logo says EAR | check which is right |
| Medium | name says ITAR/EAR, but no logo was found | the logo may be missing from the PDF, or the scan missed it - check the page |

Files whose scan ended as *Needs Review* or *Unreadable* cannot be compared and are counted separately. `EAR99` in a name
counts as EAR; the ECCN itself is not compared. Only the tag in the **file name** counts (not the folder), and it is read
the same way as in the revision check (`-EAR`, `_ITAR`, `-ITAR Redline`, `... ITAR.pdf`; colour words like `RED` are not
tags). The check needs the content scan, so it is not part of `--revisions-only`.

## Revision check: old revisions and redlines left on the server

Because the library is version-controlled, the **file name** matters: `<drawing number>_<revision>[-<classification>]`,
for example `A10-000-5660_B-EAR.pdf`. Every PDF name is read into drawing number, revision and (if present) a
REDLINE marker. Files are grouped by drawing number (across all folders you scan; case and `-`/`_`/space differences
are ignored) and every drawing with something out of date is listed in the **Revision Check** sheet and
`revision_check.csv`:

| Status | Meaning |
|---|---|
| `Newest - keep` | the highest revision of that drawing |
| `Older revision - remove?` | a lower revision of the same drawing is still on the server (`A10-000-5660_B-EAR.pdf` next to `..._C-EAR.pdf`) |
| `Current redline - keep` | the redline of the newest revision |
| `Out of date - a redline exists` | a plain file whose drawing has a shared redline of the same or a newer revision, or of no revision: `TST-010-600.pdf` next to `TST-010-600_A Redline.pdf`; the **Notes** column names the redline |
| `Old redline - remove?` | a redline of a revision that has since been superseded |
| `Same revision - extra copy` | the same drawing number and revision exists more than once (also `- Copy` / `(1)` files) |
| `Revisions cannot be ordered - verify` | revisions mix letters and numbers (e.g. `A` and `01`), so no newest one is named |

Each row also shows the folder, last-modified date, all revisions found and (in a full run) the file's export-control
group, so you can see at once whether a stale file is an ITAR/EAR drawing. Letter revisions order `A < B < ... < Z < AA`,
numeric ones numerically (`9 < 10`). **Nothing is deleted or changed; it only reports.**

**How a name is read** (worked out from the ~6,300 real file names of the library)

* The **revision** is the last short token after an underscore: `_B`, `_AB`, `_2`, `_1.0`, `_1_0`, `_1-0`, `_A0`, `_B1`. Everything
  before that underscore is the drawing number, which may itself contain underscores or a variant part
  (`A10-000-204_X_A`, `A10-000-1060-X_3`, `A10-000-4235 K-S_1.0` are three different drawing numbers' revisions).
  `1`, `1.0` and `1_0` mean the same revision, so do `A` and `A0`; `1 < 1.1 < 2`, `9 < 10`, `A < A1 < B < ... < Z < AA`.
* **Tags** may follow the revision and are never mistaken for it: classification (`-EAR`, `_ITAR`, `-EAR99`, an ECCN),
  REDLINE, and status words such as `Blocked`, `Block`, `Removed`, `Obsolete`, `In Change` (with initials like `SJS`),
  `PRELIM`, `Deviation`, `Internal Use Only`, `(upon request)`, `(129582)`. They are shown in the **Name Tags** column; a file
  already marked Blocked / Removed / Obsolete gets the note *already marked ...* so you can see it was dealt with.
* **REDLINE** (any case: `Redline`, `REDLINE`, `redline`; also `Red Line`, `redlined`, `REDLINES`) marks a redline. Colour
  words such as `RED` or `YELLOW` are not redlines. Add more words (`markup`, `rl`, ...) in `settings.ini`
  (`redline_words`) or with `--redline-word`.
* Older names without an underscore are read too: `T01-000-297 A`, `CBL-000-238-B`, `HDW-000-021-X-B`,
  `A10-000-4188 K-S 1.0 redline`, `C10256 R6`, `307837-Rev1`. A trailing `-X` is part of the number, not a revision;
  `-RevNA` means no revision.
* A name with no revision is simply the drawing number (`CHM-000-016.pdf`, `DOC-000-330 PRELIM.pdf`) and counts as older
  than any revision. Extensions in any case (`.PDF`), `..pdf`, trailing spaces and Windows copy markers (`- Copy`, `(1)`)
  are ignored.
* **Copies that disagree on classification:** if one copy of a drawing is tagged `-ITAR`/`-EAR` and another is not (for
  example `X_A.pdf` in the normal library and `X_A-ITAR.pdf` in the ITAR library), every file of that drawing gets the note
  *copies disagree on classification in the file name: ITAR vs no tag*, and the drawing is counted in the summary.

The **Drawing Number** and **Revision** columns of the *All Files* sheet show how every name was read, and the **Name Read
By** column of the revision sheet how it was recognised. To use a different scheme, give a regular expression with the
groups `number` and `rev` in `settings.ini` (`name_pattern`) or with `--name-pattern`.

### Redline list

Every file whose name contains a REDLINE word is listed - with its count - in the **Redlines** sheet and `redlines.csv`:
drawing number, revision, folder, date, the word that matched, whether it is the current or an old redline, and the plain
file(s) it makes out of date. The count also appears in the summary.

### Folders that are skipped

Any folder named **`- Engineering Release`** is skipped in all cases: the folder and everything inside it, at any depth,
and also if you give it directly (upper/lower case and extra spaces are ignored). Skipped folders are named in the summary.
Change or extend the list with `skip = ...` in `settings.ini` or `--skip-folder NAME`.

## MWI files and the General Symbol Advisory table

Pages that contain the heading **General Symbol Advisory** (taken from the PDF text; case and spacing ignored) carry a table
that shows what the ITAR and EAR logos look like. Logos inside that table are ignored, so they neither classify the
file nor raise a flag; the real classification logo (footer) is still found and counted. The table is located from the
heading: the table that contains it, or the one right below it. If no table lines can be detected, everything below the
heading down to the footer band (bottom 20% of the page) is treated as the explanation, so a logo in the footer is
never skipped. Every ignored logo is noted in the report (*Info: ... explanatory logo(s) in the advisory table were
ignored*) and saved as an `_ignored` evidence picture, so you can confirm nothing real was skipped. Add other headings
in `settings.ini` (`phrases = GENERAL SYMBOL ADVISORY; Another Heading`) or with `--advisory-phrase`. This relies on the
heading being real text; in a scanned MWI page it cannot be found.

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
3. **For EAR logos, look for an ECCN** (`9A610`, `9A610.x`, `3A001.a.2`, `5D002`, `EAR99`) in a wide area around the
   logo (8 logo diameters left/right, 4 above/below), first in the text layer, then by OCR (strip by strip, nearest the
   logo first). An ECCN written "ECCN ..." beats one without the label, then the nearest one wins.
4. **Classify the file.** ITAR on any page wins; EAR groups by ECCN; a file with both is filed under ITAR and flagged.

### Flags (Status `REVIEW`) - check these by eye

A file is flagged, but still placed in its best group, when: its file-name tag disagrees with its logo (see "Name vs logo"); a red ring with unreadable text was found; ITAR and EAR
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

Also check that file names are read correctly by the revision check (see above), that every redline in your library
appears in the Redlines list (if one is missing, add its wording to `redline_words`), and that `_ignored` evidence
pictures only show explanatory logos.

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
                  scanner.py (per page / per file, ECCN search, advisory tables, evidence)   eccn.py
                  classify.py   revisions.py (drawing number / revision / redline check)   namecheck.py (name tag vs logo)
                  settings.py (settings.ini)
                  runner.py (parallel, resume)   report.py   selftest.py (sample PDFs)   __main__.py (CLI)
settings.ini         optional: file-name pattern, redline words, skipped folders, advisory-table headings
tools/bootstrap.py   first-run installer used by the .bat files
vendor/              bundled Python, wheels, OCR data, SHA256SUMS.txt, LICENSES.md
tests/               python -m unittest discover -s tests -t .
```

Third-party components and licenses are listed in `vendor/LICENSES.md`. PyMuPDF is AGPL-3.0 (or commercial from Artifex):
fine for internal use; review it before redistributing the bundle outside your organisation.
