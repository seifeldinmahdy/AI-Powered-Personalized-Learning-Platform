import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router';
import { Route, X, CheckCircle2, PlayCircle, Lock, Circle, BookOpen, FlaskConical, ClipboardList, ChevronDown, ChevronRight } from 'lucide-react';
import { toast } from 'sonner';
import { getCurrentPathway } from '../services/pathway';
import { getEnrollments } from '../services/api';
import { getSessionCompletions } from '../services/progress';

// The three stages a session moves through. Shown as sub-points under the
// current session so the lab / problem set are placed within the session.
export type SessionStage = 'slides' | 'lab' | 'problem-set';

const STAGES: { id: SessionStage; label: string; Icon: typeof BookOpen }[] = [
  { id: 'slides', label: 'Lecture & Slides', Icon: BookOpen },
  { id: 'lab', label: 'Coding Lab', Icon: FlaskConical },
  { id: 'problem-set', label: 'Problem Set', Icon: ClipboardList },
];

interface PathwaySession {
  number: number;
  title: string;
  completed: boolean;
}

export interface PathwayDrawerProps {
  courseId: string;
  currentSessionNumber: number;
  /** Which stage of the current session the page represents. */
  activeStage: SessionStage;
  /** Live slide progress, only meaningful on the slides stage. */
  slideProgress?: { current: number; total: number; nowTitle?: string };
}

const pad2 = (n: number) => String(n).padStart(2, '0');

/**
 * The "PATHWAY" button + slide-out course drawer, shared by the live session,
 * coding lab and problem set. It self-fetches the plan + completions so any page
 * can drop it in. Under the current session it lists the three stages
 * (lecture → lab → problem set) and highlights the active one.
 */
export function PathwayDrawer({ courseId, currentSessionNumber, activeStage, slideProgress }: PathwayDrawerProps) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<PathwaySession[]>([]);
  const [courseTitle, setCourseTitle] = useState('');
  const [maxAllowed, setMaxAllowed] = useState(1);
  // Which session is expanded to reveal its stages (lecture / lab / problem set).
  // The current session starts open.
  const [expandedSession, setExpandedSession] = useState<number | null>(currentSessionNumber);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const plan = await getCurrentPathway(String(courseId));
        let completed = new Set<number>();
        let allowed = 1;
        let title = '';
        try {
          const { data: raw } = await getEnrollments();
          const enrollments = Array.isArray(raw) ? raw : raw.results ?? [];
          const enrollment = enrollments.find(
            (e: { course: number; course_title: string }) => String(e.course) === String(courseId),
          );
          if (enrollment) {
            title = enrollment.course_title ?? '';
            const comps = await getSessionCompletions(enrollment.id);
            completed = new Set(comps.filter((c) => c.status === 'Completed').map((c) => c.session_number as number));
            const maxCompleted = completed.size > 0 ? Math.max(...Array.from(completed)) : 0;
            allowed = Math.max(enrollment.current_session_number || 1, maxCompleted + 1);
          }
        } catch { /* completions are non-critical */ }
        if (cancelled) return;
        setCourseTitle(title);
        setMaxAllowed(allowed);
        setSessions(plan.sessions.map((ps) => ({
          number: ps.session_number,
          title: ps.session_title,
          completed: completed.has(ps.session_number),
        })));
      } catch { /* no plan yet */ }
    })();
    return () => { cancelled = true; };
  }, [courseId]);

  const totalSessions = sessions.length;
  const completedSessions = sessions.filter((s) => s.completed).length;
  const activeStageIdx = STAGES.findIndex((s) => s.id === activeStage);

  return (
    <>
      <button
        onClick={() => setOpen((o) => !o)}
        className="t-label"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'transparent', border: '1px solid var(--hairline)', borderRadius: 8, color: 'var(--text-secondary)', padding: '8px 12px', cursor: 'pointer' }}
      >
        <Route size={14} /> PATHWAY
      </button>

      {open && typeof document !== 'undefined' && createPortal(
        <div className="codex" style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'transparent' }}>
          <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.3)' }} onClick={() => setOpen(false)} />

          <div style={{ position: 'absolute', left: 0, top: 0, height: '100%', width: 324, background: 'var(--bg-surface)', borderRight: '1px solid var(--hairline)', display: 'flex', flexDirection: 'column', boxShadow: '2px 0 24px rgba(0,0,0,0.12)' }}>
            <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--hairline)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
              <span className="t-label" style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: 'var(--accent-primary)' }}>
                <Route size={14} /> COURSE PATHWAY
              </span>
              <button onClick={() => setOpen(false)} style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex' }}><X size={16} /></button>
            </div>

            <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--hairline)', flexShrink: 0 }}>
              {courseTitle && <div className="t-mono steel" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{courseTitle.toUpperCase()}</div>}
              <div className="t-label" style={{ color: 'var(--text-primary)', marginTop: 6 }}>SESSION {pad2(currentSessionNumber)} OF {pad2(Math.max(totalSessions, 1))}</div>
              <div className="progress" style={{ marginTop: 12 }}><i style={{ width: `${totalSessions > 0 ? Math.max(2, (completedSessions / totalSessions) * 100) : 2}%` }} /></div>
              <div className="t-mono" style={{ color: 'var(--accent-primary)', marginTop: 8 }}>{completedSessions} OF {totalSessions} COMPLETE</div>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
              {sessions.length === 0 ? (
                <div className="t-mono steel" style={{ padding: '24px 18px', textAlign: 'center' }}>NO SESSIONS YET</div>
              ) : (
                sessions.map((s) => {
                  const isCurrent = s.number === currentSessionNumber;
                  const isLocked = s.number > maxAllowed;
                  const isCompleted = s.completed;
                  const accent = isCompleted ? 'var(--accent-success)' : isCurrent ? 'var(--accent-primary)' : isLocked ? 'var(--steel)' : 'var(--steel-light)';
                  const statusTag = isCompleted ? 'DONE' : isCurrent ? 'IN PROGRESS' : isLocked ? 'LOCKED' : 'REVISIT';
                  const titleColor = isCurrent ? 'var(--accent-primary)' : isLocked ? 'var(--text-secondary)' : 'var(--text-primary)';

                  const expanded = expandedSession === s.number;
                  const goToStage = (stage: SessionStage) => {
                    const base = `/course/${courseId}/session/${s.number}`;
                    navigate(stage === 'slides' ? base : stage === 'lab' ? `${base}/lab` : `${base}/problem-set`);
                    setOpen(false);
                  };

                  return (
                    <div
                      key={s.number}
                      style={{
                        borderBottom: '1px solid var(--hairline)',
                        borderLeft: `3px solid ${isCurrent ? 'var(--accent-primary)' : isCompleted ? 'var(--accent-success)' : 'transparent'}`,
                        background: isCurrent ? 'rgba(37,99,235,0.06)' : 'transparent',
                        opacity: isLocked ? 0.6 : 1,
                      }}
                    >
                      {/* Session header — click to expand/collapse its stages. */}
                      <div
                        role="button"
                        tabIndex={isLocked ? -1 : 0}
                        onClick={() => {
                          if (isLocked) { toast.error('Complete previous sessions to unlock this one.'); return; }
                          setExpandedSession((cur) => (cur === s.number ? null : s.number));
                        }}
                        style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '12px 14px', cursor: isLocked ? 'not-allowed' : 'pointer' }}
                      >
                        {isCompleted ? <CheckCircle2 size={15} style={{ color: accent, flexShrink: 0, marginTop: 1 }} />
                          : isCurrent ? <PlayCircle size={15} style={{ color: accent, flexShrink: 0, marginTop: 1 }} />
                            : isLocked ? <Lock size={15} style={{ color: accent, flexShrink: 0, marginTop: 1 }} />
                              : <Circle size={15} style={{ color: accent, flexShrink: 0, marginTop: 1 }} />}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                            <span className="t-mono steel">SESSION {pad2(s.number)}</span>
                            <span className="t-mono" style={{ color: accent, fontSize: 9 }}>{statusTag}</span>
                          </div>
                          <div style={{ fontFamily: 'var(--ff-body)', fontSize: 13, lineHeight: 1.35, marginTop: 3, fontWeight: isCurrent ? 600 : 400, color: titleColor, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                            {s.title}
                          </div>
                        </div>
                        {!isLocked && (expanded
                          ? <ChevronDown size={15} style={{ color: 'var(--steel)', flexShrink: 0, marginTop: 1 }} />
                          : <ChevronRight size={15} style={{ color: 'var(--steel)', flexShrink: 0, marginTop: 1 }} />)}
                      </div>

                      {/* Stages — clickable: jump straight to the lecture, lab or problem set. */}
                      {expanded && !isLocked && (
                        <div style={{ padding: '0 16px 12px 39px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                          {STAGES.map((stage, idx) => {
                            const isActiveStage = isCurrent && stage.id === activeStage;
                            const isDoneStage = isCurrent && idx < activeStageIdx;
                            const color = isActiveStage ? 'var(--accent-primary)' : isDoneStage ? 'var(--accent-success)' : 'var(--steel)';
                            return (
                              <button
                                key={stage.id}
                                onClick={() => goToStage(stage.id)}
                                style={{
                                  display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 8px',
                                  background: isActiveStage ? 'rgba(37,99,235,0.08)' : 'transparent',
                                  border: 'none', borderRadius: 6, cursor: 'pointer', textAlign: 'left',
                                }}
                              >
                                <stage.Icon size={13} style={{ color, flexShrink: 0 }} />
                                <span style={{ fontFamily: 'var(--ff-body)', fontSize: 12.5, color: isActiveStage ? 'var(--accent-primary)' : 'var(--text-primary)', fontWeight: isActiveStage ? 600 : 400 }}>
                                  {stage.label}
                                </span>
                                {isActiveStage ? <span className="t-mono" style={{ marginLeft: 'auto', color: 'var(--accent-primary)', fontSize: 9 }}>NOW</span>
                                  : isDoneStage ? <CheckCircle2 size={12} style={{ marginLeft: 'auto', color: 'var(--accent-success)' }} />
                                    : <ChevronRight size={12} style={{ marginLeft: 'auto', color: 'var(--steel)' }} />}
                              </button>
                            );
                          })}

                          {/* Live slide progress (current session, slides stage). */}
                          {isCurrent && activeStage === 'slides' && slideProgress && slideProgress.total > 0 && (
                            <div style={{ marginTop: 8 }}>
                              <div className="progress"><i style={{ width: `${Math.max(2, Math.round(((slideProgress.current + 1) / slideProgress.total) * 100))}%` }} /></div>
                              <div className="t-mono" style={{ color: 'var(--accent-primary)', marginTop: 6 }}>
                                SLIDE {pad2(slideProgress.current + 1)} / {pad2(slideProgress.total)}
                              </div>
                              {slideProgress.nowTitle && (
                                <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                                  <span className="sq-bullet" style={{ marginTop: 6, background: 'var(--accent-primary)' }} />
                                  <span className="t-body" style={{ fontSize: 12.5, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                                    <span className="t-mono steel">NOW · </span>{slideProgress.nowTitle}
                                  </span>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>,
        document.body!,
      )}
    </>
  );
}
