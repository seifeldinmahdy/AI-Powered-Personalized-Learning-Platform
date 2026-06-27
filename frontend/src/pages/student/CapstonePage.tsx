import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { useParams, Link } from 'react-router';
import { toast } from 'sonner';
import {
    Loader2, Github, CheckCircle, XCircle, Clock, AlertCircle,
    Code2, Users, UserPlus, UserMinus, PartyPopper, MessageSquare, Sparkles, RefreshCw,
} from 'lucide-react';
import {
    getCapstoneForCourse, getMySubmission, submitFromRepo, provisionRepo,
    submitProposal, getMyProposals, agreeProposal, rejectProposalIdea,
    joinQueue, leaveQueue, getRecommendations, getMyTeam, acceptMatch, declineMatch,
    getRoleAdvice, refreshRoleAdvice,
    type Capstone, type CapstoneSubmission, type CapstoneProposal,
    type TeammateRec, type Team, type RoleAdvice,
} from '../../services/capstone';
import { useAuth } from '../../contexts/AuthContext';
import { getCertificate, downloadCertificatePdf, type Certificate as CertificateData } from '../../services/certificate';
import { Certificate } from '../../components/Certificate';

// Shared codex card surface.
const cardStyle: CSSProperties = {
    background: 'var(--bg-surface)', borderRadius: 12, border: '1px solid var(--hairline)', padding: 20,
    display: 'flex', flexDirection: 'column', gap: 12,
};

function StatusBadge({ status }: { status: CapstoneSubmission['status'] }) {
    const map = {
        pending: { icon: <Clock size={16} />, colour: 'var(--steel-light)', label: 'Pending' },
        evaluating: { icon: <Loader2 size={16} className="animate-spin" />, colour: 'var(--accent-primary)', label: 'Evaluating…' },
        completed: { icon: <CheckCircle size={16} />, colour: 'var(--accent-success)', label: 'Completed' },
        failed: { icon: <XCircle size={16} />, colour: 'var(--error-red)', label: 'Failed' },
    };
    const { icon, colour, label } = map[status] ?? map.pending;
    return (
        <span className="t-label" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: colour }}>
            {icon} {label}
        </span>
    );
}

function ScoreMeter({ score }: { score: number | null }) {
    if (score === null) return null;
    const colour = score >= 70 ? 'var(--accent-success)' : score >= 40 ? '#B45309' : 'var(--error-red)';
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span className="t-mono steel">SCORE</span>
                <span className="t-mono" style={{ color: colour }}>{score.toFixed(1)}%</span>
            </div>
            <div style={{ height: 8, width: '100%', background: 'var(--hairline)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${score}%`, background: colour, borderRadius: 4, transition: 'width 700ms' }} />
            </div>
        </div>
    );
}

type Tab = 'overview' | 'repo' | 'team' | 'results';

export default function CapstonePage() {
    const { courseId } = useParams<{ courseId: string }>();
    const id = Number(courseId);

    const [capstone, setCapstone] = useState<Capstone | null>(null);
    const [submission, setSubmission] = useState<CapstoneSubmission | null>(null);
    const [loading, setLoading] = useState(true);
    const [tab, setTab] = useState<Tab>('overview');

    // Submit state (single repo-based submission flow)
    const [submitting, setSubmitting] = useState(false);

    // Repo provisioning state
    const [githubUsername, setGithubUsername] = useState('');
    const [provisioning, setProvisioning] = useState(false);
    const [provisionedUrl, setProvisionedUrl] = useState('');

    // Proposal state (student_proposed mode)
    const [proposalTitle, setProposalTitle] = useState('');
    const [proposalDesc, setProposalDesc] = useState('');
    const [proposalFeatures, setProposalFeatures] = useState('');
    const [submittingProposal, setSubmittingProposal] = useState(false);

    // Team / matchmaking state
    const { user } = useAuth();
    const [team, setTeam] = useState<Team | null>(null);
    const [recs, setRecs] = useState<TeammateRec[]>([]);
    const [inQueue, setInQueue] = useState(false);
    const [queueBusy, setQueueBusy] = useState(false);
    const [matchBusy, setMatchBusy] = useState(false);
    // The team's shared proposal (or the student's own, solo) for agreement state.
    const [myProposal, setMyProposal] = useState<CapstoneProposal | null>(null);
    const [proposalBusy, setProposalBusy] = useState(false);

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
                getMyProposals().then(ps => setMyProposal(ps.find(p => p.capstone === cap.id) ?? null)).catch(() => {});
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
            const created = await submitProposal({
                capstone: capstone.id,
                title: proposalTitle,
                description: proposalDesc,
                planned_features: proposalFeatures.split('\n').map(s => s.trim()).filter(Boolean),
            });
            setMyProposal(created);
            toast.success(
                capstone.team_mode === 'team'
                    ? 'Proposal drafted — your teammates need to agree before it’s final.'
                    : 'Proposal submitted! Waiting for admin review.',
            );
        } catch (e: unknown) {
            const err = e as { response?: { data?: { detail?: string } } };
            toast.error(err?.response?.data?.detail || 'Proposal submission failed.');
        } finally {
            setSubmittingProposal(false);
        }
    }

    async function handleAgreeProposal() {
        if (!myProposal) return;
        setProposalBusy(true);
        try {
            const updated = await agreeProposal(myProposal.id);
            setMyProposal(updated);
            toast.success(updated.fully_agreed ? 'Everyone agreed — proposal is final!' : 'You agreed to the proposal.');
        } catch {
            toast.error('Could not record your agreement.');
        } finally {
            setProposalBusy(false);
        }
    }

    async function handleRejectIdea() {
        if (!myProposal) return;
        setProposalBusy(true);
        try {
            await rejectProposalIdea(myProposal.id);
            setMyProposal(null);
            toast.success('Idea rejected — your team can draft a new one.');
        } catch {
            toast.error('Could not reject the idea.');
        } finally {
            setProposalBusy(false);
        }
    }

    async function handleAcceptMatch() {
        if (!team) return;
        setMatchBusy(true);
        try {
            const updated = await acceptMatch(team.id);
            setTeam(updated);
            toast.success(updated.status === 'active' ? 'Team confirmed — you’re all set!' : 'Accepted. Waiting on your teammates.');
        } catch {
            toast.error('Could not accept the team.');
        } finally {
            setMatchBusy(false);
        }
    }

    async function handleDeclineMatch() {
        if (!team || !capstone) return;
        setMatchBusy(true);
        try {
            await declineMatch(team.id);
            // Back to the queue; refresh team (likely null) + recommendations.
            const [t, r] = await Promise.all([
                getMyTeam(capstone.id).catch(() => null),
                getRecommendations(capstone.id).catch(() => []),
            ]);
            setTeam(t);
            setRecs(r);
            setInQueue(true);
            toast.success('Declined — you’re back in the queue and won’t be re-matched with them.');
        } catch {
            toast.error('Could not decline the team.');
        } finally {
            setMatchBusy(false);
        }
    }

    if (loading) {
        return (
            <div className="codex" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-primary)' }}>
                <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
            </div>
        );
    }

    if (!capstone) {
        return (
            <div className="codex" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, background: 'var(--bg-primary)', textAlign: 'center', padding: 24 }}>
                <AlertCircle size={44} style={{ color: 'var(--steel-light)' }} />
                <p className="t-heading" style={{ fontSize: 20, color: 'var(--text-primary)' }}>No active capstone for this course yet.</p>
                <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)' }}>Check back when your instructor activates it.</p>
            </div>
        );
    }

    const tabs: { id: Tab; label: string }[] = [
        { id: 'overview', label: 'Overview' },
        { id: 'repo', label: 'Repo & Submit' },
        ...(capstone.team_mode === 'team' ? [{ id: 'team' as Tab, label: 'Team' }] : []),
        { id: 'results', label: 'Results' },
    ];

    return (
        <div className="codex" style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-primary)' }}>
            <div style={{ maxWidth: 860, margin: '0 auto', padding: '32px 24px 64px', display: 'flex', flexDirection: 'column', gap: 24 }}>
                <div>
                    <div className="t-label" style={{ color: 'var(--accent-primary)', marginBottom: 8 }}>CAPSTONE PROJECT</div>
                    <h1 className="t-display" style={{ fontSize: 'clamp(28px,4vw,40px)', color: 'var(--text-primary)', marginBottom: 8 }}>{capstone.title}</h1>
                    <p className="t-body" style={{ fontSize: 15, color: 'var(--text-secondary)', margin: 0 }}>{capstone.brief_text}</p>
                    {capstone.deadline && (
                        <p className="t-mono steel" style={{ marginTop: 8 }}>
                            DEADLINE · {new Date(capstone.deadline).toLocaleDateString()}
                        </p>
                    )}
                </div>

                {/* Tab bar */}
                <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--hairline)' }}>
                    {tabs.map(t => (
                        <button
                            key={t.id}
                            onClick={() => setTab(t.id)}
                            className="t-label"
                            style={{
                                padding: '10px 16px', marginBottom: -1, background: 'transparent', cursor: 'pointer',
                                borderTop: 'none', borderLeft: 'none', borderRight: 'none',
                                borderBottom: `2px solid ${tab === t.id ? 'var(--accent-primary)' : 'transparent'}`,
                                color: tab === t.id ? 'var(--accent-primary)' : 'var(--text-secondary)',
                            }}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>

                {/* Overview */}
                {tab === 'overview' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                        {/* In-platform editor entry */}
                        <Link to={`/course/${id}/capstone/workspace`} className="btn btn-red" style={{ padding: '12px 18px', width: 'fit-content', textDecoration: 'none' }}>
                            <Code2 size={16} /> OPEN IN-PLATFORM EDITOR
                        </Link>

                        {/* Proposal form / agreement for student_proposed capstones */}
                        {capstone.spec_mode === 'student_proposed' && (
                            myProposal ? (
                                <div style={cardStyle}>
                                    <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)' }}>Your Proposal</h2>
                                    <div>
                                        <div className="t-body" style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>{myProposal.title}</div>
                                        <p className="t-body" style={{ fontSize: 13.5, color: 'var(--text-secondary)', margin: '4px 0 0' }}>{myProposal.description}</p>
                                    </div>
                                    {capstone.team_mode === 'team' && team && (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, borderTop: '1px solid var(--hairline)', paddingTop: 12 }}>
                                            <div className="t-label" style={{ color: myProposal.fully_agreed ? 'var(--accent-success)' : 'var(--accent-warm)' }}>
                                                {myProposal.fully_agreed ? 'ALL MEMBERS AGREED' : 'AWAITING TEAM AGREEMENT'}
                                            </div>
                                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                                {team.members.map((mid, i) => (
                                                    <span key={mid} className="tag-steel">
                                                        {team.member_usernames[i]}{myProposal.agreed_member_ids.includes(mid) ? ' · agreed' : ' · pending'}
                                                    </span>
                                                ))}
                                            </div>
                                            {user && !myProposal.agreed_member_ids.includes(user.id) && !myProposal.fully_agreed && (
                                                <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
                                                    <button onClick={handleAgreeProposal} disabled={proposalBusy} className="btn btn-red" style={{ padding: '10px 16px' }}>
                                                        {proposalBusy ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle size={16} />} AGREE
                                                    </button>
                                                    <button onClick={handleRejectIdea} disabled={proposalBusy} className="btn btn-ghost-dark" style={{ padding: '10px 16px' }}>
                                                        <XCircle size={16} /> REJECT IDEA
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            ) : (
                                <div style={cardStyle}>
                                    <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)' }}>Submit Your Proposal</h2>
                                    {capstone.team_mode === 'team' && (
                                        <p className="t-body" style={{ fontSize: 13, color: 'var(--text-secondary)', margin: 0 }}>
                                            This is a team project — your team submits <strong style={{ color: 'var(--text-primary)' }}>one shared proposal</strong>.
                                            Form your team first (Team tab); any member can draft the idea, and <strong style={{ color: 'var(--text-primary)' }}>every member must agree</strong> before it’s final.
                                        </p>
                                    )}
                                    <input className="input" placeholder="Project title" value={proposalTitle} onChange={e => setProposalTitle(e.target.value)} />
                                    <textarea className="input" style={{ minHeight: 80, resize: 'vertical' }} placeholder="Description" value={proposalDesc} onChange={e => setProposalDesc(e.target.value)} />
                                    <textarea className="input" style={{ minHeight: 60, resize: 'vertical' }} placeholder="Planned features (one per line)" value={proposalFeatures} onChange={e => setProposalFeatures(e.target.value)} />
                                    <button onClick={handleSubmitProposal} disabled={submittingProposal || !proposalTitle || !proposalDesc} className="btn btn-red" style={{ padding: '10px 16px', width: 'fit-content' }}>
                                        {submittingProposal ? <Loader2 size={16} className="animate-spin" /> : null}
                                        {capstone.team_mode === 'team' ? 'SUBMIT TEAM PROPOSAL' : 'SUBMIT PROPOSAL'}
                                    </button>
                                </div>
                            )
                        )}

                        {/* Rubric overview */}
                        <div style={cardStyle}>
                            <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)' }}>Rubric Criteria</h2>
                            {capstone.rubric_items.length === 0 ? (
                                <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>No criteria published yet.</p>
                            ) : (
                                <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    {capstone.rubric_items
                                        .filter(i => i.min_team_size <= 1)
                                        .map(item => (
                                            <li key={item.id} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                                                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                                                    <span style={{ marginTop: 2, color: item.category === 'core' ? 'var(--accent-primary)' : 'var(--steel-light)' }}>
                                                        {item.category === 'core' ? '●' : '◌'}
                                                    </span>
                                                    <span className="t-body" style={{ fontSize: 14, color: 'var(--text-primary)' }}>{item.text}</span>
                                                    {item.weight > 1 && (
                                                        <span className="t-mono steel" style={{ marginLeft: 'auto', flexShrink: 0 }}>×{item.weight}</span>
                                                    )}
                                                </div>
                                                {item.checks && item.checks.length > 0 && (
                                                    <ul style={{ listStyle: 'none', margin: 0, padding: '0 0 0 20px', display: 'flex', flexDirection: 'column', gap: 3 }}>
                                                        {item.checks.map((c, ci) => (
                                                            <li key={ci} className="t-body" style={{ fontSize: 12.5, color: 'var(--text-secondary)', display: 'flex', gap: 6 }}>
                                                                <span style={{ color: 'var(--steel-light)' }}>—</span>{c.text}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                )}
                                            </li>
                                        ))}
                                </ul>
                            )}
                        </div>

                        {/* Current submission status */}
                        {submission && (
                            <div style={cardStyle}>
                                <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)' }}>Your Submission</h2>
                                <StatusBadge status={submission.status} />
                                <ScoreMeter score={submission.score} />
                            </div>
                        )}
                    </div>
                )}

                {/* GitHub repo + single submission flow */}
                {tab === 'repo' && (() => {
                    const repoUrl = provisionedUrl || submission?.repo_url || '';
                    const hasRepo = Boolean(repoUrl);
                    return (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                            <div style={cardStyle}>
                                <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <Github size={20} /> {capstone.team_mode === 'team' ? 'Your Team Repo' : 'Your Repo'}
                                </h2>
                                <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>
                                    {capstone.team_mode === 'team'
                                        ? "We'll create one private GitHub repo for your whole team and invite every member as a collaborator — you all work on the same codebase."
                                        : "We'll create a private GitHub repo from the course template under the course org and invite you as a collaborator."}
                                    {' '}You commit on the <code>work</code> branch and CI runs automatically.
                                </p>
                                {!hasRepo && (
                                    <>
                                        <input className="input" placeholder="Your GitHub username" value={githubUsername} onChange={e => setGithubUsername(e.target.value)} />
                                        <button onClick={handleProvisionRepo} disabled={provisioning || !githubUsername.trim()} className="btn btn-red" style={{ padding: '10px 16px', width: 'fit-content' }}>
                                            {provisioning ? <Loader2 size={16} className="animate-spin" /> : <Github size={16} />}
                                            {provisioning ? 'CREATING…' : 'GET MY REPO'}
                                        </button>
                                    </>
                                )}
                                {hasRepo && (
                                    <a href={repoUrl} target="_blank" rel="noopener noreferrer" className="t-body" style={{ fontSize: 13, color: 'var(--accent-primary)', textDecoration: 'underline' }}>
                                        {repoUrl}
                                    </a>
                                )}
                            </div>

                            <div style={cardStyle}>
                                <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)' }}>Submit for Grading</h2>
                                <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>
                                    When you're ready, submit your <code>work</code> branch. Grading runs on the exact
                                    commit at its head — but only once <strong style={{ color: 'var(--text-primary)' }}>CI is green</strong> on it.
                                    Your <code>main</code> branch is never touched, and your code is read transiently and never stored.
                                </p>
                                <button onClick={handleSubmitFromRepo} disabled={submitting || !hasRepo} className="btn btn-red" style={{ padding: '10px 16px', width: 'fit-content' }}>
                                    {submitting ? <Loader2 size={16} className="animate-spin" /> : <Github size={16} />}
                                    {submitting ? 'SUBMITTING…' : 'SUBMIT FOR GRADING'}
                                </button>
                                {!hasRepo && (
                                    <p className="t-mono steel" style={{ fontSize: 12 }}>Provision your repo first.</p>
                                )}
                            </div>
                        </div>
                    );
                })()}

                {/* Team / matchmaking */}
                {tab === 'team' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                        {team ? (
                            <>
                                {/* Proposed team — confirm or decline (no force-assign) */}
                                {team.status === 'forming' && (
                                    <div style={{ ...cardStyle, border: '1px solid var(--accent-primary)' }}>
                                        <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                                            <UserPlus size={20} style={{ color: 'var(--accent-primary)' }} /> You’ve been matched
                                        </h2>
                                        <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
                                            We matched you with these teammates based on complementary strengths. The team
                                            is confirmed only when <strong style={{ color: 'var(--text-primary)' }}>everyone accepts</strong>.
                                            If you decline, you’ll go back to the queue and we won’t pair you with them again.
                                        </p>
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                            {team.member_usernames.map(u => (
                                                <span key={u} className="tag-steel">
                                                    {u}{team.awaiting_confirmation.includes(u) ? ' · pending' : ' · accepted'}
                                                </span>
                                            ))}
                                        </div>
                                        {user && !team.confirmed_member_ids.includes(user.id) ? (
                                            <div style={{ display: 'flex', gap: 10 }}>
                                                <button onClick={handleAcceptMatch} disabled={matchBusy} className="btn btn-red" style={{ padding: '10px 18px' }}>
                                                    {matchBusy ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle size={16} />} ACCEPT TEAM
                                                </button>
                                                <button onClick={handleDeclineMatch} disabled={matchBusy} className="btn btn-ghost-dark" style={{ padding: '10px 18px' }}>
                                                    <UserMinus size={16} /> DECLINE
                                                </button>
                                            </div>
                                        ) : (
                                            <p className="t-mono steel" style={{ fontSize: 12 }}>You accepted — waiting on {team.awaiting_confirmation.length} teammate(s).</p>
                                        )}
                                    </div>
                                )}

                                <div style={cardStyle}>
                                    <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <Users size={20} /> {team.name || `Team ${team.id}`}
                                    </h2>
                                    <p className="t-mono steel">STATUS · {team.status.toUpperCase()}</p>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                        {team.member_usernames.map(u => (
                                            <span key={u} className="tag-steel">{u}</span>
                                        ))}
                                    </div>
                                    <p className="t-body" style={{ fontSize: 12, color: 'var(--text-secondary)', margin: 0 }}>
                                        Team evaluation uses the size-scaled rubric (core + stretch). Each member's
                                        contribution is checked from commit authorship.
                                    </p>
                                </div>

                                {/* Advisory suggested division of labor */}
                                {team.member_usernames.length < 2 ? (
                                    <div style={cardStyle}>
                                        <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>Solo project — no division of labor.</p>
                                    </div>
                                ) : (
                                    <div style={cardStyle}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                            <Sparkles size={18} style={{ color: 'var(--accent-primary)' }} />
                                            <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)' }}>Suggested division of labor</h2>
                                            <button onClick={handleRefreshRoles} disabled={refreshingRoles} className="btn btn-ghost-dark" style={{ marginLeft: 'auto', padding: '6px 12px', fontSize: 10 }}>
                                                {refreshingRoles ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                                                REFRESH
                                            </button>
                                        </div>
                                        <p className="t-body" style={{ fontSize: 12, color: 'var(--text-secondary)', margin: 0 }}>
                                            This is a <strong style={{ color: 'var(--text-primary)' }}>suggestion</strong> your team can follow or ignore. Everyone is
                                            expected to touch everything — “lead” drives an area; “support” contributes and
                                            learns from the lead.
                                        </p>

                                        {roleAdviceLoading ? (
                                            <div className="t-body" style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, color: 'var(--text-secondary)' }}>
                                                <Loader2 size={16} className="animate-spin" /> Generating suggestions…
                                            </div>
                                        ) : !roleAdvice ? (
                                            <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>
                                                No suggestions yet — click “Refresh”.
                                            </p>
                                        ) : (
                                            <>
                                                {roleAdvice.limited_data && (
                                                    <div style={{ borderRadius: 8, border: '1px solid rgba(180,83,9,0.3)', background: 'rgba(180,83,9,0.06)', padding: 12 }}>
                                                        <p className="t-body" style={{ margin: 0, fontSize: 12, color: '#B45309' }}>Based on limited data so far — these are starter suggestions. Revisit as you make progress.</p>
                                                    </div>
                                                )}
                                                {roleAdvice.team_note && (
                                                    <p className="t-body" style={{ fontSize: 14, color: 'var(--text-primary)', background: 'var(--bg-primary)', borderRadius: 8, padding: 12, margin: 0 }}>{roleAdvice.team_note}</p>
                                                )}
                                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                                    {roleAdvice.areas.map((a, i) => (
                                                        <div key={i} style={{ borderRadius: 8, border: '1px solid var(--hairline)', padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                                                            <p className="t-body" style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{a.area}</p>
                                                            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
                                                                <span className="t-mono" style={{ padding: '2px 8px', borderRadius: 999, background: 'rgba(37,99,235,0.1)', color: 'var(--accent-primary)' }}>LEAD: {a.lead}</span>
                                                                {a.support.length > 0 && (
                                                                    <span className="t-mono steel" style={{ padding: '2px 8px', borderRadius: 999, background: 'var(--bg-primary)' }}>SUPPORT: {a.support.join(', ')}</span>
                                                                )}
                                                            </div>
                                                            {a.rationale && <p className="t-body" style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)' }}>{a.rationale}</p>}
                                                        </div>
                                                    ))}
                                                </div>
                                                {roleAdvice.per_member_growth.length > 0 && (
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, paddingTop: 4 }}>
                                                        <p className="t-label" style={{ color: 'var(--text-primary)' }}>YOUR GROWTH FOCUS</p>
                                                        {roleAdvice.per_member_growth.map((g, i) => (
                                                            <p key={i} className="t-body" style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)' }}>
                                                                <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{g.member}</span>: grow on {g.grow_on} — {g.why}
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
                            <div style={cardStyle}>
                                <h2 className="t-heading" style={{ fontSize: 17, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <Users size={20} /> Find a Team
                                </h2>
                                <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>
                                    Join the matchmaking queue. We'll suggest teammates whose strengths complement
                                    yours. You'll never be force-assigned — you confirm your team. If no one else is
                                    available, you can still proceed solo with the core-only rubric.
                                </p>
                                <div style={{ display: 'flex', gap: 8 }}>
                                    {!inQueue ? (
                                        <button onClick={handleJoinQueue} disabled={queueBusy} className="btn btn-red" style={{ padding: '10px 16px' }}>
                                            {queueBusy ? <Loader2 size={16} className="animate-spin" /> : <UserPlus size={16} />}
                                            JOIN QUEUE
                                        </button>
                                    ) : (
                                        <button onClick={handleLeaveQueue} disabled={queueBusy} className="btn btn-ghost-dark" style={{ padding: '10px 16px' }}>
                                            {queueBusy ? <Loader2 size={16} className="animate-spin" /> : <UserMinus size={16} />}
                                            LEAVE QUEUE
                                        </button>
                                    )}
                                </div>

                                {recs.length > 0 && (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, paddingTop: 4 }}>
                                        <p className="t-label" style={{ color: 'var(--text-primary)' }}>SUGGESTED TEAMMATES</p>
                                        {recs.map(r => (
                                            <div key={r.student_id} style={{ display: 'flex', alignItems: 'center', gap: 12, border: '1px solid var(--hairline)', borderRadius: 8, padding: 12 }}>
                                                <span className="tag-steel">{r.username}</span>
                                                <span className="t-body" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{r.why}</span>
                                                <span className="t-mono steel" style={{ marginLeft: 'auto' }}>MATCH {(r.score * 100).toFixed(0)}%</span>
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
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                        {!submission ? (
                            <div style={cardStyle}>
                                <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>
                                    No submission yet. Open the editor, commit CI-green work, then “Submit for grading”.
                                </p>
                            </div>
                        ) : submission.status === 'evaluating' ? (
                            <div style={{ ...cardStyle, flexDirection: 'row', alignItems: 'center', gap: 12 }}>
                                <Loader2 size={20} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
                                <p className="t-body" style={{ fontSize: 14, color: 'var(--text-primary)', margin: 0 }}>Grading your submission against the rubric…</p>
                            </div>
                        ) : (
                            <>
                                {/* PASS banner */}
                                {submission.verdict === 'pass' && (
                                    <div style={{ borderRadius: 12, border: '1px solid rgba(22,163,74,0.4)', background: 'rgba(22,163,74,0.06)', padding: 20, display: 'flex', alignItems: 'center', gap: 16 }}>
                                        <PartyPopper size={28} style={{ color: 'var(--accent-success)', flexShrink: 0 }} />
                                        <div style={{ flex: 1 }}>
                                            <p className="t-body" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--accent-success)' }}>You passed the capstone!</p>
                                            <p className="t-body" style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--text-secondary)' }}>All core criteria met — the course is complete.</p>
                                        </div>
                                        <div style={{ width: 160, flexShrink: 0 }}><ScoreMeter score={submission.score} /></div>
                                    </div>
                                )}

                                {/* FAIL banner + exactly which criteria failed */}
                                {submission.verdict === 'fail' && (
                                    <div style={{ borderRadius: 12, border: '1px solid rgba(220,38,38,0.4)', background: 'rgba(220,38,38,0.05)', padding: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                            <XCircle size={24} style={{ color: 'var(--error-red)', flexShrink: 0 }} />
                                            <div>
                                                <p className="t-body" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--error-red)' }}>Not passed yet</p>
                                                <p className="t-body" style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--text-secondary)' }}>
                                                    Every <strong style={{ color: 'var(--text-primary)' }}>core</strong> criterion must pass. Fix the items below, commit
                                                    (CI runs on <span style={{ fontFamily: 'var(--ff-mono)' }}>work</span>), then re-submit.
                                                </p>
                                            </div>
                                        </div>
                                        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
                                            {capstone.rubric_items
                                                .filter(item => {
                                                    const r = submission.results[String(item.id)];
                                                    return r && !r.passed;
                                                })
                                                .map(item => {
                                                    const r = submission.results[String(item.id)];
                                                    return (
                                                        <li key={item.id} style={{ borderRadius: 8, border: '1px solid rgba(220,38,38,0.25)', background: 'var(--bg-surface)', padding: 12 }}>
                                                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                                <XCircle size={16} style={{ color: 'var(--error-red)', flexShrink: 0 }} />
                                                                <span className="t-body" style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{item.text}</span>
                                                                <span className="t-mono" style={{ marginLeft: 'auto', padding: '2px 6px', borderRadius: 4, background: item.category === 'core' ? 'rgba(220,38,38,0.12)' : 'var(--bg-primary)', color: item.category === 'core' ? 'var(--error-red)' : 'var(--steel-light)' }}>
                                                                    {item.category}
                                                                </span>
                                                            </div>
                                                            {r?.checks && Object.keys(r.checks).length > 0 ? (
                                                                <ul style={{ listStyle: 'none', margin: '6px 0 0 24px', padding: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
                                                                    {Object.entries(r.checks).map(([cid, chk]) => (
                                                                        <li key={cid} style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                                                                            {chk.passed
                                                                                ? <CheckCircle size={13} style={{ color: 'var(--accent-success)', flexShrink: 0, marginTop: 2 }} />
                                                                                : <XCircle size={13} style={{ color: 'var(--error-red)', flexShrink: 0, marginTop: 2 }} />}
                                                                            <span className="t-body" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                                                                {chk.text}{chk.evidence ? ` — ${chk.evidence}` : ''}
                                                                            </span>
                                                                        </li>
                                                                    ))}
                                                                </ul>
                                                            ) : (r?.evidence && (
                                                                <p className="t-body" style={{ margin: '4px 0 0 24px', fontSize: 12, color: 'var(--text-secondary)' }}>{r.evidence}</p>
                                                            ))}
                                                        </li>
                                                    );
                                                })}
                                        </ul>
                                        <Link to={`/course/${id}/capstone/workspace`} className="btn btn-red" style={{ padding: '10px 16px', width: 'fit-content', textDecoration: 'none' }}>
                                            <Code2 size={16} /> RE-EDIT IN THE EDITOR
                                        </Link>
                                    </div>
                                )}

                                {/* PASS → survey → certificate sequence */}
                                {submission.verdict === 'pass' && (
                                    <>
                                        {surveyDone === false && (
                                            <div style={{ ...cardStyle, flexDirection: 'row', alignItems: 'center', gap: 16, border: '1px solid var(--accent-primary)' }}>
                                                <div style={{ width: 44, height: 44, borderRadius: 12, background: 'rgba(37,99,235,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                                    <MessageSquare size={20} style={{ color: 'var(--accent-primary)' }} />
                                                </div>
                                                <div style={{ flex: 1 }}>
                                                    <p className="t-body" style={{ margin: 0, fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>One quick step: tell us about the course</p>
                                                    <p className="t-body" style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--text-secondary)' }}>Complete a short survey to unlock your certificate.</p>
                                                </div>
                                                <Link to={`/survey/${id}?next=/course/${id}/capstone`} className="btn btn-red" style={{ padding: '10px 16px', flexShrink: 0, textDecoration: 'none' }}>
                                                    TAKE SURVEY
                                                </Link>
                                            </div>
                                        )}
                                        {certificate && (
                                            <Certificate data={certificate} onDownload={handleDownloadCert} downloading={downloadingCert} />
                                        )}
                                        {surveyDone === null && !certificate && (
                                            <div style={{ ...cardStyle, flexDirection: 'row', alignItems: 'center', gap: 12 }}>
                                                <Loader2 size={16} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
                                                <p className="t-body" style={{ fontSize: 14, color: 'var(--text-secondary)', margin: 0 }}>Preparing your certificate…</p>
                                            </div>
                                        )}
                                    </>
                                )}

                                {/* Feedback */}
                                {submission.feedback && (
                                    <div style={cardStyle}>
                                        <p className="t-label" style={{ color: 'var(--text-primary)' }}>FEEDBACK</p>
                                        <p className="t-body" style={{ margin: 0, fontSize: 14, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}>{submission.feedback}</p>
                                    </div>
                                )}

                                {/* Full per-criterion breakdown */}
                                {Object.keys(submission.results).length > 0 && (
                                    <div style={cardStyle}>
                                        <p className="t-label" style={{ color: 'var(--text-primary)' }}>PER-CRITERION BREAKDOWN</p>
                                        {capstone.rubric_items.map(item => {
                                            const r = submission.results[String(item.id)];
                                            if (!r) return null;
                                            return (
                                                <div
                                                    key={item.id}
                                                    style={{
                                                        display: 'flex', alignItems: 'flex-start', gap: 12, borderRadius: 8, padding: 12,
                                                        border: `1px solid ${r.passed ? 'rgba(22,163,74,0.3)' : 'rgba(220,38,38,0.3)'}`,
                                                        background: r.passed ? 'rgba(22,163,74,0.05)' : 'rgba(220,38,38,0.05)',
                                                    }}
                                                >
                                                    {r.passed
                                                        ? <CheckCircle size={16} style={{ color: 'var(--accent-success)', flexShrink: 0, marginTop: 2 }} />
                                                        : <XCircle size={16} style={{ color: 'var(--error-red)', flexShrink: 0, marginTop: 2 }} />}
                                                    <div>
                                                        <p className="t-body" style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{item.text}</p>
                                                        {r.evidence && (
                                                            <p className="t-body" style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-secondary)' }}>{r.evidence}</p>
                                                        )}
                                                    </div>
                                                    <span className="t-mono steel" style={{ marginLeft: 'auto', flexShrink: 0 }}>×{item.weight}</span>
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
        </div>
    );
}
