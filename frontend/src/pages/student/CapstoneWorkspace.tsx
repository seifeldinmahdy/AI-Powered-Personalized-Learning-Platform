import { useEffect, useMemo, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import Editor from '@monaco-editor/react';
import { toast } from 'sonner';
import {
    Loader2, ArrowLeft, GitCommit, Play, Sparkles, FileCode, X,
    CheckCircle, XCircle, Clock, RefreshCw, Send, GraduationCap,
} from 'lucide-react';
import {
    getCapstoneForCourse, getRepoTree, getRepoFile, commitFiles, getCommitStatus,
    runFiles, getAssistQuota, askAssist, submitForGrading,
    type Capstone, type TreeNode, type CommitVerdict, type AssistQuota,
} from '../../services/capstone';

interface OpenFile {
    content: string;
    original: string;
    loaded: boolean;
}

const LANG_BY_EXT: Record<string, string> = {
    py: 'python', js: 'javascript', mjs: 'javascript', cjs: 'javascript',
    ts: 'typescript', tsx: 'typescript', jsx: 'javascript',
    json: 'json', md: 'markdown', html: 'html', css: 'css', scss: 'scss',
    yml: 'yaml', yaml: 'yaml', toml: 'ini', ini: 'ini', xml: 'xml',
    java: 'java', kt: 'kotlin', c: 'c', h: 'c', cpp: 'cpp', cc: 'cpp', hpp: 'cpp',
    cs: 'csharp', go: 'go', rs: 'rust', rb: 'ruby', php: 'php', swift: 'swift',
    sql: 'sql', sh: 'shell', bash: 'shell', lua: 'lua', r: 'r', pl: 'perl',
};

function langForPath(path: string): string {
    const ext = path.split('.').pop()?.toLowerCase() ?? '';
    return LANG_BY_EXT[ext] ?? 'plaintext';
}

export default function CapstoneWorkspace() {
    const { courseId } = useParams<{ courseId: string }>();
    const navigate = useNavigate();
    const cid = Number(courseId);

    const [capstone, setCapstone] = useState<Capstone | null>(null);
    const [capstoneId, setCapstoneId] = useState<number | null>(null);
    const [branch, setBranch] = useState('work');
    const [tree, setTree] = useState<TreeNode[]>([]);
    const [loading, setLoading] = useState(true);
    const [treeError, setTreeError] = useState('');

    const [openFiles, setOpenFiles] = useState<Record<string, OpenFile>>({});
    const [tabs, setTabs] = useState<string[]>([]);
    const [active, setActive] = useState<string | null>(null);

    // Commit
    const [showCommitModal, setShowCommitModal] = useState(false);
    const [commitMessage, setCommitMessage] = useState('');
    const [committing, setCommitting] = useState(false);
    const [lastSha, setLastSha] = useState('');
    const [verdict, setVerdict] = useState<CommitVerdict | null>(null);
    const [polling, setPolling] = useState(false);
    const [submittingGrade, setSubmittingGrade] = useState(false);
    const [showSubmitConfirm, setShowSubmitConfirm] = useState(false);

    // Run
    const [running, setRunning] = useState(false);
    const [runOutput, setRunOutput] = useState<{ stdout: string; stderr: string; success: boolean } | null>(null);

    // Assist
    const [assistOpen, setAssistOpen] = useState(false);
    const [quota, setQuota] = useState<AssistQuota | null>(null);
    const [assistQ, setAssistQ] = useState('');
    const [assistA, setAssistA] = useState('');
    const [asking, setAsking] = useState(false);

    // ---- Load capstone + tree ----
    useEffect(() => {
        setLoading(true);
        getCapstoneForCourse(cid)
            .then(async (cap) => {
                setCapstone(cap);
                setCapstoneId(cap.id);
                try {
                    const { branch: b, tree: t } = await getRepoTree(cap.id);
                    setBranch(b);
                    setTree(t.filter(n => n.type === 'blob').sort((a, b2) => a.path.localeCompare(b2.path)));
                } catch (e: unknown) {
                    const msg = (e as { response?: { data?: { error?: string } } })?.response?.data?.error;
                    setTreeError(msg || 'Could not load repo. Provision your repo first from the capstone page.');
                }
                try {
                    setQuota(await getAssistQuota(cap.id));
                } catch { /* ignore */ }
            })
            .catch(() => setTreeError('No capstone for this course.'))
            .finally(() => setLoading(false));
    }, [cid]);

    // ---- File open / edit ----
    const openFile = useCallback(async (path: string) => {
        if (capstoneId === null) return;
        setActive(path);
        setTabs(prev => (prev.includes(path) ? prev : [...prev, path]));
        if (openFiles[path]?.loaded) return;
        try {
            const f = await getRepoFile(capstoneId, path);
            setOpenFiles(prev => ({
                ...prev,
                [path]: { content: f.content, original: f.content, loaded: true },
            }));
        } catch {
            toast.error(`Could not open ${path}`);
        }
    }, [capstoneId, openFiles]);

    function editActive(value: string) {
        if (!active) return;
        setOpenFiles(prev => ({
            ...prev,
            [active]: { ...prev[active], content: value },
        }));
    }

    function closeTab(path: string) {
        setTabs(prev => prev.filter(p => p !== path));
        if (active === path) {
            const remaining = tabs.filter(p => p !== path);
            setActive(remaining.length ? remaining[remaining.length - 1] : null);
        }
    }

    const dirtyPaths = useMemo(
        () => Object.entries(openFiles).filter(([, f]) => f.loaded && f.content !== f.original).map(([p]) => p),
        [openFiles],
    );

    // ---- Commit ----
    async function doCommit() {
        if (capstoneId === null || dirtyPaths.length === 0) return;
        setCommitting(true);
        try {
            const changed = dirtyPaths.map(p => ({ path: p, content: openFiles[p].content }));
            const { commit_sha } = await commitFiles(capstoneId, changed, commitMessage);
            setLastSha(commit_sha);
            // Mark committed files clean
            setOpenFiles(prev => {
                const next = { ...prev };
                for (const p of dirtyPaths) next[p] = { ...next[p], original: next[p].content };
                return next;
            });
            setShowCommitModal(false);
            setCommitMessage('');
            toast.success('Pushed — checks running…');
            setVerdict({ status: 'queued', conclusion: null, reason: 'CI checks queued…' });
            pollVerdict(commit_sha);
        } catch (e: unknown) {
            const msg = (e as { response?: { data?: { error?: string } } })?.response?.data?.error;
            toast.error(msg || 'Commit failed.');
        } finally {
            setCommitting(false);
        }
    }

    const pollVerdict = useCallback(async (sha: string) => {
        if (capstoneId === null) return;
        setPolling(true);
        let attempts = 0;
        const tick = async () => {
            attempts += 1;
            try {
                const v = await getCommitStatus(sha, capstoneId);
                setVerdict(v);
                if (v.status === 'completed' || attempts >= 40) {
                    setPolling(false);
                    return;
                }
            } catch {
                // keep trying
            }
            setTimeout(tick, 5000);
        };
        tick();
    }, [capstoneId]);

    // ---- Submit for grading (final) ----
    async function doSubmitForGrading() {
        if (capstoneId === null) return;
        if (dirtyPaths.length > 0) {
            toast.error('Commit your changes first — only committed work is graded.');
            return;
        }
        setShowSubmitConfirm(false);
        setSubmittingGrade(true);
        try {
            await submitForGrading(capstoneId);
            toast.success('Submitted for grading — your score will appear on the capstone page shortly.');
            navigate(`/course/${cid}/capstone`);
        } catch (e: unknown) {
            const err = e as { response?: { status?: number; data?: { error?: string } } };
            if (err?.response?.status === 409) {
                toast.error(err.response.data?.error || 'CI must pass on your latest commit before submitting.');
            } else {
                toast.error(err?.response?.data?.error || 'Submit for grading failed.');
            }
        } finally {
            setSubmittingGrade(false);
        }
    }

    // ---- Run ----
    async function doRun() {
        if (capstoneId === null) return;
        const files = Object.entries(openFiles)
            .filter(([, f]) => f.loaded)
            .map(([path, f]) => ({ path, content: f.content }));
        if (files.length === 0) {
            toast.error('Open at least one file to run.');
            return;
        }
        setRunning(true);
        setRunOutput(null);
        try {
            const out = await runFiles(capstoneId, files, capstone?.run_command);
            setRunOutput({ stdout: out.stdout, stderr: out.stderr, success: out.success });
        } catch {
            toast.error('Run failed.');
        } finally {
            setRunning(false);
        }
    }

    // ---- Assist ----
    async function doAsk() {
        if (capstoneId === null || !assistQ.trim()) return;
        setAsking(true);
        setAssistA('');
        try {
            const snippet = active ? openFiles[active]?.content : '';
            const { answer, remaining } = await askAssist(capstoneId, assistQ, snippet);
            setAssistA(answer);
            setQuota(q => (q ? { ...q, remaining, used: q.limit - remaining } : q));
        } catch (e: unknown) {
            const status = (e as { response?: { status?: number } })?.response?.status;
            if (status === 429) {
                toast.error('AI assist quota exhausted for this period.');
                setQuota(q => (q ? { ...q, remaining: 0, used: q.limit } : q));
            } else {
                toast.error('Assist unavailable.');
            }
        } finally {
            setAsking(false);
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-screen">
                <Loader2 className="w-8 h-8 animate-spin text-primary" />
            </div>
        );
    }

    const activeFile = active ? openFiles[active] : null;

    return (
        <div className="flex flex-col h-screen bg-background">
            {/* Top bar */}
            <div className="flex items-center gap-3 px-4 py-2 border-b bg-card">
                <button onClick={() => navigate(`/course/${cid}/capstone`)} className="p-1.5 rounded hover:bg-muted">
                    <ArrowLeft className="w-4 h-4" />
                </button>
                <span className="font-semibold text-sm">{capstone?.title ?? 'Capstone Workspace'}</span>
                <span className="text-xs text-muted-foreground px-2 py-0.5 rounded bg-muted">branch: {branch}</span>
                <div className="ml-auto flex items-center gap-2">
                    <button
                        onClick={doRun}
                        disabled={running}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border hover:bg-muted disabled:opacity-50"
                        title="Run locally (not the official verdict)"
                    >
                        {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                        Run
                    </button>
                    <button
                        onClick={() => setShowCommitModal(true)}
                        disabled={dirtyPaths.length === 0}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                        <GitCommit className="w-4 h-4" />
                        Commit{dirtyPaths.length > 0 ? ` (${dirtyPaths.length})` : ''}
                    </button>
                    <button
                        onClick={() => setShowSubmitConfirm(true)}
                        disabled={submittingGrade || dirtyPaths.length > 0}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-green-600/40 text-green-700 hover:bg-green-50 disabled:opacity-50"
                        title="Promote your CI-passed commit to main and grade it"
                    >
                        {submittingGrade ? <Loader2 className="w-4 h-4 animate-spin" /> : <GraduationCap className="w-4 h-4" />}
                        Submit for grading
                    </button>
                    <button
                        onClick={() => setAssistOpen(v => !v)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border hover:bg-muted"
                    >
                        <Sparkles className="w-4 h-4" />
                        Assist{quota ? ` (${quota.remaining})` : ''}
                    </button>
                </div>
            </div>

            <div className="flex flex-1 min-h-0">
                {/* File tree */}
                <aside className="w-60 border-r bg-card overflow-y-auto shrink-0">
                    <div className="px-3 py-2 text-xs font-semibold text-muted-foreground uppercase">Files</div>
                    {treeError ? (
                        <p className="px-3 text-xs text-muted-foreground">{treeError}</p>
                    ) : (
                        <ul>
                            {tree.map(node => {
                                const depth = node.path.split('/').length - 1;
                                const name = node.path.split('/').pop();
                                const isDirty = openFiles[node.path]?.loaded && openFiles[node.path].content !== openFiles[node.path].original;
                                return (
                                    <li key={node.path}>
                                        <button
                                            onClick={() => openFile(node.path)}
                                            className={`flex items-center gap-1.5 w-full text-left px-3 py-1 text-sm hover:bg-muted/60 ${active === node.path ? 'bg-muted' : ''}`}
                                            style={{ paddingLeft: 12 + depth * 12 }}
                                        >
                                            <FileCode className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                                            <span className="truncate">{name}</span>
                                            {isDirty && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-amber-500 shrink-0" />}
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </aside>

                {/* Editor + tabs */}
                <main className="flex flex-col flex-1 min-w-0">
                    {/* Tabs */}
                    <div className="flex items-center border-b bg-card overflow-x-auto">
                        {tabs.map(path => {
                            const isDirty = openFiles[path]?.loaded && openFiles[path].content !== openFiles[path].original;
                            return (
                                <div
                                    key={path}
                                    className={`flex items-center gap-1.5 px-3 py-1.5 text-sm border-r cursor-pointer ${active === path ? 'bg-background' : 'bg-card hover:bg-muted/40'}`}
                                    onClick={() => setActive(path)}
                                >
                                    <span className="truncate max-w-[160px]">{path.split('/').pop()}</span>
                                    {isDirty && <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />}
                                    <button onClick={(e) => { e.stopPropagation(); closeTab(path); }} className="hover:text-destructive">
                                        <X className="w-3 h-3" />
                                    </button>
                                </div>
                            );
                        })}
                    </div>

                    {/* Editor */}
                    <div className="flex-1 min-h-0">
                        {activeFile?.loaded ? (
                            <Editor
                                height="100%"
                                language={active ? langForPath(active) : 'plaintext'}
                                theme="vs-dark"
                                value={activeFile.content}
                                onChange={(v) => editActive(v ?? '')}
                                options={{
                                    minimap: { enabled: false },
                                    scrollBeyondLastLine: false,
                                    fontSize: 14,
                                    wordWrap: 'on',
                                    automaticLayout: true,
                                }}
                            />
                        ) : (
                            <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                                {active ? <Loader2 className="w-5 h-5 animate-spin" /> : 'Select a file to edit.'}
                            </div>
                        )}
                    </div>

                    {/* Output / verdict panel */}
                    {(runOutput || verdict) && (
                        <div className="border-t bg-card max-h-56 overflow-y-auto p-3 text-sm space-y-3">
                            {verdict && (
                                <div className="space-y-1">
                                    <div className="flex items-center gap-2 font-medium">
                                        {verdict.status !== 'completed'
                                            ? <Clock className="w-4 h-4 text-blue-500" />
                                            : verdict.conclusion === 'success'
                                                ? <CheckCircle className="w-4 h-4 text-green-600" />
                                                : <XCircle className="w-4 h-4 text-red-600" />}
                                        <span>
                                            {verdict.status !== 'completed'
                                                ? 'CI running…'
                                                : verdict.conclusion === 'success' ? 'Approved' : 'Rejected'}
                                        </span>
                                        {polling && <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground" />}
                                        {lastSha && <span className="text-xs text-muted-foreground ml-auto font-mono">{lastSha.slice(0, 7)}</span>}
                                        {!polling && lastSha && (
                                            <button onClick={() => pollVerdict(lastSha)} className="text-muted-foreground hover:text-foreground">
                                                <RefreshCw className="w-3.5 h-3.5" />
                                            </button>
                                        )}
                                    </div>
                                    <pre className="whitespace-pre-wrap text-xs text-muted-foreground">{verdict.reason}</pre>
                                    <p className="text-[11px] text-muted-foreground italic">
                                        Per-commit CI is continuous feedback. The PR-to-main merge is final acceptance.
                                    </p>
                                </div>
                            )}
                            {runOutput && (
                                <div className="space-y-1">
                                    <div className={`font-medium ${runOutput.success ? 'text-green-600' : 'text-red-600'}`}>
                                        Run {runOutput.success ? 'succeeded' : 'failed'} (local only)
                                    </div>
                                    {runOutput.stdout && <pre className="whitespace-pre-wrap text-xs bg-muted/40 p-2 rounded">{runOutput.stdout}</pre>}
                                    {runOutput.stderr && <pre className="whitespace-pre-wrap text-xs text-red-500 bg-red-50 p-2 rounded">{runOutput.stderr}</pre>}
                                </div>
                            )}
                        </div>
                    )}
                </main>

                {/* Assist panel */}
                {assistOpen && (
                    <aside className="w-80 border-l bg-card flex flex-col shrink-0">
                        <div className="px-3 py-2 border-b flex items-center gap-2">
                            <Sparkles className="w-4 h-4 text-primary" />
                            <span className="font-semibold text-sm">AI Assist</span>
                            <span className="ml-auto text-xs text-muted-foreground">
                                {quota ? `${quota.remaining}/${quota.limit} left` : ''}
                            </span>
                        </div>
                        <div className="p-3 text-xs text-muted-foreground border-b">
                            I explain concepts, find bugs, and ask leading questions — but I won't write graded features for you.
                        </div>
                        <div className="flex-1 overflow-y-auto p-3">
                            {assistA
                                ? <div className="text-sm whitespace-pre-wrap">{assistA}</div>
                                : <p className="text-xs text-muted-foreground">Ask a question about your code or the concepts involved.</p>}
                        </div>
                        <div className="p-3 border-t space-y-2">
                            <textarea
                                className="w-full border rounded-lg px-2 py-1.5 text-sm min-h-[70px]"
                                placeholder="e.g. Why does my recursion never terminate?"
                                value={assistQ}
                                onChange={e => setAssistQ(e.target.value)}
                                disabled={quota?.remaining === 0}
                            />
                            <button
                                onClick={doAsk}
                                disabled={asking || !assistQ.trim() || quota?.remaining === 0}
                                className="flex items-center justify-center gap-1.5 w-full bg-primary text-primary-foreground px-3 py-1.5 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
                            >
                                {asking ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                                {quota?.remaining === 0 ? 'No credits left' : 'Ask'}
                            </button>
                        </div>
                    </aside>
                )}
            </div>

            {/* Submit-for-grading confirm */}
            {showSubmitConfirm && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
                    <div className="bg-card rounded-2xl border-2 border-border p-5 w-full max-w-md space-y-3">
                        <h2 className="flex items-center gap-2 font-semibold">
                            <GraduationCap className="w-5 h-5 text-green-700" />
                            Are you sure you're done?
                        </h2>
                        <p className="text-sm text-muted-foreground">
                            This will promote your latest CI-passed commit to <span className="font-mono">main</span> and
                            evaluate your repo against the rubric. You can still re-edit and re-submit afterward if needed.
                        </p>
                        <div className="flex gap-2 justify-end">
                            <button
                                onClick={() => setShowSubmitConfirm(false)}
                                className="px-4 py-1.5 rounded-lg text-sm border hover:bg-muted"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={doSubmitForGrading}
                                disabled={submittingGrade}
                                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
                            >
                                {submittingGrade ? <Loader2 className="w-4 h-4 animate-spin" /> : <GraduationCap className="w-4 h-4" />}
                                Yes, submit
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Commit modal */}
            {showCommitModal && (
                <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
                    <div className="bg-card rounded-2xl border-2 border-border p-5 w-full max-w-md space-y-3">
                        <h2 className="font-semibold">Commit {dirtyPaths.length} file(s)</h2>
                        <ul className="text-xs text-muted-foreground max-h-24 overflow-y-auto">
                            {dirtyPaths.map(p => <li key={p}>• {p}</li>)}
                        </ul>
                        <textarea
                            className="w-full border rounded-lg px-3 py-2 text-sm min-h-[80px]"
                            placeholder="Commit message"
                            value={commitMessage}
                            onChange={e => setCommitMessage(e.target.value)}
                        />
                        <div className="flex gap-2 justify-end">
                            <button onClick={() => setShowCommitModal(false)} className="px-4 py-1.5 rounded-lg text-sm border hover:bg-muted">
                                Cancel
                            </button>
                            <button
                                onClick={doCommit}
                                disabled={committing || !commitMessage.trim()}
                                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
                            >
                                {committing ? <Loader2 className="w-4 h-4 animate-spin" /> : <GitCommit className="w-4 h-4" />}
                                Commit & Push
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
