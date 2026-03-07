/**
 * Centralised API client.
 * All HTTP calls to Django (and, through it, to FastAPI) go through here.
 */

import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from "axios";

const API_BASE_URL: string =
    import.meta.env.VITE_API_URL || "http://localhost:8000/api";

const api: AxiosInstance = axios.create({
    baseURL: API_BASE_URL,
    headers: { "Content-Type": "application/json" },
});

// Attach auth token to every request if available
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem("token");
    if (token) {
        config.headers.Authorization = `Token ${token}`;
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
