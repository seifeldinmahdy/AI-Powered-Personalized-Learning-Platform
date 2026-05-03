"""
test_conversational_agent.py — Unit & Integration Tests for the Conversational Agent.

Covers:
    Unit         — TutorSession state, internal helpers (_advance, _peek_next),
                   repeat_lecture_chunk() behaviour.
    Integration  — Tutor router (POST /start, /continue, /ask, /repeat, /stop,
                   GET /status) and Intent router (POST /classify, /chat,
                   GET /health).

All LLM and TTS calls are mocked so tests run offline and fast.
"""

import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Path setup ────────────────────────────────────────────────────────
_AI_SERVICE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _AI_SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _AI_SERVICE_ROOT)


# ─────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────

SAMPLE_TOPICS = [
    {"name": "Variables", "subtopics": ["Intro to Variables", "Variable Types"]},
    {"name": "Functions", "subtopics": ["Defining Functions", "Return Values"]},
]

MOCK_LECTURE_TEXT = "Variables are named storage containers for data."
MOCK_REPHRASE_TEXT = "Think of variables as labelled boxes that hold information."
MOCK_ANSWER_TEXT = "Great question! A variable stores a value under a name you choose."

# ── Patch helpers ─────────────────────────────────────────────────────

def _mock_ollama(return_text: str = MOCK_LECTURE_TEXT):
    """Async mock for _call_ollama that returns *return_text* immediately."""
    return AsyncMock(return_value=return_text)


def _mock_tts():
    """Async mock for TTSService.synthesize() returning a tiny audio payload."""
    mock = AsyncMock(return_value={
        "audio_bytes": b"\xff\xfb\x90\x00",  # minimal MP3 header
        "content_type": "audio/mpeg",
        "voice": "en-US-JennyNeural",
        "rate": "+0%",
        "pitch": "+0Hz",
        "text_length": 10,
        "audio_size_bytes": 4,
        "inference_time": 0.01,
    })
    return mock


# ═════════════════════════════════════════════════════════════════════
# UNIT TESTS — TutorSession & tutor_service helpers
# ═════════════════════════════════════════════════════════════════════


class TestTutorSessionDataclass:
    """Tests for TutorSession dataclass fields and computed properties."""

    @pytest.fixture(autouse=True)
    def _clear_sessions(self):
        """Wipe the in-memory session store before each test."""
        import services.tutor_service as svc
        svc._sessions.clear()
        yield
        svc._sessions.clear()

    def _make_session(self, topics=None):
        from services.tutor_service import create_session
        from services.session_store import SharedSessionStore
        SharedSessionStore._instance = None
        with patch("services.session_store.SharedSessionStore.create_session"), \
             patch("services.session_store.SharedSessionStore.update_session"):
            return create_session(topics or SAMPLE_TOPICS, session_id="unit_test_sess")

    def test_initial_last_chunk_text_is_none(self):
        session = self._make_session()
        assert session.last_chunk_text is None

    def test_initial_last_chunk_subtopic_is_none(self):
        session = self._make_session()
        assert session.last_chunk_subtopic is None

    def test_progress_zero_initially(self):
        session = self._make_session()
        assert session.progress == 0.0

    def test_current_topic_is_first_topic(self):
        session = self._make_session()
        assert session.current_topic == "Variables"

    def test_current_subtopic_is_first_subtopic(self):
        session = self._make_session()
        assert session.current_subtopic == "Intro to Variables"

    def test_total_items_computed_correctly(self):
        session = self._make_session()
        # 2 subtopics per topic × 2 topics = 4
        assert session.total_items == 4


class TestInternalHelpers:
    """Tests for _advance() and _peek_next() without calling the LLM."""

    @pytest.fixture(autouse=True)
    def _clear_sessions(self):
        import services.tutor_service as svc
        svc._sessions.clear()
        yield
        svc._sessions.clear()

    def _make_session(self):
        import services.tutor_service as svc
        from services.tutor_service import TutorSession
        sess = TutorSession(session_id="helper_test", topics=SAMPLE_TOPICS)
        svc._sessions["helper_test"] = sess
        return sess

    def test_advance_moves_to_next_subtopic(self):
        from services.tutor_service import _advance
        sess = self._make_session()
        assert sess.current_subtopic == "Intro to Variables"
        _advance(sess)
        assert sess.current_subtopic == "Variable Types"

    def test_advance_moves_to_next_topic(self):
        from services.tutor_service import _advance
        sess = self._make_session()
        _advance(sess)  # → Variable Types
        _advance(sess)  # → next topic: Functions > Defining Functions
        assert sess.current_topic == "Functions"
        assert sess.current_subtopic == "Defining Functions"

    def test_advance_returns_true_when_finished(self):
        from services.tutor_service import _advance
        sess = self._make_session()
        for _ in range(4):
            finished = _advance(sess)
        assert finished is True
        assert sess.status == "finished"

    def test_peek_next_returns_next_subtopic(self):
        from services.tutor_service import _peek_next
        sess = self._make_session()
        nxt = _peek_next(sess)
        assert "Variable Types" in nxt

    def test_peek_next_returns_none_at_end(self):
        from services.tutor_service import _peek_next, _advance
        sess = self._make_session()
        for _ in range(3):  # advance to last subtopic
            _advance(sess)
        nxt = _peek_next(sess)
        assert nxt is None


class TestRepeatLectureChunkUnit:
    """Unit tests for repeat_lecture_chunk() without network calls."""

    @pytest.fixture(autouse=True)
    def _clear_sessions(self):
        import services.tutor_service as svc
        svc._sessions.clear()
        yield
        svc._sessions.clear()

    def _make_session_with_last_chunk(self):
        import services.tutor_service as svc
        from services.tutor_service import TutorSession
        sess = TutorSession(session_id="repeat_test", topics=SAMPLE_TOPICS)
        sess.last_chunk_text = MOCK_LECTURE_TEXT
        sess.last_chunk_subtopic = "Intro to Variables"
        sess.status = "lecturing"
        svc._sessions["repeat_test"] = sess
        return sess

    @pytest.mark.asyncio
    async def test_verbatim_returns_same_text_without_llm(self):
        self._make_session_with_last_chunk()
        with patch("services.tutor_service._call_ollama") as mock_llm, \
             patch("services.session_store.SharedSessionStore.update_session"):
            mock_llm.side_effect = AssertionError("LLM should not be called in verbatim mode")
            from services.tutor_service import repeat_lecture_chunk
            result = await repeat_lecture_chunk("repeat_test", mode="verbatim")
        assert result["text"] == MOCK_LECTURE_TEXT
        assert result["mode"] == "verbatim"

    @pytest.mark.asyncio
    async def test_rephrase_calls_llm_and_returns_new_text(self):
        self._make_session_with_last_chunk()
        with patch("services.tutor_service._call_ollama", _mock_ollama(MOCK_REPHRASE_TEXT)), \
             patch("services.session_store.SharedSessionStore.update_session"):
            from services.tutor_service import repeat_lecture_chunk
            result = await repeat_lecture_chunk("repeat_test", mode="rephrase")
        assert result["text"] == MOCK_REPHRASE_TEXT
        assert result["mode"] == "rephrase"
        assert "inference_time" in result

    @pytest.mark.asyncio
    async def test_rephrase_updates_last_chunk_text(self):
        import services.tutor_service as svc
        self._make_session_with_last_chunk()
        with patch("services.tutor_service._call_ollama", _mock_ollama(MOCK_REPHRASE_TEXT)), \
             patch("services.session_store.SharedSessionStore.update_session"):
            from services.tutor_service import repeat_lecture_chunk
            await repeat_lecture_chunk("repeat_test", mode="rephrase")
        sess = svc._sessions["repeat_test"]
        assert sess.last_chunk_text == MOCK_REPHRASE_TEXT

    @pytest.mark.asyncio
    async def test_repeat_raises_value_error_when_nothing_spoken(self):
        import services.tutor_service as svc
        from services.tutor_service import TutorSession
        sess = TutorSession(session_id="empty_test", topics=SAMPLE_TOPICS)
        svc._sessions["empty_test"] = sess  # last_chunk_text is None

        from services.tutor_service import repeat_lecture_chunk
        with pytest.raises(ValueError, match="Nothing to repeat"):
            await repeat_lecture_chunk("empty_test")

    @pytest.mark.asyncio
    async def test_repeat_raises_value_error_for_missing_session(self):
        from services.tutor_service import repeat_lecture_chunk
        with pytest.raises(ValueError, match="not found"):
            await repeat_lecture_chunk("no_such_session")

    @pytest.mark.asyncio
    async def test_repeat_does_not_advance_topic_pointer(self):
        import services.tutor_service as svc
        self._make_session_with_last_chunk()
        original_subtopic_idx = svc._sessions["repeat_test"].current_subtopic_idx
        with patch("services.tutor_service._call_ollama", _mock_ollama(MOCK_REPHRASE_TEXT)), \
             patch("services.session_store.SharedSessionStore.update_session"):
            from services.tutor_service import repeat_lecture_chunk
            await repeat_lecture_chunk("repeat_test", mode="rephrase")
        assert svc._sessions["repeat_test"].current_subtopic_idx == original_subtopic_idx


# ═════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Tutor Router (FastAPI TestClient)
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def tutor_client():
    """Return a FastAPI TestClient for the tutor router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.tutor import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_tutor_sessions():
    import services.tutor_service as svc
    svc._sessions.clear()
    yield
    svc._sessions.clear()


# ── shared patch context for all router tests ─────────────────────────
_PATCH_LLM    = "services.tutor_service._call_ollama"
_PATCH_TTS    = "services.tts_service.TTSService.synthesize"
_PATCH_STORE  = "services.session_store.SharedSessionStore.create_session"
_PATCH_UPDATE = "services.session_store.SharedSessionStore.update_session"


def _start_session(client, session_id="integ_sess"):
    with patch(_PATCH_STORE), patch(_PATCH_UPDATE):
        resp = client.post("/tutor/start", json={
            "session_id": session_id,
            "topics": [{"name": "Variables", "subtopics": ["Intro"]}],
            "voice": "en-US-JennyNeural",
        })
    return resp


class TestTutorRouterIntegration:

    def test_start_creates_session(self, tutor_client):
        resp = _start_session(tutor_client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["session_id"] == "integ_sess"

    def test_status_returns_session_state(self, tutor_client):
        _start_session(tutor_client)
        resp = tutor_client.get("/tutor/status", params={"session_id": "integ_sess"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["current_topic"] == "Variables"

    def test_status_404_for_unknown_session(self, tutor_client):
        resp = tutor_client.get("/tutor/status", params={"session_id": "ghost"})
        assert resp.status_code == 404

    def test_stop_ends_session(self, tutor_client):
        _start_session(tutor_client)
        resp = tutor_client.post("/tutor/stop", json={"session_id": "integ_sess"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "finished"

    def test_stop_404_for_unknown_session(self, tutor_client):
        resp = tutor_client.post("/tutor/stop", json={"session_id": "ghost"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_continue_returns_lecture_chunk(self, tutor_client):
        _start_session(tutor_client)
        with patch(_PATCH_LLM, _mock_ollama(MOCK_LECTURE_TEXT)), \
             patch(_PATCH_TTS, _mock_tts()), \
             patch(_PATCH_UPDATE):
            resp = tutor_client.post("/tutor/continue", json={
                "session_id": "integ_sess",
                "include_audio": False,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == MOCK_LECTURE_TEXT
        assert data["topic"] == "Variables"

    @pytest.mark.asyncio
    async def test_ask_returns_answer(self, tutor_client):
        _start_session(tutor_client)
        with patch(_PATCH_LLM, _mock_ollama(MOCK_ANSWER_TEXT)), \
             patch(_PATCH_TTS, _mock_tts()), \
             patch(_PATCH_UPDATE):
            resp = tutor_client.post("/tutor/ask", json={
                "session_id": "integ_sess",
                "question": "What is a variable?",
                "include_audio": False,
            })
        assert resp.status_code == 200
        assert resp.json()["answer"] == MOCK_ANSWER_TEXT

    @pytest.mark.asyncio
    async def test_repeat_verbatim_returns_last_chunk(self, tutor_client):
        """After one /continue, /repeat with verbatim returns the same text."""
        _start_session(tutor_client)
        # First, generate a lecture chunk to populate last_chunk_text
        with patch(_PATCH_LLM, _mock_ollama(MOCK_LECTURE_TEXT)), \
             patch(_PATCH_TTS, _mock_tts()), \
             patch(_PATCH_UPDATE):
            tutor_client.post("/tutor/continue", json={
                "session_id": "integ_sess", "include_audio": False
            })
        # Now repeat
        with patch(_PATCH_TTS, _mock_tts()), patch(_PATCH_UPDATE):
            resp = tutor_client.post("/tutor/repeat", json={
                "session_id": "integ_sess",
                "mode": "verbatim",
                "include_audio": False,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == MOCK_LECTURE_TEXT
        assert data["mode"] == "verbatim"

    @pytest.mark.asyncio
    async def test_repeat_rephrase_returns_new_text(self, tutor_client):
        _start_session(tutor_client)
        with patch(_PATCH_LLM, _mock_ollama(MOCK_LECTURE_TEXT)), \
             patch(_PATCH_TTS, _mock_tts()), \
             patch(_PATCH_UPDATE):
            tutor_client.post("/tutor/continue", json={
                "session_id": "integ_sess", "include_audio": False
            })
        with patch(_PATCH_LLM, _mock_ollama(MOCK_REPHRASE_TEXT)), \
             patch(_PATCH_TTS, _mock_tts()), \
             patch(_PATCH_UPDATE):
            resp = tutor_client.post("/tutor/repeat", json={
                "session_id": "integ_sess",
                "mode": "rephrase",
                "include_audio": False,
            })
        assert resp.status_code == 200
        assert resp.json()["text"] == MOCK_REPHRASE_TEXT

    def test_repeat_404_for_unknown_session(self, tutor_client):
        resp = tutor_client.post("/tutor/repeat", json={
            "session_id": "ghost",
            "mode": "rephrase",
        })
        assert resp.status_code == 404

    def test_repeat_400_when_nothing_spoken_yet(self, tutor_client):
        _start_session(tutor_client)
        with patch(_PATCH_UPDATE):
            resp = tutor_client.post("/tutor/repeat", json={
                "session_id": "integ_sess",
                "mode": "rephrase",
                "include_audio": False,
            })
        assert resp.status_code == 400
        assert "Nothing to repeat" in resp.json()["detail"]

    def test_repeat_400_for_invalid_mode(self, tutor_client):
        _start_session(tutor_client)
        resp = tutor_client.post("/tutor/repeat", json={
            "session_id": "integ_sess",
            "mode": "completely_wrong",
        })
        assert resp.status_code == 400


# ═════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS — Intent Router
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def intent_client():
    """Return a FastAPI TestClient for the intent router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.intent import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _mock_intent_service(predicted_name: str = "On-Topic Question",
                          confidence: float = 0.85):
    """Build a mock IntentService whose classify() returns a fixed prediction."""
    svc = MagicMock()
    svc.classifier = MagicMock()
    svc.classifier.model = MagicMock()
    svc.model_path = "/mock/best_model.pt"
    svc.classify.return_value = (
        [{
            "text": "mock input",
            "intent_name": predicted_name,
            "label_id": ["On-Topic Question", "Off-Topic Question",
                          "Emotional-State", "Pace-Related",
                          "Repeat/clarification"].index(predicted_name)
                         if predicted_name in ["On-Topic Question", "Off-Topic Question",
                                               "Emotional-State", "Pace-Related",
                                               "Repeat/clarification"] else 0,
            "confidence": confidence,
            "probabilities": {
                "On-Topic Question": 0.0,
                "Off-Topic Question": 0.0,
                "Emotional-State": 0.0,
                "Pace-Related": 0.0,
                "Repeat/clarification": 0.0,
                predicted_name: confidence,
            },
            "raw_prediction": None,
            "raw_confidence": None,
        }],
        0.05,  # inference_time
    )
    return svc


_PATCH_INTENT_SVC = "routers.intent.get_intent_service"
_PATCH_STORE_CTX  = "routers.intent.get_session_store"


class TestIntentRouterIntegration:

    def _store_mock(self):
        store = MagicMock()
        store.build_context_string.return_value = ""
        return store

    def test_classify_returns_prediction(self, intent_client):
        svc = _mock_intent_service("On-Topic Question")
        with patch(_PATCH_INTENT_SVC, return_value=svc), \
             patch(_PATCH_STORE_CTX, return_value=self._store_mock()):
            resp = intent_client.post("/intent/classify", json={
                "student_input": "How do for loops work?",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["predictions"]) == 1
        assert data["predictions"][0]["intent_name"] == "On-Topic Question"

    def test_classify_returns_inference_time(self, intent_client):
        svc = _mock_intent_service("Pace-Related")
        with patch(_PATCH_INTENT_SVC, return_value=svc), \
             patch(_PATCH_STORE_CTX, return_value=self._store_mock()):
            resp = intent_client.post("/intent/classify", json={
                "student_input": "Can you slow down?",
            })
        assert "inference_time_seconds" in resp.json()

    def test_chat_on_topic_response(self, intent_client):
        svc = _mock_intent_service("On-Topic Question")
        with patch(_PATCH_INTENT_SVC, return_value=svc), \
             patch(_PATCH_STORE_CTX, return_value=self._store_mock()):
            resp = intent_client.post("/intent/chat", json={
                "messages": [{"role": "user", "content": "How do loops work?"}],
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "On-Topic Question"
        assert data["confidence"] > 0.0

    def test_chat_repeat_clarification_response_includes_action(self, intent_client):
        """When intent is Repeat/clarification the response should reference /tutor/repeat."""
        svc = _mock_intent_service("Repeat/clarification")
        with patch(_PATCH_INTENT_SVC, return_value=svc), \
             patch(_PATCH_STORE_CTX, return_value=self._store_mock()):
            resp = intent_client.post("/intent/chat", json={
                "messages": [{"role": "user", "content": "Can you say that again?"}],
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "Repeat/clarification"
        assert "/tutor/repeat" in data["response"]

    def test_chat_400_when_no_messages(self, intent_client):
        resp = intent_client.post("/intent/chat", json={"messages": []})
        assert resp.status_code == 400

    def test_chat_400_when_no_user_message(self, intent_client):
        resp = intent_client.post("/intent/chat", json={
            "messages": [{"role": "assistant", "content": "Hello!"}],
        })
        assert resp.status_code == 400

    def test_health_returns_status_field(self, intent_client):
        svc = _mock_intent_service()
        with patch(_PATCH_INTENT_SVC, return_value=svc):
            resp = intent_client.get("/intent/health")
        assert resp.status_code == 200
        assert "status" in resp.json()
