from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
_RESERVED = ("api/", "healthz", "readyz")
# The page must be asked for again after an update, or a browser keeps showing the old one with
# the old scripts. The files under assets/ carry a hash of their content in their name, so a
# changed file has a new name and the old ones can be kept for good.
REVALIDATE = {"Cache-Control": "no-cache"}
FOREVER = {"Cache-Control": "public, max-age=31536000, immutable"}


def mount_spa(app: FastAPI, static_dir: Path = STATIC_DIR) -> None:
    """Serve the built React app, with index.html as the fallback for client-side routes."""
    index = static_dir / "index.html"
    if not index.is_file():
        return  # development: the Vite dev server serves the UI

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith(_RESERVED):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (static_dir / path).resolve()
        root = static_dir.resolve()
        if path and candidate.is_file() and root in candidate.parents:
            hashed = candidate.parent == root / "assets"
            return FileResponse(candidate, headers=FOREVER if hashed else REVALIDATE)
        return FileResponse(index, headers=REVALIDATE)
