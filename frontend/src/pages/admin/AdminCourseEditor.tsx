import { useEffect, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router';
import { toast } from 'sonner';
import {
  ChevronDown, ChevronRight, Plus, Trash2, Edit, Check, X, Loader2, BookOpen,
  Sparkles, RefreshCw, GraduationCap, MessageSquare, Hammer, ChevronRightIcon,
} from 'lucide-react';
import {
  getAdminCourses, getModulesByCourse, getLessonsByModule,
  createModule, updateModule, deleteModule,
  createLesson, updateLesson, deleteLesson,
  type AdminModule, type AdminLesson, type AdminCourse,
} from '../../services/admin';
import { AIDraftReviewTable, type Column } from '../../components/AIDraftReviewTable';
import {
  getCLOs, suggestCLOs, createCLO, deleteCLO, type CLO, type CLODraft,
} from '../../services/clos';
import { getSurveySummary, refreshSurveySummary, type SurveySummary } from '../../services/surveys';

interface LessonState {
  data: AdminLesson;
  editing: boolean;
  editTitle: string;
  editOrder: string;
}

interface ModuleState {
  data: AdminModule;
  expanded: boolean;
  editing: boolean;
  editTitle: string;
  editOrder: string;
  lessons: LessonState[];
  lessonsLoaded: boolean;
  addingLesson: boolean;
  newLessonTitle: string;
  newLessonOrder: string;
}

const CLO_EMPTY_ROW: CLODraft = { code: '', text: '', bloom_level: 'understand', concept_ids: [], order: 0 };

const CLO_COLUMNS: Column<CLODraft>[] = [
  { key: 'code', header: 'Code', editable: true, width: 'w-20' },
  { key: 'text', header: 'Outcome Statement', editable: true },
  { key: 'bloom_level', header: "Bloom's Level", editable: true, width: 'w-32' },
];

const SENTIMENT_BADGE: Record<string, string> = {
  positive: 'admin-badge-green',
  mixed: 'admin-badge-amber',
  negative: 'admin-badge',
};

export default function AdminCourseEditor() {
  const { courseId } = useParams<{ courseId: string }>();
  const navigate = useNavigate();
  const id = Number(courseId);

  const [course, setCourse] = useState<AdminCourse | null>(null);
  const [modules, setModules] = useState<ModuleState[]>([]);
  const [loading, setLoading] = useState(true);
  const [addingModule, setAddingModule] = useState(false);
  const [newModuleTitle, setNewModuleTitle] = useState('');
  const [newModuleOrder, setNewModuleOrder] = useState('');

  // CLO state
  const [clos, setClos] = useState<CLO[]>([]);
  const [cloLoading, setCloLoading] = useState(false);
  const [suggestingCLOs, setSuggestingCLOs] = useState(false);
  const [cloTab, setCloTab] = useState<'list' | 'draft'>('list');
  const [cloDrafts, setCloDrafts] = useState<CLODraft[]>([]);

  // Survey summary state
  const [summary, setSummary] = useState<SurveySummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [refreshingSummary, setRefreshingSummary] = useState(false);

  useEffect(() => {
    Promise.all([getAdminCourses(), getModulesByCourse(id)])
      .then(([courses, mods]) => {
        setCourse(courses.find((c) => c.id === id) ?? null);
        setModules(
          mods.map((m) => ({
            data: m,
            expanded: false,
            editing: false,
            editTitle: m.title,
            editOrder: String(m.module_order),
            lessons: [],
            lessonsLoaded: false,
            addingLesson: false,
            newLessonTitle: '',
            newLessonOrder: '',
          })),
        );
      })
      .catch(() => toast.error('Failed to load course content'))
      .finally(() => setLoading(false));

    // Load CLOs and survey summary in parallel
    setCloLoading(true);
    getCLOs(id)
      .then(setClos)
      .catch(() => toast.error('Failed to load CLOs'))
      .finally(() => setCloLoading(false));

    setSummaryLoading(true);
    getSurveySummary(id)
      .then(setSummary)
      .catch(() => setSummary(null))
      .finally(() => setSummaryLoading(false));
  }, [id]);

  // ---- Module helpers ----

  const toggleModule = async (idx: number) => {
    const mod = modules[idx];
    if (!mod.expanded && !mod.lessonsLoaded) {
      const lessons = await getLessonsByModule(mod.data.id).catch(() => []);
      setModules((prev) =>
        prev.map((m, i) =>
          i === idx
            ? {
                ...m,
                expanded: true,
                lessonsLoaded: true,
                lessons: lessons.map((l) => ({
                  data: l,
                  editing: false,
                  editTitle: l.title,
                  editOrder: String(l.lesson_order),
                })),
              }
            : m,
        ),
      );
    } else {
      setModules((prev) =>
        prev.map((m, i) => (i === idx ? { ...m, expanded: !m.expanded } : m)),
      );
    }
  };

  const handleAddModule = async () => {
    if (!newModuleTitle.trim()) { toast.error('Module title required'); return; }
    try {
      const created = await createModule({
        course: id,
        title: newModuleTitle.trim(),
        module_order: newModuleOrder ? Number(newModuleOrder) : modules.length + 1,
      });
      setModules((prev) => [
        ...prev,
        {
          data: created,
          expanded: false,
          editing: false,
          editTitle: created.title,
          editOrder: String(created.module_order),
          lessons: [],
          lessonsLoaded: false,
          addingLesson: false,
          newLessonTitle: '',
          newLessonOrder: '',
        },
      ]);
      setNewModuleTitle('');
      setNewModuleOrder('');
      setAddingModule(false);
      toast.success('Module added');
    } catch {
      toast.error('Failed to add module');
    }
  };

  const handleSaveModule = async (idx: number) => {
    const mod = modules[idx];
    try {
      const updated = await updateModule(mod.data.id, {
        title: mod.editTitle.trim(),
        module_order: Number(mod.editOrder),
      });
      setModules((prev) =>
        prev.map((m, i) =>
          i === idx ? { ...m, data: updated, editing: false, editTitle: updated.title, editOrder: String(updated.module_order) } : m,
        ),
      );
      toast.success('Module updated');
    } catch {
      toast.error('Failed to update module');
    }
  };

  const handleDeleteModule = async (idx: number) => {
    const mod = modules[idx];
    try {
      await deleteModule(mod.data.id);
      setModules((prev) => prev.filter((_, i) => i !== idx));
      toast.success('Module deleted');
    } catch {
      toast.error('Failed to delete module');
    }
  };

  // ---- Lesson helpers ----

  const handleAddLesson = async (modIdx: number) => {
    const mod = modules[modIdx];
    if (!mod.newLessonTitle.trim()) { toast.error('Lesson title required'); return; }
    try {
      const created = await createLesson({
        module: mod.data.id,
        title: mod.newLessonTitle.trim(),
        lesson_order: mod.newLessonOrder ? Number(mod.newLessonOrder) : mod.lessons.length + 1,
      });
      setModules((prev) =>
        prev.map((m, i) =>
          i === modIdx
            ? {
                ...m,
                addingLesson: false,
                newLessonTitle: '',
                newLessonOrder: '',
                lessons: [
                  ...m.lessons,
                  { data: created, editing: false, editTitle: created.title, editOrder: String(created.lesson_order) },
                ],
              }
            : m,
        ),
      );
      toast.success('Lesson added');
    } catch {
      toast.error('Failed to add lesson');
    }
  };

  const handleSaveLesson = async (modIdx: number, lessonIdx: number) => {
    const lesson = modules[modIdx].lessons[lessonIdx];
    try {
      const updated = await updateLesson(lesson.data.id, {
        title: lesson.editTitle.trim(),
        lesson_order: Number(lesson.editOrder),
      });
      setModules((prev) =>
        prev.map((m, mi) =>
          mi !== modIdx ? m : {
            ...m,
            lessons: m.lessons.map((l, li) =>
              li !== lessonIdx
                ? l
                : { ...l, data: updated, editing: false, editTitle: updated.title, editOrder: String(updated.lesson_order) },
            ),
          },
        ),
      );
      toast.success('Lesson updated');
    } catch {
      toast.error('Failed to update lesson');
    }
  };

  const handleDeleteLesson = async (modIdx: number, lessonIdx: number) => {
    const lesson = modules[modIdx].lessons[lessonIdx];
    try {
      await deleteLesson(lesson.data.id);
      setModules((prev) =>
        prev.map((m, mi) =>
          mi !== modIdx ? m : { ...m, lessons: m.lessons.filter((_, li) => li !== lessonIdx) },
        ),
      );
      toast.success('Lesson deleted');
    } catch {
      toast.error('Failed to delete lesson');
    }
  };

  const updateModuleField = (idx: number, field: 'editTitle' | 'editOrder' | 'editing' | 'addingLesson' | 'newLessonTitle' | 'newLessonOrder', value: string | boolean) => {
    setModules((prev) => prev.map((m, i) => i === idx ? { ...m, [field]: value } : m));
  };

  const updateLessonField = (modIdx: number, lessonIdx: number, field: 'editTitle' | 'editOrder' | 'editing', value: string | boolean) => {
    setModules((prev) =>
      prev.map((m, mi) =>
        mi !== modIdx ? m : {
          ...m,
          lessons: m.lessons.map((l, li) => li === lessonIdx ? { ...l, [field]: value } : l),
        },
      ),
    );
  };

  // ---- CLO helpers ----

  const handleSuggestCLOs = async () => {
    setSuggestingCLOs(true);
    try {
      const result = await suggestCLOs(id);
      setCloDrafts(result.drafts);
      setCloTab('draft');
    } catch {
      toast.error('CLO suggestion failed. Check AI service connection.');
    } finally {
      setSuggestingCLOs(false);
    }
  };

  const handleSaveCLOs = async (drafts: CLODraft[]) => {
    let saved = 0;
    for (const draft of drafts) {
      try {
        const created = await createCLO(id, {
          code: draft.code,
          text: draft.text,
          bloom_level: draft.bloom_level,
          concepts: draft.concept_ids.map(Number).filter(Boolean),
          order: draft.order,
        });
        setClos((prev) => [...prev.filter((c) => c.code !== created.code), created]);
        saved++;
      } catch {
        toast.error(`Failed to save CLO: ${draft.code}`);
      }
    }
    if (saved > 0) {
      toast.success(`${saved} CLO${saved > 1 ? 's' : ''} saved`);
      setCloTab('list');
    }
  };

  const handleDeleteCLO = async (cloId: number) => {
    try {
      await deleteCLO(id, cloId);
      setClos((prev) => prev.filter((c) => c.id !== cloId));
      toast.success('CLO deleted');
    } catch {
      toast.error('Failed to delete CLO');
    }
  };

  // ---- Survey summary helpers ----

  const handleRefreshSummary = async () => {
    setRefreshingSummary(true);
    try {
      const updated = await refreshSurveySummary(id);
      setSummary(updated);
      toast.success('Survey summary refreshed');
    } catch {
      toast.error('Failed to refresh summary');
    } finally {
      setRefreshingSummary(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={32} className="animate-spin" style={{ color: 'var(--admin-ink-secondary)' }} />
      </div>
    );
  }

  return (
    <div className="admin-animate-page space-y-10">
      {/* Breadcrumb header */}
      <div className="mb-8">
        <nav aria-label="Breadcrumb" className="mb-3">
          <ol className="flex items-center gap-2 admin-label">
            <li>
              <Link to="/admin" className="hover:text-[var(--admin-accent)] transition-colors">
                Admin
              </Link>
            </li>
            <li className="flex items-center gap-2">
              <span style={{ color: 'var(--admin-hairline)' }}>/</span>
              <Link to="/admin/content" className="hover:text-[var(--admin-accent)] transition-colors">
                Content
              </Link>
            </li>
            <li className="flex items-center gap-2">
              <span style={{ color: 'var(--admin-hairline)' }}>/</span>
              <span style={{ color: 'var(--admin-ink)' }}>{course?.title ?? 'Course Editor'}</span>
            </li>
          </ol>
        </nav>
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 flex items-center justify-center bg-[var(--admin-paper-dark)] text-white rounded-[var(--admin-radius-md)] flex-shrink-0">
            <BookOpen size={22} />
          </div>
          <div>
            <h1 className="admin-heading-md">{course?.title ?? 'Course Editor'}</h1>
            <p className="admin-body-lg" style={{ color: 'var(--admin-ink-secondary)' }}>
              Manage modules, lessons, and learning outcomes
            </p>
          </div>
        </div>
      </div>

      {/* ── Modules ── */}
      <section className="space-y-3">
        {modules.map((mod, modIdx) => (
          <div key={mod.data.id} className="admin-card overflow-hidden">
            {/* Module header */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--admin-hairline-light)]">
              <button onClick={() => toggleModule(modIdx)} className="text-[var(--admin-ink-secondary)] hover:text-[var(--admin-ink)] transition-colors">
                {mod.expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </button>
              {mod.editing ? (
                <div className="flex-1 flex items-center gap-2">
                  <input
                    className="admin-input flex-1"
                    style={{ paddingTop: 8, paddingBottom: 8 }}
                    value={mod.editTitle}
                    onChange={(e) => updateModuleField(modIdx, 'editTitle', e.target.value)}
                    placeholder="Module title"
                  />
                  <input
                    className="admin-input"
                    style={{ width: 64, paddingTop: 8, paddingBottom: 8 }}
                    value={mod.editOrder}
                    onChange={(e) => updateModuleField(modIdx, 'editOrder', e.target.value)}
                    placeholder="#"
                    type="number"
                  />
                  <button onClick={() => handleSaveModule(modIdx)} className="admin-btn admin-btn-icon" style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}><Check size={14} /></button>
                  <button onClick={() => updateModuleField(modIdx, 'editing', false)} className="admin-btn admin-btn-ghost admin-btn-icon"><X size={14} /></button>
                </div>
              ) : (
                <div className="flex-1 flex items-center gap-2">
                  <span className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>{mod.data.title}</span>
                  <span className="text-xs" style={{ color: 'var(--admin-ink-secondary)' }}>#{mod.data.module_order}</span>
                  <span className="text-xs" style={{ color: 'var(--admin-ink-secondary)' }}>· {mod.lessons.length} lessons</span>
                </div>
              )}
              {!mod.editing && (
                <div className="flex items-center gap-1">
                  <button onClick={() => updateModuleField(modIdx, 'editing', true)} className="admin-btn admin-btn-ghost admin-btn-icon"><Edit size={13} /></button>
                  <button onClick={() => handleDeleteModule(modIdx)} className="admin-btn admin-btn-ghost-danger admin-btn-icon"><Trash2 size={13} /></button>
                </div>
              )}
            </div>

            {/* Lessons */}
            {mod.expanded && (
              <div>
                {mod.lessons.map((lesson, lessonIdx) => (
                  <div key={lesson.data.id} className="flex items-center gap-3 px-6 py-2.5 border-b border-[var(--admin-hairline-light)] last:border-b-0">
                    {lesson.editing ? (
                      <div className="flex-1 flex items-center gap-2">
                        <input
                          className="admin-input flex-1"
                          style={{ paddingTop: 6, paddingBottom: 6 }}
                          value={lesson.editTitle}
                          onChange={(e) => updateLessonField(modIdx, lessonIdx, 'editTitle', e.target.value)}
                          placeholder="Lesson title"
                        />
                        <input
                          className="admin-input"
                          style={{ width: 56, paddingTop: 6, paddingBottom: 6 }}
                          value={lesson.editOrder}
                          onChange={(e) => updateLessonField(modIdx, lessonIdx, 'editOrder', e.target.value)}
                          placeholder="#"
                          type="number"
                        />
                        <button onClick={() => handleSaveLesson(modIdx, lessonIdx)} className="admin-btn admin-btn-icon" style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}><Check size={13} /></button>
                        <button onClick={() => updateLessonField(modIdx, lessonIdx, 'editing', false)} className="admin-btn admin-btn-ghost admin-btn-icon"><X size={13} /></button>
                      </div>
                    ) : (
                      <>
                        <span className="text-xs" style={{ color: 'var(--admin-ink-secondary)', width: 20 }}>{lesson.data.lesson_order}.</span>
                        <span className="flex-1 text-sm" style={{ color: 'var(--admin-ink)' }}>{lesson.data.title}</span>
                        <button onClick={() => updateLessonField(modIdx, lessonIdx, 'editing', true)} className="admin-btn admin-btn-ghost admin-btn-icon"><Edit size={12} /></button>
                        <button onClick={() => handleDeleteLesson(modIdx, lessonIdx)} className="admin-btn admin-btn-ghost-danger admin-btn-icon"><Trash2 size={12} /></button>
                      </>
                    )}
                  </div>
                ))}

                {/* Add lesson form */}
                {mod.addingLesson ? (
                  <div className="flex items-center gap-2 px-6 py-2.5">
                    <input
                      autoFocus
                      className="admin-input flex-1"
                      style={{ paddingTop: 6, paddingBottom: 6 }}
                      value={mod.newLessonTitle}
                      onChange={(e) => updateModuleField(modIdx, 'newLessonTitle', e.target.value)}
                      placeholder="New lesson title"
                      onKeyDown={(e) => e.key === 'Enter' && handleAddLesson(modIdx)}
                    />
                    <input
                      className="admin-input"
                      style={{ width: 56, paddingTop: 6, paddingBottom: 6 }}
                      value={mod.newLessonOrder}
                      onChange={(e) => updateModuleField(modIdx, 'newLessonOrder', e.target.value)}
                      placeholder="#"
                      type="number"
                    />
                    <button onClick={() => handleAddLesson(modIdx)} className="admin-btn admin-btn-icon" style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}><Check size={14} /></button>
                    <button onClick={() => updateModuleField(modIdx, 'addingLesson', false)} className="admin-btn admin-btn-ghost admin-btn-icon"><X size={14} /></button>
                  </div>
                ) : (
                  <button
                    onClick={() => updateModuleField(modIdx, 'addingLesson', true)}
                    className="w-full flex items-center gap-2 px-6 py-2.5 text-sm transition-colors hover:bg-[var(--admin-paper-muted)]"
                    style={{ color: 'var(--admin-ink-secondary)' }}
                  >
                    <Plus size={13} /> Add Lesson
                  </button>
                )}
              </div>
            )}
          </div>
        ))}

        {/* Add module */}
        {addingModule ? (
          <div className="admin-card p-4 flex items-center gap-2">
            <input
              autoFocus
              className="admin-input flex-1"
              value={newModuleTitle}
              onChange={(e) => setNewModuleTitle(e.target.value)}
              placeholder="New module title"
              onKeyDown={(e) => e.key === 'Enter' && handleAddModule()}
            />
            <input
              className="admin-input"
              style={{ width: 64 }}
              value={newModuleOrder}
              onChange={(e) => setNewModuleOrder(e.target.value)}
              placeholder="#"
              type="number"
            />
            <button onClick={handleAddModule} className="admin-btn admin-btn-icon" style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}><Check size={15} /></button>
            <button onClick={() => setAddingModule(false)} className="admin-btn admin-btn-ghost admin-btn-icon"><X size={15} /></button>
          </div>
        ) : (
          <button
            onClick={() => setAddingModule(true)}
            className="w-full flex items-center justify-center gap-2 py-3 admin-card border-dashed border-2 transition-colors hover:bg-[var(--admin-paper-muted)]"
            style={{ color: 'var(--admin-ink-secondary)', borderColor: 'var(--admin-hairline)' }}
          >
            <Plus size={15} /> Add Module
          </button>
        )}
      </section>

      {/* ── Course Learning Outcomes ── */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <GraduationCap size={20} style={{ color: 'var(--admin-accent)' }} />
            <h2 className="admin-heading-xs">Learning Outcomes (CLOs)</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCloTab(cloTab === 'list' ? 'draft' : 'list')}
              className="admin-btn admin-btn-ghost admin-btn-sm"
            >
              {cloTab === 'list' ? 'View Drafts' : 'View Saved'}
            </button>
            <button
              onClick={handleSuggestCLOs}
              disabled={suggestingCLOs}
              className="admin-btn admin-btn-primary admin-btn-sm flex items-center gap-2"
            >
              {suggestingCLOs ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Sparkles size={14} />
              )}
              Suggest CLOs (AI)
            </button>
          </div>
        </div>

        {cloTab === 'list' ? (
          <div className="admin-card overflow-hidden">
            {cloLoading ? (
              <div className="flex items-center justify-center py-10">
                <Loader2 size={24} className="animate-spin" style={{ color: 'var(--admin-ink-secondary)' }} />
              </div>
            ) : clos.length === 0 ? (
              <div className="py-10 text-center text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>
                No CLOs yet. Use "Suggest CLOs (AI)" to generate drafts, then approve and save them.
              </div>
            ) : (
              <table className="admin-table">
                <thead>
                  <tr>
                    <th style={{ width: '5rem' }}>Code</th>
                    <th>Outcome Statement</th>
                    <th style={{ width: '8rem' }}>Bloom Level</th>
                    <th style={{ width: '3rem' }} />
                  </tr>
                </thead>
                <tbody>
                  {clos.map((clo) => (
                    <tr key={clo.id}>
                      <td className="font-mono text-xs" style={{ color: 'var(--admin-accent)' }}>{clo.code}</td>
                      <td style={{ color: 'var(--admin-ink)' }}>{clo.text}</td>
                      <td>
                        <span className="admin-badge" style={{ background: 'var(--admin-paper-muted)', color: 'var(--admin-ink-secondary)' }}>
                          {clo.bloom_level}
                        </span>
                      </td>
                      <td>
                        <button
                          onClick={() => handleDeleteCLO(clo.id)}
                          className="admin-btn admin-btn-ghost-danger admin-btn-icon"
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ) : (
          <div className="admin-card p-4">
            <p className="text-sm mb-4" style={{ color: 'var(--admin-ink-secondary)' }}>
              Review AI-generated CLO drafts. Approve or edit each row, then click "Save Approved".
            </p>
            <AIDraftReviewTable<CLODraft>
              columns={CLO_COLUMNS}
              initialRows={cloDrafts}
              onSave={handleSaveCLOs}
              onCancel={() => setCloTab('list')}
              emptyRow={CLO_EMPTY_ROW}
            />
          </div>
        )}
      </section>

      {/* ── Capstone Project ── */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Hammer size={20} style={{ color: 'var(--admin-accent)' }} />
          <h2 className="admin-heading-xs">Capstone Project</h2>
        </div>
        <button
          onClick={() => navigate(`/admin/courses/${id}/capstone`)}
          className="w-full admin-card p-5 flex items-center justify-between hover:border-[var(--admin-accent)] transition-all group text-left"
        >
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 flex items-center justify-center bg-[var(--admin-paper-dark)] text-white rounded-[var(--admin-radius-md)]">
              <Hammer size={20} />
            </div>
            <div>
              <p className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>Manage Capstone</p>
              <p className="text-xs" style={{ color: 'var(--admin-ink-secondary)' }}>
                Configure the project, rubric, proposals, and submissions
              </p>
            </div>
          </div>
          <ChevronRightIcon size={18} style={{ color: 'var(--admin-ink-secondary)' }} />
        </button>
      </section>

      {/* ── Survey Summary ── */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MessageSquare size={20} style={{ color: 'var(--admin-accent)' }} />
            <h2 className="admin-heading-xs">Student Survey Summary</h2>
          </div>
          <button
            onClick={handleRefreshSummary}
            disabled={refreshingSummary}
            className="admin-btn admin-btn-ghost admin-btn-sm flex items-center gap-2"
          >
            {refreshingSummary ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Refresh
          </button>
        </div>

        <div className="admin-card p-6">
          {summaryLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={24} className="animate-spin" style={{ color: 'var(--admin-ink-secondary)' }} />
            </div>
          ) : summary === null ? (
            <p className="text-sm text-center py-6" style={{ color: 'var(--admin-ink-secondary)' }}>
              No survey summary yet. Students must complete the course and submit surveys first. Then click "Refresh" to generate a summary.
            </p>
          ) : (
            <div className="space-y-6">
              {/* Header row */}
              <div className="flex items-center gap-4">
                <span
                  className={`admin-badge text-sm capitalize ${SENTIMENT_BADGE[summary.sentiment] ?? 'admin-badge-gray'}`}
                  style={summary.sentiment === 'negative' ? { background: 'var(--admin-error)', color: '#fff' } : undefined}
                >
                  {summary.sentiment} overall
                </span>
                <span className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>
                  Based on {summary.response_count} response{summary.response_count !== 1 ? 's' : ''}
                </span>
                <span className="text-xs ml-auto" style={{ color: 'var(--admin-ink-secondary)' }}>
                  Last updated: {new Date(summary.generated_at).toLocaleString()}
                </span>
              </div>

              {/* Themes */}
              {summary.recurring_themes.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--admin-ink)' }}>Recurring Themes</h4>
                  <div className="flex flex-wrap gap-2">
                    {summary.recurring_themes.map((t, i) => (
                      <span key={i} className="admin-badge" style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}>
                        {t.theme} ({t.count})
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Praise + Complaints */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--admin-success)' }}>What students liked</h4>
                  <ul className="space-y-1.5">
                    {summary.top_praise.map((p, i) => (
                      <li key={i} className="text-sm flex items-start gap-2" style={{ color: 'var(--admin-ink)' }}>
                        <span className="mt-0.5" style={{ color: 'var(--admin-success)' }}>+</span> {p}
                      </li>
                    ))}
                    {summary.top_praise.length === 0 && <li className="text-xs" style={{ color: 'var(--admin-ink-secondary)' }}>None yet</li>}
                  </ul>
                </div>
                <div>
                  <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--admin-error)' }}>Areas to improve</h4>
                  <ul className="space-y-1.5">
                    {summary.top_complaints.map((c, i) => (
                      <li key={i} className="text-sm flex items-start gap-2" style={{ color: 'var(--admin-ink)' }}>
                        <span className="mt-0.5" style={{ color: 'var(--admin-error)' }}>−</span> {c}
                      </li>
                    ))}
                    {summary.top_complaints.length === 0 && <li className="text-xs" style={{ color: 'var(--admin-ink-secondary)' }}>None yet</li>}
                  </ul>
                </div>
              </div>

              {/* Per-CLO perception */}
              {Object.keys(summary.per_clo_perception).length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2" style={{ color: 'var(--admin-ink)' }}>Per-CLO Student Perception</h4>
                  <div className="space-y-2">
                    {Object.entries(summary.per_clo_perception).map(([cloText, perception]) => (
                      <div key={cloText} className="flex items-start gap-3 text-sm">
                        <span className="shrink-0 font-medium truncate" style={{ color: 'var(--admin-ink-secondary)', width: '14rem' }} title={cloText}>{cloText}</span>
                        <span style={{ color: 'var(--admin-ink)' }}>{perception}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
