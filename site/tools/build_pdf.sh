#!/usr/bin/env bash
# Compile the book to PDF, without writing anything into the upstream tree.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/site/build/pdf"
TEXIN="$ROOT/site/build/texinputs"
# \include writes one .aux per chapter, mirroring the source layout inside the
# output directory — xelatex will not create those subdirectories itself.
mkdir -p "$OUT/chapters" "$OUT/images"

if [[ ! -d "$TEXIN/images" ]]; then
    echo "missing $TEXIN/images — run tools/figures.sh first" >&2
    exit 1
fi

# preamble.tex declares a bibliography the book does not ship; an empty stub
# keeps biblatex quiet without patching upstream sources.
[[ -f "$ROOT/references.bib" ]] || : >"$OUT/references.bib"
export BIBINPUTS="$OUT:${BIBINPUTS:-}"

# preamble.tex asks standalone for mode=buildnew, which XeTeX does not support;
# it falls back to rebuilding every figure on every pass, and those sub-runs do
# not survive -output-directory. figures.sh has already built the PDFs, so tell
# standalone to just include them, and point TEXINPUTS at where they live.
export TEXINPUTS="$TEXIN:$TEXIN/images:${TEXINPUTS:-}"
PREAMBLE='\PassOptionsToPackage{mode=none}{standalone}'

cd "$ROOT"

# Three fixed passes rather than latexmk: the book has no \cite, but biblatex
# still rewrites main.bcf every run, which latexmk reads as "biber must run"
# forever and gives up with "needed too many passes". Pass 1 lays out the text,
# 2 settles the ToC, 3 settles cleveref's references.
for pass in 1 2 3; do
    echo "--- xelatex pass $pass/3"
    xelatex -shell-escape -interaction=nonstopmode -halt-on-error \
            -output-directory="$OUT" -jobname=main \
            "$PREAMBLE\\input{main.tex}" >"$OUT/pass$pass.stdout" 2>&1 \
        || { echo "--- xelatex failed: ---"; grep -A6 -E '^!' "$OUT/main.log" | tail -40; exit 1; }
done

if grep -qE "Reference \`[^']+' on page [0-9]+ undefined" "$OUT/main.log"; then
    echo "--- 仍有未解析的引用: ---"
    grep -oE "Reference \`[^']+' on page [0-9]+ undefined" "$OUT/main.log" | sort -u
fi

echo "pdf -> $OUT/main.pdf"
