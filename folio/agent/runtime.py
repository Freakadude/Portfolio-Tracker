"""Building the LLM client from the saved settings and the encrypted key."""

from __future__ import annotations

import httpx2
from sqlalchemy.orm import Session

from folio.agent.budget import agent_settings
from folio.agent.llm import LlmClient
from folio.config import Settings
from folio.security.secrets import SecretStore


def make_llm(
    db: Session, settings: Settings, transport: httpx2.BaseTransport | None = None
) -> LlmClient | None:
    """The client, or None when the agent is switched off or has no API key: with the agent
    off, rules, alerts and notifications keep working (FR-AG-09, NFR-06)."""
    if not agent_settings(db).enabled:
        return None
    key = SecretStore(db, settings.require_secret_key()).get("agent.anthropic_api_key")
    return LlmClient(key, transport=transport) if key else None
