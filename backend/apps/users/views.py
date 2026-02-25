from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.contrib.auth import authenticate
from .models import User
from .serializers import UserSerializer

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    # ---------------------------------------------------------
    # 1. Login Action
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
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
            return Response({
                'status': 'success',
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
            })
        else:
            return Response({'error': 'Invalid credentials'},
                            status=status.HTTP_401_UNAUTHORIZED)

    # ---------------------------------------------------------
    # 2. Signup Action
    # Endpoint: POST /api/users/signup/
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'], permission_classes=[AllowAny])
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
            return Response({
                'status': 'success',
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # ---------------------------------------------------------
    # 3. Profile Action (GET / PATCH)
    # Endpoint: GET  /api/users/me/?user_id=<id>
    #           PATCH /api/users/me/
    # ---------------------------------------------------------
    @action(detail=False, methods=['get', 'patch'], permission_classes=[AllowAny])
    def me(self, request):
        if request.method == 'GET':
            user_id = request.query_params.get('user_id')
            if not user_id:
                return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
            serializer = UserSerializer(user)
            return Response(serializer.data)

        # PATCH — update profile
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'error': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
