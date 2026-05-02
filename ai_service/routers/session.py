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
