#!/usr/bin/env bash
# Compile images/*.tex (standalone TikZ) once, into
#   build/figures/*.svg              for the web pages
#   build/texinputs/images/*.pdf     for the PDF build (see build_pdf.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SVG="$ROOT/site/build/figures"
PDF="$ROOT/site/build/texinputs/images"
WORK="$ROOT/site/build/figwork"
mkdir -p "$SVG" "$PDF" "$WORK"

for tex in "$ROOT"/images/*.tex; do
    base="$(basename "$tex" .tex)"
    if [[ -f "$SVG/$base.svg" && -f "$PDF/$base.pdf" && "$SVG/$base.svg" -nt "$tex" ]]; then
        echo "  = $base (up to date)"
        continue
    fi
    echo "  + $base"
    xelatex -interaction=nonstopmode -halt-on-error \
            -output-directory="$WORK" "$tex" >"$WORK/$base.stdout" 2>&1 \
        || { echo "xelatex failed for $base:"; tail -30 "$WORK/$base.stdout"; exit 1; }
    cp "$WORK/$base.pdf" "$PDF/$base.pdf"
    pdftocairo -svg "$WORK/$base.pdf" "$SVG/$base.svg"
done

echo "figures -> $SVG, $PDF"
