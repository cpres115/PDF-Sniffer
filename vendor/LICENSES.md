# Bundled third-party components

Everything in this folder is redistributed unmodified from its upstream source.
File integrity is recorded in `SHA256SUMS.txt` and checked during first-time setup.

| Component | Version | Source | License |
|---|---|---|---|
| Python (embeddable package, Windows x64, unpacked into `python/`) | 3.13.16 | https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip (SHA-256 `97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297`, as listed in python.org's SPDX manifest) | PSF License |
| PyMuPDF (includes MuPDF and Tesseract OCR) | 1.28.2 | https://pypi.org/project/PyMuPDF/ | AGPL-3.0, or a commercial license from Artifex |
| NumPy | 2.5.3 | https://pypi.org/project/numpy/ | BSD-3-Clause |
| openpyxl | 3.1.5 | https://pypi.org/project/openpyxl/ | MIT |
| et_xmlfile | 2.0.0 | https://pypi.org/project/et-xmlfile/ | MIT |
| Tesseract English model (`tessdata_fast`) | - | https://github.com/tesseract-ocr/tessdata_fast | Apache-2.0 |

The `wheels/*.whl` files are the official Windows x64 / CPython 3.13 builds from PyPI; their
SHA-256 digests match the ones published by PyPI.

**Licensing note.** PyMuPDF/MuPDF is dual-licensed (AGPL-3.0 or commercial). Running this tool
inside your own organisation is fine under the AGPL; if you ever redistribute the bundle outside
your organisation, review the AGPL obligations or obtain a commercial license from Artifex.
