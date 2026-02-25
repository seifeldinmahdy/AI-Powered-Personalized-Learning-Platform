



AI-Powered Personalized 
Learning Platform

Course Code: CSAI 498

Prepared By

Student Name
ID
Program
Seif Mahdy 
202200990
DSAI
Youssef Mohammed 
202202105
DSAI
Yusuf Tamer Sahab
202201929
DSAI
Ziad Shaaban
202201093
DSAI


Under the Supervision of:
Dr. Mohamed Ghalwash








School of Computational Sciences and Artificial Intelligence
University of Science and Technology
Zewail City of Science, Technology, and Innovation




Date of Submission: December 13, 2025

Table of Contents

1. Project Summary	3
2. Progress Since Proposal	3
2.1 Completed Tasks	3
2.2 Evidence of Progress	4
2.3 Research & Early Implementation	4
3. System Architecture Diagram	5
4. Component Breakdown	5
5. Data Flow	8
5.1 Data Flow Diagram	8
6. Work Breakdown Structure (WBS)	10
7. Risk Analysis & Mitigation Strategies	12


1. Project Summary
The project develops an AI‑powered personalized learning platform that delivers real‑time sessions through an AI tutor with personalized explanations, assessments, and voice interaction for learners interested in or currently studying programming and computer science, particularly those who lack affordable, high‑quality individualized support. The scope focuses on a web‑based platform where students first choose a course, then take a placement test to assess their knowledge of that course before the system generates a tailored course pathway, combining an Agentic RAG system, real‑time ASR/TTS interface, slides generation, adaptive pacing and explanations, an embedded code editor, and an interactive avatar‑driven learning interface.

2. Progress Since Proposal
2.1 Completed Tasks
1- Market Research
2- Market Survey
3- ERD
4- Decision flowchart
5- GitHub issues
6- User Stories
7- Functional and Non-functional requirements
8- Initial UI design
9- Initial literature review
10- Project modular design






2.2 Evidence of Progress

Figure 1: ERD Diagram (Task 3)

For the market survey (Task 2), we conducted a survey through this Form
The initial UI design (Task 8) is available at the following link
All remaining tasks are documented in the Project Repository

2.3 Research Conducted
Our research, conducted throughout this period, focused on the following areas: practical implementation of AI slide generation for automated content creation [1], speech emotional expression [2], the development of robust techniques for real-time facial expression recognition [3, 4], and the applied use of AI in education, specifically targeting enhanced one-on-one tutoring systems [5]. Throughout this process, we regularly discussed our findings and methodologies with Dr. Mohamed Ghalwash.
To advance our research in Intelligent Tutoring Systems, we proactively contacted Professor Janos Perczel, CEO of Polygence, a prominent figure in one-on-one educational models. We sought access to his work in AI tutoring to potentially integrate it into our ongoing research and are currently awaiting his response regarding a potential collaboration.



3. System Architecture Diagram

					Figure 2: System Architecture Diagram
4. Component Breakdown

Component
Main Functionality
Inputs/Expected Outputs
Technology Stack
Conversational Agent (AI Tutor)
Acts as the course instructor, generates step‑by‑step explanations, and answers questions.


Inputs: text from ASR, retrieved documents, and student state.
Outputs: speech from TTS
Open-source LLM via ChatGPT OSS/Qwen API with LangChain for tool-calling, hosted in FastAPI backend to call other services
Orchestration Agent
Monitors the state of the Session, coordinates the timing between all the agents, and ensures that the Context of Student is being read from and written to correctly, and feeding other agents with relevant course information.


Inputs: Session state, student context, agent status updates.
Outputs : Workflow coordination signals, context routing instructions.


LangChain/LangGraph with circuit breakers to define agent graphs and tools, with FastAPI microservice async endpoints.
Agentic RAG
Processes placement quiz results to determine proficiency; retrieves relevant content; generates course pathway.


Inputs: Placement quiz results, student context, course learning objectives.
Outputs: Structured learning pathway, relevant textbook sections for slide generation.


LangChain agent framework + Open-source LLM with tool-use capabilities
Slide Generation Agent
Converts textbook content to slide format; incorporates relevant figures; adjusts complexity based on student context.


Inputs:Textbook sections, student context
Outputs:Formatted slides with visual representations of concepts


LLMs + MLLMs (Multi-Modal LLM) [1]
Assessment Generation Agent
Builds and updates quizzes, coding questions, and post‑session assessments tailored to the student’s weaknesses.


Inputs: course syllabus, current session content, student context, previous assessment results.
Outputs: Assessment questions, scoring, knowledge gaps.
LLM‑based generator wrapped in FastAPI, or use of a transformer‑based classification model.
Real‑Time Voice Layer (ASR/TTS)
Converts student speech to text and tutor text to speech, manages streaming audio during sessions.


Inputs: microphone audio, tutor response.
Outputs: transcribed text for agents and synthesized audio for the student.
External ASR/TTS APIs connected with FastAPI, WebRTC with simple‑peer/adapter.js in React for low‑latency.
Intent Classifier
Analyzes student interactions to determine their communication intent and routes appropriate responses.


Inputs: User prompt
Outputs: Decision based on the intention


MLP classifier with text to vector layer
Context Cache / Session Memory
Stores short‑term and long‑term session context, recent dialogue, selected course, pathway, emotional state, and performance.
Inputs: Emotional analysis results, assessment answers, session interactions.
Outputs: Updated student context including emotional state and learning gaps.
Redis (in-memory data store) with RedisJSON (for structured context storage).
Vector Database
Storage of the reference educational materials (books) in embeddings for RAG.
Inputs: Pre-processed chunks.
Outputs: Relevant textbook sections based on learning context..
Pinecone or ChromaDB for scalable semantic search, integrates seamlessly with LangChain tools.
SQL Database
Stores structured data: users, courses, enrollment
Inputs:Student data, course enrollment, course data
Outputs: Student profile records, enrollment history, educational background
PostgreSQL (ACID-compliant, supports JSONB for flexible data requirements) with Django ORM
NoSQL
Stores generated slides and generated assessments of the student.


Inputs: Generated slides, assessment questions, student responses.
Outputs: Session content for current and past sessions, assessment history.
MongoDB for schema‑flexible content, pairs well with dynamic slide and assessment structures generated by LLMs.
Emotional Analysis
Analyzes student emotional state during sessions.
Inputs: Audio/video from session interface.
Outputs: Emotional state indicators (frustration, engagement, confusion).
Combined CNN Architecture for Audio Emotional Analysis [2] + Facial Expression Analysis



3D Avatar
Emotionally expressive visual representation of the instructor with synchronized lip-syncing and facial expressions.
Inputs: Teaching scripts from Conversational Agent, Emotional state indicators from Emotional Analysis
Outputs: Real-time rendered 3D face mesh with appropriate expressions, Lip-synced animation synchronized with speech audio
Blender for design, MediaPipe Face Mesh for facial landmarks, Wav2Lip or RIFE, WebGL for browser-based rendering
Embedded Code Editor
Let students write and run code snippets during sessions.
Inputs: code, programming language.
Outputs: execution results.
React components
Session Component
A page where the student interacts with the tutor, slides, and code editor.
Inputs: user actions (voice, text, clicks).
Outputs: UI updates, messages.
React components
Naïve RAG
Answers student questions during sessions.


Inputs: Student questions, current session context, student context.
Outputs: Contextual answers to questions, confidence scores.
LangChain with open-source SLM



5. Data Flow 
The tutoring platform initiates the personalized learning process upon student enrollment, storing personal data in an SQL Database. After a placement quiz establishes initial knowledge, this information is sent to the Agentic RAG, which establishes the student's initial context. The Agentic RAG then queries a Vector Database to retrieve relevant course materials and generate a personalized learning pathway, specifying textbook content for slide and script generation. This pathway is passed to the Orchestration Agent, which directs the Slide Generation Agent to create session slides using the student context. These generated slides, along with assessments created by the Assessment Agent, are stored in a No-SQL Database.
During a session, the Orchestration Agent loads the slides and uses the learning pathway and student context to generate a dynamic teaching script, which is loaded into the Session Interface. Concurrently, the Emotional Analysis Model monitors the student's video and audio data, updating the student context with detected emotions to allow the Orchestration Agent to adapt the script in real-time. Assessment results also continuously update the student context cache, informing future content generation and instruction. For student questions, the Orchestration Agent utilizes a Naive RAG to query the Vector Database for accurate answers. The final response is converted to speech via TTS, delivered by a 3D Avatar that lip-syncs and displays context-appropriate emotional expressions.

5.1 Data Flow Diagram


Figure 3: Data Flow Diagram

6. Work Breakdown Structure (WBS)

WBS Number
Task Title
Task Owner
Start Date
Due Date
Status

1
Project Documentation








1.1
Project Proposal
All Team
10/20/25
10/25/25
Completed
1.2
Market Survey
Yusuf Sahab
11/25/25
11/30/25
Completed
1.3
Market Research
Seif Mahdy
12/10/25
12/13/25
Completed
1.4
Initial System Design & Work Division
All Team
12/10/25
12/13/25
Completed
1.4.1
Modular Project Design
All Team
12/10/25
12/13/25
Completed
1.4.2
System Architecture Design
Seif Mahdy
12/10/25
12/13/25
Completed
1.4.3
Data Flow Diagram
All Team
12/10/25
12/13/25
Completed
1.4.4
Work Breakdown Structure
Yusuf Sahab
12/10/25
12/13/25
Completed
1.4.5
Design Initial Wireframes
Seif Mahdy
12/10/25
12/13/25
Completed
1.4.6
Risk Analysis
Seif Mahdy
12/10/25
12/13/25
Completed
1.5
Initial UI Design
Ziad Shaaban
12/10/25
12/13/25
Completed
1.6
Final Report
All Team
12/31/25
1/3/26
In Progress
1.6.1
Literature Review
Yusuf Sahab
12/31/25
1/3/26
In Progress
1.6.2
Requirements Analysis
All Team
12/31/25
1/3/26
In Progress
1.6.3
Challenges and Solutions
All Team
12/31/25
1/3/26
In Progress
1.6.4
Work Summary
All Team
12/31/25
1/3/26
In Progress
1.7
Entity Relationship Diagram (ERD)
Ziad Shaaban
12/21/25
12/22/25
In Progress
2
Data Collection, Database, and RAG Setup








2.1
No-SQL Database setup
Youssef Ahmed
12/21/25
12/27/25
In Progress
2.1.1
Scraping SlideShare Data
Seif Mahdy
12/21/25
1/10/26
In Progress
2.1.2
Scraping Assessment Data
Seif Mahdy
12/21/25
1/10/26
In Progress
2.2
Postgres Database Setup
Ziad Shaaban
12/21/25
12/27/25
In Progress
2.3
Vector Database Setup
YS, SM
12/21/25
12/27/25
In Progress
2.3.1
Collecting Books for the courses
Seif Mahdy
12/21/25
1/10/26
In Progress
2.4
Redis Cache Setup
YS, YA
12/21/25
12/27/25
In Progress
2.5
Naive RAG Setup
Yusuf Sahab
1/3/26
1/10/26
In Progress
2.6
Agentic RAG Setup
Seif Mahdy
1/3/26
1/10/26
In Progress
3
From Scratch model building








3.1
Slides Generation Model
Seif Mahdy
1/10/26
1/31/26
Not Started
3.2
Intent Classification Model
Yusuf Sahab
1/10/26
1/31/26
Not Started
3.3
Assessment Generation Model (MCQ)
Seif Mahdy
1/10/26
1/31/26
Not Started
3.4
Assessment Generation Model (Code)
Ziad Shaaban
1/10/26
1/31/26
Not Started
3.5
Emotional Analysis (Audio)
Youssef Ahmed
1/10/26
1/31/26
Not Started
3.6
Emotional Analysis (Video)
Youssef Ahmed
1/10/26
1/31/26
Not Started
3.7
Emotionally intelligent avatar
Youssef Ahmed
1/10/26
1/31/26
Not Started
3.8
Avatar Lip Syncing
Youssef Ahmed
1/10/26
1/31/26
Not Started
4
Finetuned Models








4.1
Learning Pathway Generator
Seif Mahdy
1/10/26
1/31/26
Not Started
4.2
Conversational Agent
Yusuf Sahab
1/10/26
1/31/26
Not Started
5
Software Development








5.1
Set up React front-end
Ziad Shaaban
1/3/26
1/10/26
Not Started
5.2
Set up Django Backend
Ziad Shaaban
1/3/26
1/10/26
Not Started
5.3
Set up Fast API
All Team
1/3/26
1/10/26
Not Started
5.4
ASR setup
Yusuf Sahab
1/3/26
1/10/26
Not Started
5.5
TTS setup
Youssef Ahmed
1/3/26
1/10/26
Not Started
5.6
Design and develop the avatar
Youssef Ahmed
1/3/26
1/10/26
Not Started
6
Testing and Deployment








6.1
Test all the models
All Team
1/31/26
2/7/26
Not Started
6.2
Integrate Everything
All Team
1/31/26
2/7/26
Not Started
6.3
Final Testing
All Team
2/7/26
2/14/26
Not Started
6.4
Deploy to production
All Team
2/14/26
2/28/26
Not Started
6.5
Final Report
All Team
2/28/26
3/7/26
Not Started






7. Risk Analysis & Mitigation Strategies

Risk Category
Risk Description
Probability / Impact
Mitigation Strategy
Technical
LLM Provider Availability: API outage or service disruption from the primary Large Language Model provider.
Low / Critical
Implement a fallback mechanism to an open-source model to ensure service continuity.
Technical
GPU Inference Provider Availability: Lack of capacity or service failure from the GPU provider is necessary for fine-tuned/custom models.
Medium / High
Reserve dedicated GPU instances rather than relying solely on spot instances, and maintain a backup configuration for a secondary cloud provider.
Resource
Lack of Communication between team members: Breakdown in information exchange between team members, which can lead to misaligned objectives and duplicated work.
Low / Medium
Establish strict weekly follow-up meetings and a shared Kanban board to ensure everyone is aligned on the objectives.
Technical
Incorrect Intent Classification: The system misinterprets the student's conversational query or goal.
Medium / High
Implement a confidence score threshold, if the score is below X%, the system must ask a clarifying question ("Did you mean...?") rather than guessing.
Technical
Incorrect Course Pathway Generation: The system generates a curriculum that ignores the specific skill gaps and strengths of the student identified in the placement test.
Medium / High
Implement a validation layer that checks the generated pathway against the student’s skill profile and forces regeneration if specific adaptation criteria are missing.
Technical
Speech-to-Text errors: The STT fails to correctly classify the user's spoken input.
High / Medium
Display the transcribed text to the student for confirmation/editing before the AI processes the answer, and use a context-aware STT model.
Technical
LLM Hallucination: The LLM generates factually incorrect information in the slides or assessments.
High / High
Use Retrieval-Augmented Generation (RAG) strictly grounded in verified course material and implement a "human-in-the-loop" review step.
Technical
Context Window Overflow: The volume of session data (history, RAG, profile) exceeds the LLM's memory limit, causing the model to forget instructions or crash.
High / High
Implement token budgeting to allocate fixed limits for system instructions and RAG context, combined with recursive summarization within the Orchestrator to condense older dialogue into a persistent memory state, ensuring the prompt remains within the model's effective context window.
Technical
Code Execution Security: Student code submitted in the embedded editor contains malicious logic (e.g., infinite loops, system calls)
Low / Critical
Implement a hybrid defense technique where a lightweight AI model pre-scans code for malicious patterns, followed by execution in an isolated sandbox to catch any threats the AI misses.
Technical
Avatar/TTS Sync Issues: The Avatar's lip movements drift out of sync with the audio due to network jitter.
Medium/Low
Implement a Client-Side Buffer. Download the first chunk of audio and animation data before playing and synchronize them using the client's local clock rather than relying on stream arrival times.
Timeline
Integration Difficulties: Connecting and debugging the communication between multiple AI agents.
High/High
Use API-First Development, where the JSON inputs/outputs are defined for every agent first. Allow team members to build their parts independently using "mock data" before connecting them.
Technical
STT Phonetic Errors in Technical Jargon: The STT misinterprets technical terms, causing the Tutor to give a nonsensical answer.
High/Medium
Dynamically update the STT model's vocabulary bias with keywords from the active module to ensure technical terms are recognized correctly.

	

References
[1] H. Zheng et al., “PPTAgent: Generating and evaluating presentations beyond text-to-slides,” Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing, pp. 14413–14429, 2025. doi:10.18653/v1/2025.emnlp-main.728 
[2] R. Begazo, A. Aguilera, I. Dongo, and Y. Cardinale, “A combined CNN Architecture for Speech Emotion Recognition,” Sensors, vol. 24, no. 17, p. 5797, Sep. 2024. doi:10.3390/s24175797 
[3] A. I. Siam, N. F. Soliman, A. D. Algarni, F. E. Abd El-Samie, and A. Sedik, “Deploying machine learning techniques for human emotion detection,” Computational Intelligence and Neuroscience, vol. 2022, pp. 1–16, Feb. 2022. doi:10.1155/2022/8032673 
[4] P. Dhope and M. B. Neelagar, “Real-time emotion recognition from facial expressions using artificial intelligence,” 2022 2nd International Conference on Artificial Intelligence and Signal Processing (AISP), pp. 1–6, Feb. 2022. doi:10.1109/aisp53593.2022.9760654 
[5] J. Perczel, J. Chow, and D. Demszky, "TeachLM: Post-Training LLMs for Education Using Authentic Learning Data," arXiv preprint arXiv:2510.05087, 2025.


------------------------




AI-Powered Personalized 
Educational Platform

Team Number: 31

Prepared By

Student Name
ID
Program
Seif Mahdy 
202200990
DSAI
Youssef Mohammed 
202202105
DSAI
Yusuf Tamer Sahab
202201929
DSAI
Ziad Shaaban
202201093
DSAI



Course Code: CSAI 498

Under the Supervision of:
Dr. Mohamed Ghalwash












School of Computational Sciences and Artificial Intelligence
University of Science and Technology
Zewail City of Science, Technology, and Innovation

Academic Year: 2025/2026
Date of Submission: 1/1/2026
Table of Contents
1. Introduction	4
1.1 Abstract	4
1.2 Problem Statement	4
1.3 Motivation and Impact	4
1.4 Proposed Solution Overview	5
2. Literature Review and Market Survey	5
2.1 Literature Review	5
2.1.1 Automated Teaching Pipeline Generation from Structured Content	5
2.1.2 Agentic and Multi-Agent Systems for Instructional Design	6
2.1.3 Pedagogical Optimization of Language Models for Tutoring	7
2.1.4 Knowledge-Grounded Tutoring and Retrieval-Augmented Generation	7
2.1.5 Automated Assessment and Content Generation	8
2.2 Market Survey Analysis	8
2.3 Existing Systems and Market Solutions	9
2.4 Comparative Analysis	9
1. Technologies	9
2. Features	10
3. Limitations	10
2.5 Identified Gap	10
3. Requirements Analysis	11
3.1 Functional Requirements	11
Section 1: User Management & Profiling	11
Section 2: Learner Modeling & Personalization	11
Section 3: Curriculum & Content Generation	11
Section 4: Slide Generation & Delivery	12
Section 5: Assessment Generation	12
Section 6: Assessment Evaluation & Feedback	12
Section 7: Interactive Learning Support (Tutor Agent)	12
Section 8: Coding Practice & Evaluation	12
Section 9: Avatar Instructor	13
Section 10: Data Management & Session Handling	13
3.2 Non-Functional Requirements	13
Section 1: Performance	13
Section 2: Security	14
Section 3: Scalability	14
Section 4: Usability	14
Section 5: Reliability	14
4. System Design	15
4.1 Overall System Architecture	15
4.2 Component Breakdown	15
4.3 Design Decisions and Rationale	18
4.4 DSAI – Data Science & AI	19
5. Project Timeline	21
6. Challenges & Solutions	23
7. Work Summary	24
References	25


1. Introduction
1.1 Abstract
This project develops an AI-Powered Personalized Learning Platform intended to transform programming and Computer Science education through real-time, adaptive one-on-one tutoring. Addressing the limitations of static e-learning and the high cost of human tutoring, the system uses a Multi-Agent architecture to create a highly responsive learning environment. The platform integrates an Agentic Retrieval-Augmented Generation (RAG) system to construct dynamic course pathways based on initial placement tests, ensuring content is tailored to the learner's proficiency. Key technical features include a central Orchestration Agent for workflow management, real-time Automatic Speech Recognition (ASR) and Text-to-Speech (TTS) for natural voice interaction, and generation of slides and assessments. Furthermore, the system includes an emotionally intelligent 3D avatar and an embedded code editor to facilitate multimodal engagement. 
1.2 Problem Statement
While digital education has expanded access to learning materials, traditional e-learning platforms and conventional classrooms suffer from significant limitations regarding personalization and interactivity.
One-Size-Fits-All Instruction: In standard classrooms, instructors cannot easily tailor explanations to individual learning speeds or styles (e.g., visual vs. auditory preferences).
Passive Learning: Most online platforms rely on pre-recorded content with limited interactivity, failing to engage students dynamically or address specific misconceptions in real-time.
Accessibility of Tutoring: High-quality, personalized one-on-one tutoring is often cost-prohibitive or geographically inaccessible for many students.
Lack of Adaptive Feedback: Existing automated systems often struggle to interpret the user's emotional state or specific intent, leading to generic responses that do not resolve the learner's confusion.
These issues result in a "gap" where students who lack affordable individual support often struggle to master complex technical subjects like Computer Science.
1.3 Motivation and Impact
The primary motivation behind this project is to make high-quality education accessible by building an autonomous system capable of replicating the efficacy of a human tutor. 
Project Impact:
Scalability: The platform offers an infinitely scalable tutoring solution that is not constrained by human availability or time zones.
Enhanced Engagement: By utilizing a 3D avatar that utilizes lip-syncing and facial expressions based on real-time emotional analysis, the system provides a deeper connection with the learner compared to text-based interfaces.
Dynamic Curriculum: Unlike static courses, the use of Agentic RAG allows the curriculum to evolve based on the student's performance, ensuring time is spent efficiently on weak areas rather than redundant topics.

1.4 Proposed Solution Overview
The proposed solution is a web-based, AI-driven learning platform designed specifically for Computer Science and programming education. The system is built upon a Multi-Agent Architecture orchestrated to deliver a smooth learning experience.
The core components of the solution include:
Agentic RAG & Pathway Generation: Upon enrollment, students take a placement test. The Agentic RAG system analyzes the results and queries a Vector Database to generate a personalized learning pathway, selecting specific textbook content for instruction.
Orchestration & Conversational Agents: An Orchestration Agent manages the session flow, coordinating between the Conversational Agent (the AI Tutor) and other specialized agents to ensure context-aware responses.
Real-Time Content Generation:
Slide Generation Agent: dynamically converts textbook material into formatted slides with visual representations.
Assessment Agent: generates quizzes and coding challenges tailored to the student's identified knowledge gaps.
Multimodal Interface: The student interacts via an embedded code editor and real-time voice (ASR/TTS). A 3D Avatar serves as the visual interface, displaying lip-synced speech and emotional expressions derived from an analysis of the student's audio and video input.

2. Literature Review and Market Survey
2.1 Literature Review
2.1.1 Automated Teaching Pipeline Generation from Structured Content
Recent research has begun to address the computational challenge of automating the end-to-end teaching of the comprehensive process of generating curricula, instructional scripts, assessments, and adaptive learning experiences from source materials. Early work focused on isolated components; contemporary systems increasingly integrate multiple stages into coherent workflows.
Lecture Script and Content Generation.
Wang et al. [1] introduced AUTOLV, an end-to-end system generating lecture videos from annotated slides using speech synthesis and talking-head generation. While this work addresses video generation, it assumes pre-authored slides and speaker scripts exist; the upstream problem of generating those scripts from raw content remains largely unaddressed. More recent work has employed large language models (LLMs) to generate lecture scripts directly. Script2Transcript [2] generates transcripts from slide titles, establishing a baseline for automated explanation generation. Building on this, contemporary systems like MAIC [3] demonstrate that multimodal LLMs can extract content from textbook slides, generate structured knowledge representations, and produce pedagogically coherent lecture scripts, substantially advancing the automation frontier.
Knowledge Extraction and Representation.
A critical challenge in automated instruction is extracting and structuring domain knowledge to support coherent, connected explanations. Traditional Knowledge Space Theory-based systems (e.g., ALEKS [4]) require manual knowledge engineering; contemporary approaches employ LLMs for automated knowledge graph construction. Knowledge graphs enable two critical functions: (1) structured representation of concept relationships (prerequisites, related concepts, misconceptions), and (2) knowledge-guided retrieval that incorporates contextual relationships rather than relying solely on semantic similarity. Research on Knowledge Graph-enhanced Retrieval-Augmented Generation (KG-RAG) demonstrates that structured knowledge retrieval outperforms vanilla RAG by 35% on educational assessments ($n=76$), validating the pedagogical advantage of interconnected knowledge representation aligned with constructivist learning theory [5].
2.1.2 Agentic and Multi-Agent Systems for Instructional Design
The emergence of large language models as foundational agents has enabled the simulation of complex instructional workflows through multi-agent systems. Unlike single-LLM tutors that lack explicit instructional reasoning, multi-agent architectures distribute pedagogical tasks across specialized agents, each embodying specific expertise.
MAIC: Massive AI-Empowered Courses.
The MAIC framework [3] represents the most comprehensive implementation of end-to-end automated teaching using multi-agent orchestration. The system decomposes teaching into two major pipelines: Teaching Pipeline (Course Preparation): The Read stage employs multimodal LLMs to extract textual and visual content from instructor-provided slides, generate comprehensive descriptions, and construct knowledge taxonomies. The subsequent Plan stage generates lecture scripts with embedded teaching actions (e.g., ShowFile, ReadScript, AskQuestion) using long-context encoding, produces question banks, and configures teacher and teaching assistant agents via RAG over extended course materials. Critically, all outputs undergo human review and refinement before deployment, instantiating a supervised automation workflow. Learning Pipeline (Multi-Agent Classroom): MAIC instantiates a "1 student + $N$ AI agents" classroom where a teacher agent controls progression through pre-planned action sequences, a teaching assistant agent manages classroom order and safety, and four classmate agents (Class Clown, Deep Thinker, Note Taker, Inquisitive Mind) simulate peer interactions. A hidden Manager Agent routes control to the most appropriate agent, enabling dynamic response to student needs while maintaining instructional coherence.
Affective Computing and Emotional Companionship.
A key innovation in agentic classrooms is the "Session Controller," which enforces pedagogical principles such as Emotional Companionship and In-depth Discussion. To effectively implement such companionship, systems require robust affect detection capabilities. Recent technical advancements, such as the combined Convolutional Neural Network (CNN) architecture proposed by Begazo et al. [6], have achieved significant improvements in Speech Emotion Recognition (SER) by effectively extracting spectral and prosodic features. Integrating such architectures allows the Session Controller to accurately detect student frustration or disengagement from voice inputs and trigger empathetic interventions, thereby grounding the "Emotional Companionship" principle in measurable sensor data.
Instructional Agents: ADDIE-Grounded Course Generation.
Complementary work by Yao et al. [7] introduced Instructional Agents, a multi-agent system grounded in the ADDIE instructional design framework. The system's core innovation is embedding pedagogical theory directly into agent workflows through role-based collaboration:
Analyze Phase: Teaching Faculty and Instructional Designer agents collaboratively define learning objectives, analyze learner profiles, and assess institutional constraints.
Design Phase: Agents develop syllabi with structured topics and readings, plan instructional flows for each weekly topic, and design multi-stage assessments aligned with objectives.
Develop Phase: Teaching Faculty, Instructional Designer, and Teaching Assistant agents generate LaTeX slides, slide scripts, and assessments from design outputs. Generated materials undergo validation by Teaching Faculty and Program Chair agents, followed by pilot testing with simulated student agents.
Evaluation across five computer science courses using the Quality Matters higher education rubric revealed that "Full Co-Pilot Mode" achieves a 3.98/5 average quality (vs. 3.22 for Autonomous mode). Cost analysis showed Autonomous mode at $0.22 per course, while Full Co-Pilot costs 0.36 and requires 30 to 45 minutes of instructor effort [7].
2.1.3 Pedagogical Optimization of Language Models for Tutoring
A fundamental challenge is that off-the-shelf LLMs, optimized for general helpfulness and productivity, systematically encode behaviors antithetical to effective tutoring. Expert teaching requires withholding answers, asking probing questions, and dynamically adapting to learner confusion, friction-generating behaviors that conflict with standard LLM training objectives.
TeachLM: Post-Training on Authentic Learning Data.
Perczel et al. [8] introduced TeachLM, an LLM optimized for teaching through parameter-efficient fine-tuning on 100,000+ hours of authentic one-on-one tutoring sessions from the Polygence platform. The work established that prompt engineering, even sophisticated multi-round prompt refinement, cannot bridge the pedagogical gap. By contrast, fine-tuning on authentic learning data yielded substantial pedagogical improvements: doubled student talk time (from ~5–15% to ~30%, aligning with human tutoring), improved questioning style (reduced multiple questions per turn), extended dialogue length (+50% turns), and greater personalization.
2.1.4 Knowledge-Grounded Tutoring and Retrieval-Augmented Generation
RAG systems address hallucination and knowledge staleness by retrieving relevant documents before generation. However, standard RAG relies on semantic similarity, which cannot capture the structured domain knowledge necessary for coherent educational explanations.
Knowledge Graph-Enhanced RAG (KG-RAG).
Dong et al. [5] introduced KG-RAG, integrating structured knowledge graphs with LLM-based tutoring. Their key finding is that knowledge graphs enable concept relationship traversal, yielding contextually rich explanations that align with constructivist learning theory. In a controlled evaluation (n=76 students, finance domain), KG-RAG-generated answers achieved 35% higher assessment scores (6.37/10 vs. 4.71/10 for standard RAG, Cohen's d=0.86, p<0.001$). Knowledge graph construction employed DeepSeek-V3 with expert validation, ensuring accuracy while automating extraction. This work establishes knowledge-guided retrieval as a critical architectural component for coherent automated instruction.
2.1.5 Automated Assessment and Content Generation
MCQ Generation and Quality Assurance.
Comparative studies confirm that GPT-4-generated multiple-choice questions achieve pedagogical quality comparable to or exceeding human-authored questions [9]. Critically, AI-generated MCQs demonstrate superior learning objective alignment, a metric of instructional coherence. Guidelines for high-quality AI-driven assessment emphasize structured prompting (explicit MCQ templates), multi-round refinement, domain grounding via knowledge graphs, and human subject-matter expert review.
Lecture Script and Slide Generation.
MAIC's lecture script generation component [3] produces pedagogically aligned, contextually coherent scripts by conditioning on previous slide content, visual elements, and structured knowledge. Evaluation across slide planning baselines revealed that MAIC-FuncGen achieves 4.00/5.0 overall quality.
Extending the capabilities of slide generation, Zheng et al. [10] introduced PPTAgent, an autonomous framework designed to address the "visual-centric" nature of presentations often overlooked by text-summarization approaches. Unlike traditional models that treat slides as static text containers, PPTAgent employs a two-stage, edit-based workflow (Presentation Analysis and Presentation Generation) to simulate human design processes. This approach significantly improves structural coherence and visual design, ensuring that generated materials maintain narrative flow and aesthetic quality comparable to human-edited standards.


2.2 Market Survey Analysis
To validate the project's motivation, we conducted a targeted survey of 55 respondents, most of them are undergraduate university students (76.4%) aged 18-24. The majority of respondents (63.6%) identified "Programming and Computer Science" as the primary subject requiring assistance.
Key Findings & Pain Points:
Motivation & Structure: The most significant challenges reported were "Staying motivated" (65.5%) and "Finding structured material" (52.7%). This validates the need for our system's Personalized Learning Pathway, which 60% of respondents rated as a "most valuable feature".
Interactive Needs: While 90.9% of respondents currently use YouTube and 41.8% use online courses (Coursera/Udemy), satisfaction is moderate, with qualitative feedback highlighting a desire for "step-by-step solutions" and "detecting weaknesses" rather than passive content consumption.
The "AI Trust" Gap: Although 81.8% of respondents already use AI tools like ChatGPT, 92.7% listed Accuracy/Hallucinations as their biggest concern. Qualitative responses explicitly mentioned frustration with "generic explanations" and the "lack of connection" with current AI platforms.
Demand for Features: The proposed features were highly validated, with 78.2% of users desiring "Step-by-step tutor explanations" and 60% requesting "Instant practice questions".

2.3 Existing Systems and Market Solutions
To understand the current landscape of AI-driven education and position our "AI-Powered Personalized Educational Platform" effectively, we analyzed existing market solutions that address similar problems in technical training and tutoring. We specifically examined three prominent platforms: AlgoCademy, SigIQ, and Studeo.
1. AlgoCademy: AlgoCademy is a specialized web-based platform designed primarily for technical interview preparation. It helps users master algorithms and data structures through interactive coding exercises. The system utilizes Large Language Models (LLMs) to provide a guided problem-solving environment where users can practice coding challenges that mimic the rigorous testing standards of top-tier technology companies.
2. SigIQ: SigIQ is an AI tutoring platform that emphasizes conversational learning and exam preparation. It leverages a technology stack combining LLMs with emotional analysis and voice interaction (Speech-to-Text and Text-to-Speech) to create a dialogue-driven tutoring experience. Its primary focus is on individual test preparation, offering a personalized response style that adapts to the user's engagement level.
3. Studeo Studeo is a mobile app offering "AI Avatars" for STEM and language tutoring. It features 3D avatars that can solve math problems from photos or chat. While it popularizes the concept of an "Avatar Tutor," it operates primarily as a homework helper for high schoolers (K-12) rather than a comprehensive university-level system.
2.4 Comparative Analysis
The following analysis compares our proposed solution against AlgoCademy, SigIQ, and Studeo across three critical dimensions: Technologies, Features, and Limitations.
1. Technologies
AlgoCademy: The platform’s architecture is centered around a text-based Large Language Model (LLM) integrated with a standard Code Editor. This setup is optimized for text-based coding drills and algorithmic logic verification.
SigIQ: This platform employs a stack comprising LLMs, Emotional Analysis, and Speech-to-Text/Text-to-Speech (STT + TTS). This combination enables a voice-first interface that can detect and respond to user sentiment.
Studeo: Uses a mobile-first stack with OCR (Optical Character Recognition) to scan homework photos and 3D Avatars for delivery. However, it lacks a live coding environment or integration with external developer tools.
Our Solution: We deploy a comprehensive multi-agent stack that integrates LLMs, a 3D Avatar, an Embedded Code Editor, STT + TTS, and a unique AI-Generated Slides engine. Unlike competitors that rely on a single modality (text or voice), our technology stack supports a fully multimodal learning experience (visual, auditory, and kinesthetic).
2. Features
AlgoCademy: Features are strictly aligned with technical proficiency for employment. Key offerings include interactive coding exercises, guided problem-solving, and algorithm challenges specifically tailored for interview preparation.
SigIQ: Features focus on the "human" element of tutoring for exams. It provides a conversational tutor that uses user emotion analysis to adapt its response style, simulating a supportive study partner.
Studeo: Focuses on homework help and micro-learning. It offers instant answers to specific math/science problems and short explanatory videos. It does not offer structured, long-form university courses.
Our Solution: Our features simulate a complete private tutoring session for university education. These include an interactive avatar that acts as a lecturer, personalized explanations, dynamically generated slides that visualize complex theoretical topics (a feature absent in both competitors), and AI-assisted coding for real-time debugging.
3. Limitations
AlgoCademy:
Scope Limitation: The platform is heavily specialized for short-term interview prep. It lacks the broader academic context required for mastering foundational university Computer Science courses.
Modality Limitation: It is primarily text-centric and lacks the voice interaction or visual teaching aids (like slides) necessary for diverse learning styles.
SigIQ:
Scope Limitation: Designed primarily for individual test preparation, limiting its utility for long-term subject mastery or complex project-based learning.
Visual Limitation: While conversational, it lacks dynamic visual aids (such as real-time slide generation), forcing users to rely mostly on audio-based dialogue for understanding.
Studeo:
Target Audience Limitation: Primarily targets High School (K-12) students with "bite-sized" content. It is not designed for the depth or complexity of university Computer Science subjects.
Tool Limitation: Lacks an embedded IDE or Code Editor, making it unsuitable for learning programming.
Our Solution:
Addressed Limitation: By combining the coding rigor of AlgoCademy with the voice interaction of SigIQ, and adding visual slide generation, our solution overcomes the "single-mode" limitation of existing tools.
2.5 Identified Gap
Through our comparative analysis, we have identified a significant gap in the current EdTech market: The lack of a comprehensive, multimodal private tutor for university-level Computer Science education.
1. The "Interview vs. Education" Gap: Existing platforms like AlgoCademy are designed for interview drilling, while tools like SigIQ focus on exam prep, also Studeo serve K-12 students with homework help. There is no dedicated AI solution that supports a student through their university subjects (e.g., "Introduction to CS," "Data Structures"). Our project addresses this by tailoring the learning journey to the individual student's academic pace and course goals, rather than just passing a specific test.
2. The Visual-Context Gap: Competitors generally offer either "Text + Code" (AlgoCademy) or "Voice + Chat" (SigIQ). Missing from the market is a solution that provides visual context alongside these modalities. Our solution fills this gap with the Slide Generation Agent, which transforms raw text explanations into structured presentation slides, mimicking the visual aid of a classroom lecture.
3. The Engagement Gap: Students struggle to stay motivated with purely text-based or voice-only tools. By integrating an Emotionally Intelligent 3D Avatar with Real-Time Voice and Interactive Coding, our platform creates a "presence" that passive tools lack, fostering a deeper, more engaging connection similar to human-to-human tutoring.
3. Requirements Analysis
3.1 Functional Requirements
Section 1: User Management & Profiling
FR-1 The system shall allow users to register and authenticate using a valid email address and secure password.
FR-2 The system shall allow users to manage their profile information, including name, educational goals, and current experience level.
FR-3 The system shall administer an initial Placement Quiz (MCQ and/or Coding) upon course enrollment to establish a baseline skill profile.
FR-4 The system shall persistently store the user's initial skill metrics and demographic data in the primary database to inform the Personalization Engine.
Section 2: Learner Modeling & Personalization
FR-5 The system shall maintain a dynamic Knowledge State profile for each user, tracking mastery levels for specific topics (e.g., "High Mastery in Loops," "Low Mastery in Recursion").
FR-6 The system shall adapt the learning pace and explanation depth based on the user's historical performance and real-time interaction patterns.
FR-7 The system shall store historical interaction logs (confusion markers, mistakes, time-on-task) to refine the learner model over time.
FR-8 The system shall utilize a low-latency Caching Mechanism to retrieve active learner state data for real-time personalization during sessions.
Section 3: Curriculum & Content Generation
FR-9 The Content Generation Module shall generate a personalized Course Pathway based on the user's placement results, omitting topics the user has already mastered.
FR-10 The system shall utilize an Agentic Retrieval-Augmented Generation (RAG) process to source all educational content from verified documents in the Vector Database.
FR-11 The system shall ensure all generated content aligns with the predefined curriculum structure and dependency logic (e.g., ensuring "Variables" precedes "Functions").
Section 4: Slide Generation & Delivery
FR-12 The system shall generate structured Slides containing titles, bullet points, and code examples, derived from the RAG-verified content.
FR-13 The system shall display slides within a dedicated presentation interface, synchronized with the Tutor Agent's current explanation.
FR-14 The system shall cache generated slides to allow for reuse if the user reviews the same module, avoiding redundant generation costs.
FR-15 The system shall prevent the generation of new slides during an active live session.
Section 5: Assessment Generation
FR-16 The system shall pre-generate a bank of assessments (MCQs, True/False, Short Answer) associated with each generated slide cluster.
FR-17 The system shall adjust the difficulty of generated questions based on the learner's Knowledge State (e.g., harder questions for advanced users).
Section 6: Assessment Evaluation & Feedback
FR-18 The system shall automatically evaluate student responses using a combination of rule-based logic (for MCQs) and AI-based semantic analysis (for text answers).
FR-19 The system shall route all assessment scores to the Orchestrator to update the user's Knowledge State immediately.
Section 7: Interactive Learning Support (Tutor Agent)
FR-20 The Tutor Agent shall provide real-time conversational guidance, answering questions and providing hints based solely on the context provided by the Orchestrator.
FR-21 The system shall use Speech-to-Text (STT) to transcribe user voice input into text for the Orchestrator.
FR-22 The system shall perform Emotional Analysis (Audio/Video) to detect student frustration or confusion and trigger the Tutor to adjust its tone or speed.
FR-23 The Orchestrator shall manage the context window by aggregating User Profile, Session State, and RAG outputs into a single structured prompt for the Tutor.
Section 8: Coding Practice & Evaluation
FR-24 The system shall provide an integrated Code Editor (e.g., Monaco) allowing students to write and run code within the browser.
FR-25 The system shall pre-scan all submitted code using a Malicious Code Detection model to identify security threats (e.g., infinite loops, system calls).
FR-26 The system shall execute valid code in a secure Sandbox Environment and return the standard output (stdout) or errors to the user.
Section 9: Avatar Instructor
FR-27 The Avatar System shall generate a 3D animated character that lip-syncs to the audio output in real-time.
FR-28 The system shall use a Text-to-Speech (TTS) engine to convert the Tutor's textual response into an audio stream.
FR-29 The Avatar shall display facial expressions (Neutral, Happy, Concerned) corresponding to the sentiment tag provided by the Orchestrator.
FR-30 The Avatar module shall be purely presentational and shall not store any business logic or user data.
Section 10: Data Management & Session Handling
FR-31 The system shall store all persistent data (Users, Course Content, Assessment Results) in a scalable Database System (e.g., Document Store).
FR-32 The system shall use a High-Performance Caching Layer to store transient session data (Active Slides, Chat History) for low-latency access.
FR-33 The system shall ensure data persistence by periodically flushing the Cache state to the Main Database to prevent data loss during server restarts.

3.2 Non-Functional Requirements
Section 1: Performance
NFR-1 The system shall achieve a maximum End-to-End Latency of 3 seconds (from the end of user speech to the start of the Avatar’s audio response) to maintain a natural conversational flow.
NFR-2 The Avatar Rendering module shall maintain a minimum frame rate of 24 FPS (Frames Per Second) on standard client hardware to ensure smooth lip-sync synchronization.
NFR-3 The Code Evaluation module shall execute and return results for standard student code submissions within 5 seconds to prevent user frustration during assessments.
NFR-4 The system shall preload upcoming slide assets into the client-side cache at least one slide in advance to ensure zero-delay transitions during the lecture.
Section 2: Security
NFR-5 The Code Execution Sandbox shall enforce strict resource quotas (CPU usage < 20% of host, RAM < 512MB, Execution Time < 10s) to prevent Denial of Service (DoS) attacks from malicious loops.
NFR-6 The system shall completely isolate the Code Execution environment from the internal network, blocking all outbound internet access to prevent data exfiltration.
NFR-7 All sensitive user data (passwords, email addresses, session transcripts) shall be encrypted at rest in the persistent database and in transit using standard protocols (e.g., TLS 1.3).
NFR-8 The system shall sanitize all text inputs sent to the SQL/NoSQL databases to prevent Injection attacks.
Section 3: Scalability
NFR-9 The backend architecture shall be stateless (utilizing external caching like Redis for session state) to allow for Horizontal Scaling by adding more server instances under load.
NFR-10 The system shall support a minimum of 50 concurrent active sessions on the target deployment hardware without degrading response times below the thresholds defined in NFR-1.
NFR-11 The Database architecture shall support partitioning or sharding to handle the accumulation of session logs and student data over time without impacting query performance.
Section 4: Usability
NFR-12 The User Interface shall be responsive and fully functional on standard Desktop and Laptop resolutions (min-width: 1366px) to accommodate the primary student demographic.
NFR-13 The system shall provide clear, human-readable error messages (e.g., "The Tutor is currently busy, please wait..." instead of "HTTP 500") to guide the user during system faults.
Section 5: Reliability
NFR-14 The system shall implement Graceful Degradation: if the Avatar Rendering module fails or experiences excessive latency, the system shall automatically fallback to an "Audio-Only" mode without terminating the session.
NFR-15 The system shall support State Recovery: in the event of a browser crash or network disconnect, the user shall be able to resume their session from the exact slide and context state where they left off.
NFR-16 The system shall maintain an uptime availability of 99.0% during scheduled active testing hours.

4. System Design
4.1 Overall System Architecture


4.2 Component Breakdown

Component
Main Functionality
Inputs/Expected Outputs
Technology Stack
Conversational Agent (AI Tutor)
Acts as the course instructor, generates step‑by‑step explanations, and answers questions.


Inputs: text from ASR, retrieved documents, and student state.
Outputs: speech from TTS
Open-source LLM via ChatGPT OSS/Qwen API with LangChain for tool-calling, hosted in FastAPI backend to call other services
Orchestration Agent
Monitors the state of the Session, coordinates the timing between all the agents, and ensures that the Context of Student is being read from and written to correctly, and feeding other agents with relevant course information.


Inputs: Session state, student context, agent status updates.
Outputs : Workflow coordination signals, context routing instructions.


LangChain/LangGraph with circuit breakers to define agent graphs and tools, with FastAPI microservice async endpoints.
Agentic RAG
Processes placement quiz results to determine proficiency; retrieves relevant content; generates course pathway.


Inputs: Placement quiz results, student context, course learning objectives.
Outputs: Structured learning pathway, relevant textbook sections for slide generation.


LangChain agent framework + Open-source LLM with tool-use capabilities
Slide Generation Agent
Converts textbook content to slide format; incorporates relevant figures; adjusts complexity based on student context.


Inputs:Textbook sections, student context
Outputs:Formatted slides with visual representations of concepts


LLMs + MLLMs (Multi-Modal LLM) [1]
Assessment Generation Agent
Builds and updates quizzes, coding questions, and post‑session assessments tailored to the student’s weaknesses.


Inputs: course syllabus, current session content, student context, previous assessment results.
Outputs: Assessment questions, scoring, knowledge gaps.
LLM‑based generator wrapped in FastAPI, or use of a transformer‑based classification model.
Real‑Time Voice Layer (ASR/TTS)
Converts student speech to text and tutor text to speech, manages streaming audio during sessions.


Inputs: microphone audio, tutor response.
Outputs: transcribed text for agents and synthesized audio for the student.
External ASR/TTS APIs connected with FastAPI, WebRTC with simple‑peer/adapter.js in React for low‑latency.
Intent Classifier
Analyzes student interactions to determine their communication intent and routes appropriate responses.


Inputs: User prompt
Outputs: Decision based on the intention


MLP classifier with text to vector layer
Context Cache / Session Memory
Stores short‑term and long‑term session context, recent dialogue, selected course, pathway, emotional state, and performance.
Inputs: Emotional analysis results, assessment answers, session interactions.
Outputs: Updated student context including emotional state and learning gaps.
Redis (in-memory data store) with RedisJSON (for structured context storage).
Vector Database
Storage of the reference educational materials (books) in embeddings for RAG.
Inputs: Pre-processed chunks.
Outputs: Relevant textbook sections based on learning context..
Pinecone or ChromaDB for scalable semantic search, integrates seamlessly with LangChain tools.
SQL Database
Stores structured data: users, courses, enrollment
Inputs:Student data, course enrollment, course data
Outputs: Student profile records, enrollment history, educational background
PostgreSQL (ACID-compliant, supports JSONB for flexible data requirements) with Django ORM
NoSQL
Stores generated slides and generated assessments of the student.


Inputs: Generated slides, assessment questions, student responses.
Outputs: Session content for current and past sessions, assessment history.
MongoDB for schema‑flexible content, pairs well with dynamic slide and assessment structures generated by LLMs.
Emotional Analysis
Analyzes student emotional state during sessions.
Inputs: Audio/video from session interface.
Outputs: Emotional state indicators (frustration, engagement, confusion).
Combined CNN Architecture for Audio Emotional Analysis [2] + Facial Expression Analysis



3D Avatar
Emotionally expressive visual representation of the instructor with synchronized lip-syncing and facial expressions.
Inputs: Teaching scripts from Conversational Agent, Emotional state indicators from Emotional Analysis
Outputs: Real-time rendered 3D face mesh with appropriate expressions, Lip-synced animation synchronized with speech audio
Blender for design, MediaPipe Face Mesh for facial landmarks, Wav2Lip or RIFE, WebGL for browser-based rendering
Embedded Code Editor
Let students write and run code snippets during sessions.
Inputs: code, programming language.
Outputs: execution results.
React components
Session Component
A page where the student interacts with the tutor, slides, and code editor.
Inputs: user actions (voice, text, clicks).
Outputs: UI updates, messages.
React components
Naïve RAG
Answers student questions during sessions.


Inputs: Student questions, current session context, student context.
Outputs: Contextual answers to questions, confidence scores.
LangChain with open-source SLM



4.3 Design Decisions and Rationale

The system’s architectural and technological choices are driven by the need to balance modularity, data integrity, and real-time responsiveness within a complex AI-driven educational environment:

1. Multi-Agent Orchestration Architecture

Decoupling of Responsibilities: The architecture employs a Multi-Agent System (MAS) to separate complex tasks. Instead of a single monolithic model attempting to handle tutoring, visual generation, and assessment simultaneously, specialized agents (Conversational, Slide Generation, Assessment) operate independently. This prevents context pollution and ensures that the "Slide Generation Agent" focuses solely on visual formatting while the "Conversational Agent" focuses on pedagogy.

Centralized State Management: The Orchestration Agent (built on LangChain/LangGraph) acts as the central nervous system. It manages workflow coordination. This design choice ensures a logical flow of information between the "Session" and the back-end agents.

2. Polyglot Persistence Strategy (Database Segmentation)

Structured Data Integrity (PostgreSQL): The system uses PostgreSQL for user profiles, course enrollment, and educational background data. The justification here is ACID compliance; these records require strict transactional consistency to prevent errors in student records or billing/access rights.

Dynamic Content Flexibility (NoSQL/MongoDB): MongoDB is selected to store generated slides and assessments. Since AI-generated content is inherently variable, slides may have different numbers of bullet points, images, or layout structures. A rigid SQL schema would be inefficient. MongoDB accommodates outputs from LLMs without requiring constant database migration.

Low-Latency Context Retrieval (Redis): The "Context Cache" utilizes Redis (specifically RedisJSON) to store the student's immediate emotional state, recent dialogue, and session memory. Because the Orchestration Agent and Conversational Agent need to access this data in milliseconds to generate real-time responses, a disk-based database would introduce unacceptable latency. 

3. Dual-RAG Approach (Agentic vs. Naïve)

Complex Planning (Agentic RAG): The system uses Agentic RAG for "Course pathway generation." This choice is justified because defining a learning trajectory requires multi-step reasoning: analyzing placement quiz results, mapping them to learning objectives, and structuring a curriculum. A simple retrieval system cannot perform this higher-order logic.

Rapid Information Retrieval (Naïve RAG): For immediate, in-session questions (e.g., "What does this term mean?"), the system utilizes Naïve RAG. This is a lightweight, lower-latency approach that retrieves context directly from the Vector Database (Pinecone/ChromaDB) without the overhead of complex agentic reasoning, ensuring the student gets quick answers during the flow of conversation.

4. Real-Time Interaction Layer

Asynchronous Processing (FastAPI): The backend is hosted on FastAPI, chosen for its native support of asynchronous endpoints. This is critical for handling concurrent operations, such as streaming audio to the student via the Voice Layer while simultaneously processing the next set of slides in the background without blocking the main thread.

Low-Latency Audio (WebRTC): The Voice Layer uses WebRTC (via simple-peer/adapter.js) rather than standard HTTP requests. This design minimizes the delay between the student speaking and the system receiving the audio, which is essential for maintaining the illusion of a natural, human-like conversation.

5. Affective Computing and User Experience

Adaptive Feedback Loop (Emotional Analysis): The inclusion of a dedicated Emotional Analysis module (using CNNs for audio and facial analysis) justifies the need for personalized pacing. By feeding "Emotional state indicators" (frustration, confusion) into the Context Cache, the agents can dynamically adjust the complexity of the material.

Immersive Engagement (3D Avatar): The 3D Avatar connects the "Conversational Agent" outputs to a visual interface. By synchronizing lip-sync (Wav2Lip) and facial expressions with the generated text, the system provides non-verbal cues that enhance student engagement, differentiating it from a standard text-based chatbot.

4.4 Program Specific Focus: DSAI – Data Science & AI 

1. Data Lifecycle and Collection Strategy

Emotion Recognition: Trained on established public online datasets containing labeled audio and video to ensure robust multi-modal detection.

Slides Generation: Data scraped from SlideShare to build a corpus of professional layouts, summaries, and content hierarchies.

Intent Classification: Synthetic user-query pairs generated internally to create a specific training set for the educational context.

Avatar Animation: Utilizes published high-quality datasets specialized for lip-syncing and facial expressions.

Assessments: Ground-truth logic established by creating manual assessments and testing them on students to calibrate difficulty and validity.

2. ML / AI Models and Justification

Multi-modal Emotional Analysis: Uses Combined CNN Architectures to extract spatial features from video frames and spectral features from audio for real-time state detection.

Slide Generation: Multi-Modal LLMs (MLLMs) trained on the SlideShare corpus to learn the relationship between text summaries and visual layouts.

3D Avatar: Wav2Lip or RIFE models used for precise lip-syncing, mapping audio phonemes to visual visemes.

Intent Classifier: A lightweight MLP Classifier trained on synthetic pairs to ensure high-speed routing of user requests without the latency of large models.

Assessment Generator: LLM-based generation tailored to student proficiency levels, utilizing the logic derived from validated testing.

3. Feature Engineering and Evaluation Metrics

Feature Extraction: Utilizes MFCCs for audio and facial landmarks for video processing; text inputs are converted to semantic vectors for intent detection.

Student-Centric Evaluation (Slides): Performance is measured by actual student ratings of generated slides regarding clarity, layout, and utility.

Assessment Validation: Generated quizzes and code problems are evaluated via student pilot testing to ensure appropriate difficulty curves.

Classifier Metrics: Standard F1-scores, Precision, and Recall are used to validate the accuracy of the Intent Classifier and Emotion Recognition models.

4. Model Integration

Microservices Architecture: Models are deployed as independent FastAPI services to allow individual scaling.

Orchestration: The Orchestration Agent triggers models asynchronously via API calls (e.g., sending audio to the emotion engine).

Feedback Loop: Student ratings and assessment performance data are fed back into the system to fine-tune model parameters and prompts.




5. Project Timeline 

Phase
Goal
Milestones
Deliverables
Responsibilities
Phase 1: Data Infrastructure & RAG Setup
Build the data pipelines, databases, and retrieval systems necessary for the AI.
• Database Cluster Operational (NoSQL + Postgres + Vector)
• Data Scraping Pipeline Completed
• RAG System (Naive & Agentic) Deployed
• Functional NoSQL Database with Scraped Data
• Functional PostgreSQL Database
• Vector Database populated with Course Books
• Redis Cache Implementation
• Naive & Agentic RAG Pipelines
Seif Mahdy: Scraping SlideShare, Collecting Books, Agentic RAG Setup, Vector DB (Shared)
Youssef Ahmed: No-SQL DB Setup, Redis Cache (Shared)
Ziad Shaaban: Postgres DB Setup
Yusuf Sahab: Naive RAG Setup, Vector DB (Shared), Redis Cache (Shared)
Phase 2: Software Architecture & Base Integration
Establish the frontend/backend frameworks and core audio/visual services.
• Frontend & Backend Connection Established
• Speech Services (ASR/TTS) Functional
• Avatar Base Design Completed
• React Frontend Codebase
• Django Backend API
• FastAPI Microservices
• ASR (Speech-to-Text) Module
• TTS (Text-to-Speech) Module
• Base Avatar Assets
Ziad Shaaban: Set up React Frontend, Set up Django Backend
All Team: Set up FastAPI
Yusuf Sahab: ASR Setup
Youssef Ahmed: TTS Setup, Design and Develop the Avatar
Phase 3: Model Training & From-Scratch Development
Train and develop the custom AI models that drive content generation and interaction.
• Content Generation Models Ready
• Emotion Analysis Models Trained
• Avatar Lip Syncing Functional
• Slides Generation Model
• Assessment Generation Models (MCQ & Code)
• Intent Classification Model
• Multi-modal Emotion Analysis System
• Lip-Syncing Model
Seif Mahdy: Slides Gen Model, Assessment Gen Model (MCQ)
Yusuf Sahab: Intent Classification Model
Ziad Shaaban: Assessment Gen Model (Code)
Youssef Ahmed: Emotional Analysis (Audio & Video), Intelligent Avatar, Lip Syncing
Phase 4: Model Fine-Tuning & Optimization
Refine the "Brain" of the tutor and the learning path logic.
• Learning Pathway Logic Finalized
• Conversational Tutor Fine-Tuned
• Learning Pathway Generator Model
• Fine-Tuned Conversational Agent
Seif Mahdy: Learning Pathway Generator
Yusuf Sahab: Conversational Agent
Phase 5: Testing, Integration & Deployment
Combine all modules, test for bugs, and launch the final product.
• System Integration Complete
• User Acceptance Testing (UAT) Passed
• Production Deployment Live
• Integrated System (Frontend + Backend + AI)
• Test Reports (Unit & Integration)
• Deployed Application
All Team: Test all models, Integrate Everything, Final Testing, Deploy to Production, Final Report


6. Challenges & Solutions

Challenge 
Challenge Description
Solution / Mitigation Strategy
System complexity and multi-agent design
The architecture connects many components (conversational tutor, Agentic RAG, slide generation, assessments, emotional analysis, databases, real-time interaction), which can cause integration issues and unclear responsibilities if not managed early.
The team created detailed system architecture and data flow diagrams, and adopted an API-first, modular design so each agent has clear inputs/outputs and can be developed with mock data before integration.
Reliability of AI-generated educational content
LLM-generated explanations, slides, and assessments may be factually incorrect, which is critical for core programming and computer science topics.
The design uses an Agentic RAG pipeline grounded in verified course materials and includes planned accuracy metrics and, for sensitive content like assessments, possible human or rule-based validation before deployment.
ASR/TTS and technical vocabulary issues
Future speech interaction must handle diverse accents, noise, and technical terminology, misrecognition would lead to irrelevant answers and a poor user experience.
The team plans to use context-aware ASR, and display recognized text in the UI for student confirmation or correction before processing.
Scope management and team coordination
The project scope is large, with many AI and UI features and several team members, without structure there is a risk of overcommitting and misalignment on priorities and deadlines.
The team defined a Work Breakdown Structure, prioritized must-have vs could-have features, set a phased timeline, and chose tools (Discord, Notion, ClickUp, GitHub Projects) and weekly meetings to maintain coordination and adjust scope when needed.











7. Work Summary

Task Title
Task Owner
Status

Project Documentation




Project Proposal
All Team
Completed
Market Survey
Yusuf Sahab
Completed
Market Research
Seif Mahdy
Completed
Initial System Design & Work Division
All Team
Completed
Modular Project Design
All Team
Completed
System Architecture Design
Youssef Mohammed
Completed
Data Flow Diagram
Youssef Mohammed
Completed
Work Breakdown Structure
Yusuf Sahab
Completed
Design Initial Wireframes
Seif Mahdy
Completed
Risk Analysis
Seif Mahdy
Completed
Initial UI Design
Ziad Shaaban
Completed


References

[1] J. Wang, R. Xiao, X. Hou, J. Stamper, et al., "AUTOLV: Automatic Lecture Video Generator," in Proceedings of the 31st International Joint Conference on Artificial Intelligence (IJCAI), Vienna, Austria, 2022.

[2] T. Nguyen et al., "Script2Transcript: Generating Transcripts from Slide Titles," in Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing, Singapore, 2023.

[3] J. Yu, Z. Zhang, S. Tu, et al., "From MOOC to MAIC: Reshaping online teaching and learning through LLM-driven agents," arXiv preprint arXiv:2409.03512, 2024.

[4] "Knowledge Space Theory and ALEKS," in Handbook of Research on Adaptive Learning Systems for Personalized Education, Hershey, PA: IGI Global, 2018.

[5] C. Dong, Y. Yuan, K. Chen, S. Cheng, and C. Wen, "How to build an adaptive AI tutor for any course using knowledge graph-enhanced retrieval-augmented generation," arXiv preprint arXiv:2311.17696, 2023.

[6] R. Begazo, A. Aguilera, I. Dongo, and Y. Cardinale, "A combined CNN architecture for speech emotion recognition," Sensors, vol. 24, no. 17, p. 5797, 2024.

[7] H. Yao, W. Xu, J. Turnau, N. Kellam, and H. Wei, "Instructional Agents: LLM agents on automated course material generation," arXiv preprint arXiv:2508.19611, 2025.

[8] J. Perczel, J. Chow, D. Demszky, et al., "TeachLM: Post-training LLMs for education using authentic learning data," arXiv preprint arXiv:2510.05087, 2025.

[9] "Assessment Generation in Education: Guidelines for AI-Generated MCQs," Educational Assessment Review, vol. 12, no. 3, 2024.

[10] H. Zheng, X. Guan, H. Kong, et al., "PPTAgent: Generating and evaluating presentations beyond text-to-slides," arXiv preprint arXiv:2501.03936, 2025.

[11] J. Wang, R. Xiao, X. Hou, J. Stamper, et al., "Enabling multi-agent systems as learning designers: Applying learning sciences to AI instructional design," arXiv preprint arXiv:2508.16659, 2024.

[12] "AcademicRAG: Knowledge Graph Enhanced Retrieval-Augmented Generation for Academic Content," Master's thesis, KTH Royal Institute of Technology, Stockholm, Sweden, 2025.


