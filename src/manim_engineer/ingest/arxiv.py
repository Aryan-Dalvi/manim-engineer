"""arXiv adapter: fetch LaTeX source, flatten inputs, extract an equation ledger.

A paper's equations must reach the plan verbatim, so they are read from the
LaTeX source rather than re-typed from rendered text. `document_from_latex` is
pure and does the whole extraction; only `fetch_source` touches the network.
"""

from __future__ import annotations

import gzip
import re
import shutil
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

from manim_engineer.core import Document, Modality, Segment, SegmentKind, SourceSpan
from manim_engineer.ingest.common import doc_id_for

SourceFetcher = Callable[[str, Path], Path]

_ID_ONLY = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")
_PREFIXED = re.compile(r"^arxiv:\s*(\d{4}\.\d{4,5})(v\d+)?$", re.I)
_IN_URL = re.compile(r"arxiv\.org/(?:abs|pdf|e-print|src)/(\d{4}\.\d{4,5})(v\d+)?", re.I)

_INPUT = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
_DISPLAY = re.compile(
    r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?)\}(.+?)\\end\{\1\}"
    r"|\\\[(.+?)\\\]"
    r"|\$\$(.+?)\$\$",
    re.S,
)
_LABEL = re.compile(r"\\label\s*\{([^}]+)\}")
_SECTION = re.compile(r"^\\(?:sub)*section\*?\s*\{(.*?)\}", re.S)
_TITLE = re.compile(r"\\title\s*\{(.+?)\}\s*\n", re.S)
_MACRO = re.compile(
    r"^[ \t]*\\(?:newcommand|renewcommand|providecommand|DeclareMathOperator|def)\b.*$", re.M
)
_BEGIN_DOC = re.compile(r"\\begin\{document\}")
_END_DOC = re.compile(r"\\end\{document\}")

_ARG_CMD = re.compile(r"\\(?:textbf|textit|emph|texttt|textrm|mbox|text)\s*\{([^{}]*)\}")
_DROP_CMD = re.compile(r"\\(?:cite[a-z]*|ref|eqref|label|footnote|autoref)\s*\{[^}]*\}")
_BARE_CMD = re.compile(r"\\[A-Za-z@]+\*?")


def arxiv_id(source: str) -> str:
    """Accept '2211.17192', 'arXiv:2211.17192v2' or any arxiv.org URL."""
    s = source.strip()
    m = _IN_URL.search(s) or _PREFIXED.match(s) or _ID_ONLY.match(s)
    if not m:
        raise ValueError(f"not an arXiv id or URL: {source!r}")
    return m.group(1) + (m.group(2) or "")


def is_arxiv(source: str) -> bool:
    try:
        arxiv_id(source)
    except ValueError:
        return False
    return True


def fetch_source(aid: str, workdir: Path) -> Path:
    """Download the author's source package. Replaced by a fake in tests."""
    import urllib.request

    workdir.mkdir(parents=True, exist_ok=True)
    dest = workdir / f"{aid}.tar.gz"
    req = urllib.request.Request(
        f"https://arxiv.org/e-print/{aid}",
        headers={"User-Agent": "manim-engineer (https://github.com/NUSAISoc/manim-engineer)"},
    )
    with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)
    return dest


def extract_source(archive: Path, dest: Path) -> Path:
    """Unpack a source package (tarball, gzipped .tex, or plain .tex) and find the main file."""
    dest.mkdir(parents=True, exist_ok=True)
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            tf.extractall(dest, filter="data")
    else:
        raw = archive.read_bytes()
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError):
            pass
        (dest / "main.tex").write_bytes(raw)
    return main_tex(dest)


def main_tex(root: Path) -> Path:
    candidates = sorted(root.rglob("*.tex"))
    if not candidates:
        raise ValueError(f"no .tex file found under {root}")
    for p in candidates:
        if "\\documentclass" in p.read_text(errors="ignore"):
            return p
    return candidates[0]


def strip_comments(tex: str) -> str:
    """Drop % comments while respecting \\%."""
    out: list[str] = []
    for line in tex.splitlines():
        i, cut = 0, None
        while i < len(line):
            if line[i] == "\\":
                i += 2
                continue
            if line[i] == "%":
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def flatten(main: Path, root: Path, depth: int = 0) -> str:
    """Inline \\input / \\include / \\subfile so the paper is one string."""
    text = main.read_text(errors="ignore")
    if depth >= 8:
        return text

    def sub(m: re.Match) -> str:
        name = m.group(1).strip()
        for cand in (root / name, root / f"{name}.tex"):
            if cand.is_file():
                return flatten(cand, root, depth + 1)
        return ""

    return _INPUT.sub(sub, text)


def clean_text(s: str) -> str:
    s = _DROP_CMD.sub("", s)
    for _ in range(3):
        s, n = _ARG_CMD.subn(r"\1", s)
        if not n:
            break
    s = _BARE_CMD.sub("", s)
    s = s.replace("{", "").replace("}", "").replace("~", " ")
    return re.sub(r"\s+", " ", s).strip()


def document_from_latex(
    tex: str, source: str, title: str | None = None, arxiv_id_: str = ""
) -> Document:
    """Parse flattened LaTeX into Segments plus an equation ledger in `meta`."""
    doc_id = doc_id_for(source)
    macros = "\n".join(m.group(0).strip() for m in _MACRO.finditer(tex))
    if title is None:
        mt = _TITLE.search(tex)
        title = clean_text(mt.group(1)) if mt else ""

    body = tex
    if (bd := _BEGIN_DOC.search(body)) is not None:
        body = body[bd.end() :]
    if (ed := _END_DOC.search(body)) is not None:
        body = body[: ed.start()]

    equations: dict[str, tuple[str, str, str]] = {}

    def pull(m: re.Match) -> str:
        env = m.group(1) or ("display" if m.group(3) else "dollars")
        raw = m.group(2) or m.group(3) or m.group(4) or ""
        label = lm.group(1) if (lm := _LABEL.search(raw)) else ""
        latex = re.sub(r"\s+", " ", _LABEL.sub("", raw).replace("\\nonumber", "")).strip()
        key = f"\x00EQ{len(equations)}\x00"
        equations[key] = (latex, label, env)
        return f"\n\n{key}\n\n"

    body = _DISPLAY.sub(pull, body)

    segments: list[Segment] = []
    ledger: list[dict[str, str]] = []
    section = 0
    para = 0
    eq_n = 0

    def add(kind: SegmentKind, text: str, latex: str | None = None) -> str:
        nonlocal para, eq_n
        if not text:
            return ""
        if kind == SegmentKind.EQUATION:
            eq_n += 1
            pid = f"sec{section}.eq{eq_n}"
        elif kind == SegmentKind.HEADING:
            pid = f"sec{section}.h"
        else:
            para += 1
            pid = f"sec{section}.p{para}"
        segments.append(
            Segment(
                seg_id=f"s{len(segments):04d}",
                text=text,
                kind=kind,
                latex=latex,
                span=SourceSpan(modality=Modality.MANUSCRIPT, doc_id=doc_id, para_id=pid),
            )
        )
        return pid

    for block in re.split(r"\n\s*\n", body):
        block = block.strip()
        if not block:
            continue
        if block in equations:
            latex, label, env = equations[block]
            if not latex:
                continue
            pid = add(SegmentKind.EQUATION, latex, latex=latex)
            ledger.append(
                {
                    "label": label or pid,
                    "latex": latex,
                    "para_id": pid,
                    "env": env,
                    "tex_label": label,
                }
            )
            continue
        if (sm := _SECTION.match(block)) is not None:
            section += 1
            para = 0
            add(SegmentKind.HEADING, clean_text(sm.group(1)))
            add(SegmentKind.BODY, clean_text(block[sm.end() :]))
            continue
        add(SegmentKind.BODY, clean_text(block))

    return Document(
        doc_id=doc_id,
        title=title or arxiv_id_ or "untitled",
        modality=Modality.MANUSCRIPT,
        source=source,
        segments=segments,
        meta={
            "arxiv_id": arxiv_id_,
            "macros": macros,
            "equation_ledger": ledger,
            "has_equation_ledger": bool(ledger),
        },
    )


def load_arxiv(
    source: str,
    title: str | None = None,
    workdir: Path | None = None,
    fetch: SourceFetcher | None = None,
) -> Document:
    aid = arxiv_id(source)
    wd = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="me-arxiv-"))
    archive = (fetch or fetch_source)(aid, wd / "arxiv")
    main = extract_source(Path(archive), wd / "arxiv" / "src")
    tex = strip_comments(flatten(main, main.parent))
    return document_from_latex(
        tex, source=f"https://arxiv.org/abs/{aid}", title=title, arxiv_id_=aid
    )
