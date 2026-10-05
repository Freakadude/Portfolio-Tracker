"""Reading and writing the strategy YAML, with every problem tied to its line (FR-ST-01).

The text is parsed twice: once into values, once into PyYAML's node tree, which keeps where
each value sits. A validation error carries a path such as ("strategy", "sleeves", 2,
"target_pct"); walking that path through the node tree gives the line to show the owner.
Numbers are read as exact decimals, never through binary floats.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import yaml
from pydantic import ValidationError

from folio.strategies.schema import StrategyDef, StrategyDocument


@dataclass(frozen=True)
class Problem:
    line: int | None  # 1-based; None when the text has no line to point at
    path: str  # e.g. "strategy.sleeves[2].target_pct"
    message: str


class StrategyError(ValueError):
    """The YAML cannot be used; `problems` says what to fix, and where."""

    def __init__(self, problems: list[Problem]) -> None:
        first = problems[0]
        where = f"line {first.line}: " if first.line else ""
        super().__init__(f"{where}{first.message}")
        self.problems = problems


class _Loader(yaml.SafeLoader):
    """Safe loading, with floats kept as exact decimals."""


def _decimal(loader: yaml.SafeLoader, node: yaml.Node) -> Decimal:
    text = str(loader.construct_scalar(node)).replace("_", "")  # type: ignore[arg-type]
    try:
        return Decimal(text)
    except InvalidOperation:  # .inf and .nan
        raise yaml.constructor.ConstructorError(
            None, None, f"{text!r} is not a usable number", node.start_mark
        ) from None


_Loader.add_constructor("tag:yaml.org,2002:float", _decimal)


class _Dumper(yaml.SafeDumper):
    pass


def _represent_decimal(dumper: yaml.SafeDumper, value: Decimal) -> yaml.Node:
    text = format(value, "f")
    return dumper.represent_scalar(
        "tag:yaml.org,2002:float" if "." in text else "tag:yaml.org,2002:int", text
    )


_Dumper.add_representer(Decimal, _represent_decimal)


def _path_text(loc: tuple[int | str, ...]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _line_of(root: yaml.Node | None, loc: tuple[int | str, ...]) -> int | None:
    """The line of the deepest node the path reaches. Path parts that are not in the document
    (the rule type pydantic adds for a tagged union, or a key that is missing) are skipped, so
    a missing field points at the item that lacks it."""
    if root is None:
        return None
    node: yaml.Node = root
    for part in loc:
        if isinstance(node, yaml.MappingNode):
            found = next((v for k, v in node.value if getattr(k, "value", None) == part), None)
            if found is None:
                continue
            node = found
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int):
            if 0 <= part < len(node.value):
                node = node.value[part]
        # a scalar has nothing deeper
    return int(node.start_mark.line) + 1


def _message(error: Any) -> str:
    text = str(error["msg"])
    return text.removeprefix("Value error, ")


def parse(text: str) -> StrategyDef:
    """Validate the YAML and return the strategy. Raises StrategyError with line numbers."""
    try:
        data = yaml.load(text, Loader=_Loader)  # noqa: S506 - _Loader is a SafeLoader
        root = yaml.compose(text, Loader=_Loader)  # noqa: S506
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = None if mark is None else int(mark.line) + 1
        problem = exc.problem or "This is not valid YAML."
        raise StrategyError([Problem(line, "", f"YAML syntax: {problem}")]) from None
    except yaml.YAMLError as exc:
        raise StrategyError([Problem(None, "", f"YAML syntax: {exc}")]) from None
    if not isinstance(data, dict):
        raise StrategyError([Problem(1, "", "The file must start with `strategy:`.")])
    try:
        return StrategyDocument.model_validate(data).strategy
    except ValidationError as exc:
        problems = [
            Problem(_line_of(root, tuple(e["loc"])), _path_text(tuple(e["loc"])), _message(e))
            for e in exc.errors()
        ]
        raise StrategyError(problems) from None


def from_definition(definition: dict[str, Any]) -> StrategyDef:
    """Validate a strategy sent as JSON (the form view). Problems carry paths, not lines."""
    try:
        return StrategyDef.model_validate(definition)
    except ValidationError as exc:
        problems = [
            Problem(None, _path_text(("strategy", *tuple(e["loc"]))), _message(e))
            for e in exc.errors()
        ]
        raise StrategyError(problems) from None


def to_yaml(strategy: StrategyDef) -> str:
    """The canonical YAML of a strategy, as written when the form view saves."""
    data = {"strategy": strategy.model_dump(mode="python", exclude_none=False)}
    return yaml.dump(data, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=100)


def to_json(strategy: StrategyDef) -> dict[str, Any]:
    return strategy.model_dump(mode="json")
