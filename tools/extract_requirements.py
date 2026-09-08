#!/usr/bin/env python3
"""Emit a mechanical Markdown rendering of a .docx requirements document.

    python tools/extract_requirements.py path/to/requirements.docx > raw.md

This reads WordprocessingML directly (stdlib only) and preserves heading levels
and table structure. The result is an **unchecked** extraction: it is a reading
aid for producing or reviewing docs/requirements/cpu-stage-extract.md, and it is
not an authoritative replacement for the source document.
"""

from __future__ import annotations

import sys
import zipfile
from xml.etree import ElementTree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(W + "t"))


def paragraph_style(paragraph: ElementTree.Element) -> str:
    properties = paragraph.find(W + "pPr")
    if properties is None:
        return ""
    style = properties.find(W + "pStyle")
    return (style.get(W + "val") or "") if style is not None else ""


def render(element: ElementTree.Element, out: list[str]) -> None:
    for child in element:
        if child.tag == W + "p":
            text = paragraph_text(child)
            style = paragraph_style(child)
            if style.startswith("Heading"):
                level = int("".join(c for c in style if c.isdigit()) or "1")
                out.append("#" * level + " " + text)
            elif style == "Title":
                out.append("# " + text)
            else:
                out.append(text)
        elif child.tag == W + "tbl":
            rows = []
            for row in child.findall(W + "tr"):
                cells = [
                    " ".join(paragraph_text(p) for p in cell.findall(W + "p"))
                    .strip()
                    .replace("|", r"\|")
                    for cell in row.findall(W + "tc")
                ]
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                rows.insert(1, "|" + "---|" * (rows[0].count("|") - 1))
                out.extend([*rows, ""])
        else:
            render(child, out)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    with zipfile.ZipFile(argv[1]) as archive:
        # The input is the project owner's own requirements document, committed
        # to this repository and hash-recorded in docs/requirements/README.md.
        # It is not untrusted input, and pulling in defusedxml for a developer
        # reading aid would add a dependency the package does not otherwise need.
        root = ElementTree.fromstring(archive.read("word/document.xml"))  # noqa: S314
    body = root.find(W + "body")
    if body is None:
        print("no document body found", file=sys.stderr)
        return 1
    lines: list[str] = []
    render(body, lines)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
