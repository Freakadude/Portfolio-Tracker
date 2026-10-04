from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
_RESERVED = ("api/", "healthz", "readyz")


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
        if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)
