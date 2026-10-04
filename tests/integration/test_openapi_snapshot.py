import json
from pathlib import Path

from folio.api.app import create_app
from folio.config import Settings

SNAPSHOT = Path(__file__).resolve().parents[2] / "web" / "openapi.json"


def test_committed_openapi_snapshot_matches_the_api(settings: Settings) -> None:
    """The web client's types are generated from web/openapi.json. If this fails, the API
    changed: run `npm run gen:api` in web/ and commit web/openapi.json and src/api/schema.d.ts."""
    current = create_app(settings).openapi()
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert current == committed
