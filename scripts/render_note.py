"""Render docs/architecture.md to docs/architecture.pdf and report the page count.

The brief caps the note at two pages, so the check is part of the build. Uses headless Chrome
(present on the dev machine); markdown and pypdf are pulled in by `uv run --with`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "architecture.md"
OUT = ROOT / "docs" / "architecture.pdf"
CHROME = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
    "chromium-browser",
]
STYLE = """
@page { size: Letter; margin: 0.6in 0.7in; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; line-height: 1.28; }
h1 { font-size: 16pt; margin: 0 0 6pt; } h2 { font-size: 12pt; margin: 10pt 0 4pt; }
p { margin: 0 0 6pt; } pre { font-size: 7.4pt; line-height: 1.15; margin: 4pt 0; }
table { border-collapse: collapse; font-size: 9pt; margin: 4pt 0; }
td, th { border: 1px solid #999; padding: 2px 5px; vertical-align: top; }
ol { margin: 0; padding-left: 18pt; } li { margin-bottom: 4pt; }
img { width: 100%; height: auto; display: block; margin: 2pt auto 6pt; }
"""


def main() -> int:
    import markdown  # noqa: PLC0415
    from pypdf import PdfReader  # noqa: PLC0415

    chrome = next((c for c in CHROME if Path(c).exists() or shutil.which(c)), None)
    if not chrome:
        print("no Chrome/Chromium found; cannot render", file=sys.stderr)
        return 1
    body = markdown.markdown(SRC.read_text(), extensions=["tables", "fenced_code"])
    html = ROOT / "docs" / ".architecture.html"
    html.write_text(f'<html><head><meta charset="utf-8"><style>{STYLE}</style></head><body>{body}</body></html>')
    try:
        args = ["--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={OUT}"]
        subprocess.run([chrome, *args, html.as_uri()], check=True, capture_output=True)
    finally:
        html.unlink(missing_ok=True)
    pages = len(PdfReader(str(OUT)).pages)
    print(f"{OUT.relative_to(ROOT)}: {pages} page(s)")
    return 0 if pages <= 2 else 2


if __name__ == "__main__":
    sys.exit(main())
