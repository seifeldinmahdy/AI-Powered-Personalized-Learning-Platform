import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { Loader2, Trophy, Github } from 'lucide-react';
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
export function CapstoneStartCTA({ courseId, variant = 'card' }: { courseId: number; variant?: Variant }) {
    const navigate = useNavigate();
    const [capstone, setCapstone] = useState<Capstone | null>(null);
    const [checking, setChecking] = useState(true);
    const [starting, setStarting] = useState(false);
    const [askUser, setAskUser] = useState(false);
    const [ghUser, setGhUser] = useState('');

    useEffect(() => {
        let cancelled = false;
        getCapstoneForCourse(courseId)
            .then(cap => { if (!cancelled) setCapstone(cap); })
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
            disabled={starting}
            className="flex items-center gap-2 bg-primary text-primary-foreground px-5 py-2.5 rounded-xl text-sm font-semibold hover:opacity-90 disabled:opacity-50"
        >
            {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trophy className="w-4 h-4" />}
            Start your capstone
        </button>
    );

    const modal = askUser && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
            <div className="bg-card rounded-2xl border-2 border-border p-5 w-full max-w-md space-y-3">
                <h2 className="flex items-center gap-2 font-semibold">
                    <Github className="w-5 h-5" /> Connect your GitHub
                </h2>
                <p className="text-sm text-muted-foreground">
                    We'll create your capstone repository and invite you as a collaborator.
                </p>
                <input
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    placeholder="Your GitHub username"
                    value={ghUser}
                    onChange={e => setGhUser(e.target.value)}
                    autoFocus
                />
                <div className="flex gap-2 justify-end">
                    <button onClick={() => setAskUser(false)} className="px-4 py-1.5 rounded-lg text-sm border hover:bg-muted">
                        Cancel
                    </button>
                    <button
                        onClick={provisionAndGo}
                        disabled={starting || !ghUser.trim()}
                        className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
                    >
                        {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Github className="w-4 h-4" />}
                        Create repo & start
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
                <div className="bg-card rounded-2xl border-2 border-primary/30 p-6 shadow-sm flex items-center gap-5">
                    <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
                        <Trophy className="w-6 h-6 text-primary" />
                    </div>
                    <div className="flex-1">
                        <p className="font-semibold text-foreground mb-0.5">You finished the coursework — time for your capstone!</p>
                        <p className="text-sm text-muted-foreground">Start the project to get your repo and the in-platform editor.</p>
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
            <div className="bg-gradient-to-br from-primary/5 to-secondary/5 rounded-2xl border-2 border-primary/30 p-6 space-y-3">
                <h3 className="flex items-center gap-2 font-semibold">
                    <Trophy className="w-5 h-5 text-primary" /> Capstone project
                </h3>
                <p className="text-sm text-muted-foreground">
                    You've completed the coursework. Start your capstone — we'll set up your GitHub repo
                    and open the in-platform editor.
                </p>
                {button}
            </div>
            {modal}
        </>
    );
}
