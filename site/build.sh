#!/usr/bin/env bash
# Build the static site (and, unless --no-pdf, the downloadable PDF).
#
#   site/build.sh            figures + PDF + markdown + mdBook
#   site/build.sh --no-pdf   skip the LaTeX run while iterating on the site
set -euo pipefail

SITE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WITH_PDF=1
[[ "${1:-}" == "--no-pdf" ]] && WITH_PDF=0

echo "==> TikZ figures"
"$SITE/tools/figures.sh"

if (( WITH_PDF )); then
    echo "==> PDF"
    "$SITE/tools/build_pdf.sh"
fi

echo "==> LaTeX -> Markdown"
python3 "$SITE/tools/build_md.py"

if [[ -f "$SITE/build/pdf/main.pdf" ]]; then
    cp "$SITE/build/pdf/main.pdf" "$SITE/src/fcpp-for-dbd.pdf"
else
    echo "   (no PDF yet — the download link on the front page will 404)"
fi

echo "==> mdBook"
mdbook build "$SITE"

echo
echo "done: $SITE/book/index.html"
