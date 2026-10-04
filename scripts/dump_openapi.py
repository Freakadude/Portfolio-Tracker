"""Print the OpenAPI spec to stdout (used by `npm run gen:api`). Needs no database or real key."""

import json
import sys
import tempfile
from pathlib import Path

from folio.api.app import create_app
from folio.config import Settings


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            secret_key="openapi-dump-only-key-0123456789abcdef",  # noqa: S106
            db_url=f"sqlite:///{Path(tmp) / 'dump.db'}",
            _env_file=None,  # type: ignore[call-arg]
        )
        app = create_app(settings, static_dir=Path(tmp) / "none")
        sys.stdout.write(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
