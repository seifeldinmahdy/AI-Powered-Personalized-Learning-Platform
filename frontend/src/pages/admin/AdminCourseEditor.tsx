import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import { toast } from 'sonner';
import {
  ChevronDown, ChevronRight, Plus, Trash2, Edit, Check, X, Loader2, ArrowLeft, BookOpen,
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
  positive: 'bg-green-100 text-green-700',
  mixed: 'bg-amber-100 text-amber-700',
  negative: 'bg-red-100 text-red-700',
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
        <Loader2 size={32} className="animate-spin text-secondary" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto py-8 px-4 space-y-10">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button onClick={() => navigate('/admin')} className="p-2 rounded-xl hover:bg-muted/60 transition-colors">
          <ArrowLeft size={18} className="text-muted-foreground" />
        </button>
        <div className="p-2 rounded-xl bg-gradient-to-br from-primary/20 to-secondary/20">
          <BookOpen size={22} className="text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold">{course?.title ?? 'Course Editor'}</h1>
          <p className="text-sm text-muted-foreground">Manage modules, lessons, and learning outcomes</p>
        </div>
      </div>

      {/* ── Modules ── */}
      <div className="space-y-3">
        {modules.map((mod, modIdx) => (
          <div key={mod.data.id} className="bg-card rounded-2xl border border-border shadow-sm overflow-hidden">
            {/* Module header */}
            <div className="flex items-center gap-3 px-4 py-3">
              <button onClick={() => toggleModule(modIdx)} className="text-muted-foreground hover:text-foreground transition-colors">
                {mod.expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </button>
              {mod.editing ? (
                <div className="flex-1 flex items-center gap-2">
                  <input
                    className="flex-1 border border-border rounded-lg px-3 py-1.5 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring"
                    value={mod.editTitle}
                    onChange={(e) => updateModuleField(modIdx, 'editTitle', e.target.value)}
                    placeholder="Module title"
                  />
                  <input
                    className="w-16 border border-border rounded-lg px-2 py-1.5 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring"
                    value={mod.editOrder}
                    onChange={(e) => updateModuleField(modIdx, 'editOrder', e.target.value)}
                    placeholder="#"
                    type="number"
                  />
                  <button onClick={() => handleSaveModule(modIdx)} className="p-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20"><Check size={14} /></button>
                  <button onClick={() => updateModuleField(modIdx, 'editing', false)} className="p-1.5 rounded-lg bg-muted text-muted-foreground hover:bg-muted/80"><X size={14} /></button>
                </div>
              ) : (
                <div className="flex-1 flex items-center gap-2">
                  <span className="font-semibold text-sm">{mod.data.title}</span>
                  <span className="text-xs text-muted-foreground">#{mod.data.module_order}</span>
                  <span className="text-xs text-muted-foreground ml-1">· {mod.lessons.length} lessons</span>
                </div>
              )}
              {!mod.editing && (
                <div className="flex items-center gap-1">
                  <button onClick={() => updateModuleField(modIdx, 'editing', true)} className="p-1.5 rounded-lg hover:bg-muted/60 text-muted-foreground"><Edit size={13} /></button>
                  <button onClick={() => handleDeleteModule(modIdx)} className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive"><Trash2 size={13} /></button>
                </div>
              )}
            </div>

            {/* Lessons */}
            {mod.expanded && (
              <div className="border-t border-border">
                {mod.lessons.map((lesson, lessonIdx) => (
                  <div key={lesson.data.id} className="flex items-center gap-3 px-6 py-2.5 border-b border-border/50 last:border-b-0">
                    {lesson.editing ? (
                      <div className="flex-1 flex items-center gap-2">
                        <input
                          className="flex-1 border border-border rounded-lg px-3 py-1 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring"
                          value={lesson.editTitle}
                          onChange={(e) => updateLessonField(modIdx, lessonIdx, 'editTitle', e.target.value)}
                          placeholder="Lesson title"
                        />
                        <input
                          className="w-14 border border-border rounded-lg px-2 py-1 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring"
                          value={lesson.editOrder}
                          onChange={(e) => updateLessonField(modIdx, lessonIdx, 'editOrder', e.target.value)}
                          placeholder="#"
                          type="number"
                        />
                        <button onClick={() => handleSaveLesson(modIdx, lessonIdx)} className="p-1 rounded-lg bg-primary/10 text-primary hover:bg-primary/20"><Check size={13} /></button>
                        <button onClick={() => updateLessonField(modIdx, lessonIdx, 'editing', false)} className="p-1 rounded-lg bg-muted text-muted-foreground hover:bg-muted/80"><X size={13} /></button>
                      </div>
                    ) : (
                      <>
                        <span className="text-xs text-muted-foreground w-5">{lesson.data.lesson_order}.</span>
                        <span className="flex-1 text-sm">{lesson.data.title}</span>
                        <button onClick={() => updateLessonField(modIdx, lessonIdx, 'editing', true)} className="p-1 rounded-lg hover:bg-muted/60 text-muted-foreground"><Edit size={12} /></button>
                        <button onClick={() => handleDeleteLesson(modIdx, lessonIdx)} className="p-1 rounded-lg hover:bg-destructive/10 text-destructive"><Trash2 size={12} /></button>
                      </>
                    )}
                  </div>
                ))}

                {/* Add lesson form */}
                {mod.addingLesson ? (
                  <div className="flex items-center gap-2 px-6 py-2.5">
                    <input
                      autoFocus
                      className="flex-1 border border-border rounded-lg px-3 py-1.5 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring"
                      value={mod.newLessonTitle}
                      onChange={(e) => updateModuleField(modIdx, 'newLessonTitle', e.target.value)}
                      placeholder="New lesson title"
                      onKeyDown={(e) => e.key === 'Enter' && handleAddLesson(modIdx)}
                    />
                    <input
                      className="w-14 border border-border rounded-lg px-2 py-1.5 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring"
                      value={mod.newLessonOrder}
                      onChange={(e) => updateModuleField(modIdx, 'newLessonOrder', e.target.value)}
                      placeholder="#"
                      type="number"
                    />
                    <button onClick={() => handleAddLesson(modIdx)} className="p-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20"><Check size={14} /></button>
                    <button onClick={() => updateModuleField(modIdx, 'addingLesson', false)} className="p-1.5 rounded-lg bg-muted text-muted-foreground"><X size={14} /></button>
                  </div>
                ) : (
                  <button
                    onClick={() => updateModuleField(modIdx, 'addingLesson', true)}
                    className="w-full flex items-center gap-2 px-6 py-2.5 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
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
          <div className="bg-card rounded-2xl border border-border shadow-sm p-4 flex items-center gap-2">
            <input
              autoFocus
              className="flex-1 border border-border rounded-lg px-3 py-2 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring"
              value={newModuleTitle}
              onChange={(e) => setNewModuleTitle(e.target.value)}
              placeholder="New module title"
              onKeyDown={(e) => e.key === 'Enter' && handleAddModule()}
            />
            <input
              className="w-16 border border-border rounded-lg px-2 py-2 text-sm bg-input-background focus:outline-none focus:ring-1 focus:ring-ring"
              value={newModuleOrder}
              onChange={(e) => setNewModuleOrder(e.target.value)}
              placeholder="#"
              type="number"
            />
            <button onClick={handleAddModule} className="p-2 rounded-xl bg-primary/10 text-primary hover:bg-primary/20"><Check size={15} /></button>
            <button onClick={() => setAddingModule(false)} className="p-2 rounded-xl bg-muted text-muted-foreground hover:bg-muted/80"><X size={15} /></button>
          </div>
        ) : (
          <button
            onClick={() => setAddingModule(true)}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-2xl border-2 border-dashed border-border text-sm text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
          >
            <Plus size={15} /> Add Module
          </button>
        )}
      </div>

      {/* ── Course Learning Outcomes ── */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <GraduationCap size={20} className="text-primary" />
            <h2 className="text-lg font-bold mb-0">Learning Outcomes (CLOs)</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setCloTab(cloTab === 'list' ? 'draft' : 'list')}
              className="px-3 py-1.5 rounded-xl text-xs border border-border text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors"
            >
              {cloTab === 'list' ? 'View Drafts' : 'View Saved'}
            </button>
            <button
              onClick={handleSuggestCLOs}
              disabled={suggestingCLOs}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors"
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
          <div className="bg-card rounded-2xl border border-border shadow-sm overflow-hidden">
            {cloLoading ? (
              <div className="flex items-center justify-center py-10">
                <Loader2 size={24} className="animate-spin text-secondary" />
              </div>
            ) : clos.length === 0 ? (
              <div className="py-10 text-center text-muted-foreground text-sm">
                No CLOs yet. Use "Suggest CLOs (AI)" to generate drafts, then approve and save them.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="px-4 py-3 text-left font-semibold text-muted-foreground w-20">Code</th>
                    <th className="px-4 py-3 text-left font-semibold text-muted-foreground">Outcome Statement</th>
                    <th className="px-4 py-3 text-left font-semibold text-muted-foreground w-32">Bloom Level</th>
                    <th className="px-4 py-3 w-12" />
                  </tr>
                </thead>
                <tbody>
                  {clos.map((clo) => (
                    <tr key={clo.id} className="border-t border-border hover:bg-muted/30 transition-colors">
                      <td className="px-4 py-3 font-mono text-xs text-primary">{clo.code}</td>
                      <td className="px-4 py-3 text-foreground">{clo.text}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded-full text-xs bg-secondary/10 text-secondary capitalize">
                          {clo.bloom_level}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => handleDeleteCLO(clo.id)}
                          className="p-1.5 rounded-lg hover:bg-destructive/10 text-destructive"
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
          <div className="bg-card rounded-2xl border border-border shadow-sm p-4">
            <p className="text-sm text-muted-foreground mb-4">
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
          <Hammer size={20} className="text-primary" />
          <h2 className="text-lg font-bold mb-0">Capstone Project</h2>
        </div>
        <button
          onClick={() => navigate(`/admin/courses/${id}/capstone`)}
          className="w-full bg-card rounded-2xl border border-border shadow-sm p-5 flex items-center justify-between hover:border-primary/40 hover:shadow-md transition-all group"
        >
          <div className="flex items-center gap-4">
            <div className="p-2.5 rounded-xl bg-gradient-to-br from-primary/20 to-secondary/20">
              <Hammer size={20} className="text-primary" />
            </div>
            <div className="text-left">
              <p className="font-semibold text-sm">Manage Capstone</p>
              <p className="text-xs text-muted-foreground">
                Configure the project, rubric, proposals, and submissions
              </p>
            </div>
          </div>
          <ChevronRightIcon size={18} className="text-muted-foreground group-hover:text-primary transition-colors" />
        </button>
      </section>

      {/* ── Survey Summary ── */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <MessageSquare size={20} className="text-primary" />
            <h2 className="text-lg font-bold mb-0">Student Survey Summary</h2>
          </div>
          <button
            onClick={handleRefreshSummary}
            disabled={refreshingSummary}
            className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-border text-sm text-muted-foreground hover:text-foreground hover:border-primary/40 disabled:opacity-60 transition-colors"
          >
            {refreshingSummary ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Refresh
          </button>
        </div>

        <div className="bg-card rounded-2xl border border-border shadow-sm p-6">
          {summaryLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={24} className="animate-spin text-secondary" />
            </div>
          ) : summary === null ? (
            <p className="text-sm text-muted-foreground text-center py-6">
              No survey summary yet. Students must complete the course and submit surveys first. Then click "Refresh" to generate a summary.
            </p>
          ) : (
            <div className="space-y-6">
              {/* Header row */}
              <div className="flex items-center gap-4">
                <span className={`px-3 py-1 rounded-full text-sm font-semibold capitalize ${SENTIMENT_BADGE[summary.sentiment] ?? 'bg-muted text-muted-foreground'}`}>
                  {summary.sentiment} overall
                </span>
                <span className="text-sm text-muted-foreground">
                  Based on {summary.response_count} response{summary.response_count !== 1 ? 's' : ''}
                </span>
                <span className="text-xs text-muted-foreground ml-auto">
                  Last updated: {new Date(summary.generated_at).toLocaleString()}
                </span>
              </div>

              {/* Themes */}
              {summary.recurring_themes.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">Recurring Themes</h4>
                  <div className="flex flex-wrap gap-2">
                    {summary.recurring_themes.map((t, i) => (
                      <span key={i} className="px-2.5 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium">
                        {t.theme} ({t.count})
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Praise + Complaints */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <h4 className="text-sm font-semibold text-green-700 mb-2">What students liked</h4>
                  <ul className="space-y-1.5">
                    {summary.top_praise.map((p, i) => (
                      <li key={i} className="text-sm text-foreground flex items-start gap-2">
                        <span className="text-green-500 mt-0.5">+</span> {p}
                      </li>
                    ))}
                    {summary.top_praise.length === 0 && <li className="text-xs text-muted-foreground">None yet</li>}
                  </ul>
                </div>
                <div>
                  <h4 className="text-sm font-semibold text-red-600 mb-2">Areas to improve</h4>
                  <ul className="space-y-1.5">
                    {summary.top_complaints.map((c, i) => (
                      <li key={i} className="text-sm text-foreground flex items-start gap-2">
                        <span className="text-red-400 mt-0.5">−</span> {c}
                      </li>
                    ))}
                    {summary.top_complaints.length === 0 && <li className="text-xs text-muted-foreground">None yet</li>}
                  </ul>
                </div>
              </div>

              {/* Per-CLO perception */}
              {Object.keys(summary.per_clo_perception).length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">Per-CLO Student Perception</h4>
                  <div className="space-y-2">
                    {Object.entries(summary.per_clo_perception).map(([cloText, perception]) => (
                      <div key={cloText} className="flex items-start gap-3 text-sm">
                        <span className="text-muted-foreground shrink-0 font-medium w-56 truncate" title={cloText}>{cloText}</span>
                        <span className="text-foreground">{perception}</span>
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
