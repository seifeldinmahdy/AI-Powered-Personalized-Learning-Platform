import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.courses.models import PlacementQuestion, Course
from apps.courses.serializers import PlacementQuestionWriteSerializer

# Create a dummy course if not exists
course, _ = Course.objects.get_or_create(id=16, title='Test')

pq = PlacementQuestion(course=course, question='Test', options=['A','B','C','D'], correct_answer='A', topic='Test', order=1)
pq.save()

serializer = PlacementQuestionWriteSerializer(pq)
print('SERIALIZER DATA:', serializer.data)

pq.delete()
