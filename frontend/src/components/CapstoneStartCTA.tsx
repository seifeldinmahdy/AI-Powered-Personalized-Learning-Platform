import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { Loader2, Trophy, Github, Lock } from 'lucide-react';
import {
    getCapstoneForCourse, getMySubmission, provisionRepo,
    type Capstone,
} from '../services/capstone';

type Variant = 'card' | 'banner' | 'inline';

/**
 * "Start your capstone" entry point. Renders nothing unless the course has an
 * active capstone. On start: if the student already has a repo, jumps straight
 * into the workspace; otherwise prompts once for a GitHub username and
 * auto-provisions the repo, then opens the workspace.
 *
 * Gate it on material completion at the call site (pass when progress is 100%).
 */
export function CapstoneStartCTA({ courseId, variant = 'card', locked = false }: { courseId: number; variant?: Variant, locked?: boolean }) {
    const navigate = useNavigate();
    const [capstone, setCapstone] = useState<Capstone | null>(null);
    const [checking, setChecking] = useState(true);
    const [starting, setStarting] = useState(false);
    const [askUser, setAskUser] = useState(false);
    const [ghUser, setGhUser] = useState('');

    useEffect(() => {
        let cancelled = false;
        getCapstoneForCourse(courseId)
            .then(cap => {
                if (cancelled) return;
                setCapstone(cap);
                // Pre-fill the GitHub handle the student used before, so they
                // never retype it (empty on their very first capstone).
                if (cap?.suggested_github_username) setGhUser(cap.suggested_github_username);
            })
            .catch(() => { if (!cancelled) setCapstone(null); })
            .finally(() => { if (!cancelled) setChecking(false); });
        return () => { cancelled = true; };
    }, [courseId]);

    if (checking || !capstone) return null;

    const workspace = `/course/${courseId}/capstone/workspace`;

    async function handleStart() {
        if (!capstone) return;
        setStarting(true);
        try {
            const sub = await getMySubmission(capstone.id);
            if (sub?.repo_url) {
                navigate(workspace);
                return;
            }
            setAskUser(true); // need a GitHub username to provision
        } catch {
            setAskUser(true);
        } finally {
            setStarting(false);
        }
    }

    async function provisionAndGo() {
        if (!capstone || !ghUser.trim()) return;
        setStarting(true);
        try {
            await provisionRepo(capstone.id, ghUser.trim());
            toast.success('Your capstone repo is ready!');
            navigate(workspace);
        } catch {
            toast.error('Could not create your repo — check your GitHub username and the app config.');
        } finally {
            setStarting(false);
        }
    }

    const button = (
        <button
            onClick={handleStart}
            disabled={starting || locked}
            className={locked ? 'btn btn-ghost-dark' : 'btn btn-red'}
            style={{ padding: '12px 20px', ...(locked ? { cursor: 'not-allowed', opacity: 0.7 } : {}) }}
        >
            {starting ? <Loader2 size={16} className="animate-spin" /> : locked ? <Lock size={16} /> : <Trophy size={16} />}
            {locked ? 'FINISH COURSEWORK TO START' : 'START YOUR CAPSTONE'}
        </button>
    );

    const modal = askUser && (
        <div className="codex" style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.45)', padding: 16 }}>
            <div style={{ width: '100%', maxWidth: 440, background: 'var(--bg-surface)', borderRadius: 12, border: '1px solid var(--hairline)', padding: 24, display: 'flex', flexDirection: 'column', gap: 14 }}>
                <h2 className="t-heading" style={{ fontSize: 20, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Github size={20} /> Connect your GitHub
                </h2>
                <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>
                    We'll create your capstone repository and invite you as a collaborator.
                </p>
                <input
                    className="input"
                    placeholder="Your GitHub username"
                    value={ghUser}
                    onChange={e => setGhUser(e.target.value)}
                    autoFocus
                />
                <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                    <button onClick={() => setAskUser(false)} className="btn btn-ghost-dark" style={{ padding: '10px 16px' }}>CANCEL</button>
                    <button onClick={provisionAndGo} disabled={starting || !ghUser.trim()} className="btn btn-red" style={{ padding: '10px 16px' }}>
                        {starting ? <Loader2 size={16} className="animate-spin" /> : <Github size={16} />}
                        CREATE REPO & START
                    </button>
                </div>
            </div>
        </div>
    );

    if (variant === 'inline') {
        return (<>{button}{modal}</>);
    }

    if (variant === 'banner') {
        return (
            <>
                <div className="codex" style={{ display: 'flex', alignItems: 'center', gap: 20, background: 'var(--bg-surface)', borderRadius: 12, border: '1px solid var(--accent-primary)', padding: 24 }}>
                    <div style={{ width: 48, height: 48, borderRadius: 12, flexShrink: 0, background: 'rgba(37,99,235,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Trophy size={24} style={{ color: 'var(--accent-primary)' }} />
                    </div>
                    <div style={{ flex: 1 }}>
                        <p className="t-body" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
                            {locked ? 'Capstone project locked' : 'You finished the coursework — time for your capstone!'}
                        </p>
                        <p className="t-body" style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--text-secondary)' }}>
                            {locked ? 'Complete all sessions to unlock your capstone project.' : 'Start the project to get your repo and the in-platform editor.'}
                        </p>
                    </div>
                    {button}
                </div>
                {modal}
            </>
        );
    }

    // card
    return (
        <>
            <div className="codex" style={{ display: 'flex', flexDirection: 'column', gap: 12, background: 'var(--bg-surface)', borderRadius: 12, border: '1px solid var(--accent-primary)', padding: 24 }}>
                <h3 className="t-heading" style={{ fontSize: 18, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Trophy size={18} style={{ color: locked ? 'var(--steel-light)' : 'var(--accent-primary)' }} /> Capstone project
                </h3>
                <p className="t-body" style={{ margin: 0, fontSize: 14, color: 'var(--text-secondary)' }}>
                    {locked
                        ? "Complete all your coursework sessions first. Then you can start your capstone, and we'll set up your GitHub repo and open the in-platform editor."
                        : "You've completed the coursework. Start your capstone — we'll set up your GitHub repo and open the in-platform editor."}
                </p>
                {button}
            </div>
            {modal}
        </>
    );
}
