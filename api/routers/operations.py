"""Operations router (02): SSE stream of async doc/task operation events (03/05)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from ..deps import ActiveProject, get_active_project, get_operations
from ..services.operations import OperationManager

router = APIRouter(tags=["operations"])


@router.get("/operations/stream")
async def operations_stream(
    ap: ActiveProject = Depends(get_active_project),
    ops: OperationManager = Depends(get_operations),
):
    async def event_gen():
        async for msg in ops.stream(ap.name):
            yield {"event": msg["event"], "data": json.dumps(msg["data"])}

    return EventSourceResponse(event_gen())
