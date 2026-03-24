import { CompactTutor } from '../components/CompactTutor';
import type { TopicInput } from '../services/tutor';

/**
 * Standalone test page for the AI tutor — no auth required.
 * Access at: http://localhost:3000/test-tutor
 */
export default function TestTutor() {
  const testTopics: TopicInput[] = [
    {
      name: 'Python Variables',
      subtopics: [
        'What is a variable and why do we need them',
        'Variable naming rules and conventions',
        'Assigning values to variables',
      ],
    },
    {
      name: 'Data Types in Python',
      subtopics: [
        'Integers and floating-point numbers',
        'Strings and basic string operations',
        'Booleans and type conversion',
      ],
    },
    {
      name: 'Type Conversion',
      subtopics: [
        'Implicit vs explicit type conversion',
        'Common conversion functions: int(), float(), str()',
        'Handling conversion errors',
      ],
    },
  ];

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        background: 'var(--background, #0a0a0f)',
        color: 'var(--foreground, #e0e0e0)',
      }}
    >
      {/* Left side: instructions */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '2rem',
          gap: '1rem',
        }}
      >
        <h1 style={{ fontSize: '2rem', fontWeight: 700 }}>🧪 AI Tutor Test Page</h1>
        <p style={{ opacity: 0.7, maxWidth: '500px', textAlign: 'center', lineHeight: 1.6 }}>
          Click <strong>"Start Session"</strong> on the right panel to begin.
          The AI tutor will lecture through the topics, and you can pause or ask questions mid-lecture.
        </p>
        <div
          style={{
            marginTop: '1rem',
            padding: '1rem 1.5rem',
            background: 'rgba(76, 111, 255, 0.1)',
            border: '1px solid rgba(76, 111, 255, 0.2)',
            borderRadius: '12px',
            fontSize: '0.85rem',
            maxWidth: '400px',
          }}
        >
          <strong>Requirements:</strong>
          <ul style={{ marginTop: '0.5rem', paddingLeft: '1.2rem', lineHeight: 1.8 }}>
            <li>AI Service running on port 8001</li>
            <li>GEMINI_API_KEY set in .env</li>
          </ul>
        </div>
      </div>

      {/* Right side: the tutor panel */}
      <CompactTutor topics={testTopics} />
    </div>
  );
}
