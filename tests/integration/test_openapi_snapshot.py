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


# Two routers that name a model alike make FastAPI rename both in the OpenAPI document
# (folio__api__routers__<router>__<Name>), which breaks the web client's `schemas['<Name>']` types.
# These are the ones that already existed; a new model must get a name of its own.
ALREADY_QUALIFIED = {
    "folio__api__routers__accounts__AccountIn",
    "folio__api__routers__accounts__AccountOut",
    "folio__api__routers__analytics__SeriesOut",
    "folio__api__routers__imports__PreviewOut",
    "folio__api__routers__instruments__PriceOut",
    "folio__api__routers__macro__SeriesOut",
    "folio__api__routers__positions__MatchOut",
    "folio__api__routers__positions__PriceOut",
    "folio__api__routers__setup__AccountIn",
    "folio__api__routers__setup__AccountOut",
    "folio__api__routers__transactions__MatchOut",
}


def test_a_new_response_model_does_not_share_its_name_with_another(settings: Settings) -> None:
    schemas = create_app(settings).openapi()["components"]["schemas"]
    qualified = {name for name in schemas if name.startswith("folio__")}
    assert qualified <= ALREADY_QUALIFIED, (
        f"Rename the new model(s) so the name is unique: {sorted(qualified - ALREADY_QUALIFIED)}"
    )
