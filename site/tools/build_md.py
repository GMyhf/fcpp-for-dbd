#!/usr/bin/env python3
"""Convert the LaTeX book into an mdBook source tree.

  site/tools/build_md.py [--src site/src]

One page per \\section, plus a landing page per \\chapter. Cross-references are
resolved after the split, once every label's page is known.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preprocess import preprocess  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
FILTER = SITE / "tools" / "filters" / "fcpp.lua"

XREF = re.compile(r"@@XREF\|(\w+)\|([^@]+)@@")
ANCHOR = re.compile(r'id="([^"]+)"')
FENCE = re.compile(r"^\s*(```|~~~)")


class Page:
    def __init__(self, name: str, title: str, lines: list[str], level: int):
        self.name = name          # file name inside src/
        self.title = title
        self.lines = lines
        self.level = level        # 0 = chapter, 1 = section

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip() + "\n"


def chapters_from_main(main: Path) -> list[Path]:
    order = re.findall(r"\\include\{([^}]*)\}", main.read_text(encoding="utf-8"))
    out = []
    for rel in order:
        p = ROOT / (rel if rel.endswith(".tex") else rel + ".tex")
        if not p.exists():
            raise FileNotFoundError(p)
        out.append(p)
    return out


def run_pandoc(tex: str, chapnum: int, workdir: Path) -> tuple[str, dict]:
    src = workdir / f"ch{chapnum:02d}.tex"
    src.write_text(tex, encoding="utf-8")
    refs = workdir / f"ch{chapnum:02d}.refs.json"
    cmd = [
        "pandoc",
        "-f", "latex-smart",          # keep the author's 「」“” punctuation as-is
        "-t", "gfm",
        "--wrap=none",
        # keep footnote definitions next to their reference — the chapter gets
        # split into per-section pages further down
        "--reference-location=block",
        f"--lua-filter={FILTER}",
        "-M", f"chapnum={chapnum}",
        "-M", f"refsfile={refs}",
        str(src),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        sys.exit(f"pandoc failed on {src}:\n{proc.stderr}")
    if proc.stderr.strip():
        for line in proc.stderr.strip().splitlines():
            print(f"  pandoc: {line}", file=sys.stderr)
    table = json.loads(refs.read_text(encoding="utf-8")) if refs.exists() else {}
    return proc.stdout, table


def shift_headings(lines: list[str]) -> list[str]:
    """Promote a section page's headings so its own title becomes h1."""
    out, fenced = [], False
    for ln in lines:
        if FENCE.match(ln):
            fenced = not fenced
        elif not fenced:
            m = re.match(r"^(#{2,6}) (.*)$", ln)
            if m:
                ln = "#" * (len(m.group(1)) - 1) + " " + m.group(2)
        out.append(ln)
    return out


# A \section with at least this many \subsections gets a page per subsection —
# otherwise the STL tour would be one page listing every container.
SUBSPLIT_MIN = 6


def split_at(lines: list[str], marker: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Cut `lines` before every heading of the given level."""
    head: list[str] = []
    parts: list[tuple[str, list[str]]] = []
    fenced = False
    for ln in lines:
        if FENCE.match(ln):
            fenced = not fenced
        if not fenced and ln.startswith(marker):
            parts.append((ln[len(marker):].strip(), [ln]))
        elif parts:
            parts[-1][1].append(ln)
        else:
            head.append(ln)
    return head, parts


def split_chapter(md: str, chapnum: int) -> list[Page]:
    """Break a converted chapter into pages at \\section (and long \\subsections)."""
    lines = md.split("\n")
    chap_title = next((l[2:].strip() for l in lines if l.startswith("# ")), f"第{chapnum}章")

    head, sections = split_at(lines, "## ")
    pages = [Page(f"ch{chapnum:02d}.md", chap_title, head, 0)]

    for i, (title, body) in enumerate(sections, 1):
        stem = f"ch{chapnum:02d}-{i:02d}"
        sec_head, subs = split_at(body, "### ")
        if len(subs) < SUBSPLIT_MIN:
            pages.append(Page(f"{stem}.md", title, shift_headings(body), 1))
            continue
        pages.append(Page(f"{stem}.md", title, shift_headings(sec_head), 1))
        for j, (sub_title, sub_body) in enumerate(subs, 1):
            pages.append(Page(f"{stem}-{j:02d}.md", sub_title,
                              shift_headings(shift_headings(sub_body)), 2))
    return pages


def add_child_lists(pages: list[Page]) -> None:
    """Give title-only landing pages a table of their subsections."""
    for i, page in enumerate(pages):
        if page.level == 2:
            continue
        body = [l for l in page.lines if l.strip() and not l.startswith("#")]
        if body:
            continue
        children = [p for p in pages[i + 1:] if p.level == page.level + 1
                    and p.name.startswith(page.name[:-3] + "-")]
        if not children:
            continue
        page.lines += ["", "本" + ("章" if page.level == 0 else "节") + "包含：", ""]
        page.lines += [f"- [{c.title}]({c.name})" for c in children]


def resolve_refs(pages: list[Page], labels: dict[str, dict]) -> int:
    """Replace @@XREF@@ tokens once every label's home page is known."""
    home: dict[str, str] = {}
    for page in pages:
        for label in ANCHOR.findall(page.text):
            home.setdefault(label, page.name)

    missing = 0
    for page in pages:
        text = page.text

        def repl(m: re.Match[str]) -> str:
            nonlocal missing
            kind, label = m.group(1), m.group(2)
            info = labels.get(label)
            if info is None or label not in home:
                missing += 1
                print(f"  ! unresolved \\{kind}{{{label}}} in {page.name}", file=sys.stderr)
                return info["text"] if info else f"({label})"

            if kind == "nameref":
                shown = info["name"]
            elif kind == "ref":
                shown = info["text"].split(" ")[-1]
            else:
                shown = info["text"]
                # The book writes "如图~\cref{...}"; cref already prints "图 x.y".
                # (pandoc turns the ~ into a non-breaking space.)
                before = text[: m.start()].rstrip(" ~ ")
                if before and shown and before[-1] == shown[0]:
                    shown = shown[1:].lstrip()

            target = f"#{label}" if home[label] == page.name else f"{home[label]}#{label}"
            return f"[{shown}]({target})"

        page.lines = XREF.sub(repl, text).split("\n")
    return missing


def write_summary(src: Path, pages: list[Page]) -> None:
    out = ["# Summary", "", "[前言](introduction.md)", ""]
    for page in pages:
        out.append(f"{'  ' * page.level}- [{page.title}]({page.name})")
    out.append("")
    (src / "SUMMARY.md").write_text("\n".join(out), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SITE / "src"), help="mdBook src directory")
    args = ap.parse_args()

    src = Path(args.src)
    if src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True)

    pages: list[Page] = []
    labels: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for n, tex_path in enumerate(chapters_from_main(ROOT / "main.tex"), 1):
            print(f"[{n}] {tex_path.relative_to(ROOT)}")
            md, table = run_pandoc(preprocess(tex_path, ROOT), n, work)
            labels.update(table)
            pages.extend(split_chapter(md, n))

    add_child_lists(pages)
    missing = resolve_refs(pages, labels)
    for page in pages:
        (src / page.name).write_text(page.text, encoding="utf-8")

    intro = SITE / "content" / "introduction.md"
    shutil.copy(intro, src / "introduction.md")
    figures = SITE / "build" / "figures"
    if figures.is_dir():
        shutil.copytree(figures, src / "figures")
    else:
        print("  ! site/build/figures missing — run tools/figures.sh first", file=sys.stderr)

    write_summary(src, pages)
    print(f"\n{len(pages)} pages -> {src}"
          + (f"  ({missing} unresolved references)" if missing else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
