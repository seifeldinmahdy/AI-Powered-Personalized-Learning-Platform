# System Module Breakdown

This document outlines the high-level modular architecture of the AI-Powered Personalized Learning Platform. The system is divided into four distinct, independent modules, each responsible for specific logical components of the educational pipeline.

---

## Module 1: Curriculum & Content Generation
**Focus:** Educational content creation, curriculum planning, and adaptability logic.

* **Slides Generation**
    * Dynamic creation of lecture slides using RAG-based content.
    * Structure includes titles, bullet points, and visual descriptions.
* **Assessments Generation (MCQ)**
    * Automated creation of Multiple Choice Questions based on slide content.
* **Placement Quiz**
    * Domain-specific diagnostic testing to establish student baselines.
* **Personalized Learning Pathway Generation**
    * Adaptive curriculum generation that modifies module sequence based on placement results and mastery models.

---

## Module 2: Embodied Avatar & Synthesis
**Focus:** The visual and auditory presentation layer (The "Face" and "Voice" of the system).

* **Avatar Design/Development**
    * 3D/2D visual pipeline for rendering the virtual tutor.
* **Emotional Expressions**
    * Mapping logic that translates system states into avatar blend shapes (smiling, neutral, concerned).
* **Lip Syncing**
    * Deep Learning models to synchronize avatar mouth movements with audio streams.
* **Text-to-Speech (TTS)**
    * Generation of natural-sounding speech audio from the Tutor's text responses.

---

## Module 3: Teaching & Student Interaction
**Focus:** The perception, intent understanding, and conversational logic (The "Brain" and "Ears").

* **Intent Classification**
    * NLP models to categorize student inputs (e.g., "Requesting Hint," "Answering Question," "Stopping Session").
* **Conversational Agent**
    * The core Tutor LLM/SLM responsible for pedagogical dialogue, hints, and explanations.
* **Automatic Speech Recognition (ASR)**
    * Speech-to-Text (STT) pipeline to transcribe student voice input.
* **Emotional Analysis**
    * Multi-modal perception system detecting student states (Confusion, Frustration) via audio/video analysis.

---

## Module 4: Interactive Practice & Code Evaluation
**Focus:** Hands-on skill application and security (The "Lab" environment).

* **Coding Assessments Generation**
    * Creation of coding challenges tailored to the current lesson topic.
* **Code Evaluation and Feedback**
    * Automated grading logic using static analysis and output verification.
* **Coding Environment + Security AI**
    * Secure browser-based IDE.
    * **Malicious Code Detection:** AI model to pre-scan and block harmful code before execution.