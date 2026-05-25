from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth import authenticate
from .models import User, StudentProfile, UserPreferences
from .serializers import UserSerializer, StudentProfileSerializer, UserPreferencesSerializer


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        """
        Lock down the default ModelViewSet CRUD actions.
        Only admins can list/retrieve/create/update/destroy users directly.
        Custom actions define their own permissions.
        """
        if self.action in ('list', 'retrieve', 'create', 'update', 'partial_update', 'destroy'):
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    # ---------------------------------------------------------
    # Helper: build JWT token pair for a user
    # ---------------------------------------------------------
    @staticmethod
    def _get_tokens_for_user(user):
        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }

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
                return Response({'error': 'Invalid credentials'},
                                status=status.HTTP_401_UNAUTHORIZED)

        user = authenticate(username=login_id, password=password)

        if user is not None:
            if not user.is_active:
                return Response({'error': 'Account is disabled'},
                                status=status.HTTP_403_FORBIDDEN)

            tokens = self._get_tokens_for_user(user)
            return Response({
                'status': 'success',
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'access': tokens['access'],
                'refresh': tokens['refresh'],
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
        username = request.data.get('username', '').strip()
        email = request.data.get('email', '').strip()
        password = request.data.get('password', '')
        role = request.data.get('role', 'student')  # Default to 'student' if not sent

        # Validate required fields
        if not username or not email or not password:
            return Response({'error': 'Username, email, and password are required'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Validate password length
        if len(password) < 8:
            return Response({'error': 'Password must be at least 8 characters long'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Check if username exists
        if User.objects.filter(username=username).exists():
            return Response({'error': 'Username already taken'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Check if email exists
        if User.objects.filter(email=email).exists():
            return Response({'error': 'An account with this email already exists'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Prevent non-admins from creating admin/instructor accounts
        if role not in ('student',):
            role = 'student'

        # Create the user securely (hashes password)
        try:
            user = User.objects.create_user(username=username, email=email, password=password, role=role)
            tokens = self._get_tokens_for_user(user)
            return Response({
                'status': 'success',
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'access': tokens['access'],
                'refresh': tokens['refresh'],
            }, status=status.HTTP_201_CREATED)
        except Exception:
            return Response({'error': 'Could not create account. Please try again.'},
                            status=status.HTTP_400_BAD_REQUEST)

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
    # 6. Logout Action — blacklists the refresh token
    # Endpoint: POST /api/users/logout/
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def logout(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'error': 'Refresh token is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            # Token is already blacklisted or invalid — that's fine
            pass
        return Response({'status': 'logged out'}, status=status.HTTP_200_OK)

    # ---------------------------------------------------------
    # 7. Token Refresh
    # Endpoint: POST /api/users/refresh/
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], permission_classes=[AllowAny], authentication_classes=[])
    def refresh(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'error': 'Refresh token is required'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            from rest_framework_simplejwt.serializers import TokenRefreshSerializer
            serializer = TokenRefreshSerializer(data={'refresh': refresh_token})
            serializer.is_valid(raise_exception=True)
            return Response(serializer.validated_data)
        except (TokenError, Exception):
            return Response({'error': 'Invalid or expired refresh token'},
                            status=status.HTTP_401_UNAUTHORIZED)

    # ---------------------------------------------------------
    # 8. Admin: List all students with profiles
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
    # 9. Leaderboard
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
