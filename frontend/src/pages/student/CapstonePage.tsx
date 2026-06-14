import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router';
import { toast } from 'sonner';
import {
    Loader2, Github, Upload, CheckCircle, XCircle, Clock, AlertCircle,
    Code2, Users, UserPlus, UserMinus, PartyPopper, MessageSquare, Sparkles, RefreshCw,
} from 'lucide-react';
import {
    getCapstoneForCourse, getMySubmission, submitArchive, submitFromRepo, provisionRepo,
    submitProposal,
    joinQueue, leaveQueue, getRecommendations, getMyTeam,
    getRoleAdvice, refreshRoleAdvice,
    type Capstone, type CapstoneSubmission,
    type TeammateRec, type Team, type RoleAdvice,
} from '../../services/capstone';
import { getCertificate, downloadCertificatePdf, type Certificate as CertificateData } from '../../services/certificate';
import { Certificate } from '../../components/Certificate';

function StatusBadge({ status }: { status: CapstoneSubmission['status'] }) {
    const map = {
        pending: { icon: <Clock className="w-4 h-4" />, colour: 'text-muted-foreground', label: 'Pending' },
        evaluating: { icon: <Loader2 className="w-4 h-4 animate-spin" />, colour: 'text-blue-600', label: 'Evaluating…' },
        completed: { icon: <CheckCircle className="w-4 h-4" />, colour: 'text-green-600', label: 'Completed' },
        failed: { icon: <XCircle className="w-4 h-4" />, colour: 'text-red-600', label: 'Failed' },
    };
    const { icon, colour, label } = map[status] ?? map.pending;
    return (
        <span className={`flex items-center gap-1 font-medium ${colour}`}>
            {icon} {label}
        </span>
    );
}

function ScoreMeter({ score }: { score: number | null }) {
    if (score === null) return null;
    const colour = score >= 70 ? '#16a34a' : score >= 40 ? '#d97706' : '#dc2626';
    return (
        <div className="space-y-1">
            <div className="flex justify-between text-sm font-medium">
                <span>Score</span>
                <span style={{ color: colour }}>{score.toFixed(1)}%</span>
            </div>
            <div className="h-3 w-full bg-muted rounded-full overflow-hidden">
                <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{ width: `${score}%`, backgroundColor: colour }}
                />
            </div>
        </div>
    );
}

type Tab = 'overview' | 'submit' | 'repo' | 'team' | 'results';

export default function CapstonePage() {
    const { courseId } = useParams<{ courseId: string }>();
    const id = Number(courseId);

    const [capstone, setCapstone] = useState<Capstone | null>(null);
    const [submission, setSubmission] = useState<CapstoneSubmission | null>(null);
    const [loading, setLoading] = useState(true);
    const [tab, setTab] = useState<Tab>('overview');

    // Archive submit state
    const [codeBundle, setCodeBundle] = useState('');
    const [submitting, setSubmitting] = useState(false);

    // Repo submit state
    const [repoUrl, setRepoUrl] = useState('');
    const [commitSha, setCommitSha] = useState('');
    const [githubUsername, setGithubUsername] = useState('');
    const [provisioning, setProvisioning] = useState(false);
    const [provisionedUrl, setProvisionedUrl] = useState('');

    // Proposal state (student_proposed mode)
    const [proposalTitle, setProposalTitle] = useState('');
    const [proposalDesc, setProposalDesc] = useState('');
    const [proposalFeatures, setProposalFeatures] = useState('');
    const [submittingProposal, setSubmittingProposal] = useState(false);

    // Team / matchmaking state
    const [team, setTeam] = useState<Team | null>(null);
    const [recs, setRecs] = useState<TeammateRec[]>([]);
    const [inQueue, setInQueue] = useState(false);
    const [queueBusy, setQueueBusy] = useState(false);

    // Advisory team role suggestions
    const [roleAdvice, setRoleAdvice] = useState<RoleAdvice | null>(null);
    const [roleAdviceLoading, setRoleAdviceLoading] = useState(false);
    const [refreshingRoles, setRefreshingRoles] = useState(false);

    // Completion sequence: PASS → survey → certificate
    const [surveyDone, setSurveyDone] = useState<boolean | null>(null);
    const [certificate, setCertificate] = useState<CertificateData | null>(null);
    const [downloadingCert, setDownloadingCert] = useState(false);
    const [pollAttempts, setPollAttempts] = useState(0);

    useEffect(() => {
        Promise.all([
            getCapstoneForCourse(id).catch(() => null),
        ]).then(([cap]) => {
            setCapstone(cap);
            if (cap) {
                getMySubmission(cap.id).then(sub => setSubmission(sub));
                if (cap.team_mode === 'team') {
                    getMyTeam(cap.id).then(t => setTeam(t)).catch(() => {});
                }
            }
        }).finally(() => setLoading(false));
    }, [id]);

    // React to submission state: poll while grading, drive the completion
    // sequence off the certificate gate once a PASS lands.
    useEffect(() => {
        if (!submission || !capstone) return;

        // Poll while grading runs, or briefly if a verdict hasn't landed yet
        // (covers the small window where CI/webhook flips status before the
        // background grader writes the verdict). Bounded so it can't spin forever.
        const awaitingVerdict =
            submission.status === 'evaluating' ||
            (submission.status === 'completed' && submission.verdict === 'pending');
        if (awaitingVerdict && pollAttempts < 45) {
            const t = setTimeout(async () => {
                setPollAttempts((a) => a + 1);
                const sub = await getMySubmission(capstone.id).catch(() => null);
                if (sub) setSubmission(sub);
            }, 4000);
            return () => clearTimeout(t);
        }

        if (submission.verdict === 'pass') {
            let cancelled = false;
            (async () => {
                try {
                    const cert = await getCertificate(id);
                    if (!cancelled) { setCertificate(cert); setSurveyDone(true); }
                } catch (e: unknown) {
                    const reason = (e as { response?: { data?: { reason?: string } } })?.response?.data?.reason;
                    if (!cancelled) {
                        setCertificate(null);
                        setSurveyDone(reason === 'survey_required' ? false : null);
                    }
                }
            })();
            return () => { cancelled = true; };
        }
    }, [submission, capstone, id, pollAttempts]);

    // Load cached role advice when a real team (>=2) is present.
    useEffect(() => {
        if (!team || team.member_usernames.length < 2) {
            setRoleAdvice(null);
            return;
        }
        let cancelled = false;
        setRoleAdviceLoading(true);
        getRoleAdvice(team.id)
            .then(r => { if (!cancelled) setRoleAdvice(r.role_advice); })
            .catch(() => { if (!cancelled) setRoleAdvice(null); })
            .finally(() => { if (!cancelled) setRoleAdviceLoading(false); });
        return () => { cancelled = true; };
    }, [team]);

    async function handleRefreshRoles() {
        if (!team) return;
        setRefreshingRoles(true);
        try {
            const r = await refreshRoleAdvice(team.id);
            setRoleAdvice(r.role_advice);
            toast.success('Suggestions refreshed.');
        } catch {
            toast.error('Could not refresh suggestions.');
        } finally {
            setRefreshingRoles(false);
        }
    }

    async function handleDownloadCert() {
        setDownloadingCert(true);
        try {
            await downloadCertificatePdf(id);
        } catch {
            toast.error('Could not download certificate.');
        } finally {
            setDownloadingCert(false);
        }
    }

    async function handleJoinQueue() {
        if (!capstone) return;
        setQueueBusy(true);
        try {
            await joinQueue(capstone.id);
            setInQueue(true);
            toast.success('Joined the matchmaking queue.');
            const [t, r] = await Promise.all([
                getMyTeam(capstone.id).catch(() => null),
                getRecommendations(capstone.id).catch(() => []),
            ]);
            setTeam(t);
            setRecs(r);
        } catch {
            toast.error('Could not join queue.');
        } finally {
            setQueueBusy(false);
        }
    }

    async function handleLeaveQueue() {
        if (!capstone) return;
        setQueueBusy(true);
        try {
            await leaveQueue(capstone.id);
            setInQueue(false);
            setRecs([]);
            toast.success('Left the queue.');
        } catch {
            toast.error('Could not leave queue.');
        } finally {
            setQueueBusy(false);
        }
    }

    async function handleSubmitArchive() {
        if (!capstone || !codeBundle.trim()) return;
        setSubmitting(true);
        try {
            const result = await submitArchive(capstone.id, codeBundle);
            setSubmission(result);
            setTab('results');
            toast.success('Submission evaluated!');
        } catch {
            toast.error('Submission failed. Please try again.');
        } finally {
            setSubmitting(false);
        }
    }

    async function handleProvisionRepo() {
        if (!capstone || !githubUsername.trim()) return;
        setProvisioning(true);
        try {
            const result = await provisionRepo(capstone.id, githubUsername);
            setProvisionedUrl(result.repo_url);
            toast.success('Repo provisioned! Check your GitHub.');
        } catch {
            toast.error('Provisioning failed.');
        } finally {
            setProvisioning(false);
        }
    }

    async function handleSubmitFromRepo() {
        if (!capstone) return;
        setSubmitting(true);
        try {
            // The backend grades the PROVISIONED repo (server-resolved work-branch
            // HEAD, CI-gated). Any typed repo/sha are ignored for integrity.
            const result = await submitFromRepo(capstone.id);
            setSubmission(result.submission);
            setTab('results');
            toast.success('Submitted for grading — your score will appear shortly.');
        } catch (e: unknown) {
            const err = e as { response?: { status?: number; data?: { error?: string } } };
            toast.error(err?.response?.data?.error || 'Submission failed.');
        } finally {
            setSubmitting(false);
        }
    }

    async function handleSubmitProposal() {
        if (!capstone) return;
        setSubmittingProposal(true);
        try {
            await submitProposal({
                capstone: capstone.id,
                title: proposalTitle,
                description: proposalDesc,
                planned_features: proposalFeatures.split('\n').map(s => s.trim()).filter(Boolean),
            });
            toast.success('Proposal submitted! Waiting for admin review.');
        } catch {
            toast.error('Proposal submission failed.');
        } finally {
            setSubmittingProposal(false);
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 animate-spin text-primary" />
            </div>
        );
    }

    if (!capstone) {
        return (
            <div className="max-w-2xl mx-auto px-4 py-16 text-center">
                <AlertCircle className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
                <p className="text-lg font-medium">No active capstone for this course yet.</p>
                <p className="text-muted-foreground text-sm mt-1">Check back when your instructor activates it.</p>
            </div>
        );
    }

    const tabs: { id: Tab; label: string }[] = [
        { id: 'overview', label: 'Overview' },
        { id: 'submit', label: 'Submit Code' },
        { id: 'repo', label: 'GitHub Repo' },
        ...(capstone.team_mode === 'team' ? [{ id: 'team' as Tab, label: 'Team' }] : []),
        { id: 'results', label: 'Results' },
    ];

    return (
        <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
            <div>
                <h1 className="text-2xl font-bold">{capstone.title}</h1>
                <p className="text-muted-foreground text-sm mt-1">{capstone.brief_text}</p>
                {capstone.deadline && (
                    <p className="text-sm mt-1">
                        Deadline: <strong>{new Date(capstone.deadline).toLocaleDateString()}</strong>
                    </p>
                )}
            </div>

            {/* Tab bar */}
            <div className="flex gap-1 border-b">
                {tabs.map(t => (
                    <button
                        key={t.id}
                        onClick={() => setTab(t.id)}
                        className={`px-4 py-2 text-sm font-medium border-b-2 transition -mb-px ${
                            tab === t.id
                                ? 'border-primary text-primary'
                                : 'border-transparent text-muted-foreground hover:text-foreground'
                        }`}
                    >
                        {t.label}
                    </button>
                ))}
            </div>

            {/* Overview */}
            {tab === 'overview' && (
                <div className="space-y-4">
                    {/* In-platform editor entry */}
                    <Link
                        to={`/course/${id}/capstone/workspace`}
                        className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2.5 rounded-xl text-sm font-medium hover:opacity-90 w-fit"
                    >
                        <Code2 className="w-4 h-4" />
                        Open in-platform editor
                    </Link>

                    {/* Proposal form for student_proposed capstones */}
                    {capstone.spec_mode === 'student_proposed' && (
                        <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-3">
                            <h2 className="font-semibold">Submit Your Proposal</h2>
                            <input
                                className="w-full border rounded-lg px-3 py-2 text-sm"
                                placeholder="Project title"
                                value={proposalTitle}
                                onChange={e => setProposalTitle(e.target.value)}
                            />
                            <textarea
                                className="w-full border rounded-lg px-3 py-2 text-sm min-h-[80px]"
                                placeholder="Description"
                                value={proposalDesc}
                                onChange={e => setProposalDesc(e.target.value)}
                            />
                            <textarea
                                className="w-full border rounded-lg px-3 py-2 text-sm min-h-[60px]"
                                placeholder="Planned features (one per line)"
                                value={proposalFeatures}
                                onChange={e => setProposalFeatures(e.target.value)}
                            />
                            <button
                                onClick={handleSubmitProposal}
                                disabled={submittingProposal || !proposalTitle || !proposalDesc}
                                className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
                            >
                                {submittingProposal ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                                Submit Proposal
                            </button>
                        </div>
                    )}

                    {/* Rubric overview */}
                    <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-3">
                        <h2 className="font-semibold">Rubric Criteria</h2>
                        {capstone.rubric_items.length === 0 ? (
                            <p className="text-sm text-muted-foreground">No criteria published yet.</p>
                        ) : (
                            <ul className="space-y-2">
                                {capstone.rubric_items
                                    .filter(i => i.min_team_size <= 1)
                                    .map(item => (
                                        <li key={item.id} className="flex items-start gap-2 text-sm">
                                            <span className={item.category === 'core' ? 'text-blue-600 mt-0.5' : 'text-purple-500 mt-0.5'}>
                                                {item.category === 'core' ? '●' : '◌'}
                                            </span>
                                            <span>{item.text}</span>
                                            {item.weight > 1 && (
                                                <span className="ml-auto text-xs text-muted-foreground shrink-0">
                                                    ×{item.weight}
                                                </span>
                                            )}
                                        </li>
                                    ))}
                            </ul>
                        )}
                    </div>

                    {/* Current submission status */}
                    {submission && (
                        <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-3">
                            <h2 className="font-semibold">Your Submission</h2>
                            <StatusBadge status={submission.status} />
                            <ScoreMeter score={submission.score} />
                        </div>
                    )}
                </div>
            )}

            {/* Submit code (archive) */}
            {tab === 'submit' && (
                <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-4">
                    <h2 className="font-semibold">Paste Your Code</h2>
                    <p className="text-sm text-muted-foreground">
                        Paste your complete code (all files concatenated, or a ZIP as base64) for AI evaluation.
                    </p>
                    <textarea
                        className="w-full border rounded-lg px-3 py-2 text-sm font-mono min-h-[300px]"
                        placeholder="# Paste your code here..."
                        value={codeBundle}
                        onChange={e => setCodeBundle(e.target.value)}
                    />
                    <button
                        onClick={handleSubmitArchive}
                        disabled={submitting || !codeBundle.trim()}
                        className="flex items-center gap-2 bg-primary text-primary-foreground px-5 py-2 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
                    >
                        {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                        {submitting ? 'Evaluating…' : 'Submit & Evaluate'}
                    </button>
                </div>
            )}

            {/* GitHub repo flow */}
            {tab === 'repo' && (
                <div className="space-y-4">
                    <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-3">
                        <h2 className="flex items-center gap-2 font-semibold">
                            <Github className="w-5 h-5" /> Provision Your Repo
                        </h2>
                        <p className="text-sm text-muted-foreground">
                            We'll create a public GitHub repo from the course template under the course org and invite you as a collaborator.
                        </p>
                        <input
                            className="w-full border rounded-lg px-3 py-2 text-sm"
                            placeholder="Your GitHub username"
                            value={githubUsername}
                            onChange={e => setGithubUsername(e.target.value)}
                        />
                        <button
                            onClick={handleProvisionRepo}
                            disabled={provisioning || !githubUsername.trim()}
                            className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
                        >
                            {provisioning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Github className="w-4 h-4" />}
                            {provisioning ? 'Creating…' : 'Get My Repo'}
                        </button>
                        {provisionedUrl && (
                            <a
                                href={provisionedUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="block text-primary underline text-sm"
                            >
                                {provisionedUrl}
                            </a>
                        )}
                    </div>

                    <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-3">
                        <h2 className="font-semibold">Record a Commit</h2>
                        <p className="text-sm text-muted-foreground">
                            After pushing to your repo, paste the repo URL and commit SHA to record your submission.
                            CI will run automatically and results will appear in the Results tab.
                        </p>
                        <input
                            className="w-full border rounded-lg px-3 py-2 text-sm"
                            placeholder="https://github.com/org/repo-name"
                            value={repoUrl}
                            onChange={e => setRepoUrl(e.target.value)}
                        />
                        <input
                            className="w-full border rounded-lg px-3 py-2 text-sm font-mono"
                            placeholder="Commit SHA (40 characters)"
                            value={commitSha}
                            onChange={e => setCommitSha(e.target.value)}
                        />
                        <button
                            onClick={handleSubmitFromRepo}
                            disabled={submitting || !repoUrl || !commitSha}
                            className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
                        >
                            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Github className="w-4 h-4" />}
                            Record Submission
                        </button>
                    </div>
                </div>
            )}

            {/* Team / matchmaking */}
            {tab === 'team' && (
                <div className="space-y-4">
                    {team ? (
                        <>
                            <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-3">
                                <h2 className="flex items-center gap-2 font-semibold">
                                    <Users className="w-5 h-5" /> {team.name || `Team ${team.id}`}
                                </h2>
                                <p className="text-sm text-muted-foreground">Status: {team.status}</p>
                                <div className="flex flex-wrap gap-2">
                                    {team.member_usernames.map(u => (
                                        <span key={u} className="px-3 py-1 rounded-full bg-muted text-sm">{u}</span>
                                    ))}
                                </div>
                                <p className="text-xs text-muted-foreground">
                                    Team evaluation uses the size-scaled rubric (core + stretch). Each member's
                                    contribution is checked from commit authorship.
                                </p>
                            </div>

                            {/* Advisory suggested division of labor */}
                            {team.member_usernames.length < 2 ? (
                                <div className="bg-card rounded-2xl border-2 border-border p-5">
                                    <p className="text-sm text-muted-foreground">Solo project — no division of labor.</p>
                                </div>
                            ) : (
                                <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-4">
                                    <div className="flex items-center gap-2">
                                        <Sparkles className="w-5 h-5 text-primary" />
                                        <h2 className="font-semibold">Suggested division of labor</h2>
                                        <button
                                            onClick={handleRefreshRoles}
                                            disabled={refreshingRoles}
                                            className="ml-auto flex items-center gap-1.5 text-xs border px-2.5 py-1 rounded-lg hover:bg-muted disabled:opacity-50"
                                        >
                                            {refreshingRoles ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
                                            Refresh suggestions
                                        </button>
                                    </div>
                                    <p className="text-xs text-muted-foreground">
                                        This is a <strong>suggestion</strong> your team can follow or ignore. Everyone is
                                        expected to touch everything — “lead” drives an area; “support” contributes and
                                        learns from the lead.
                                    </p>

                                    {roleAdviceLoading ? (
                                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                            <Loader2 className="w-4 h-4 animate-spin" /> Generating suggestions…
                                        </div>
                                    ) : !roleAdvice ? (
                                        <p className="text-sm text-muted-foreground">
                                            No suggestions yet — click “Refresh suggestions”.
                                        </p>
                                    ) : (
                                        <>
                                            {roleAdvice.limited_data && (
                                                <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
                                                    Based on limited data so far — these are starter suggestions. Revisit as you make progress.
                                                </div>
                                            )}
                                            {roleAdvice.team_note && (
                                                <p className="text-sm bg-muted/40 rounded-xl p-3">{roleAdvice.team_note}</p>
                                            )}
                                            <div className="space-y-2">
                                                {roleAdvice.areas.map((a, i) => (
                                                    <div key={i} className="rounded-xl border border-border p-3 text-sm space-y-1.5">
                                                        <p className="font-medium">{a.area}</p>
                                                        <div className="flex flex-wrap items-center gap-2 text-xs">
                                                            <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary">Lead: {a.lead}</span>
                                                            {a.support.length > 0 && (
                                                                <span className="px-2 py-0.5 rounded-full bg-muted">Support: {a.support.join(', ')}</span>
                                                            )}
                                                        </div>
                                                        {a.rationale && <p className="text-xs text-muted-foreground">{a.rationale}</p>}
                                                    </div>
                                                ))}
                                            </div>
                                            {roleAdvice.per_member_growth.length > 0 && (
                                                <div className="space-y-1 pt-1">
                                                    <p className="text-sm font-medium">Your growth focus</p>
                                                    {roleAdvice.per_member_growth.map((g, i) => (
                                                        <p key={i} className="text-xs text-muted-foreground">
                                                            <span className="font-medium text-foreground">{g.member}</span>: grow on {g.grow_on} — {g.why}
                                                        </p>
                                                    ))}
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-3">
                            <h2 className="flex items-center gap-2 font-semibold">
                                <Users className="w-5 h-5" /> Find a Team
                            </h2>
                            <p className="text-sm text-muted-foreground">
                                Join the matchmaking queue. We'll suggest teammates whose strengths complement
                                yours. You'll never be force-assigned — you confirm your team. If no one else is
                                available, you can still proceed solo with the core-only rubric.
                            </p>
                            <div className="flex gap-2">
                                {!inQueue ? (
                                    <button
                                        onClick={handleJoinQueue}
                                        disabled={queueBusy}
                                        className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm hover:opacity-90 disabled:opacity-50"
                                    >
                                        {queueBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserPlus className="w-4 h-4" />}
                                        Join Queue
                                    </button>
                                ) : (
                                    <button
                                        onClick={handleLeaveQueue}
                                        disabled={queueBusy}
                                        className="flex items-center gap-2 border px-4 py-2 rounded-lg text-sm hover:bg-muted disabled:opacity-50"
                                    >
                                        {queueBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <UserMinus className="w-4 h-4" />}
                                        Leave Queue
                                    </button>
                                )}
                            </div>

                            {recs.length > 0 && (
                                <div className="space-y-2 pt-2">
                                    <p className="text-sm font-medium">Suggested teammates</p>
                                    {recs.map(r => (
                                        <div key={r.student_id} className="flex items-center gap-3 border rounded-xl p-3 text-sm">
                                            <span className="px-2.5 py-1 rounded-full bg-muted">{r.username}</span>
                                            <span className="text-muted-foreground text-xs">{r.why}</span>
                                            <span className="ml-auto text-xs text-muted-foreground">match {(r.score * 100).toFixed(0)}%</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Results */}
            {tab === 'results' && (
                <div className="space-y-4">
                    {!submission ? (
                        <div className="bg-card rounded-2xl border-2 border-border p-5">
                            <p className="text-sm text-muted-foreground">
                                No submission yet. Open the editor, commit CI-green work, then “Submit for grading”.
                            </p>
                        </div>
                    ) : submission.status === 'evaluating' ? (
                        <div className="bg-card rounded-2xl border-2 border-border p-5 flex items-center gap-3">
                            <Loader2 className="w-5 h-5 animate-spin text-primary" />
                            <p className="text-sm">Grading your submission against the rubric…</p>
                        </div>
                    ) : (
                        <>
                            {/* PASS banner */}
                            {submission.verdict === 'pass' && (
                                <div className="rounded-2xl border-2 border-green-300 bg-green-50 p-5 flex items-center gap-4">
                                    <PartyPopper className="w-7 h-7 text-green-600 shrink-0" />
                                    <div className="flex-1">
                                        <p className="font-semibold text-green-800">You passed the capstone!</p>
                                        <p className="text-sm text-green-700">All core criteria met — the course is complete.</p>
                                    </div>
                                    <div className="w-40 shrink-0"><ScoreMeter score={submission.score} /></div>
                                </div>
                            )}

                            {/* FAIL banner + exactly which criteria failed */}
                            {submission.verdict === 'fail' && (
                                <div className="rounded-2xl border-2 border-red-300 bg-red-50 p-5 space-y-3">
                                    <div className="flex items-center gap-3">
                                        <XCircle className="w-6 h-6 text-red-600 shrink-0" />
                                        <div>
                                            <p className="font-semibold text-red-800">Not passed yet</p>
                                            <p className="text-sm text-red-700">
                                                Every <strong>core</strong> criterion must pass. Fix the items below, commit
                                                (CI runs on <span className="font-mono">work</span>), then re-submit.
                                            </p>
                                        </div>
                                    </div>
                                    <ul className="space-y-2">
                                        {capstone.rubric_items
                                            .filter(item => {
                                                const r = submission.results[String(item.id)];
                                                return r && !r.passed;
                                            })
                                            .map(item => {
                                                const r = submission.results[String(item.id)];
                                                return (
                                                    <li key={item.id} className="rounded-xl border border-red-200 bg-card p-3 text-sm">
                                                        <div className="flex items-center gap-2">
                                                            <XCircle className="w-4 h-4 text-red-500 shrink-0" />
                                                            <span className="font-medium">{item.text}</span>
                                                            <span className={`ml-auto text-[11px] px-1.5 py-0.5 rounded ${
                                                                item.category === 'core'
                                                                    ? 'bg-red-100 text-red-700'
                                                                    : 'bg-muted text-muted-foreground'
                                                            }`}>
                                                                {item.category}
                                                            </span>
                                                        </div>
                                                        {r?.evidence && (
                                                            <p className="text-xs text-muted-foreground mt-1 ml-6">{r.evidence}</p>
                                                        )}
                                                    </li>
                                                );
                                            })}
                                    </ul>
                                    <Link
                                        to={`/course/${id}/capstone/workspace`}
                                        className="inline-flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm hover:opacity-90 w-fit"
                                    >
                                        <Code2 className="w-4 h-4" /> Re-edit in the editor
                                    </Link>
                                </div>
                            )}

                            {/* PASS → survey → certificate sequence */}
                            {submission.verdict === 'pass' && (
                                <>
                                    {surveyDone === false && (
                                        <div className="bg-card rounded-2xl border-2 border-primary/30 p-5 flex items-center gap-4">
                                            <div className="w-11 h-11 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
                                                <MessageSquare className="w-5 h-5 text-primary" />
                                            </div>
                                            <div className="flex-1">
                                                <p className="font-semibold">One quick step: tell us about the course</p>
                                                <p className="text-sm text-muted-foreground">Complete a short survey to unlock your certificate.</p>
                                            </div>
                                            <Link
                                                to={`/survey/${id}?next=/course/${id}/capstone`}
                                                className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:opacity-90 shrink-0"
                                            >
                                                Take survey
                                            </Link>
                                        </div>
                                    )}
                                    {certificate && (
                                        <Certificate data={certificate} onDownload={handleDownloadCert} downloading={downloadingCert} />
                                    )}
                                    {surveyDone === null && !certificate && (
                                        <div className="bg-card rounded-2xl border-2 border-border p-5 flex items-center gap-3">
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                            <p className="text-sm text-muted-foreground">Preparing your certificate…</p>
                                        </div>
                                    )}
                                </>
                            )}

                            {/* Feedback */}
                            {submission.feedback && (
                                <div className="bg-card rounded-2xl border-2 border-border p-5">
                                    <p className="font-medium text-sm mb-1">Feedback</p>
                                    <p className="text-sm text-muted-foreground whitespace-pre-wrap">{submission.feedback}</p>
                                </div>
                            )}

                            {/* Full per-criterion breakdown */}
                            {Object.keys(submission.results).length > 0 && (
                                <div className="bg-card rounded-2xl border-2 border-border p-5 space-y-2">
                                    <p className="text-sm font-medium">Per-criterion breakdown</p>
                                    {capstone.rubric_items.map(item => {
                                        const r = submission.results[String(item.id)];
                                        if (!r) return null;
                                        return (
                                            <div
                                                key={item.id}
                                                className={`flex items-start gap-3 rounded-xl p-3 text-sm border ${
                                                    r.passed ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'
                                                }`}
                                            >
                                                {r.passed
                                                    ? <CheckCircle className="w-4 h-4 text-green-600 shrink-0 mt-0.5" />
                                                    : <XCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
                                                }
                                                <div>
                                                    <p className="font-medium">{item.text}</p>
                                                    {r.evidence && (
                                                        <p className="text-xs text-muted-foreground mt-0.5">{r.evidence}</p>
                                                    )}
                                                </div>
                                                <span className="ml-auto text-xs text-muted-foreground shrink-0">
                                                    ×{item.weight}
                                                </span>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
