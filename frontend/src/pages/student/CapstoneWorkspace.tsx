import { useEffect, useMemo, useState, useCallback } from 'react';
import type { CSSProperties } from 'react';
import { useParams, useNavigate } from 'react-router';
import Editor from '@monaco-editor/react';
import { defineCodexTheme, CODEX_MONACO_THEME, CODEX_MONACO_FONT } from '../../lib/monacoTheme';
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

// Shared toolbar-button base.
const toolBtn: CSSProperties = {
    display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', borderRadius: 8,
    border: '1px solid var(--hairline)', background: 'var(--bg-surface)', color: 'var(--text-primary)',
    cursor: 'pointer', fontSize: 12, fontWeight: 500, letterSpacing: '0.06em', textTransform: 'uppercase',
};
const modalBackdrop: CSSProperties = {
    position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'rgba(0,0,0,0.45)', padding: 16,
};
const modalCard: CSSProperties = {
    width: '100%', maxWidth: 440, background: 'var(--bg-surface)', borderRadius: 12,
    border: '1px solid var(--hairline)', padding: 20, display: 'flex', flexDirection: 'column', gap: 14,
};

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
            <div className="codex" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)' }}>
                <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
            </div>
        );
    }

    const activeFile = active ? openFiles[active] : null;
    const noCredits = quota?.remaining === 0;

    return (
        <div className="codex" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', background: 'var(--bg-primary)' }}>
            {/* Top bar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px', borderBottom: '1px solid var(--hairline)', background: 'var(--bg-surface)', flexShrink: 0 }}>
                <button onClick={() => navigate(`/course/${cid}/capstone`)} style={{ padding: 6, borderRadius: 8, border: 'none', background: 'transparent', color: 'var(--text-primary)', cursor: 'pointer', display: 'flex' }} title="Back to capstone">
                    <ArrowLeft size={16} />
                </button>
                <span className="t-body" style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{capstone?.title ?? 'Capstone Workspace'}</span>
                <span className="t-mono steel" style={{ padding: '3px 8px', borderRadius: 6, background: 'var(--bg-primary)', border: '1px solid var(--hairline)' }}>BRANCH: {branch}</span>
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <button onClick={doRun} disabled={running} style={{ ...toolBtn, opacity: running ? 0.5 : 1 }} title="Run locally (not the official verdict)">
                        {running ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                        Run
                    </button>
                    <button onClick={() => setShowCommitModal(true)} disabled={dirtyPaths.length === 0} className="btn btn-red" style={{ padding: '8px 12px', opacity: dirtyPaths.length === 0 ? 0.5 : 1 }}>
                        <GitCommit size={14} />
                        Commit{dirtyPaths.length > 0 ? ` (${dirtyPaths.length})` : ''}
                    </button>
                    <button onClick={() => setShowSubmitConfirm(true)} disabled={submittingGrade || dirtyPaths.length > 0} style={{ ...toolBtn, borderColor: 'rgba(22,163,74,0.4)', color: 'var(--accent-success)', opacity: (submittingGrade || dirtyPaths.length > 0) ? 0.5 : 1 }} title="Promote your CI-passed commit to main and grade it">
                        {submittingGrade ? <Loader2 size={14} className="animate-spin" /> : <GraduationCap size={14} />}
                        Submit for grading
                    </button>
                    <button onClick={() => setAssistOpen(v => !v)} style={toolBtn}>
                        <Sparkles size={14} />
                        Assist{quota ? ` (${quota.remaining})` : ''}
                    </button>
                </div>
            </div>

            <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
                {/* File tree */}
                <aside style={{ width: 240, borderRight: '1px solid var(--hairline)', background: 'var(--bg-surface)', overflowY: 'auto', flexShrink: 0 }}>
                    <div className="t-label" style={{ padding: '10px 12px', color: 'var(--steel-light)' }}>Files</div>
                    {treeError ? (
                        <p className="t-body" style={{ padding: '0 12px', fontSize: 12, color: 'var(--text-secondary)' }}>{treeError}</p>
                    ) : (
                        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                            {tree.map(node => {
                                const depth = node.path.split('/').length - 1;
                                const name = node.path.split('/').pop();
                                const isDirty = openFiles[node.path]?.loaded && openFiles[node.path].content !== openFiles[node.path].original;
                                return (
                                    <li key={node.path}>
                                        <button
                                            onClick={() => openFile(node.path)}
                                            className="t-body"
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: 6, width: '100%', textAlign: 'left',
                                                padding: '4px 12px', paddingLeft: 12 + depth * 12, fontSize: 13, cursor: 'pointer',
                                                border: 'none', color: 'var(--text-primary)',
                                                background: active === node.path ? 'rgba(37,99,235,0.08)' : 'transparent',
                                            }}
                                        >
                                            <FileCode size={14} style={{ color: 'var(--steel-light)', flexShrink: 0 }} />
                                            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
                                            {isDirty && <span style={{ marginLeft: 'auto', width: 6, height: 6, borderRadius: '50%', background: '#B45309', flexShrink: 0 }} />}
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    )}
                </aside>

                {/* Editor + tabs */}
                <main style={{ display: 'flex', flexDirection: 'column', flex: 1, minWidth: 0 }}>
                    {/* Tabs */}
                    <div style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid var(--hairline)', background: 'var(--bg-surface)', overflowX: 'auto', flexShrink: 0 }}>
                        {tabs.map(path => {
                            const isDirty = openFiles[path]?.loaded && openFiles[path].content !== openFiles[path].original;
                            const isActive = active === path;
                            return (
                                <div
                                    key={path}
                                    onClick={() => setActive(path)}
                                    className="t-body"
                                    style={{
                                        display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', fontSize: 13, cursor: 'pointer',
                                        borderRight: '1px solid var(--hairline)', color: 'var(--text-primary)',
                                        background: isActive ? 'var(--bg-primary)' : 'transparent',
                                    }}
                                >
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160 }}>{path.split('/').pop()}</span>
                                    {isDirty && <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#B45309' }} />}
                                    <button onClick={(e) => { e.stopPropagation(); closeTab(path); }} style={{ border: 'none', background: 'transparent', color: 'var(--steel-light)', cursor: 'pointer', display: 'flex' }}>
                                        <X size={12} />
                                    </button>
                                </div>
                            );
                        })}
                    </div>

                    {/* Editor */}
                    <div style={{ flex: 1, minHeight: 0 }}>
                        {activeFile?.loaded ? (
                            <Editor
                                height="100%"
                                language={active ? langForPath(active) : 'plaintext'}
                                theme={CODEX_MONACO_THEME}
                                beforeMount={defineCodexTheme}
                                value={activeFile.content}
                                onChange={(v) => editActive(v ?? '')}
                                options={{
                                    minimap: { enabled: false },
                                    scrollBeyondLastLine: false,
                                    fontSize: 14,
                                    fontFamily: CODEX_MONACO_FONT,
                                    wordWrap: 'on',
                                    automaticLayout: true,
                                }}
                            />
                        ) : (
                            <div className="t-body" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)', fontSize: 14 }}>
                                {active ? <Loader2 size={20} className="animate-spin" /> : 'Select a file to edit.'}
                            </div>
                        )}
                    </div>

                    {/* Output / verdict panel */}
                    {(runOutput || verdict) && (
                        <div style={{ borderTop: '1px solid var(--hairline)', background: 'var(--bg-surface)', maxHeight: 224, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 12, flexShrink: 0 }}>
                            {verdict && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <div className="t-body" style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                                        {verdict.status !== 'completed'
                                            ? <Clock size={16} style={{ color: 'var(--accent-primary)' }} />
                                            : verdict.conclusion === 'success'
                                                ? <CheckCircle size={16} style={{ color: 'var(--accent-success)' }} />
                                                : <XCircle size={16} style={{ color: 'var(--error-red)' }} />}
                                        <span>
                                            {verdict.status !== 'completed'
                                                ? 'CI running…'
                                                : verdict.conclusion === 'success' ? 'Approved' : 'Rejected'}
                                        </span>
                                        {polling && <Loader2 size={14} className="animate-spin" style={{ color: 'var(--steel-light)' }} />}
                                        {lastSha && <span className="t-mono steel" style={{ marginLeft: 'auto' }}>{lastSha.slice(0, 7)}</span>}
                                        {!polling && lastSha && (
                                            <button onClick={() => pollVerdict(lastSha)} style={{ border: 'none', background: 'transparent', color: 'var(--steel-light)', cursor: 'pointer', display: 'flex' }}>
                                                <RefreshCw size={14} />
                                            </button>
                                        )}
                                    </div>
                                    <pre className="t-mono" style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)', margin: 0 }}>{verdict.reason}</pre>
                                    <p className="t-body" style={{ fontSize: 11, fontStyle: 'italic', color: 'var(--text-secondary)', margin: 0 }}>
                                        Per-commit CI is continuous feedback. The PR-to-main merge is final acceptance.
                                    </p>
                                </div>
                            )}
                            {runOutput && (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <div className="t-label" style={{ color: runOutput.success ? 'var(--accent-success)' : 'var(--error-red)' }}>
                                        Run {runOutput.success ? 'succeeded' : 'failed'} (local only)
                                    </div>
                                    {runOutput.stdout && <pre className="codeblock" style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0 }}>{runOutput.stdout}</pre>}
                                    {runOutput.stderr && <pre className="codeblock" style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0, color: '#FCA5A5' }}>{runOutput.stderr}</pre>}
                                </div>
                            )}
                        </div>
                    )}
                </main>

                {/* Assist panel */}
                {assistOpen && (
                    <aside style={{ width: 320, borderLeft: '1px solid var(--hairline)', background: 'var(--bg-surface)', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
                        <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--hairline)', display: 'flex', alignItems: 'center', gap: 8 }}>
                            <Sparkles size={16} style={{ color: 'var(--accent-primary)' }} />
                            <span className="t-body" style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>AI Assist</span>
                            <span className="t-mono steel" style={{ marginLeft: 'auto' }}>{quota ? `${quota.remaining}/${quota.limit} LEFT` : ''}</span>
                        </div>
                        <div className="t-body" style={{ padding: 12, fontSize: 12, color: 'var(--text-secondary)', borderBottom: '1px solid var(--hairline)' }}>
                            I explain concepts, find bugs, and ask leading questions — but I won't write graded features for you.
                        </div>
                        <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
                            {assistA
                                ? <div className="t-body" style={{ fontSize: 14, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>{assistA}</div>
                                : <p className="t-body" style={{ fontSize: 12, color: 'var(--text-secondary)', margin: 0 }}>Ask a question about your code or the concepts involved.</p>}
                        </div>
                        <div style={{ padding: 12, borderTop: '1px solid var(--hairline)', display: 'flex', flexDirection: 'column', gap: 8 }}>
                            <textarea
                                className="input"
                                style={{ minHeight: 70, resize: 'vertical', fontSize: 13 }}
                                placeholder="e.g. Why does my recursion never terminate?"
                                value={assistQ}
                                onChange={e => setAssistQ(e.target.value)}
                                disabled={noCredits}
                            />
                            <button onClick={doAsk} disabled={asking || !assistQ.trim() || noCredits} className="btn btn-red" style={{ justifyContent: 'center', padding: '8px 12px', opacity: (asking || !assistQ.trim() || noCredits) ? 0.5 : 1 }}>
                                {asking ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                                {noCredits ? 'NO CREDITS LEFT' : 'ASK'}
                            </button>
                        </div>
                    </aside>
                )}
            </div>

            {/* Submit-for-grading confirm */}
            {showSubmitConfirm && (
                <div className="codex" style={modalBackdrop}>
                    <div style={modalCard}>
                        <h2 className="t-heading" style={{ fontSize: 18, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                            <GraduationCap size={20} style={{ color: 'var(--accent-success)' }} />
                            Are you sure you're done?
                        </h2>
                        <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>
                            This will promote your latest CI-passed commit to <span style={{ fontFamily: 'var(--ff-mono)' }}>main</span> and
                            evaluate your repo against the rubric. You can still re-edit and re-submit afterward if needed.
                        </p>
                        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                            <button onClick={() => setShowSubmitConfirm(false)} className="btn btn-ghost-dark" style={{ padding: '10px 16px' }}>CANCEL</button>
                            <button onClick={doSubmitForGrading} disabled={submittingGrade} className="btn" style={{ padding: '10px 16px', background: 'var(--accent-success)', color: '#fff' }}>
                                {submittingGrade ? <Loader2 size={16} className="animate-spin" /> : <GraduationCap size={16} />}
                                YES, SUBMIT
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Commit modal */}
            {showCommitModal && (
                <div className="codex" style={modalBackdrop}>
                    <div style={modalCard}>
                        <h2 className="t-heading" style={{ fontSize: 18, color: 'var(--text-primary)' }}>Commit {dirtyPaths.length} file(s)</h2>
                        <ul className="t-mono steel" style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 96, overflowY: 'auto' }}>
                            {dirtyPaths.map(p => <li key={p}>• {p}</li>)}
                        </ul>
                        <textarea
                            className="input"
                            style={{ minHeight: 80, resize: 'vertical' }}
                            placeholder="Commit message"
                            value={commitMessage}
                            onChange={e => setCommitMessage(e.target.value)}
                        />
                        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                            <button onClick={() => setShowCommitModal(false)} className="btn btn-ghost-dark" style={{ padding: '10px 16px' }}>CANCEL</button>
                            <button onClick={doCommit} disabled={committing || !commitMessage.trim()} className="btn btn-red" style={{ padding: '10px 16px' }}>
                                {committing ? <Loader2 size={16} className="animate-spin" /> : <GitCommit size={16} />}
                                COMMIT & PUSH
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
