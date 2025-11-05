<h1 align="center">AI-Powered Personalized Educational Platform</h1>

<p align="center">
An adaptive, real-time one-on-one AI tutoring system that personalizes learning through voice interaction, emotion-aware responses, dynamic content generation, and live coding, all running directly in the browser.</p>

---

## 🎯 Project Vision

The goal is to build an intelligent, emotionally responsive, and personalized AI tutoring platform. This system blends adaptive learning, real-time voice interaction (via WebRTC), and emotional understanding into one seamless educational experience, moving beyond static content to provide true 1-on-1 mentorship.

## 🧩 Core Features

The platform is built around a core set of AI-driven and interactive features to create an engaging experience.

| Feature | Description |
| :--- | :--- |
| 🤖 **Personalized Learning Agent** | The core AI tutor that delivers lessons adaptively based on learner progress.
| 🗣️ **Live 1-on-1 Voice Sessions** | Real-time, voice-based interaction (ASR/TTS) between student and AI tutor.
| 🖥️ **Synchronized Slides** | AI generates and displays structured learning slides, changing them contextually.
| ⌨️ **Embedded Code Editor** | Interactive coding environment with real-time evaluation and safe moderation.
| 📈 **Adaptive Assessment** | Provides interactive quizzes and guidance, adapting to help students correct mistakes.
| 😊 **Expressive Avatar** | 2D/3D visual representation of the AI tutor that displays realistic facial expressions.
| 😢 **Student Emotion Tracking** | Analyzes learner emotions via voice/video to adapt pacing and tone.

## 🛠️ Tech Stack & Architecture

This project uses a hybrid Python backend to separate core API logic from high-throughput asynchronous tasks. Django serves as the robust core for data and authentication, while FastAPI provides a high-performance engine for real-time AI agent interactions.

### **Frontend**
* **Framework:** **ReactJS** (Chosen for its simplicity, modularity, and strong community support)
* **Real-time Communication:** **WebRTC** (via `simple-peer` or `adapter.js`) for live, peer-to-peer voice/video sessions.

### **Backend (Hybrid)**
* **Core API & ORM:** **Django** with **Django REST Framework (DRF)**. A self-contained, Python-native framework for the core API, authentication, and user data management.
* **Async Agent & Signaling:** **FastAPI (Python)**. Used for high-performance, asynchronous AI agent communication, background tasks, and handling real-time signaling.

### **AI & NLP**
* **Core Logic:** **LLM APIs** (e.g., ChatGPT, Qwen)
* **Agent Frameworks:** **Langchain** / **Langraph** (To build and manage the AI tutor's reasoning flow)
* **Factual Grounding:** **RAG** (Retrieval-Augmented Generation)

### **Database & Caching**
* **Primary DB:** **PostgreSQL** (Manages user data, progress, and structured content)
* **Vector DB:** **Pinecone** / **ChromaDB** (For scalable, low-latency similarity search for RAG)
* **Caching & Task Queues:** **Redis** (In-memory caching and message broker)

### **DevOps & Tools**
* **Containerization:** **Docker** (For consistent development and deployment environments)
* **Version Control:** **Git** & **GitHub**

## 🚀 Getting Started

Instructions on setting up and running the project locally.

### Prerequisites

* Node.js (v18+)
* Python (v3.10+)
* PostgreSQL
* Redis
* Docker (Recommended)
* API keys for (OpenAI, Pinecone, etc.)
