"""Live updates as server-sent events (FR-DB-04).

The worker writes a row to `app_event` when new data lands; this stream polls that table and
sends each new row to the browser, which refreshes the widgets that depend on it. The two are
separate processes, so the database is the only thing they share (ADR 0018).
"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from folio.api.deps import UserDep
from folio.events import events_after, latest_event_id

router = APIRouter(tags=["events"])

POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 15.0  # keeps proxies from closing a quiet connection


def _first_id(request: Request, query_id: int | None, factory) -> int:  # type: ignore[no-untyped-def]
    """Where to resume: the browser's Last-Event-ID, else only what happens from now on."""
    header = request.headers.get("last-event-id", "")
    if header.isdigit():
        return int(header)
    if query_id is not None:
        return query_id
    with factory() as db:
        return latest_event_id(db)


@router.get("/events")
async def events(
    request: Request,
    _user: UserDep,
    last_event_id: Annotated[int | None, Query(ge=0)] = None,
    seconds: Annotated[float, Query(ge=0, le=3600)] = 0,
) -> StreamingResponse:
    """A stream of price_update and job_status events. `seconds` ends the stream after that
    long (0: until the browser disconnects); the browser reconnects and resumes by itself."""
    factory = request.app.state.session_factory

    def poll(after: int) -> list[tuple[int, str, dict[str, object]]]:
        with factory() as db:
            return [(e.id, e.type, dict(e.payload or {})) for e in events_after(db, after)]

    last = await run_in_threadpool(_first_id, request, last_event_id, factory)

    async def stream() -> AsyncIterator[str]:
        nonlocal last
        yield "retry: 3000\n\n"
        started = quiet_since = time.monotonic()
        while not await request.is_disconnected():
            rows = await run_in_threadpool(poll, last)
            for event_id, kind, payload in rows:
                yield f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(payload)}\n\n"
                last = event_id
            now = time.monotonic()
            if rows:
                quiet_since = now
            elif now - quiet_since >= HEARTBEAT_SECONDS:
                yield ": heartbeat\n\n"
                quiet_since = now
            if seconds and now - started >= seconds:
                return
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
