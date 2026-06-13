import { useEffect, useState } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { Loader2, Send, Star } from 'lucide-react';
import { Header } from '../../components/Header';
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
    const next = current.includes(option)
      ? current.filter((o) => o !== option)
      : [...current, option];
    setAnswer(questionId, next);
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
      <>
        <Header title="Course Survey" subtitle="Loading..." />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={36} className="animate-spin text-secondary" />
        </div>
      </>
    );
  }

  if (alreadySubmitted) {
    return (
      <>
        <Header title="Course Survey" subtitle="Already submitted" />
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-4">
            <p className="text-muted-foreground">You have already submitted feedback for this course.</p>
            <button
              onClick={() => navigate(next)}
              className="px-6 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-colors"
            >
              Continue
            </button>
          </div>
        </div>
      </>
    );
  }

  const total = questions.length;
  const answeredCount = questions.filter((q) => {
    const a = answers[q.id];
    if (q.kind === 'text') return typeof a === 'string' && a.trim() !== '';
    return a !== undefined && a !== '' && !(Array.isArray(a) && a.length === 0);
  }).length;

  return (
    <>
      <Header title="Course Feedback" subtitle="Help us improve this course for future students" />
      <div className="flex-1 overflow-y-auto">
        <div className="p-8 max-w-2xl mx-auto space-y-6">
          {/* Progress indicator */}
          {total > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>Takes under a minute</span>
                <span>{answeredCount} / {total} answered</span>
              </div>
              <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all duration-300"
                  style={{ width: `${total ? (answeredCount / total) * 100 : 0}%` }}
                />
              </div>
            </div>
          )}

          {questions.map((q) => (
            <div key={q.id} className="bg-card rounded-2xl border border-border shadow-sm p-6">
              <p className="font-semibold text-foreground mb-4">{q.prompt}</p>

              {/* Likert: 1-5 star-style radio */}
              {q.kind === 'likert' && (
                <div className="flex items-center gap-3">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      onClick={() => setAnswer(q.id, n)}
                      className={`flex flex-col items-center gap-1 p-2 rounded-xl transition-colors ${
                        answers[q.id] === n
                          ? 'bg-primary/10 text-primary'
                          : 'text-muted-foreground hover:bg-muted/50'
                      }`}
                    >
                      <Star
                        size={22}
                        fill={Number(answers[q.id]) >= n ? 'currentColor' : 'none'}
                        className={Number(answers[q.id]) >= n ? 'text-primary' : 'text-muted-foreground'}
                      />
                      <span className="text-xs font-medium">{n}</span>
                    </button>
                  ))}
                  <span className="text-xs text-muted-foreground ml-2">
                    {answers[q.id] !== undefined
                      ? ['', 'Strongly Disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly Agree'][Number(answers[q.id])]
                      : ''}
                  </span>
                </div>
              )}

              {/* Free text */}
              {q.kind === 'text' && (
                <textarea
                  className="w-full border border-border rounded-xl px-4 py-3 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring resize-none"
                  rows={4}
                  placeholder="Your response..."
                  value={(answers[q.id] as string) ?? ''}
                  onChange={(e) => setAnswer(q.id, e.target.value)}
                />
              )}

              {/* Single choice */}
              {q.kind === 'single' && (
                <div className="space-y-2">
                  {q.options.map((opt) => (
                    <label
                      key={opt}
                      className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                        answers[q.id] === opt
                          ? 'border-primary bg-primary/5'
                          : 'border-border hover:bg-muted/30'
                      }`}
                    >
                      <input
                        type="radio"
                        name={`q-${q.id}`}
                        checked={answers[q.id] === opt}
                        onChange={() => setAnswer(q.id, opt)}
                        className="accent-primary"
                      />
                      <span className="text-sm">{opt}</span>
                    </label>
                  ))}
                </div>
              )}

              {/* Multi choice */}
              {q.kind === 'multi' && (
                <div className="space-y-2">
                  {q.options.map((opt) => {
                    const selected = ((answers[q.id] as string[]) ?? []).includes(opt);
                    return (
                      <label
                        key={opt}
                        className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                          selected ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/30'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleMulti(q.id, opt)}
                          className="accent-primary"
                        />
                        <span className="text-sm">{opt}</span>
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          ))}

          {questions.length > 0 && (
            <div className="flex items-center justify-between pt-2">
              <button
                onClick={() => navigate('/dashboard')}
                className="px-4 py-2.5 rounded-xl text-sm text-muted-foreground hover:bg-muted/60 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors"
              >
                {submitting ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                Submit Feedback
              </button>
            </div>
          )}

          {questions.length === 0 && (
            <div className="text-center py-10 text-muted-foreground text-sm">
              No survey questions found for this course.
            </div>
          )}
        </div>
      </div>
    </>
  );
}
