"""
Session Router — cleanup endpoint for shared session state.
"""

from fastapi import APIRouter, HTTPException
import logging
from services.session_store import get_session_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/session",
    tags=["Session Management"],
)


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Clean up shared session state when a session ends.

    Removes all shared context for the given ``session_id`` from the
    ``SharedSessionStore``.  This should be called by the frontend (or
    the tutor's stop-session flow) to free memory.

    Parameters
    ----------
    session_id : str
        The session to delete (path parameter).

    Returns
    -------
    dict
        ``{"success": True, "session_id": "..."}`` on success, or 404 if
        the session was not found.
    """
    store = get_session_store()
    deleted = store.delete_session(session_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found in shared store",
        )

    logger.info("Session %s cleaned up via DELETE endpoint", session_id)
    return {"success": True, "session_id": session_id}


@router.get("/{session_id}")
async def get_session_state(session_id: str):
    """Return the current shared session state (debug / introspection).

    Parameters
    ----------
    session_id : str
        The session to retrieve (path parameter).

    Returns
    -------
    dict
        The full shared session state, or 404 if not found.
    """
    store = get_session_store()
    data = store.get_session(session_id)

    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found in shared store",
        )

    return {"success": True, **data.model_dump()}


from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class UpdateLiveSessionRequest(BaseModel):
    current_slide_index: Optional[int] = None
    current_slide_title: Optional[str] = None
    current_slide_content: Optional[str] = None
    current_topic: Optional[str] = None
    current_subtopic: Optional[str] = None
    visited_slides_push: Optional[int] = None
    time_spent_update: Optional[Dict[str, float]] = None
    tutor_event_push: Optional[Dict[str, Any]] = None

@router.patch("/{session_id}")
async def update_session_state(session_id: str, request: UpdateLiveSessionRequest):
    """Update fields in the live session state."""
    store = get_session_store()
    data = store.get_session(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    live_kwargs = {}
    if request.current_slide_index is not None:
        live_kwargs["current_slide_index"] = request.current_slide_index
    if request.current_slide_title is not None:
        live_kwargs["current_slide_title"] = request.current_slide_title
    if request.current_slide_content is not None:
        live_kwargs["current_slide_content"] = request.current_slide_content
    if request.current_topic is not None:
        live_kwargs["current_topic"] = request.current_topic
    if request.current_subtopic is not None:
        live_kwargs["current_subtopic"] = request.current_subtopic

    # For lists and dicts, we need to merge the existing with the new
    if request.visited_slides_push is not None or request.time_spent_update is not None or request.tutor_event_push is not None:
        visited = list(data.live.visited_slides)
        if request.visited_slides_push is not None and request.visited_slides_push not in visited:
            visited.append(request.visited_slides_push)
            live_kwargs["visited_slides"] = visited

        if request.time_spent_update is not None:
            time_spent = dict(data.live.time_spent_per_slide)
            for k, v in request.time_spent_update.items():
                time_spent[k] = time_spent.get(k, 0.0) + v
            live_kwargs["time_spent_per_slide"] = time_spent

        if request.tutor_event_push is not None:
            events = list(data.live.tutor_events)
            events.append(request.tutor_event_push)
            live_kwargs["tutor_events"] = events

    if live_kwargs:
        updated = store.update_session(session_id, live_kwargs=live_kwargs)
        return {"success": True, "live": updated.live.model_dump()}
    
    return {"success": True, "live": data.live.model_dump()}
