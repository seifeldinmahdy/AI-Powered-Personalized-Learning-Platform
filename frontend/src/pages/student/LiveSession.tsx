import { Header } from '../../components/Header';
import { CodePanel } from '../../components/CodePanel';
import { SlidesViewer } from '../../components/SlidesViewer';
import { CompactTutor } from '../../components/CompactTutor';
import { SessionControls } from '../../components/SessionControls';
import { useParams } from 'react-router';
import type { TopicInput } from '../../services/tutor';

export default function LiveSession() {
  const { courseId, lessonId } = useParams();

  const lessonTitle = 'Intro to Python Variables';
  const courseTitle = 'Python 101';

  // Topics for this lesson (We would get it from the backend in the future using the course outline generated from the other AI models)
  const lessonTopics: TopicInput[] = [
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
    <>
      <Header
        title={`${courseTitle}: ${lessonTitle}`}
        backLink="/dashboard"
        backLabel="Dashboard"
      />

      <div className="flex-1 flex overflow-hidden gap-0">
        {/* Left Panel - Code Editor (30%) */}
        <CodePanel />

        {/* Center - Slides Viewer (50%) */}
        <SlidesViewer />

        {/* Right Panel - AI Tutor (20%) */}
        <CompactTutor topics={lessonTopics} />
      </div>

      {/* Bottom Controls */}
      <SessionControls />
    </>
  );
}
