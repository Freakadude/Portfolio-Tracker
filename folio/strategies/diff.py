"""A side-by-side diff of two strategy versions (FR-ST-01)."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Literal

Kind = Literal["same", "changed", "added", "removed"]


@dataclass(frozen=True)
class DiffRow:
    kind: Kind
    old_line: int | None
    old_text: str | None
    new_line: int | None
    new_text: str | None


def side_by_side(old: str, new: str) -> list[DiffRow]:
    """Rows pairing the old and new text line by line; a changed block pairs its lines up and
    pads the shorter side."""
    a, b = old.splitlines(), new.splitlines()
    rows: list[DiffRow] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            rows += [
                DiffRow("same", i + 1, a[i], j + 1, b[j])
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True)
            ]
        elif tag == "delete":
            rows += [DiffRow("removed", i + 1, a[i], None, None) for i in range(i1, i2)]
        elif tag == "insert":
            rows += [DiffRow("added", None, None, j + 1, b[j]) for j in range(j1, j2)]
        else:  # replace
            for k in range(max(i2 - i1, j2 - j1)):
                i, j = i1 + k, j1 + k
                left = i < i2
                right = j < j2
                kind: Kind = "changed" if left and right else ("removed" if left else "added")
                rows.append(
                    DiffRow(
                        kind,
                        i + 1 if left else None,
                        a[i] if left else None,
                        j + 1 if right else None,
                        b[j] if right else None,
                    )
                )
    return rows
