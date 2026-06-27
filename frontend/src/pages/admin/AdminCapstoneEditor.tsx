import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router';
import { toast } from 'sonner';
import {
    Trash2, Edit, Check, X, Loader2, ArrowLeft, Sparkles, FileText,
    ChevronDown, ChevronRight, Users,
} from 'lucide-react';
import {
    getCapstoneForCourse, createCapstone, updateCapstone,
    createRubricItem, updateRubricItem, deleteRubricItem,
    draftRubric, extractSpec, suggestLanguage, draftCi,
    listProposals, approveProposal,
    listSubmissions, processMatchmaking,
    type Capstone, type CapstoneProposal,
    type CapstoneSubmission,
} from '../../services/capstone';
import { AIDraftReviewTable, type Column } from '../../components/AIDraftReviewTable';

// ---- Rubric item draft shape for AIDraftReviewTable ----
type RubricRow = {
    text: string;
    // Atomic binary sub-checks drafted by the AI; carried through to save so the
    // hierarchical rubric is persisted (criterion passes iff all checks pass).
    checks?: { text: string }[];
    category: string;
    weight: number;
    min_team_size: number;
    order: number;
    rationale: string;
};

const RUBRIC_EMPTY_ROW: RubricRow = {
    text: '',
    category: 'core',
    weight: 1,
    min_team_size: 1,
    order: 0,
    rationale: '',
};

const RUBRIC_COLUMNS: Column<RubricRow>[] = [
    { key: 'text', header: 'Criterion (yes/no question)', editable: true },
    { key: 'category', header: 'Category', editable: true, width: 'w-24' },
    { key: 'weight', header: 'Weight', editable: true, width: 'w-16' },
    { key: 'min_team_size', header: 'Min team', editable: true, width: 'w-20' },
    { key: 'rationale', header: 'Rationale', editable: true },
];

// ---- Score colour ----
function scoreColour(score: number | null): string {
    if (score === null) return 'text-muted-foreground';
    if (score >= 70) return 'text-green-600';
    if (score >= 40) return 'text-amber-600';
    return 'text-red-600';
}

export default function AdminCapstoneEditor() {
    const { courseId } = useParams<{ courseId: string }>();
    const navigate = useNavigate();
    const id = Number(courseId);

    const [capstone, setCapstone] = useState<Capstone | null>(null);
    const [loading, setLoading] = useState(true);

    // Capstone edit form
    const [editing, setEditing] = useState(false);
    const [form, setForm] = useState<Partial<Capstone>>({});

    // Rubric AI draft
    const [rubricDrafting, setRubricDrafting] = useState(false);
    const [rubricDrafts, setRubricDrafts] = useState<RubricRow[] | null>(null);

    // Spec extract
    const [specText, setSpecText] = useState('');
    const [specExtracting, setSpecExtracting] = useState(false);
    const [showSpecInput, setShowSpecInput] = useState(false);

    // Proposals
    const [proposals, setProposals] = useState<CapstoneProposal[]>([]);
    const [proposalsOpen, setProposalsOpen] = useState(false);
    const [approvingId, setApprovingId] = useState<number | null>(null);

    // Submissions
    const [submissions, setSubmissions] = useState<CapstoneSubmission[]>([]);
    const [submissionsOpen, setSubmissionsOpen] = useState(false);

    // Matchmaking
    const [processingQueue, setProcessingQueue] = useState(false);

    // Language + CI authoring
    const [suggesting, setSuggesting] = useState(false);
    const [generatingCi, setGeneratingCi] = useState(false);

    useEffect(() => {
        setLoading(true);
        getCapstoneForCourse(id)
            .then(c => {
                setCapstone(c);
                setForm(c);
            })
            .catch(() => {
                // No capstone yet — admin can create one
                setCapstone(null);
                setForm({ course: id, status: 'draft', spec_mode: 'admin_defined', team_mode: 'solo', team_cap: 4 });
            })
            .finally(() => setLoading(false));
    }, [id]);

    async function handleCreateOrSave() {
        try {
            if (capstone) {
                const updated = await updateCapstone(capstone.id, form);
                setCapstone(updated);
                setForm(updated);
                toast.success('Capstone updated.');
            } else {
                const created = await createCapstone({ ...form, course: id });
                setCapstone(created);
                setForm(created);
                toast.success('Capstone created.');
            }
            setEditing(false);
        } catch {
            toast.error('Save failed.');
        }
    }

    async function handleDraftRubric() {
        if (!capstone) return;
        setRubricDrafting(true);
        try {
            const result = await draftRubric(capstone.id);
            setRubricDrafts(result.rubric_items.map((item, i) => ({ ...item, order: i })));
        } catch {
            toast.error('AI draft failed.');
        } finally {
            setRubricDrafting(false);
        }
    }

    async function handleExtractSpec() {
        if (!capstone || !specText.trim()) return;
        setSpecExtracting(true);
        try {
            const result = await extractSpec(capstone.id, specText);
            setRubricDrafts(result.rubric_items.map((item, i) => ({ ...item, order: i })));
            setShowSpecInput(false);
        } catch {
            toast.error('Spec extraction failed.');
        } finally {
            setSpecExtracting(false);
        }
    }

    async function handleSuggestLanguage() {
        if (!capstone) return;
        setSuggesting(true);
        try {
            const r = await suggestLanguage(capstone.id);
            setForm(f => ({ ...f, language: r.language }));
            toast.success(
                `Suggested: ${r.language} (${Math.round((r.confidence ?? 0) * 100)}% confidence)`,
            );
        } catch {
            toast.error('Could not suggest a language.');
        } finally {
            setSuggesting(false);
        }
    }

    async function handleGenerateCi() {
        if (!capstone) return;
        setGeneratingCi(true);
        try {
            const r = await draftCi(capstone.id, {
                language: form.language,
                run_command: form.run_command,
            });
            setForm(f => ({ ...f, ci_workflow: r.ci_workflow }));
            toast.success('CI workflow generated — review it, then Save.');
        } catch {
            toast.error('Could not generate the CI workflow.');
        } finally {
            setGeneratingCi(false);
        }
    }

    async function handleSaveRubricDrafts(rows: RubricRow[]) {
        if (!capstone) return;
        for (const row of rows) {
            await createRubricItem(capstone.id, {
                text: row.text,
                checks: row.checks ?? [],
                category: row.category as 'core' | 'stretch',
                weight: Number(row.weight),
                min_team_size: Number(row.min_team_size),
                order: Number(row.order),
                clo: null,
                concept: null,
            });
        }
        const updated = await getCapstoneForCourse(id);
        setCapstone(updated);
        setRubricDrafts(null);
        toast.success(`${rows.length} rubric item(s) saved.`);
    }

    async function handleDeleteItem(itemId: number) {
        if (!capstone) return;
        await deleteRubricItem(capstone.id, itemId);
        const updated = await getCapstoneForCourse(id);
        setCapstone(updated);
    }

    async function loadProposals() {
        if (!capstone) return;
        const p = await listProposals(capstone.id);
        setProposals(p);
    }

    async function loadSubmissions() {
        const s = await listSubmissions(capstone?.id);
        setSubmissions(s);
    }

    async function handleProcessQueue() {
        if (!capstone) return;
        setProcessingQueue(true);
        try {
            const { teams_formed } = await processMatchmaking(capstone.id);
            toast.success(`${teams_formed} team(s) formed.`);
        } catch {
            toast.error('Could not process the queue.');
        } finally {
            setProcessingQueue(false);
        }
    }

    async function handleApprove(proposalId: number, action: 'approved' | 'rejected') {
        setApprovingId(proposalId);
        try {
            await approveProposal(proposalId, action);
            await loadProposals();
            toast.success(`Proposal ${action}.`);
        } catch {
            toast.error('Action failed.');
        } finally {
            setApprovingId(null);
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 animate-spin text-primary" />
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
            {/* Header */}
            <div className="flex items-center gap-3">
                <button onClick={() => navigate(-1)} className="p-2 rounded-lg hover:bg-muted transition">
                    <ArrowLeft className="w-5 h-5" />
                </button>
                <h1 className="text-2xl font-bold">Capstone Editor</h1>
                <span className="text-muted-foreground text-sm">Course #{courseId}</span>
            </div>

            {/* Capstone definition card */}
            <div className="bg-card rounded-2xl border-2 border-border p-6 space-y-4">
                <div className="flex items-center justify-between">
                    <h2 className="text-lg font-semibold">Capstone Definition</h2>
                    {!editing && (
                        <button
                            onClick={() => setEditing(true)}
                            className="flex items-center gap-1 text-sm text-primary hover:underline"
                        >
                            <Edit className="w-4 h-4" />
                            {capstone ? 'Edit' : 'Create'}
                        </button>
                    )}
                </div>

                {editing ? (
                    <div className="space-y-3">
                        <input
                            className="w-full border rounded-lg px-3 py-2 text-sm"
                            placeholder="Title"
                            value={form.title ?? ''}
                            onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                        />
                        <textarea
                            className="w-full border rounded-lg px-3 py-2 text-sm min-h-[100px]"
                            placeholder="Brief / description shown to students"
                            value={form.brief_text ?? ''}
                            onChange={e => setForm(f => ({ ...f, brief_text: e.target.value }))}
                        />
                        <div className="flex gap-3 flex-wrap">
                            <div>
                                <label className="text-xs text-muted-foreground">Spec mode</label>
                                <select
                                    className="border rounded-lg px-2 py-1 text-sm block mt-1"
                                    value={form.spec_mode ?? 'admin_defined'}
                                    onChange={e => setForm(f => ({ ...f, spec_mode: e.target.value as Capstone['spec_mode'] }))}
                                >
                                    <option value="admin_defined">Admin-defined</option>
                                    <option value="student_proposed">Student-proposed</option>
                                </select>
                            </div>
                            <div>
                                <label className="text-xs text-muted-foreground">Team mode</label>
                                <select
                                    className="border rounded-lg px-2 py-1 text-sm block mt-1"
                                    value={form.team_mode ?? 'solo'}
                                    onChange={e => setForm(f => ({ ...f, team_mode: e.target.value as Capstone['team_mode'] }))}
                                >
                                    <option value="solo">Solo</option>
                                    <option value="team">Team</option>
                                </select>
                            </div>
                            <div>
                                <label className="text-xs text-muted-foreground">Status</label>
                                <select
                                    className="border rounded-lg px-2 py-1 text-sm block mt-1"
                                    value={form.status ?? 'draft'}
                                    onChange={e => setForm(f => ({ ...f, status: e.target.value as Capstone['status'] }))}
                                >
                                    <option value="draft">Draft</option>
                                    <option value="active">Active</option>
                                    <option value="completed">Completed</option>
                                    <option value="archived">Archived</option>
                                </select>
                            </div>
                        </div>
                        <input
                            className="w-full border rounded-lg px-3 py-2 text-sm"
                            placeholder="GitHub template repo (e.g. my-org/capstone-template)"
                            value={form.github_template_repo ?? ''}
                            onChange={e => setForm(f => ({ ...f, github_template_repo: e.target.value }))}
                        />
                        <input
                            className="w-full border rounded-lg px-3 py-2 text-sm"
                            placeholder="CI run command (e.g. pytest, npm test, go test ./...)"
                            value={form.run_command ?? ''}
                            onChange={e => setForm(f => ({ ...f, run_command: e.target.value }))}
                        />

                        {/* Programming language (AI-suggested, admin-editable) */}
                        <div className="space-y-1">
                            <label className="text-xs text-muted-foreground">Programming language</label>
                            <div className="flex gap-2">
                                <input
                                    className="flex-1 border rounded-lg px-3 py-2 text-sm"
                                    placeholder="e.g. python, javascript, java, go, cpp"
                                    value={form.language ?? ''}
                                    onChange={e => setForm(f => ({ ...f, language: e.target.value }))}
                                />
                                <button
                                    type="button"
                                    onClick={handleSuggestLanguage}
                                    disabled={suggesting || !capstone}
                                    title={!capstone ? 'Save the capstone first' : 'Infer from the course'}
                                    className="flex items-center gap-1.5 border px-3 py-2 rounded-lg text-sm hover:bg-muted disabled:opacity-50 shrink-0"
                                >
                                    {suggesting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
                                    Suggest (AI)
                                </button>
                            </div>
                        </div>

                        {/* Standardized CI workflow (generated, admin-editable) */}
                        <div className="space-y-1">
                            <div className="flex items-center justify-between">
                                <label className="text-xs text-muted-foreground">
                                    CI workflow (.github/workflows/ci.yml)
                                </label>
                                <button
                                    type="button"
                                    onClick={handleGenerateCi}
                                    disabled={generatingCi || !capstone}
                                    title={!capstone ? 'Save the capstone first' : 'Generate from language + run command'}
                                    className="flex items-center gap-1.5 text-xs text-primary hover:underline disabled:opacity-50"
                                >
                                    {generatingCi ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
                                    Generate CI
                                </button>
                            </div>
                            <textarea
                                className="w-full border rounded-lg px-3 py-2 text-xs font-mono min-h-[160px]"
                                placeholder="Click 'Generate CI' to create a standard workflow for this language, or paste your own. If left blank (and no template repo is set), a language default is generated automatically at provisioning."
                                value={form.ci_workflow ?? ''}
                                onChange={e => setForm(f => ({ ...f, ci_workflow: e.target.value }))}
                            />
                            <p className="text-[11px] text-muted-foreground">
                                Seeded verbatim into every student's repo at provisioning so the required <code>ci</code> check is identical for all students.
                            </p>
                        </div>
                        <div className="flex gap-2">
                            <button
                                onClick={handleCreateOrSave}
                                className="flex items-center gap-1 bg-primary text-primary-foreground px-4 py-1.5 rounded-lg text-sm hover:opacity-90"
                            >
                                <Check className="w-4 h-4" />
                                Save
                            </button>
                            <button
                                onClick={() => { setEditing(false); setForm(capstone ?? {}); }}
                                className="flex items-center gap-1 border px-4 py-1.5 rounded-lg text-sm hover:bg-muted"
                            >
                                <X className="w-4 h-4" />
                                Cancel
                            </button>
                        </div>
                    </div>
                ) : capstone ? (
                    <div className="space-y-1 text-sm">
                        <p className="font-medium text-base">{capstone.title}</p>
                        <p className="text-muted-foreground">{capstone.brief_text || 'No brief set.'}</p>
                        <div className="flex gap-3 mt-2 flex-wrap text-xs text-muted-foreground">
                            <span>Spec: <strong>{capstone.spec_mode}</strong></span>
                            <span>Mode: <strong>{capstone.team_mode}</strong></span>
                            <span>Status: <strong>{capstone.status}</strong></span>
                            <span>Language: <strong>{capstone.language || 'python'}</strong></span>
                            <span>CI: <strong>{capstone.ci_workflow ? 'custom' : (capstone.github_template_repo ? 'from template' : 'auto-generated')}</strong></span>
                            {capstone.github_template_repo && (
                                <span>Template: <strong>{capstone.github_template_repo}</strong></span>
                            )}
                        </div>
                    </div>
                ) : (
                    <p className="text-sm text-muted-foreground">
                        No capstone defined for this course yet. Click <strong>Create</strong> to start.
                    </p>
                )}
            </div>

            {/* Rubric items */}
            {capstone && (
                <div className="bg-card rounded-2xl border-2 border-border p-6 space-y-4">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                        <h2 className="text-lg font-semibold">Rubric Criteria</h2>
                        <div className="flex gap-2 flex-wrap">
                            <button
                                onClick={handleDraftRubric}
                                disabled={rubricDrafting}
                                className="flex items-center gap-1.5 bg-primary text-primary-foreground px-3 py-1.5 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
                            >
                                {rubricDrafting
                                    ? <Loader2 className="w-4 h-4 animate-spin" />
                                    : <Sparkles className="w-4 h-4" />}
                                Draft Rubric (AI)
                            </button>
                            <button
                                onClick={() => setShowSpecInput(v => !v)}
                                className="flex items-center gap-1.5 border px-3 py-1.5 rounded-lg text-sm hover:bg-muted"
                            >
                                <FileText className="w-4 h-4" />
                                Extract from Spec
                            </button>
                        </div>
                    </div>

                    {/* Spec paste area */}
                    {showSpecInput && (
                        <div className="space-y-2">
                            <textarea
                                className="w-full border rounded-lg px-3 py-2 text-sm min-h-[120px]"
                                placeholder="Paste your specification document here..."
                                value={specText}
                                onChange={e => setSpecText(e.target.value)}
                            />
                            <button
                                onClick={handleExtractSpec}
                                disabled={specExtracting || !specText.trim()}
                                className="flex items-center gap-1.5 bg-primary text-primary-foreground px-3 py-1.5 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
                            >
                                {specExtracting
                                    ? <Loader2 className="w-4 h-4 animate-spin" />
                                    : <Sparkles className="w-4 h-4" />}
                                Extract Criteria
                            </button>
                        </div>
                    )}

                    {/* AI Draft review table */}
                    {rubricDrafts !== null && (
                        <div className="border-2 border-primary/30 rounded-xl p-4">
                            <p className="text-sm font-medium text-primary mb-3">
                                Review AI-drafted criteria before saving:
                            </p>
                            <AIDraftReviewTable<RubricRow>
                                columns={RUBRIC_COLUMNS}
                                initialRows={rubricDrafts}
                                emptyRow={RUBRIC_EMPTY_ROW}
                                onSave={handleSaveRubricDrafts}
                                onCancel={() => setRubricDrafts(null)}
                            />
                        </div>
                    )}

                    {/* Existing rubric items */}
                    {capstone.rubric_items.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No criteria yet. Use AI draft or extract from spec.</p>
                    ) : (
                        <div className="space-y-2">
                            {capstone.rubric_items.map(item => (
                                <div
                                    key={item.id}
                                    className="flex items-start justify-between gap-3 rounded-xl border p-3 hover:bg-muted/30 transition text-sm"
                                >
                                    <div className="flex-1">
                                        <p>{item.text}</p>
                                        <div className="flex gap-2 mt-1 text-xs text-muted-foreground">
                                            <span className={item.category === 'core' ? 'text-blue-600' : 'text-purple-600'}>
                                                {item.category}
                                            </span>
                                            <span>weight: {item.weight}</span>
                                            <span>min_team: {item.min_team_size}</span>
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => handleDeleteItem(item.id)}
                                        className="text-destructive hover:opacity-70 p-1"
                                    >
                                        <Trash2 className="w-4 h-4" />
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Matchmaking (team-mode) */}
            {capstone && capstone.team_mode === 'team' && (
                <div className="bg-card rounded-2xl border-2 border-border p-6 space-y-3">
                    <h2 className="flex items-center gap-2 text-lg font-semibold">
                        <Users className="w-5 h-5" /> Matchmaking
                    </h2>
                    <p className="text-sm text-muted-foreground">
                        Form the best available teams from the waiting queue now. Students with no
                        teammates are placed into a solo team (core-only rubric) so the queue never deadlocks.
                    </p>
                    <button
                        onClick={handleProcessQueue}
                        disabled={processingQueue}
                        className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
                    >
                        {processingQueue ? <Loader2 className="w-4 h-4 animate-spin" /> : <Users className="w-4 h-4" />}
                        Process Queue Now
                    </button>
                </div>
            )}

            {/* Proposals section */}
            {capstone && capstone.spec_mode === 'student_proposed' && (
                <div className="bg-card rounded-2xl border-2 border-border p-6 space-y-3">
                    <button
                        className="flex items-center gap-2 w-full text-left"
                        onClick={() => {
                            setProposalsOpen(v => !v);
                            if (!proposalsOpen) loadProposals();
                        }}
                    >
                        {proposalsOpen ? <ChevronDown className="w-5 h-5" /> : <ChevronRight className="w-5 h-5" />}
                        <span className="text-lg font-semibold">Student Proposals</span>
                        <span className="ml-auto text-sm text-muted-foreground">{proposals.length} loaded</span>
                    </button>
                    {proposalsOpen && (
                        <div className="space-y-2">
                            {proposals.length === 0 && (
                                <p className="text-sm text-muted-foreground">No proposals yet.</p>
                            )}
                            {proposals.map(p => (
                                <div key={p.id} className="border rounded-xl p-3 text-sm space-y-1">
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="font-medium">{p.title}</span>
                                        <span className={
                                            p.approval_status === 'approved' ? 'text-green-600 text-xs' :
                                            p.approval_status === 'rejected' ? 'text-red-600 text-xs' :
                                            'text-amber-600 text-xs'
                                        }>
                                            {p.approval_status}
                                        </span>
                                    </div>
                                    <p className="text-muted-foreground">{p.description}</p>
                                    {p.approval_status === 'pending' && (
                                        <div className="flex gap-2 pt-1">
                                            <button
                                                onClick={() => handleApprove(p.id, 'approved')}
                                                disabled={approvingId === p.id}
                                                className="flex items-center gap-1 bg-green-600 text-white px-3 py-1 rounded-lg text-xs hover:opacity-90 disabled:opacity-50"
                                            >
                                                <Check className="w-3 h-3" /> Approve
                                            </button>
                                            <button
                                                onClick={() => handleApprove(p.id, 'rejected')}
                                                disabled={approvingId === p.id}
                                                className="flex items-center gap-1 bg-destructive text-destructive-foreground px-3 py-1 rounded-lg text-xs hover:opacity-90 disabled:opacity-50"
                                            >
                                                <X className="w-3 h-3" /> Reject
                                            </button>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Submissions section */}
            {capstone && (
                <div className="bg-card rounded-2xl border-2 border-border p-6 space-y-3">
                    <button
                        className="flex items-center gap-2 w-full text-left"
                        onClick={() => {
                            setSubmissionsOpen(v => !v);
                            if (!submissionsOpen) loadSubmissions();
                        }}
                    >
                        {submissionsOpen ? <ChevronDown className="w-5 h-5" /> : <ChevronRight className="w-5 h-5" />}
                        <span className="text-lg font-semibold">Submissions</span>
                        <span className="ml-auto text-sm text-muted-foreground">{submissions.length} loaded</span>
                    </button>
                    {submissionsOpen && (
                        <div className="space-y-2">
                            {submissions.length === 0 && (
                                <p className="text-sm text-muted-foreground">No submissions yet.</p>
                            )}
                            {submissions.map(sub => (
                                <div key={sub.id} className="border rounded-xl p-3 text-sm space-y-1">
                                    <div className="flex items-center justify-between">
                                        <span className="font-medium">Enrollment #{sub.enrollment}</span>
                                        <span className={`font-semibold ${scoreColour(sub.score)}`}>
                                            {sub.score !== null ? `${sub.score.toFixed(1)}%` : sub.status}
                                        </span>
                                    </div>
                                    {sub.repo_url && (
                                        <a
                                            href={sub.repo_url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="text-primary text-xs underline"
                                        >
                                            {sub.repo_url}
                                        </a>
                                    )}
                                    {sub.feedback && (
                                        <p className="text-muted-foreground text-xs">{sub.feedback}</p>
                                    )}
                                    {Object.keys(sub.results).length > 0 && (
                                        <div className="mt-2 space-y-1">
                                            {Object.entries(sub.results).map(([itemId, r]) => (
                                                <div key={itemId} className="flex items-start gap-2 text-xs">
                                                    <span className={r.passed ? 'text-green-600' : 'text-red-500'}>
                                                        {r.passed ? '✓' : '✗'}
                                                    </span>
                                                    <span className="text-muted-foreground">{r.evidence}</span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
