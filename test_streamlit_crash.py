import sys
sys.path.insert(0, './src')
from pathway.config import get_settings
from pathway.models.schemas import StudentContext
from router import _get_generator

gen = _get_generator()
ctx = StudentContext(
    student_id="test_user",
    course_id="pythonlearn",
    mastery_level="Intermediate",
    use_synthetic_context=True
)

res = gen.generate(ctx)
print("Success:", len(res.sessions))
