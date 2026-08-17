"""Rewrite the book's LaTeX into a dialect pandoc reads faithfully.

Nothing here touches the upstream sources — chapters are read, transformed in
memory and handed to pandoc, so `git pull` from upstream stays conflict-free.
"""

from __future__ import annotations

import re
from pathlib import Path

# tcbtheorem environments: \begin{env}{title}{label}. The third argument of
# \newtcbtheorem in preamble.tex is the label prefix cleveref refers to.
THEOREMS = {
    "theorem": "thm",
    "lemma": "lm",
    "proposition": "prop",
    "corollary": "cor",
    "definition": "def",
    "example": "ex",
}

# \newtcolorbox environments taking a single title argument.
TITLED_BOXES = {"remark"}

# Environments with no arguments that still deserve a styled box; the filter
# supplies their heading.
PLAIN_BOXES = {"proof"}

SHIM = r"\newcommand{\fcppboxhead}[1]{\subparagraph{#1}}" + "\n"


def _read_group(text: str, i: int) -> tuple[str, int]:
    """Read a balanced {...} group starting at text[i] == '{'."""
    assert text[i] == "{"
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "{" and (j == i or text[j - 1] != "\\"):
            depth += 1
        elif c == "}" and text[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[i + 1 : j], j + 1
        j += 1
    raise ValueError(f"unbalanced brace group at offset {i}")


def _skip_space(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\n":
        i += 1
    return i


def resolve_inputs(path: Path, root: Path) -> str:
    """Inline \\input{...} / \\include{...} so a chapter converts as one unit."""
    text = path.read_text(encoding="utf-8")

    def sub(m: re.Match[str]) -> str:
        target = m.group(2)
        if not target.endswith(".tex"):
            target += ".tex"
        child = root / target
        if not child.exists():
            child = path.parent / target
        if not child.exists():
            raise FileNotFoundError(f"{path}: cannot resolve \\{m.group(1)}{{{target}}}")
        return resolve_inputs(child, root)

    return re.sub(r"\\(input|include)\{([^}]*)\}", sub, text)


def rewrite_boxes(text: str) -> str:
    """Turn tcolorbox environments into \\begin{fcpp<kind>} + \\fcppboxhead{}."""
    out: list[str] = []
    i = 0
    envs = list(THEOREMS) + sorted(TITLED_BOXES) + sorted(PLAIN_BOXES)
    begin_re = re.compile(r"\\begin\{(" + "|".join(envs) + r")\}")
    while True:
        m = begin_re.search(text, i)
        if not m:
            out.append(text[i:])
            break
        out.append(text[i : m.start()])
        env = m.group(1)
        j = m.end()

        if env in THEOREMS:
            j = _skip_space(text, j)
            title, j = _read_group(text, j)
            j = _skip_space(text, j)
            label, j = _read_group(text, j)
            head = f"\\begin{{fcpp{env}}}\n\\fcppboxhead{{{title}}}"
            if label.strip():
                head += f"\\label{{{THEOREMS[env]}:{label.strip()}}}"
            out.append(head + "\n")
        elif env in TITLED_BOXES:
            j = _skip_space(text, j)
            title, j = _read_group(text, j)
            out.append(f"\\begin{{fcpp{env}}}\n\\fcppboxhead{{{title}}}\n")
        else:
            out.append(f"\\begin{{fcpp{env}}}\n\\fcppboxhead{{}}\n")
        i = j

    text = "".join(out)
    for env in envs:
        text = text.replace(f"\\end{{{env}}}", f"\\end{{fcpp{env}}}")
    return text


def simplify_longtables(text: str) -> str:
    r"""Drop a longtable's page-break furniture.

    The repeated header and the "接下页" footer only make sense in print; pandoc
    turns them into extra body rows. Keeping the first header and dropping
    everything from \endfirsthead to \endlastfoot leaves the plain table.
    """
    for closing in (r"\\endlastfoot", r"\\endfoot", r"\\endhead"):
        text = re.sub(r"\\endfirsthead.*?" + closing, r"\\endhead", text, flags=re.S)
    return text


def flatten_subtables(text: str) -> str:
    r"""Promote \begin{subtable} groups to top-level tables.

    pandoc stamps the enclosing float's label onto every table it finds inside,
    so three subtables sharing one \begin{table} all come out with the last
    label. Giving each its own float keeps the anchors distinct; on a page they
    stack instead of sitting side by side, which reads fine.
    """
    if "\\begin{subtable}" not in text:
        return text

    out: list[str] = []
    i = 0
    while True:
        start = text.find("\\begin{table}", i)
        if start < 0:
            out.append(text[i:])
            break
        end = text.find("\\end{table}", start)
        if end < 0:
            out.append(text[i:])
            break
        body = text[start + len("\\begin{table}") : end]
        out.append(text[i:start])
        if "\\begin{subtable}" in body:
            body = re.sub(r"\\begin\{subtable\}(\[[^\]]*\])?\{[^}]*\}",
                          r"\\begin{table}", body)
            body = body.replace("\\end{subtable}", "\\end{table}")
            out.append(body)
        else:
            out.append(text[start : end + len("\\end{table}")])
        i = end + len("\\end{table}")
    return "".join(out)


def rewrite_figures(text: str) -> str:
    """\\includestandalone{images/x} -> \\includegraphics{figures/x.svg}."""
    return re.sub(
        r"\\includestandalone(\[[^\]]*\])?\{(?:images/)?([^}]+)\}",
        lambda m: f"\\includegraphics{m.group(1) or ''}{{figures/{m.group(2)}.svg}}",
        text,
    )


def rewrite_refs(text: str) -> str:
    """Tag every reference with its flavour so the filter can tell them apart."""
    return re.sub(
        r"\\(Cref|cref|nameref|autoref|ref)\{([^}]*)\}",
        lambda m: f"\\ref{{{m.group(1)}--{m.group(2)}}}",
        text,
    )


def preprocess(path: Path, root: Path) -> str:
    text = resolve_inputs(path, root)
    text = rewrite_boxes(text)
    text = simplify_longtables(text)
    text = flatten_subtables(text)
    text = rewrite_figures(text)
    text = rewrite_refs(text)
    return SHIM + text
