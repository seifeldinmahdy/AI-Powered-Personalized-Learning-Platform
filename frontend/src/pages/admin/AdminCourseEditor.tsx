import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import { toast } from 'sonner';
import {
  ChevronDown, ChevronRight, Plus, Trash2, Edit, Check, X, Loader2, ArrowLeft, BookOpen,
} from 'lucide-react';
import {
  getAdminCourses, getModulesByCourse, getLessonsByModule,
  createModule, updateModule, deleteModule,
  createLesson, updateLesson, deleteLesson,
  type AdminModule, type AdminLesson, type AdminCourse,
} from '../../services/admin';

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

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={32} className="animate-spin text-secondary" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto py-8 px-4">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => navigate('/admin')} className="p-2 rounded-xl hover:bg-muted/60 transition-colors">
          <ArrowLeft size={18} className="text-muted-foreground" />
        </button>
        <div className="p-2 rounded-xl bg-gradient-to-br from-primary/20 to-secondary/20">
          <BookOpen size={22} className="text-primary" />
        </div>
        <div>
          <h1 className="text-xl font-bold">{course?.title ?? 'Course Editor'}</h1>
          <p className="text-sm text-muted-foreground">Manage modules and lessons</p>
        </div>
      </div>

      {/* Modules */}
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
    </div>
  );
}
