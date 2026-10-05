"""The structured output the agent returns (spec appendix C).

The schema avoids numeric bounds and string lengths, which structured outputs do not support,
and sets `additionalProperties: false` everywhere. `departs_from_principles` is where the
agent must say when its advice goes against the owner's principles (FR-ST-07). Enum values are
compared case-insensitively when the output is read, because capitalisation is not guaranteed.
"""

from __future__ import annotations

from typing import Any

ACTION_TYPES = (
    "direct_contribution",
    "trim",
    "rebalance",
    "hold",
    "review_thesis",
    "watch",
    "hedge_check",
    "info",
)

RECOMMENDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["digest", "recommendations"],
    "properties": {
        "digest": {"type": "string"},
        "recommendations": {"type": "array", "items": {"$ref": "#/$defs/rec"}},
    },
    "$defs": {
        "rec": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "action_type",
                "severity",
                "subjects",
                "title",
                "summary",
                "rationale",
                "calculation_id",
                "evidence",
                "sources",
                "confidence",
                "departs_from_principles",
                "what_would_change_this",
                "expires_in_days",
            ],
            "properties": {
                "action_type": {"type": "string", "enum": list(ACTION_TYPES)},
                "severity": {
                    "type": "string",
                    "enum": ["info", "low", "medium", "high", "critical"],
                },
                "subjects": {"type": "array", "items": {"type": "string"}},
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "rationale": {"type": "string"},
                "calculation_id": {"type": ["string", "null"]},
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind", "ref", "note"],
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "signal",
                                    "news_cluster",
                                    "metric",
                                    "macro_series",
                                    "web_source",
                                ],
                            },
                            "ref": {"type": "string"},
                            "note": {"type": "string"},
                        },
                    },
                },
                "sources": {"type": "array", "items": {"type": "string", "format": "uri"}},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                "departs_from_principles": {"type": ["string", "null"]},
                "what_would_change_this": {"type": "string"},
                "expires_in_days": {"type": "integer"},
            },
        }
    },
}
