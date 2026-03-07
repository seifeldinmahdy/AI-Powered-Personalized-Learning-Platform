import { Header } from '../../components/Header';
import { CodePanel } from '../../components/CodePanel';
import { SlidesViewer } from '../../components/SlidesViewer';
import { CompactTutor } from '../../components/CompactTutor';
import { SessionControls } from '../../components/SessionControls';
import { useParams } from 'react-router';

export default function LiveSession() {
  const { courseId, lessonId } = useParams();

  const lessonTitle = 'Intro to Python Variables';
  const courseTitle = 'Python 101';

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

        {/* Right Panel - Compact Tutor (20%) */}
        <CompactTutor />
      </div>

      {/* Bottom Controls */}
      <SessionControls />
    </>
  );
}
