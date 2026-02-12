/**
 * Centralised API client.
 * All HTTP calls to Django (and, through it, to FastAPI) go through here.
 */

import axios from "axios";

const API_BASE_URL = process.env.REACT_APP_API_URL || "http://localhost:8000/api";

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
});

// Attach auth token to every request if available
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Token ${token}`;
  }
  return config;
});

// ---------- Auth ----------
export const register = (data) => api.post("/users/register/", data);
export const getMe = () => api.get("/users/me/");

// ---------- Courses ----------
export const getCourses = () => api.get("/courses/courses/");
export const getCourse = (id) => api.get(`/courses/courses/${id}/`);
export const createCourse = (data) => api.post("/courses/courses/", data);

// ---------- Enrollments ----------
export const getEnrollments = () => api.get("/courses/enrollments/");
export const enroll = (courseId) =>
  api.post("/courses/enrollments/", { course: courseId });

// ---------- AI ----------
export const getRecommendations = (data) => api.post("/ai/recommend/", data);

// ---------- Health ----------
export const healthCheck = () => api.get("/health/");

export default api;
