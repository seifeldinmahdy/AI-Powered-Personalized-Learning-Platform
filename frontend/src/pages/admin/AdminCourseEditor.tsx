import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router';
import { toast } from 'sonner';
import {
  ChevronDown, ChevronRight, Plus, Trash2, Edit, Check, X, Loader2, BookOpen,
  Sparkles, RefreshCw, GraduationCap, MessageSquare, Hammer,
  Upload, FileText,
} from 'lucide-react';
import {
  getAdminCourses, getModulesByCourse, getLessonsByModule,
  createModule, updateModule, deleteModule,
  createLesson, updateLesson, deleteLesson,
  getAvailableBooks, updateCourse,
  type AdminModule, type AdminLesson, type AdminCourse,
} from '../../services/admin';
import { AIDraftReviewTable, type Column } from '../../components/AIDraftReviewTable';
import {
  getCLOs, suggestCLOs, createCLO, updateCLO, deleteCLO, getCLOAttainment,
  type CLO, type CLODraft, type CLOAttainment,
} from '../../services/clos';
import { getSurveySummary, refreshSurveySummary, type SurveySummary } from '../../services/surveys';
import {
  getCapstoneForCourse, createCapstone, updateCapstone,
  createRubricItem, updateRubricItem, deleteRubricItem,
  draftRubric, extractSpec, listProposals, approveProposal, listSubmissions,
  type Capstone, type CapstoneRubricItem, type CapstoneProposal,
  type CapstoneSubmission, type RubricDraft,
} from '../../services/capstone';
import {
  getCourse, draftCourseDescription, getPathwayVersions, regeneratePathway,
  type Course, type PathwayVersion,
} from '../../services/courses';
import { getConcepts, type Concept } from '../../services/concepts';
import {
  getCourseCorpus, uploadBook, addCorpusSource,
  removeCorpusSource, getIndexStatus, type CourseCorpus, type CorpusSource,
  type CorpusSourceType, type AvailableBook,
} from '../../services/corpus';

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
  const id = Number(courseId);

  const [course, setCourse] = useState<AdminCourse | null>(null);
  const [courseDetail, setCourseDetail] = useState<Course | null>(null);
  const [modules, setModules] = useState<ModuleState[]>([]);
  const [loading, setLoading] = useState(true);

  // Course metadata form
  const [courseForm, setCourseForm] = useState<Partial<Course>>({});
  const [savingCourse, setSavingCourse] = useState(false);
  const [savedCourse, setSavedCourse] = useState(false);
  const [draftingDescription, setDraftingDescription] = useState(false);

  // Corpus state
  const [corpus, setCorpus] = useState<CourseCorpus | null>(null);
  const [corpusLoading, setCorpusLoading] = useState(false);
  const [availableBooks, setAvailableBooks] = useState<AvailableBook[]>([]);
  const [selectedBookStem, setSelectedBookStem] = useState('');
  const [uploading, setUploading] = useState(false);
  const [pollingStems, setPollingStems] = useState<Set<string>>(new Set());
  const [addingModule, setAddingModule] = useState(false);
  const [newModuleTitle, setNewModuleTitle] = useState('');
  const [newModuleOrder, setNewModuleOrder] = useState('');

  // CLO state
  const [clos, setClos] = useState<CLO[]>([]);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [cloLoading, setCloLoading] = useState(false);
  const [suggestingCLOs, setSuggestingCLOs] = useState(false);
  const [cloTab, setCloTab] = useState<'list' | 'draft'>('list');
  const [cloDrafts, setCloDrafts] = useState<CLODraft[]>([]);
  const [editingCLOId, setEditingCLOId] = useState<number | null>(null);
  const [cloEditForm, setCloEditForm] = useState<Partial<CLO>>({});
  const [addingClo, setAddingClo] = useState(false);
  const [newCloForm, setNewCloForm] = useState<Omit<CLO, 'id'>>({
    code: '',
    text: '',
    bloom_level: 'understand',
    concepts: [],
    order: 1,
  });
  const [savingNewClo, setSavingNewClo] = useState(false);
  const newCloRowRef = useRef<HTMLTableRowElement>(null);
  const indexedStemsRef = useRef<Set<string>>(new Set());
  const [cloAttainment, setCloAttainment] = useState<CLOAttainment[]>([]);
  const [attainmentStudentId, setAttainmentStudentId] = useState('');
  const [loadingAttainment, setLoadingAttainment] = useState(false);

  // Capstone state
  const [capstone, setCapstone] = useState<Capstone | null>(null);
  const [capstoneLoading, setCapstoneLoading] = useState(false);
  const [capstoneForm, setCapstoneForm] = useState<Partial<Capstone>>({});
  const [savingCapstone, setSavingCapstone] = useState(false);
  const [rubricItems, setRubricItems] = useState<CapstoneRubricItem[]>([]);
  const [editingRubricId, setEditingRubricId] = useState<number | null>(null);
  const [rubricEditForm, setRubricEditForm] = useState<Partial<CapstoneRubricItem>>({});
  const [draftingRubric, setDraftingRubric] = useState(false);
  const [extractSpecText, setExtractSpecText] = useState('');
  const [extractingSpec, setExtractingSpec] = useState(false);
  const [proposals, setProposals] = useState<CapstoneProposal[]>([]);
  const [submissions, setSubmissions] = useState<CapstoneSubmission[]>([]);
  const [proposalFeedback, setProposalFeedback] = useState<Record<number, string>>({});

  // Pathway admin state
  const [pathwayVersions, setPathwayVersions] = useState<PathwayVersion[]>([]);
  const [pathwayStudentId, setPathwayStudentId] = useState('');
  const [loadingPathway, setLoadingPathway] = useState(false);
  const [regeneratingPathway, setRegeneratingPathway] = useState(false);

  // Survey summary state
  const [summary, setSummary] = useState<SurveySummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [refreshingSummary, setRefreshingSummary] = useState(false);

  useEffect(() => {
    Promise.all([getAdminCourses(), getModulesByCourse(id), getCourse(id)])
      .then(([courses, mods, detail]) => {
        setCourse(courses.find((c) => c.id === id) ?? null);
        setCourseDetail(detail);
        setCourseForm({
          title: detail.title,
          description: detail.description,
          difficulty: detail.difficulty,
          status: detail.status,
          tags: detail.tags,
          price: detail.price,
          syllabus: detail.syllabus,
          is_published: detail.is_published,
        });
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

    // Load CLOs, concepts, and survey summary in parallel
    setCloLoading(true);
    getCLOs(id)
      .then(setClos)
      .catch(() => toast.error('Failed to load CLOs'))
      .finally(() => setCloLoading(false));

    getConcepts(id)
      .then(setConcepts)
      .catch(() => toast.error('Failed to load concepts'));

    setSummaryLoading(true);
    getSurveySummary(id)
      .then(setSummary)
      .catch(() => setSummary(null))
      .finally(() => setSummaryLoading(false));

    // Load corpus
    loadCorpus();
    loadAvailableBooks();

    // Load capstone
    loadCapstone();
  }, [id]);

  const loadCapstone = async () => {
    setCapstoneLoading(true);
    try {
      const data = await getCapstoneForCourse(id);
      setCapstone(data);
      setCapstoneForm({
        title: data.title,
        spec_mode: data.spec_mode,
        team_mode: data.team_mode,
        team_cap: data.team_cap,
        deadline: data.deadline ? data.deadline.slice(0, 16) : '',
        status: data.status,
        pass_policy: data.pass_policy,
        brief_text: data.brief_text,
        github_template_repo: data.github_template_repo,
        run_command: data.run_command,
      });
      setRubricItems(data.rubric_items ?? []);
      loadCapstoneRelated(data.id);
    } catch {
      // No capstone yet is OK; leave form empty.
      setCapstone(null);
    } finally {
      setCapstoneLoading(false);
    }
  };

  const loadCapstoneRelated = async (capstoneId: number) => {
    try {
      const [proposalsData, submissionsData] = await Promise.all([
        listProposals(capstoneId),
        listSubmissions(capstoneId),
      ]);
      setProposals(proposalsData);
      setSubmissions(submissionsData);
    } catch {
      toast.error('Failed to load capstone related data');
    }
  };

  const loadCorpus = async () => {
    setCorpusLoading(true);
    try {
      const data = await getCourseCorpus(id);
      setCorpus(data);
      if (data) {
        const active = data.sources
          .filter((s) => s.index_status === 'indexing' || s.index_status === 'pending')
          .map((s) => s.book_stem);
        setPollingStems((prev) => new Set([...prev, ...active]));
      }
    } catch {
      toast.error('Failed to load corpus');
    } finally {
      setCorpusLoading(false);
    }
  };

  const loadAvailableBooks = useCallback(async () => {
    try {
      const books = await getAvailableBooks(id);
      setAvailableBooks(books);
    } catch {
      toast.error('Failed to load available books');
    }
  }, [id]);

  // Poll indexing status for active sources
  useEffect(() => {
    if (pollingStems.size === 0) return;
    const interval = setInterval(async () => {
      const updates = await Promise.all(
        Array.from(pollingStems).map(async (bookStem) => {
          try {
            const status = await getIndexStatus(id, bookStem);
            return { bookStem, status };
          } catch {
            return { bookStem, status: { status: 'failed' as const } };
          }
        }),
      );
      setCorpus((prev) => {
        if (!prev) return prev;
        const nextSources = prev.sources.map((s) => {
          const update = updates.find((u) => u.bookStem === s.book_stem);
          if (!update) return s;
          return {
            ...s,
            index_status: update.status.status,
            chunk_count: update.status.chunk_count ?? s.chunk_count,
          };
        });
        return { ...prev, sources: nextSources };
      });
      setPollingStems((prev) => {
        const next = new Set(prev);
        updates.forEach(({ bookStem, status }) => {
          if (status.status !== 'indexing' && status.status !== 'pending') {
            next.delete(bookStem);
          }
        });
        return next;
      });
    }, 3000);
    return () => clearInterval(interval);
  }, [id, pollingStems]);

  // Refetch available books whenever a corpus source transitions to indexed
  useEffect(() => {
    const currentIndexed = new Set(
      corpus?.sources.filter((s) => s.index_status === 'indexed').map((s) => s.book_stem) ?? [],
    );
    const newlyIndexed = Array.from(currentIndexed).filter(
      (stem) => !indexedStemsRef.current.has(stem),
    );
    if (newlyIndexed.length > 0) {
      loadAvailableBooks();
    }
    indexedStemsRef.current = currentIndexed;
  }, [corpus?.sources, loadAvailableBooks]);

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

  const resetNewCloForm = () => {
    const nextOrder = clos.length > 0 ? Math.max(...clos.map((c) => c.order)) + 1 : 1;
    const nextCodeNumber = clos.length + 1;
    setNewCloForm({
      code: `CLO${nextCodeNumber}`,
      text: '',
      bloom_level: 'understand',
      concepts: [],
      order: nextOrder,
    });
  };

  const handleOpenAddClo = () => {
    if (addingClo) {
      newCloRowRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      return;
    }
    resetNewCloForm();
    setAddingClo(true);
  };

  const handleCancelNewClo = () => {
    setAddingClo(false);
    setNewCloForm({ code: '', text: '', bloom_level: 'understand', concepts: [], order: 1 });
  };

  const handleSaveNewClo = async () => {
    if (!newCloForm.code.trim() || !newCloForm.text.trim()) {
      toast.error('Code and outcome statement are required');
      return;
    }
    setSavingNewClo(true);
    try {
      const created = await createCLO(id, {
        code: newCloForm.code.trim(),
        text: newCloForm.text.trim(),
        bloom_level: newCloForm.bloom_level,
        concepts: newCloForm.concepts,
        order: Number(newCloForm.order),
      });
      setClos((prev) => [...prev, created]);
      setAddingClo(false);
      setNewCloForm({ code: '', text: '', bloom_level: 'understand', concepts: [], order: 1 });
      toast.success('CLO created');
    } catch {
      toast.error('Failed to create CLO');
    } finally {
      setSavingNewClo(false);
    }
  };

  const parseConceptInput = (value: string): number[] =>
    value
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean)
      .map(Number)
      .filter((n) => Number.isFinite(n) && n > 0);

  // ---- Course metadata helpers ----

  const updateCourseForm = (field: keyof Course, value: unknown) => {
    setCourseForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSaveCourseDetails = async () => {
    setSavingCourse(true);
    try {
      const payload: Partial<AdminCourse> = {
        title: courseForm.title,
        description: courseForm.description,
        difficulty: courseForm.difficulty,
        status: courseForm.status,
        tags: Array.isArray(courseForm.tags) ? courseForm.tags : [],
        price: courseForm.price,
        syllabus: courseForm.syllabus,
        is_published: courseForm.is_published,
      };
      const updated = await updateCourse(id, payload);
      setCourseDetail(updated);
      setCourse((prev) =>
        prev
          ? {
              ...prev,
              title: updated.title,
              description: updated.description,
              difficulty: updated.difficulty,
              status: updated.status,
              tags: updated.tags,
              price: updated.price,
            }
          : null,
      );
      setSavedCourse(true);
      setTimeout(() => setSavedCourse(false), 2000);
      toast.success('Course details saved');
    } catch {
      toast.error('Failed to save course details');
    } finally {
      setSavingCourse(false);
    }
  };

  const handleDraftDescription = async () => {
    setDraftingDescription(true);
    try {
      const result = await draftCourseDescription(id, {
        current_description: courseForm.description,
        topics: [],
      });
      setCourseForm((prev) => ({ ...prev, description: result.description }));
      toast.success('Description draft generated');
    } catch {
      toast.error('Failed to draft description');
    } finally {
      setDraftingDescription(false);
    }
  };

  // ---- Corpus helpers ----

  const handleUploadBook = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const data = await uploadBook(id, file);
      toast.success(`Uploaded ${file.name}`);
      const bookStem = (data as { book_stem?: string })?.book_stem ?? file.name.replace(/\.[^/.]+$/, '');
      await handleAttachSource(bookStem, file.name, 'pdf');
    } catch {
      toast.error('Failed to upload book');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const handleAttachSource = async (bookStem: string, title: string, sourceType: CorpusSourceType) => {
    try {
      const source = await addCorpusSource(id, {
        title,
        book_stem: bookStem,
        source_type: sourceType,
        concept: null,
        is_active: true,
      });
      setCorpus((prev) => {
        if (!prev) return prev;
        return { ...prev, sources: [...prev.sources, source] };
      });
      setPollingStems((prev) => new Set([...prev, source.book_stem]));
      toast.success('Source attached; indexing started');
    } catch {
      toast.error('Failed to attach source');
    }
  };

  const handleAttachAvailableBook = async () => {
    if (!selectedBookStem) return;
    const book = availableBooks.find((b) => b.book_stem === selectedBookStem);
    if (!book) return;
    await handleAttachSource(book.book_stem, book.title, book.source_type ?? 'pdf');
    setSelectedBookStem('');
  };

  const handleRemoveSource = async (sourceId: number, bookStem: string) => {
    try {
      await removeCorpusSource(id, sourceId);
      setCorpus((prev) => {
        if (!prev) return prev;
        return { ...prev, sources: prev.sources.filter((s) => s.id !== sourceId) };
      });
      setPollingStems((prev) => {
        const next = new Set(prev);
        next.delete(bookStem);
        return next;
      });
      toast.success('Source removed');
    } catch {
      toast.error('Failed to remove source');
    }
  };

  // ---- CLO edit helpers ----

  const startEditCLO = (clo: CLO) => {
    setEditingCLOId(clo.id);
    setCloEditForm({ ...clo });
  };

  const cancelEditCLO = () => {
    setEditingCLOId(null);
    setCloEditForm({});
  };

  const handleSaveCLO = async (cloId: number) => {
    try {
      if (cloId === -1) {
        const created = await createCLO(id, {
          code: cloEditForm.code ?? '',
          text: cloEditForm.text ?? '',
          bloom_level: cloEditForm.bloom_level ?? 'understand',
          concepts: cloEditForm.concepts ?? [],
          order: cloEditForm.order ?? clos.length + 1,
        });
        setClos((prev) => [...prev, created]);
        setEditingCLOId(null);
        toast.success('CLO created');
      } else {
        const updated = await updateCLO(id, cloId, {
          code: cloEditForm.code,
          text: cloEditForm.text,
          bloom_level: cloEditForm.bloom_level,
          concepts: cloEditForm.concepts,
          order: cloEditForm.order,
        });
        setClos((prev) => prev.map((c) => (c.id === cloId ? updated : c)));
        setEditingCLOId(null);
        toast.success('CLO updated');
      }
    } catch {
      toast.error(cloId === -1 ? 'Failed to create CLO' : 'Failed to update CLO');
    }
  };

  const startAddCLO = () => {
    setEditingCLOId(-1);
    setCloEditForm({
      code: '',
      text: '',
      bloom_level: 'understand',
      concepts: [],
      order: clos.length + 1,
    });
  };

  const handleLoadAttainment = async () => {
    setLoadingAttainment(true);
    try {
      const data = await getCLOAttainment(
        id,
        attainmentStudentId ? Number(attainmentStudentId) : undefined,
      );
      setCloAttainment(data);
    } catch {
      toast.error('Failed to load CLO attainment');
    } finally {
      setLoadingAttainment(false);
    }
  };

  // ---- Capstone helpers ----

  const updateCapstoneForm = (field: keyof Capstone, value: unknown) => {
    setCapstoneForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSaveCapstone = async () => {
    setSavingCapstone(true);
    try {
      const payload: Partial<Capstone> = {
        course: id,
        title: capstoneForm.title,
        spec_mode: capstoneForm.spec_mode,
        team_mode: capstoneForm.team_mode,
        team_cap: capstoneForm.team_cap != null ? Number(capstoneForm.team_cap) : undefined,
        deadline: capstoneForm.deadline ? new Date(capstoneForm.deadline).toISOString() : null,
        status: capstoneForm.status,
        pass_policy: capstoneForm.pass_policy,
        brief_text: capstoneForm.brief_text,
        github_template_repo: capstoneForm.github_template_repo,
        run_command: capstoneForm.run_command,
      };
      if (capstone) {
        const updated = await updateCapstone(capstone.id, payload);
        setCapstone(updated);
        setRubricItems(updated.rubric_items ?? []);
        toast.success('Capstone updated');
      } else {
        const created = await createCapstone(payload);
        setCapstone(created);
        setRubricItems(created.rubric_items ?? []);
        toast.success('Capstone created');
      }
    } catch {
      toast.error('Failed to save capstone');
    } finally {
      setSavingCapstone(false);
    }
  };

  const startEditRubric = (item: CapstoneRubricItem) => {
    setEditingRubricId(item.id);
    setRubricEditForm({ ...item });
  };

  const cancelEditRubric = () => {
    setEditingRubricId(null);
    setRubricEditForm({});
  };

  const handleSaveRubric = async (itemId: number) => {
    if (!capstone) return;
    try {
      const payload: Partial<CapstoneRubricItem> = {
        text: rubricEditForm.text,
        category: rubricEditForm.category,
        clo: rubricEditForm.clo,
        concept: rubricEditForm.concept,
        weight: rubricEditForm.weight != null ? Number(rubricEditForm.weight) : undefined,
        min_team_size: rubricEditForm.min_team_size != null ? Number(rubricEditForm.min_team_size) : undefined,
        order: rubricEditForm.order != null ? Number(rubricEditForm.order) : undefined,
      };
      const updated = await updateRubricItem(capstone.id, itemId, payload);
      setRubricItems((prev) => prev.map((i) => (i.id === itemId ? updated : i)));
      setEditingRubricId(null);
      toast.success('Rubric item updated');
    } catch {
      toast.error('Failed to update rubric item');
    }
  };

  const handleAddRubricItem = async () => {
    if (!capstone) return;
    try {
      const created = await createRubricItem(capstone.id, {
        text: 'New criterion',
        category: 'core',
        clo: null,
        concept: null,
        weight: 1,
        min_team_size: 1,
        order: rubricItems.length,
      });
      setRubricItems((prev) => [...prev, created]);
      startEditRubric(created);
    } catch {
      toast.error('Failed to add rubric item');
    }
  };

  const handleDeleteRubric = async (itemId: number) => {
    if (!capstone) return;
    try {
      await deleteRubricItem(capstone.id, itemId);
      setRubricItems((prev) => prev.filter((i) => i.id !== itemId));
      toast.success('Rubric item deleted');
    } catch {
      toast.error('Failed to delete rubric item');
    }
  };

  const applyRubricDrafts = async (drafts: RubricDraft[]) => {
    if (!capstone) return;
    let saved = 0;
    for (const draft of drafts) {
      try {
        await createRubricItem(capstone.id, {
          text: draft.text,
          category: draft.category as 'core' | 'stretch',
          clo: null,
          concept: null,
          weight: draft.weight,
          min_team_size: draft.min_team_size,
          order: draft.order,
        });
        saved++;
      } catch {
        toast.error('Failed to save rubric draft');
      }
    }
    if (saved > 0) {
      toast.success(`${saved} rubric items added`);
      loadCapstone();
    }
  };

  const handleDraftRubric = async () => {
    if (!capstone) return;
    setDraftingRubric(true);
    try {
      const result = await draftRubric(capstone.id);
      await applyRubricDrafts(result.rubric_items);
    } catch {
      toast.error('Failed to draft rubric');
    } finally {
      setDraftingRubric(false);
    }
  };

  const handleExtractSpec = async () => {
    if (!capstone || !extractSpecText.trim()) return;
    setExtractingSpec(true);
    try {
      const result = await extractSpec(capstone.id, extractSpecText.trim());
      await applyRubricDrafts(result.rubric_items);
      setExtractSpecText('');
    } catch {
      toast.error('Failed to extract spec');
    } finally {
      setExtractingSpec(false);
    }
  };

  const handleReviewProposal = async (proposalId: number, status: 'approved' | 'rejected') => {
    try {
      await approveProposal(proposalId, status, proposalFeedback[proposalId] ?? '');
      toast.success(`Proposal ${status}`);
      if (capstone) loadCapstoneRelated(capstone.id);
    } catch {
      toast.error('Failed to review proposal');
    }
  };

  // ---- Pathway admin helpers ----

  const handleLoadPathwayVersions = async () => {
    setLoadingPathway(true);
    try {
      const data = await getPathwayVersions(
        id,
        pathwayStudentId ? Number(pathwayStudentId) : undefined,
      );
      setPathwayVersions(data);
    } catch {
      toast.error('Failed to load pathway versions');
    } finally {
      setLoadingPathway(false);
    }
  };

  const handleRegeneratePathway = async () => {
    if (!pathwayStudentId) {
      toast.error('Enter a student ID to regenerate');
      return;
    }
    if (!confirm(`Regenerate pathway for student ${pathwayStudentId}? This may take a while.`)) return;
    setRegeneratingPathway(true);
    try {
      await regeneratePathway(id, Number(pathwayStudentId));
      toast.success('Pathway regeneration triggered');
      handleLoadPathwayVersions();
    } catch {
      toast.error('Failed to regenerate pathway');
    } finally {
      setRegeneratingPathway(false);
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

      {/* ── Course Details ── */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <BookOpen size={20} style={{ color: 'var(--admin-accent)' }} />
          <h2 className="admin-heading-xs">Course Details</h2>
        </div>
        <div className="admin-card p-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="admin-input-label">Title</label>
              <input
                className="admin-input w-full"
                value={courseForm.title ?? ''}
                onChange={(e) => updateCourseForm('title', e.target.value)}
                placeholder="Course title"
              />
            </div>
            <div>
              <label className="admin-input-label">Status</label>
              <select
                className="admin-input admin-select w-full"
                value={courseForm.status ?? 'Draft'}
                onChange={(e) => updateCourseForm('status', e.target.value)}
              >
                {['Draft', 'Published', 'Archived'].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="admin-input-label">Difficulty</label>
              <select
                className="admin-input admin-select w-full"
                value={courseForm.difficulty ?? 'Beginner'}
                onChange={(e) => updateCourseForm('difficulty', e.target.value)}
              >
                {['Beginner', 'Intermediate', 'Advanced'].map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="admin-input-label">Price</label>
              <input
                className="admin-input w-full"
                value={courseForm.price ?? ''}
                onChange={(e) => updateCourseForm('price', e.target.value)}
                placeholder="0.00"
              />
            </div>
            <div className="md:col-span-2">
              <div className="flex items-center justify-between">
                <label className="admin-input-label">Description</label>
                <button
                  onClick={handleDraftDescription}
                  disabled={draftingDescription}
                  className="admin-btn admin-btn-ghost admin-btn-sm flex items-center gap-1 mb-1"
                >
                  {draftingDescription ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                  Draft with AI
                </button>
              </div>
              <textarea
                className="admin-input w-full resize-none"
                rows={4}
                value={courseForm.description ?? ''}
                onChange={(e) => updateCourseForm('description', e.target.value)}
                placeholder="Course description..."
              />
            </div>
            <div>
              <label className="admin-input-label">Tags (comma separated)</label>
              <input
                className="admin-input w-full"
                value={Array.isArray(courseForm.tags) ? courseForm.tags.join(', ') : ''}
                onChange={(e) => updateCourseForm('tags', e.target.value.split(',').map((t) => t.trim()).filter(Boolean))}
                placeholder="python, data-science"
              />
            </div>
            <div className="flex items-center gap-2 md:col-span-2">
              <input
                id="is-published"
                type="checkbox"
                checked={courseForm.is_published ?? false}
                onChange={(e) => updateCourseForm('is_published', e.target.checked)}
                className="w-4 h-4"
              />
              <label htmlFor="is-published" className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>
                Published on course catalog
              </label>
            </div>
          </div>
          <div className="flex justify-end">
            <button
              onClick={handleSaveCourseDetails}
              disabled={savingCourse}
              className="admin-btn admin-btn-primary admin-btn-sm flex items-center gap-2"
            >
              {savingCourse ? (
                <Loader2 size={14} className="animate-spin" />
              ) : savedCourse ? (
                <Check size={14} />
              ) : null}
              {savedCourse ? 'Saved' : 'Save Details'}
            </button>
          </div>
        </div>
      </section>

      {/* ── Course Corpus ── */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <FileText size={20} style={{ color: 'var(--admin-accent)' }} />
          <h2 className="admin-heading-xs">Course Corpus</h2>
        </div>
        <div className="admin-card p-5 space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[200px]">
              <label className="admin-input-label">Attach an available book</label>
              <select
                className="admin-input admin-select w-full"
                value={selectedBookStem}
                onChange={(e) => setSelectedBookStem(e.target.value)}
              >
                <option value="">Select a book...</option>
                {availableBooks.map((b) => (
                  <option key={b.book_stem} value={b.book_stem}>{b.title}</option>
                ))}
              </select>
            </div>
            <button
              onClick={handleAttachAvailableBook}
              disabled={!selectedBookStem}
              className="admin-btn admin-btn-primary admin-btn-sm"
            >
              Attach
            </button>
            <div>
              <label className="admin-input-label">Or upload a PDF</label>
              <label className="admin-btn admin-btn-ghost admin-btn-sm flex items-center gap-2 cursor-pointer">
                <Upload size={14} />
                {uploading ? 'Uploading...' : 'Upload Book'}
                <input
                  type="file"
                  accept="application/pdf"
                  className="hidden"
                  onChange={handleUploadBook}
                  disabled={uploading}
                />
              </label>
            </div>
          </div>

          {corpusLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={24} className="animate-spin" style={{ color: 'var(--admin-ink-secondary)' }} />
            </div>
          ) : !corpus || corpus.sources.length === 0 ? (
            <p className="text-sm text-center py-6" style={{ color: 'var(--admin-ink-secondary)' }}>
              No sources attached yet. Attach or upload a book to build the course corpus.
            </p>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Chunks</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {corpus.sources.map((source) => (
                  <tr key={source.id}>
                    <td>
                      <p className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>{source.title}</p>
                      <p className="text-xs" style={{ color: 'var(--admin-ink-tertiary)' }}>{source.book_stem}</p>
                    </td>
                    <td className="text-sm capitalize" style={{ color: 'var(--admin-ink-secondary)' }}>{source.source_type}</td>
                    <td>
                      <span
                        className="admin-badge text-xs px-2 py-1 rounded-lg capitalize"
                        style={{
                          background: source.index_status === 'indexed'
                            ? 'var(--admin-success)22'
                            : source.index_status === 'failed'
                            ? 'var(--admin-error)22'
                            : 'var(--admin-warning)22',
                          color: source.index_status === 'indexed'
                            ? 'var(--admin-success)'
                            : source.index_status === 'failed'
                            ? 'var(--admin-error)'
                            : 'var(--admin-warning)',
                        }}
                      >
                        {source.index_status}
                      </span>
                    </td>
                    <td className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>{source.chunk_count}</td>
                    <td>
                      <button
                        onClick={() => handleRemoveSource(source.id, source.book_stem)}
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
      </section>

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
              onClick={handleOpenAddClo}
              className="admin-btn admin-btn-primary admin-btn-sm flex items-center gap-2"
            >
              <Plus size={14} />
              + ADD CLO
            </button>
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
            ) : clos.length === 0 && !addingClo ? (
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
                    <th>Concepts</th>
                    <th style={{ width: '4rem' }}>Order</th>
                    <th style={{ width: '5rem' }} />
                  </tr>
                </thead>
                <tbody>
                  {clos.map((clo) => {
                    const isEditing = editingCLOId === clo.id;
                    return (
                      <tr key={clo.id}>
                        {isEditing ? (
                          <>
                            <td>
                              <input
                                className="admin-input w-full"
                                style={{ padding: '6px 8px' }}
                                value={cloEditForm.code ?? ''}
                                onChange={(e) => setCloEditForm((prev) => ({ ...prev, code: e.target.value }))}
                              />
                            </td>
                            <td>
                              <input
                                className="admin-input w-full"
                                style={{ padding: '6px 8px' }}
                                value={cloEditForm.text ?? ''}
                                onChange={(e) => setCloEditForm((prev) => ({ ...prev, text: e.target.value }))}
                              />
                            </td>
                            <td>
                              <select
                                className="admin-input admin-select w-full"
                                style={{ padding: '6px 8px' }}
                                value={cloEditForm.bloom_level ?? 'understand'}
                                onChange={(e) => setCloEditForm((prev) => ({ ...prev, bloom_level: e.target.value }))}
                              >
                                {['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'].map((b) => (
                                  <option key={b} value={b}>{b}</option>
                                ))}
                              </select>
                            </td>
                            <td>
                              <select
                                multiple
                                className="admin-input w-full"
                                style={{ padding: '6px 8px', minHeight: 80 }}
                                value={cloEditForm.concepts?.map(String) ?? []}
                                onChange={(e) => {
                                  const selected = Array.from(e.target.selectedOptions).map((o) => Number(o.value));
                                  setCloEditForm((prev) => ({ ...prev, concepts: selected }));
                                }}
                              >
                                {concepts.map((c) => (
                                  <option key={c.id} value={c.id}>{c.label}</option>
                                ))}
                              </select>
                            </td>
                            <td>
                              <input
                                className="admin-input w-full"
                                style={{ padding: '6px 8px' }}
                                type="number"
                                value={cloEditForm.order ?? 0}
                                onChange={(e) => setCloEditForm((prev) => ({ ...prev, order: Number(e.target.value) }))}
                              />
                            </td>
                            <td>
                              <div className="flex items-center gap-1">
                                <button onClick={() => handleSaveCLO(clo.id)} className="admin-btn admin-btn-icon" style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}><Check size={13} /></button>
                                <button onClick={cancelEditCLO} className="admin-btn admin-btn-ghost admin-btn-icon"><X size={13} /></button>
                              </div>
                            </td>
                          </>
                        ) : (
                          <>
                            <td className="font-mono text-xs" style={{ color: 'var(--admin-accent)' }}>{clo.code}</td>
                            <td style={{ color: 'var(--admin-ink)' }}>{clo.text}</td>
                            <td>
                              <span className="admin-badge" style={{ background: 'var(--admin-paper-muted)', color: 'var(--admin-ink-secondary)' }}>
                                {clo.bloom_level}
                              </span>
                            </td>
                            <td>
                              <div className="flex flex-wrap gap-1">
                                {clo.concepts.map((conceptId) => {
                                  const concept = concepts.find((c) => c.id === conceptId);
                                  return (
                                    <span key={conceptId} className="admin-badge text-xs px-2 py-0.5" style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}>
                                      {concept?.label ?? conceptId}
                                    </span>
                                  );
                                })}
                                {clo.concepts.length === 0 && <span className="text-xs" style={{ color: 'var(--admin-ink-tertiary)' }}>—</span>}
                              </div>
                            </td>
                            <td className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>{clo.order}</td>
                            <td>
                              <div className="flex items-center gap-1">
                                <button onClick={() => startEditCLO(clo)} className="admin-btn admin-btn-ghost admin-btn-icon"><Edit size={13} /></button>
                                <button onClick={() => handleDeleteCLO(clo.id)} className="admin-btn admin-btn-ghost-danger admin-btn-icon"><Trash2 size={13} /></button>
                              </div>
                            </td>
                          </>
                        )}
                      </tr>
                    );
                  })}
                  {addingClo && (
                    <tr ref={newCloRowRef}>
                      <td>
                        <input
                          autoFocus
                          className="admin-input w-full"
                          style={{ padding: '6px 8px' }}
                          value={newCloForm.code}
                          onChange={(e) => setNewCloForm((prev) => ({ ...prev, code: e.target.value }))}
                          placeholder={`CLO${clos.length + 1}`}
                        />
                      </td>
                      <td>
                        <input
                          className="admin-input w-full"
                          style={{ padding: '6px 8px' }}
                          value={newCloForm.text}
                          onChange={(e) => setNewCloForm((prev) => ({ ...prev, text: e.target.value }))}
                          placeholder="Enter outcome statement…"
                        />
                      </td>
                      <td>
                        <select
                          className="admin-input admin-select w-full"
                          style={{ padding: '6px 8px' }}
                          value={newCloForm.bloom_level}
                          onChange={(e) => setNewCloForm((prev) => ({ ...prev, bloom_level: e.target.value }))}
                        >
                          {['remember', 'understand', 'apply', 'analyze', 'evaluate', 'create'].map((b) => (
                            <option key={b} value={b}>{b}</option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <input
                          className="admin-input w-full"
                          style={{ padding: '6px 8px' }}
                          value={newCloForm.concepts.join(', ')}
                          onChange={(e) => setNewCloForm((prev) => ({ ...prev, concepts: parseConceptInput(e.target.value) }))}
                          placeholder="—"
                        />
                      </td>
                      <td>
                        <input
                          type="number"
                          className="admin-input w-full"
                          style={{ padding: '6px 8px' }}
                          value={newCloForm.order}
                          onChange={(e) => setNewCloForm((prev) => ({ ...prev, order: Number(e.target.value) }))}
                        />
                      </td>
                      <td>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={handleSaveNewClo}
                            disabled={savingNewClo}
                            className="admin-btn admin-btn-icon"
                            style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}
                          >
                            {savingNewClo ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                          </button>
                          <button
                            onClick={handleCancelNewClo}
                            disabled={savingNewClo}
                            className="admin-btn admin-btn-ghost admin-btn-icon"
                          >
                            <X size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
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

      {/* ── CLO Attainment ── */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <GraduationCap size={20} style={{ color: 'var(--admin-accent)' }} />
            <h2 className="admin-heading-xs">CLO Attainment</h2>
          </div>
        </div>
        <div className="admin-card p-5 space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <input
              type="text"
              placeholder="Student user ID (optional)"
              value={attainmentStudentId}
              onChange={(e) => setAttainmentStudentId(e.target.value)}
              className="admin-input max-w-xs"
            />
            <button
              onClick={handleLoadAttainment}
              disabled={loadingAttainment}
              className="admin-btn admin-btn-ghost admin-btn-sm flex items-center gap-2"
            >
              {loadingAttainment ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              Load Attainment
            </button>
          </div>
          {cloAttainment.length === 0 ? (
            <p className="text-sm text-center py-4" style={{ color: 'var(--admin-ink-secondary)' }}>
              No attainment data loaded.
            </p>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th>CLO</th>
                  <th>Attainment</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {cloAttainment.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <p className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>{a.code}</p>
                      <p className="text-xs" style={{ color: 'var(--admin-ink-tertiary)' }}>{a.text}</p>
                    </td>
                    <td>
                      <span
                        className="admin-badge text-xs px-2 py-1 rounded-lg"
                        style={{
                          background: (a.attainment ?? 0) >= 0.7 ? 'var(--admin-success)22' : (a.attainment ?? 0) >= 0.4 ? 'var(--admin-warning)22' : 'var(--admin-error)22',
                          color: (a.attainment ?? 0) >= 0.7 ? 'var(--admin-success)' : (a.attainment ?? 0) >= 0.4 ? 'var(--admin-warning)' : 'var(--admin-error)',
                        }}
                      >
                        {a.attainment != null ? `${(a.attainment * 100).toFixed(0)}%` : 'N/A'}
                      </span>
                    </td>
                    <td className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>{a.evidence_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {/* ── Capstone Project ── */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <Hammer size={20} style={{ color: 'var(--admin-accent)' }} />
          <h2 className="admin-heading-xs">Capstone Project</h2>
        </div>

        {capstoneLoading ? (
          <div className="flex items-center justify-center py-8 admin-card">
            <Loader2 size={24} className="animate-spin" style={{ color: 'var(--admin-ink-secondary)' }} />
          </div>
        ) : (
          <div className="admin-card p-5 space-y-6">
            {/* Definition */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="admin-input-label">Title</label>
                <input
                  className="admin-input w-full"
                  value={capstoneForm.title ?? ''}
                  onChange={(e) => updateCapstoneForm('title', e.target.value)}
                  placeholder="Capstone title"
                />
              </div>
              <div>
                <label className="admin-input-label">Status</label>
                <select
                  className="admin-input admin-select w-full"
                  value={capstoneForm.status ?? 'draft'}
                  onChange={(e) => updateCapstoneForm('status', e.target.value)}
                >
                  {['draft', 'active', 'completed', 'archived'].map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="admin-input-label">Spec Mode</label>
                <select
                  className="admin-input admin-select w-full"
                  value={capstoneForm.spec_mode ?? 'admin_defined'}
                  onChange={(e) => updateCapstoneForm('spec_mode', e.target.value)}
                >
                  <option value="admin_defined">Admin Defined</option>
                  <option value="student_proposed">Student Proposed</option>
                </select>
              </div>
              <div>
                <label className="admin-input-label">Team Mode</label>
                <select
                  className="admin-input admin-select w-full"
                  value={capstoneForm.team_mode ?? 'solo'}
                  onChange={(e) => updateCapstoneForm('team_mode', e.target.value)}
                >
                  <option value="solo">Solo</option>
                  <option value="team">Team</option>
                </select>
              </div>
              <div>
                <label className="admin-input-label">Team Cap</label>
                <input
                  type="number"
                  className="admin-input w-full"
                  value={capstoneForm.team_cap ?? ''}
                  onChange={(e) => updateCapstoneForm('team_cap', e.target.value)}
                />
              </div>
              <div>
                <label className="admin-input-label">Deadline</label>
                <input
                  type="datetime-local"
                  className="admin-input w-full"
                  value={capstoneForm.deadline ?? ''}
                  onChange={(e) => updateCapstoneForm('deadline', e.target.value)}
                />
              </div>
              <div className="md:col-span-2">
                <label className="admin-input-label">Brief / Spec</label>
                <textarea
                  className="admin-input w-full resize-none"
                  rows={4}
                  value={capstoneForm.brief_text ?? ''}
                  onChange={(e) => updateCapstoneForm('brief_text', e.target.value)}
                  placeholder="Describe the capstone project..."
                />
              </div>
              <div>
                <label className="admin-input-label">GitHub Template Repo</label>
                <input
                  className="admin-input w-full"
                  value={capstoneForm.github_template_repo ?? ''}
                  onChange={(e) => updateCapstoneForm('github_template_repo', e.target.value)}
                  placeholder="owner/repo"
                />
              </div>
              <div>
                <label className="admin-input-label">Run Command</label>
                <input
                  className="admin-input w-full"
                  value={capstoneForm.run_command ?? ''}
                  onChange={(e) => updateCapstoneForm('run_command', e.target.value)}
                  placeholder="python main.py"
                />
              </div>
            </div>
            <div className="flex justify-end">
              <button
                onClick={handleSaveCapstone}
                disabled={savingCapstone}
                className="admin-btn admin-btn-primary admin-btn-sm flex items-center gap-2"
              >
                {savingCapstone ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                {capstone ? 'Save Capstone' : 'Create Capstone'}
              </button>
            </div>

            {/* Rubric */}
            {capstone && (
              <>
                <div className="border-t border-[var(--admin-hairline-light)] pt-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="admin-heading-xs">Rubric</h3>
                    <div className="flex items-center gap-2 flex-wrap">
                      <button
                        onClick={handleDraftRubric}
                        disabled={draftingRubric}
                        className="admin-btn admin-btn-ghost admin-btn-sm flex items-center gap-1"
                      >
                        {draftingRubric ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                        Draft Rubric (AI)
                      </button>
                      <button
                        onClick={handleAddRubricItem}
                        className="admin-btn admin-btn-primary admin-btn-sm flex items-center gap-1"
                      >
                        <Plus size={12} /> Add Criterion
                      </button>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 mb-4">
                    <textarea
                      className="admin-input flex-1 resize-none"
                      rows={2}
                      value={extractSpecText}
                      onChange={(e) => setExtractSpecText(e.target.value)}
                      placeholder="Paste a project spec to extract rubric criteria..."
                    />
                    <button
                      onClick={handleExtractSpec}
                      disabled={extractingSpec || !extractSpecText.trim()}
                      className="admin-btn admin-btn-ghost admin-btn-sm flex items-center gap-1"
                    >
                      {extractingSpec ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                      Extract
                    </button>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="admin-table">
                      <thead>
                        <tr>
                          <th>Criterion</th>
                          <th>Category</th>
                          <th>CLO</th>
                          <th>Concept</th>
                          <th>Weight</th>
                          <th>Min Team</th>
                          <th>Order</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {rubricItems.map((item) => {
                          const isEditing = editingRubricId === item.id;
                          return (
                            <tr key={item.id}>
                              {isEditing ? (
                                <>
                                  <td><input className="admin-input w-full" style={{ padding: '6px 8px' }} value={rubricEditForm.text ?? ''} onChange={(e) => setRubricEditForm((prev) => ({ ...prev, text: e.target.value }))} /></td>
                                  <td>
                                    <select className="admin-input admin-select w-full" style={{ padding: '6px 8px' }} value={rubricEditForm.category ?? 'core'} onChange={(e) => setRubricEditForm((prev) => ({ ...prev, category: e.target.value as 'core' | 'stretch' }))}>
                                      <option value="core">core</option>
                                      <option value="stretch">stretch</option>
                                    </select>
                                  </td>
                                  <td>
                                    <select className="admin-input admin-select w-full" style={{ padding: '6px 8px' }} value={rubricEditForm.clo ?? ''} onChange={(e) => setRubricEditForm((prev) => ({ ...prev, clo: e.target.value ? Number(e.target.value) : null }))}>
                                      <option value="">—</option>
                                      {clos.map((c) => (<option key={c.id} value={c.id}>{c.code}</option>))}
                                    </select>
                                  </td>
                                  <td>
                                    <select className="admin-input admin-select w-full" style={{ padding: '6px 8px' }} value={rubricEditForm.concept ?? ''} onChange={(e) => setRubricEditForm((prev) => ({ ...prev, concept: e.target.value ? Number(e.target.value) : null }))}>
                                      <option value="">—</option>
                                      {concepts.map((c) => (<option key={c.id} value={c.id}>{c.label}</option>))}
                                    </select>
                                  </td>
                                  <td><input type="number" className="admin-input w-full" style={{ padding: '6px 8px' }} value={rubricEditForm.weight ?? ''} onChange={(e) => setRubricEditForm((prev) => ({ ...prev, weight: Number(e.target.value) }))} /></td>
                                  <td><input type="number" className="admin-input w-full" style={{ padding: '6px 8px' }} value={rubricEditForm.min_team_size ?? ''} onChange={(e) => setRubricEditForm((prev) => ({ ...prev, min_team_size: Number(e.target.value) }))} /></td>
                                  <td><input type="number" className="admin-input w-full" style={{ padding: '6px 8px' }} value={rubricEditForm.order ?? ''} onChange={(e) => setRubricEditForm((prev) => ({ ...prev, order: Number(e.target.value) }))} /></td>
                                  <td>
                                    <div className="flex items-center gap-1">
                                      <button onClick={() => handleSaveRubric(item.id)} className="admin-btn admin-btn-icon" style={{ background: 'var(--admin-accent-subtle)', color: 'var(--admin-accent)' }}><Check size={13} /></button>
                                      <button onClick={cancelEditRubric} className="admin-btn admin-btn-ghost admin-btn-icon"><X size={13} /></button>
                                    </div>
                                  </td>
                                </>
                              ) : (
                                <>
                                  <td style={{ color: 'var(--admin-ink)' }}>{item.text}</td>
                                  <td><span className="admin-badge text-xs px-2 py-0.5 capitalize" style={{ background: item.category === 'core' ? 'var(--admin-accent-subtle)' : 'var(--admin-warning-subtle)', color: item.category === 'core' ? 'var(--admin-accent)' : 'var(--admin-warning)' }}>{item.category}</span></td>
                                  <td style={{ color: 'var(--admin-ink-secondary)' }}>{clos.find((c) => c.id === item.clo)?.code ?? '—'}</td>
                                  <td style={{ color: 'var(--admin-ink-secondary)' }}>{concepts.find((c) => c.id === item.concept)?.label ?? '—'}</td>
                                  <td style={{ color: 'var(--admin-ink-secondary)' }}>{item.weight}</td>
                                  <td style={{ color: 'var(--admin-ink-secondary)' }}>{item.min_team_size}</td>
                                  <td style={{ color: 'var(--admin-ink-secondary)' }}>{item.order}</td>
                                  <td>
                                    <div className="flex items-center gap-1">
                                      <button onClick={() => startEditRubric(item)} className="admin-btn admin-btn-ghost admin-btn-icon"><Edit size={13} /></button>
                                      <button onClick={() => handleDeleteRubric(item.id)} className="admin-btn admin-btn-ghost-danger admin-btn-icon"><Trash2 size={13} /></button>
                                    </div>
                                  </td>
                                </>
                              )}
                            </tr>
                          );
                        })}
                        {rubricItems.length === 0 && (
                          <tr>
                            <td colSpan={8} className="text-center text-sm py-6" style={{ color: 'var(--admin-ink-secondary)' }}>
                              No rubric items. Add one manually or generate with AI.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Proposals */}
                {capstoneForm.spec_mode === 'student_proposed' && (
                  <div className="border-t border-[var(--admin-hairline-light)] pt-5">
                    <h3 className="admin-heading-xs mb-4">Proposals</h3>
                    {proposals.length === 0 ? (
                      <p className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>No proposals yet.</p>
                    ) : (
                      <div className="space-y-3">
                        {proposals.map((p) => (
                          <div key={p.id} className="admin-card p-4">
                            <div className="flex items-start justify-between">
                              <div>
                                <p className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>{p.title}</p>
                                <p className="text-xs" style={{ color: 'var(--admin-ink-tertiary)' }}>by {p.student_username} · {p.approval_status}</p>
                                <p className="text-sm mt-2" style={{ color: 'var(--admin-ink-secondary)' }}>{p.description}</p>
                              </div>
                              {p.approval_status === 'pending' && (
                                <div className="flex items-center gap-2">
                                  <input
                                    type="text"
                                    placeholder="Feedback"
                                    value={proposalFeedback[p.id] ?? ''}
                                    onChange={(e) => setProposalFeedback((prev) => ({ ...prev, [p.id]: e.target.value }))}
                                    className="admin-input text-sm"
                                  />
                                  <button onClick={() => handleReviewProposal(p.id, 'approved')} className="admin-btn admin-btn-primary admin-btn-sm">Approve</button>
                                  <button onClick={() => handleReviewProposal(p.id, 'rejected')} className="admin-btn admin-btn-ghost-danger admin-btn-sm">Reject</button>
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Submissions */}
                <div className="border-t border-[var(--admin-hairline-light)] pt-5">
                  <h3 className="admin-heading-xs mb-4">Submissions</h3>
                  {submissions.length === 0 ? (
                    <p className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>No submissions yet.</p>
                  ) : (
                    <table className="admin-table">
                      <thead>
                        <tr>
                          <th>Repo</th>
                          <th>Status</th>
                          <th>Verdict</th>
                          <th>Score</th>
                        </tr>
                      </thead>
                      <tbody>
                        {submissions.map((s) => (
                          <tr key={s.id}>
                            <td><a href={s.repo_url} target="_blank" rel="noreferrer" className="text-sm hover:underline" style={{ color: 'var(--admin-accent)' }}>{s.repo_url}</a></td>
                            <td style={{ color: 'var(--admin-ink-secondary)' }}>{s.status}</td>
                            <td style={{ color: 'var(--admin-ink-secondary)' }}>{s.verdict}</td>
                            <td style={{ color: 'var(--admin-ink-secondary)' }}>{s.score != null ? s.score.toFixed(1) : '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </section>

      {/* ── Pathway Admin ── */}
      <section>
        <div className="flex items-center gap-2 mb-4">
          <RefreshCw size={20} style={{ color: 'var(--admin-accent)' }} />
          <h2 className="admin-heading-xs">Pathway Admin</h2>
        </div>
        <div className="admin-card p-5 space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[200px] max-w-xs">
              <label className="admin-input-label">Student ID</label>
              <input
                type="text"
                className="admin-input w-full"
                value={pathwayStudentId}
                onChange={(e) => setPathwayStudentId(e.target.value)}
                placeholder="Student user ID"
              />
            </div>
            <button
              onClick={handleLoadPathwayVersions}
              disabled={loadingPathway}
              className="admin-btn admin-btn-ghost admin-btn-sm flex items-center gap-2"
            >
              {loadingPathway ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              Load Versions
            </button>
            <button
              onClick={handleRegeneratePathway}
              disabled={regeneratingPathway || !pathwayStudentId}
              className="admin-btn admin-btn-primary admin-btn-sm flex items-center gap-2"
            >
              {regeneratingPathway ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              Regenerate Pathway
            </button>
          </div>
          {pathwayVersions.length === 0 ? (
            <p className="text-sm text-center py-4" style={{ color: 'var(--admin-ink-secondary)' }}>
              No pathway versions loaded.
            </p>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Version</th>
                  <th>Generated</th>
                  <th>Sessions</th>
                  <th>Chunks</th>
                </tr>
              </thead>
              <tbody>
                {pathwayVersions.map((v, idx) => (
                  <tr key={idx}>
                    <td className="font-semibold text-sm" style={{ color: 'var(--admin-ink)' }}>v{v.plan_version}</td>
                    <td className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>{new Date(v.generated_at).toLocaleString()}</td>
                    <td className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>{v.total_sessions}</td>
                    <td className="text-sm" style={{ color: 'var(--admin-ink-secondary)' }}>{v.total_chunks}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
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
