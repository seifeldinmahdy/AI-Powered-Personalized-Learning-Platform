from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from .models import User, StudentProfile, UserPreferences
from .serializers import UserSerializer, StudentProfileSerializer, UserPreferencesSerializer

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    # ---------------------------------------------------------
    # 1. Login Action
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], permission_classes=[AllowAny], authentication_classes=[])
    def login(self, request):
        login_id = request.data.get('username', '').strip()
        password = request.data.get('password')

        if not login_id or not password:
            return Response({'error': 'Username/email and password are required'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Allow login with email: look up the username by email
        if '@' in login_id:
            try:
                login_id = User.objects.get(email=login_id).username
            except User.DoesNotExist:
                return Response({'error': 'No account found with that email'},
                                status=status.HTTP_401_UNAUTHORIZED)

        user = authenticate(username=login_id, password=password)

        if user is not None:
            token, _ = Token.objects.get_or_create(user=user)
            return Response({
                'status': 'success',
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'token': token.key,
            })
        else:
            return Response({'error': 'Invalid credentials'},
                            status=status.HTTP_401_UNAUTHORIZED)

    # ---------------------------------------------------------
    # 2. Signup Action
    # Endpoint: POST /api/users/signup/
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], permission_classes=[AllowAny], authentication_classes=[])
    def signup(self, request):
        username = request.data.get('username')
        email = request.data.get('email')
        password = request.data.get('password')
        role = request.data.get('role', 'student') # Default to 'student' if not sent

        # Check if username exists
        if User.objects.filter(username=username).exists():
            return Response({'error': 'Username already taken'}, status=status.HTTP_400_BAD_REQUEST)

        # Create the user securely (hashes password)
        try:
            user = User.objects.create_user(username=username, email=email, password=password, role=role)
            token, _ = Token.objects.get_or_create(user=user)
            return Response({
                'status': 'success',
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'token': token.key,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # ---------------------------------------------------------
    # 3. Profile Action (GET / PATCH)
    # Endpoint: GET  /api/users/me/
    #           PATCH /api/users/me/
    # ---------------------------------------------------------
    @action(detail=False, methods=['get', 'patch'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        user = request.user

        if request.method == 'GET':
            serializer = UserSerializer(user)
            return Response(serializer.data)

        # PATCH — update profile
        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ---------------------------------------------------------
    # 4. Student Profile (GET / PATCH)
    # Endpoint: GET/PATCH /api/users/student-profile/
    # ---------------------------------------------------------
    @action(detail=False, methods=['get', 'patch'], url_path='student-profile',
            permission_classes=[permissions.IsAuthenticated])
    def student_profile(self, request):
        profile, _ = StudentProfile.objects.get_or_create(user=request.user)

        if request.method == 'GET':
            serializer = StudentProfileSerializer(profile)
            return Response(serializer.data)

        serializer = StudentProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ---------------------------------------------------------
    # 5. User Preferences (GET / PATCH)
    # Endpoint: GET/PATCH /api/users/preferences/
    # ---------------------------------------------------------
    @action(detail=False, methods=['get', 'patch'],
            permission_classes=[permissions.IsAuthenticated])
    def preferences(self, request):
        prefs, _ = UserPreferences.objects.get_or_create(user=request.user)

        if request.method == 'GET':
            serializer = UserPreferencesSerializer(prefs)
            return Response(serializer.data)

        serializer = UserPreferencesSerializer(prefs, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ---------------------------------------------------------
    # 6. Logout Action
    # Endpoint: POST /api/users/logout/
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def logout(self, request):
        try:
            request.user.auth_token.delete()
        except Token.DoesNotExist:
            pass
        return Response({'status': 'logged out'}, status=status.HTTP_200_OK)

    # ---------------------------------------------------------
    # 7. Admin: List all students with profiles
    # Endpoint: GET /api/users/admin-students/
    # ---------------------------------------------------------
    @action(detail=False, methods=['get'], url_path='admin-students',
            permission_classes=[permissions.IsAuthenticated])
    def admin_students(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)

        from apps.gamification.models import UserAchievement
        from apps.courses.models import Enrollment

        students = User.objects.filter(role='student').prefetch_related(
            'student_profile', 'earned_achievements'
        )
        result = []
        for student in students:
            profile = getattr(student, 'student_profile', None)
            enrollment_count = Enrollment.objects.filter(student=student).count()
            achievement_count = UserAchievement.objects.filter(user=student).count()
            result.append({
                'id': student.id,
                'username': student.username,
                'email': student.email,
                'joined': student.date_joined,
                'level': profile.level if profile else 1,
                'current_xp': profile.current_xp if profile else 0,
                'current_streak': profile.current_streak if profile else 0,
                'total_minutes_learned': profile.total_minutes_learned if profile else 0,
                'enrollments': enrollment_count,
                'achievements': achievement_count,
            })

        return Response(result)

    # ---------------------------------------------------------
    # 8. Leaderboard
    # Endpoint: GET /api/users/leaderboard/
    # ---------------------------------------------------------
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def leaderboard(self, request):
        from django.db.models import F
        students = (
            User.objects.filter(role='student')
            .select_related('student_profile')
            .order_by(F('student_profile__current_xp').desc(nulls_last=True))[:20]
        )
        current_user_id = request.user.id
        top20 = []
        current_user_in_top = None
        for rank, student in enumerate(students, start=1):
            profile = getattr(student, 'student_profile', None)
            entry = {
                'rank': rank,
                'username': student.username,
                'level': profile.level if profile else 1,
                'current_xp': profile.current_xp if profile else 0,
                'current_streak': profile.current_streak if profile else 0,
            }
            top20.append(entry)
            if student.id == current_user_id:
                current_user_in_top = entry

        # Build current_user entry (rank outside top 20 if not already there)
        if current_user_in_top:
            current_user_entry = current_user_in_top
        else:
            own_profile = getattr(request.user, 'student_profile', None)
            own_xp = own_profile.current_xp if own_profile else 0
            higher_count = StudentProfile.objects.filter(current_xp__gt=own_xp).count()
            current_user_entry = {
                'rank': higher_count + 1,
                'username': request.user.username,
                'level': own_profile.level if own_profile else 1,
                'current_xp': own_xp,
                'current_streak': own_profile.current_streak if own_profile else 0,
            }

        return Response({'top20': top20, 'current_user': current_user_entry})
