"""What the AI agent (Phase 4) is given from the strategy: the owner's principles and position
theses, word for word (FR-ST-07). The agent must flag any advice that departs from them; the
recommendation schema has a `departs_from_principles` field for that (folio/agent/schema.py).
"""

from __future__ import annotations

from typing import Any

from folio.strategies.schema import StrategyDef


def principles_and_theses(strategy: StrategyDef) -> dict[str, Any]:
    """Principles and theses exactly as the owner wrote them: no summarising, no reordering."""
    return {
        "principles": list(strategy.principles),
        "theses": [t.model_dump(mode="json") for t in strategy.theses],
    }
