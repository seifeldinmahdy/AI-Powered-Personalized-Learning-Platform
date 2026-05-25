/**
 * Centralised API client.
 * All HTTP calls to Django (and, through it, to FastAPI) go through here.
 *
 * Uses JWT Bearer tokens with automatic refresh on 401 responses.
 */

import axios, { type AxiosInstance, type InternalAxiosRequestConfig, type AxiosError } from "axios";

const API_BASE_URL: string =
    import.meta.env.VITE_API_URL || "http://localhost:8000/api";

const api: AxiosInstance = axios.create({
    baseURL: API_BASE_URL,
    headers: { "Content-Type": "application/json" },
});

// ---- Request interceptor: attach access token ----
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem("access_token");
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// ---- Response interceptor: auto-refresh on 401 ----
let isRefreshing = false;
let failedQueue: Array<{
    resolve: (value: unknown) => void;
    reject: (reason: unknown) => void;
}> = [];

const processQueue = (error: unknown, token: string | null = null) => {
    failedQueue.forEach(({ resolve, reject }) => {
        if (error) {
            reject(error);
        } else {
            resolve(token);
        }
    });
    failedQueue = [];
};

api.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
        const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean; _sentToken?: string };

        // Only attempt refresh for 401 errors, and never retry login/signup/refresh endpoints
        if (
            error.response?.status === 401 &&
            !originalRequest._retry &&
            originalRequest.url &&
            !originalRequest.url.includes("/users/login/") &&
            !originalRequest.url.includes("/users/signup/") &&
            !originalRequest.url.includes("/users/refresh/")
        ) {
            // Check if the token has already been refreshed since this request was sent.
            // If so, just retry with the current token instead of triggering another refresh.
            const currentToken = localStorage.getItem("access_token");
            const sentToken = originalRequest._sentToken || originalRequest.headers.Authorization?.toString().replace("Bearer ", "");
            if (currentToken && sentToken && currentToken !== sentToken) {
                // Token was already refreshed by another request — just retry with the new token
                originalRequest.headers.Authorization = `Bearer ${currentToken}`;
                originalRequest._retry = true;
                return api(originalRequest);
            }

            if (isRefreshing) {
                // Another refresh is in progress — queue this request
                return new Promise((resolve, reject) => {
                    failedQueue.push({ resolve, reject });
                }).then((token) => {
                    originalRequest.headers.Authorization = `Bearer ${token}`;
                    return api(originalRequest);
                });
            }

            originalRequest._retry = true;
            isRefreshing = true;

            const refreshToken = localStorage.getItem("refresh_token");
            if (!refreshToken) {
                // No refresh token — force logout
                localStorage.removeItem("access_token");
                localStorage.removeItem("refresh_token");
                localStorage.removeItem("auth_user");
                window.location.href = "/login";
                return Promise.reject(error);
            }

            try {
                const { data } = await axios.post(`${API_BASE_URL}/users/refresh/`, {
                    refresh: refreshToken,
                });

                localStorage.setItem("access_token", data.access);
                localStorage.setItem("refresh_token", data.refresh);

                originalRequest.headers.Authorization = `Bearer ${data.access}`;
                processQueue(null, data.access);

                return api(originalRequest);
            } catch (refreshError) {
                processQueue(refreshError, null);
                // Refresh failed — tokens are invalid, force logout
                localStorage.removeItem("access_token");
                localStorage.removeItem("refresh_token");
                localStorage.removeItem("auth_user");
                window.location.href = "/login";
                return Promise.reject(refreshError);
            } finally {
                isRefreshing = false;
            }
        }

        return Promise.reject(error);
    }
);

// Also tag outgoing requests with the token they were sent with, so we can
// detect stale-token retries later in the response interceptor.
api.interceptors.request.use((config: InternalAxiosRequestConfig & { _sentToken?: string }) => {
    const token = localStorage.getItem("access_token");
    if (token) {
        config._sentToken = token;
    }
    return config;
});

// ---------- Types ----------
export interface RegisterData {
    email: string;
    password: string;
    full_name?: string;
    role?: "student" | "admin";
}

export interface CourseData {
    name: string;
    description?: string;
    lessons?: number;
    difficulty?: string;
}

export interface RecommendationData {
    student_id?: number;
    course_id?: number;
    [key: string]: unknown;
}

// ---------- Auth ----------
export const login = (data: { email: string; password: string }) =>
    api.post("/users/login/", data);
export const register = (data: RegisterData) =>
    api.post("/users/register/", data);
export const getMe = () => api.get("/users/me/");

// ---------- Courses ----------
export const getCourses = () => api.get("/courses/courses/");
export const getCourse = (id: number | string) =>
    api.get(`/courses/courses/${id}/`);
export const createCourse = (data: CourseData) =>
    api.post("/courses/courses/", data);

// ---------- Enrollments ----------
export const getEnrollments = () => api.get("/courses/enrollments/");
export const enroll = (courseId: number | string) =>
    api.post("/courses/enrollments/", { course: courseId });

// ---------- AI ----------
export const getRecommendations = (data: RecommendationData) =>
    api.post("/ai/recommend/", data);

// ---------- Health ----------
export const healthCheck = () => api.get("/health/");

export default api;
