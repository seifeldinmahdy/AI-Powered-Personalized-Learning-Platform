import { useEffect, useState } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { Loader2, Send, Star, ClipboardCheck } from 'lucide-react';
import { getEnrollments } from '../../services/api';
import {
  getSurveyStatus, getSurveyQuestions, submitSurveyResponse,
  type SurveyQuestion,
} from '../../services/surveys';

interface EnrollmentData {
  id: number;
  course: number;
  progress_percentage: string;
}

const LIKERT_LABELS = ['', 'Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree'];

export default function SurveyPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = searchParams.get('next') || '/dashboard';
  const id = Number(courseId);

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [questions, setQuestions] = useState<SurveyQuestion[]>([]);
  const [enrollmentId, setEnrollmentId] = useState<number | null>(null);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<number, string | number | string[]>>({});
  const [alreadySubmitted, setAlreadySubmitted] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const enrollRes = await getEnrollments();
        const raw = enrollRes.data;
        const enrollments: EnrollmentData[] = Array.isArray(raw)
          ? raw
          : (raw as { results?: EnrollmentData[] }).results ?? [];
        const enrollment = enrollments.find((e) => e.course === id);
        if (!enrollment) {
          toast.error('You are not enrolled in this course.');
          navigate('/dashboard');
          return;
        }
        setEnrollmentId(enrollment.id);

        const [statusRes, questionsRes] = await Promise.all([
          getSurveyStatus(enrollment.id),
          getSurveyQuestions(id),
        ]);

        if (cancelled) return;

        if (!statusRes.pending) {
          setAlreadySubmitted(true);
          setLoading(false);
          return;
        }

        setTemplateId(statusRes.template_id);
        setQuestions(questionsRes.sort((a, b) => a.order - b.order));
      } catch {
        toast.error('Failed to load survey.');
        navigate('/dashboard');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [id, navigate]);

  const setAnswer = (questionId: number, value: string | number | string[]) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }));
  };

  const toggleMulti = (questionId: number, option: string) => {
    const current = (answers[questionId] as string[] | undefined) ?? [];
    const updated = current.includes(option)
      ? current.filter((o) => o !== option)
      : [...current, option];
    setAnswer(questionId, updated);
  };

  const handleSubmit = async () => {
    if (!enrollmentId || !templateId) return;

    // Validation — every question except optional free-text must be answered
    const unanswered = questions.filter((q) => {
      if (q.kind === 'text') return false; // free-text is optional
      const a = answers[q.id];
      return a === undefined || a === '' || (Array.isArray(a) && a.length === 0);
    });
    if (unanswered.length > 0) {
      toast.error(`Please answer all ${unanswered.length} remaining question(s).`);
      return;
    }

    setSubmitting(true);
    try {
      await submitSurveyResponse({ enrollment_id: enrollmentId, template_id: templateId, answers });
      toast.success('Thank you for your feedback!');
      navigate(next);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 409) {
        toast.info('You have already submitted this survey.');
        navigate(next);
      } else {
        toast.error('Failed to submit survey. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="codex" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)' }}>
        <Loader2 size={36} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
      </div>
    );
  }

  if (alreadySubmitted) {
    return (
      <div className="codex" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, background: 'var(--bg-primary)', textAlign: 'center', padding: 24 }}>
        <div style={{ width: 48, height: 48, borderRadius: 12, background: 'rgba(22,163,74,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <ClipboardCheck size={24} style={{ color: 'var(--accent-success)' }} />
        </div>
        <div className="t-label" style={{ color: 'var(--accent-success)' }}>FEEDBACK RECEIVED</div>
        <p className="t-body" style={{ fontSize: 15, color: 'var(--text-secondary)', maxWidth: 360 }}>You have already submitted feedback for this course.</p>
        <button onClick={() => navigate(next)} className="btn btn-paper" style={{ padding: '12px 22px' }}>CONTINUE →</button>
      </div>
    );
  }

  const total = questions.length;
  const answeredCount = questions.filter((q) => {
    const a = answers[q.id];
    if (q.kind === 'text') return typeof a === 'string' && a.trim() !== '';
    return a !== undefined && a !== '' && !(Array.isArray(a) && a.length === 0);
  }).length;
  const progressPct = total ? (answeredCount / total) * 100 : 0;

  return (
    <div className="codex" style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-primary)' }}>
      <div style={{ maxWidth: 720, margin: '0 auto', padding: '32px 24px 64px', display: 'flex', flexDirection: 'column', gap: 24 }}>
        {/* Page header */}
        <div>
          <div className="t-label" style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>COURSE FEEDBACK</div>
          <h1 className="t-display" style={{ fontSize: 'clamp(28px,4vw,38px)', color: 'var(--text-primary)', marginBottom: 8 }}>Help us improve this course</h1>
          <p className="t-body" style={{ fontSize: 15, color: 'var(--text-secondary)' }}>Your feedback shapes this course for future students. Takes under a minute.</p>
        </div>

        {/* Progress indicator */}
        {total > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="t-mono steel">{answeredCount} OF {total} ANSWERED</span>
              <span className="t-mono" style={{ color: 'var(--accent-primary)' }}>{Math.round(progressPct)}%</span>
            </div>
            <div className="progress"><i style={{ width: `${progressPct}%` }} /></div>
          </div>
        )}

        {questions.map((q, qi) => (
          <div key={q.id} style={{ background: 'var(--bg-surface)', borderRadius: 12, border: '1px solid var(--hairline)', padding: 24 }}>
            <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
              <span className="t-mono steel" style={{ marginTop: 2 }}>{String(qi + 1).padStart(2, '0')}</span>
              <p className="t-body" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.4 }}>{q.prompt}</p>
            </div>

            {/* Likert: 1-5 star-style radio */}
            {q.kind === 'likert' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                {[1, 2, 3, 4, 5].map((n) => {
                  const selected = Number(answers[q.id]) >= n;
                  return (
                    <button
                      key={n}
                      onClick={() => setAnswer(q.id, n)}
                      style={{
                        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, padding: 8, borderRadius: 8,
                        border: 'none', cursor: 'pointer', background: answers[q.id] === n ? 'rgba(37,99,235,0.08)' : 'transparent',
                      }}
                    >
                      <Star size={22} fill={selected ? 'currentColor' : 'none'} style={{ color: selected ? 'var(--accent-primary)' : 'var(--steel)' }} />
                      <span className="t-mono" style={{ color: answers[q.id] === n ? 'var(--accent-primary)' : 'var(--steel-light)' }}>{n}</span>
                    </button>
                  );
                })}
                <span className="t-body" style={{ fontSize: 13, color: 'var(--text-secondary)', marginLeft: 8 }}>
                  {answers[q.id] !== undefined ? LIKERT_LABELS[Number(answers[q.id])] : ''}
                </span>
              </div>
            )}

            {/* Free text */}
            {q.kind === 'text' && (
              <textarea
                className="input"
                style={{ minHeight: 96, resize: 'vertical', fontSize: 14 }}
                rows={4}
                placeholder="Your response… (optional)"
                value={(answers[q.id] as string) ?? ''}
                onChange={(e) => setAnswer(q.id, e.target.value)}
              />
            )}

            {/* Single choice */}
            {q.kind === 'single' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {q.options.map((opt) => {
                  const selected = answers[q.id] === opt;
                  return (
                    <label
                      key={opt}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 12, padding: 12, borderRadius: 8, cursor: 'pointer',
                        border: `1px solid ${selected ? 'var(--accent-primary)' : 'var(--hairline)'}`,
                        background: selected ? 'rgba(37,99,235,0.05)' : 'var(--bg-primary)',
                      }}
                    >
                      <input type="radio" name={`q-${q.id}`} checked={selected} onChange={() => setAnswer(q.id, opt)} style={{ accentColor: 'var(--accent-primary)' }} />
                      <span className="t-body" style={{ fontSize: 14, color: 'var(--text-primary)' }}>{opt}</span>
                    </label>
                  );
                })}
              </div>
            )}

            {/* Multi choice */}
            {q.kind === 'multi' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {q.options.map((opt) => {
                  const selected = ((answers[q.id] as string[]) ?? []).includes(opt);
                  return (
                    <label
                      key={opt}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 12, padding: 12, borderRadius: 8, cursor: 'pointer',
                        border: `1px solid ${selected ? 'var(--accent-primary)' : 'var(--hairline)'}`,
                        background: selected ? 'rgba(37,99,235,0.05)' : 'var(--bg-primary)',
                      }}
                    >
                      <input type="checkbox" checked={selected} onChange={() => toggleMulti(q.id, opt)} style={{ accentColor: 'var(--accent-primary)' }} />
                      <span className="t-body" style={{ fontSize: 14, color: 'var(--text-primary)' }}>{opt}</span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        ))}

        {questions.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: 4 }}>
            <button onClick={() => navigate('/dashboard')} className="btn btn-ghost-dark" style={{ padding: '12px 18px' }}>CANCEL</button>
            <button onClick={handleSubmit} disabled={submitting} className="btn btn-red" style={{ padding: '12px 22px' }}>
              {submitting ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              SUBMIT FEEDBACK
            </button>
          </div>
        )}

        {questions.length === 0 && (
          <div className="t-body" style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-secondary)', fontSize: 14 }}>
            No survey questions found for this course.
          </div>
        )}
      </div>
    </div>
  );
}
