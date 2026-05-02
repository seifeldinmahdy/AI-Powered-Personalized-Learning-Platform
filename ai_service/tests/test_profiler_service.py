import pytest
from unittest.mock import patch, MagicMock
from schemas.student_context import UnifiedStudentContext, StudentProfileState, LiveSessionState
from services.profiler_service import update_profile

@pytest.mark.asyncio
async def test_update_profile_injects_student_context():
    profile = StudentProfileState(
        student_id="test_student",
        course_id="python_101",
        mastery_level="Intermediate",
        composition_mode="balanced",
        language_proficiency="Advanced",
        strengths=["for loops", "variables"],
        weaknesses=["classes"],
        incorrectly_answered=["q1", "q2"]
    )
    live = LiveSessionState()
    student_ctx = UnifiedStudentContext(profile=profile, live=live)
    
    with patch("services.profiler_service._get_groq_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"profile_summary": "Test", "profile_data": {}}'
        mock_client.chat.completions.create.return_value = mock_response
        
        await update_profile(
            student_id=123,
            lesson_title="Test Lesson",
            session_log=[],
            student_context=student_ctx
        )
        
        # Verify call was made
        mock_client.chat.completions.create.assert_called_once()
        
        # Extract the prompt sent to the LLM
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        user_prompt = next(m["content"] for m in messages if m["role"] == "user")
        
        # Assert the formatted structured block is in the prompt
        assert "STUDENT CONTEXT (Global):" in user_prompt
        assert "Mastery Level: Intermediate" in user_prompt
        assert "Language Proficiency: Advanced" in user_prompt
        assert "Strengths: for loops, variables" in user_prompt
        assert "Weaknesses: classes" in user_prompt
        assert "Incorrectly Answered: q1, q2" in user_prompt
