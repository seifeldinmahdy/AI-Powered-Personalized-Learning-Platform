import { useState, useEffect } from "react";
import { useNavigate, useLocation, Navigate } from "react-router";
import { useAuth } from "../../contexts/AuthContext";
import { PaperField } from "../../components/personifai/PaperField";
import { GoogleIcon, GitHubIcon, FacebookIcon } from "../../components/personifai/SocialIcons";
import { SlidePreviewCard, KnowledgeCheckCard, ExercisesCard } from "./AuthPreviewCards";
import { startOAuth, type OAuthProvider } from "../../services/oauth";

interface LocationState {
  from?: { pathname: string };
}

const CAROUSEL = [
  { key: "slides", tilt: "rotate(-1.8deg)", Card: SlidePreviewCard },
  { key: "knowledge", tilt: "rotate(1.3deg)", Card: KnowledgeCheckCard },
  { key: "exercises", tilt: "rotate(-1.1deg)", Card: ExercisesCard },
];
const SLIDE_MS = 6000;

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, signup, isAuthenticated, user } = useAuth();

  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [idx, setIdx] = useState(0);
  const [hoverSocial, setHoverSocial] = useState<string | null>(null);

  // Auto-advance the left-panel preview carousel.
  useEffect(() => {
    const t = setTimeout(() => setIdx((i) => (i + 1) % CAROUSEL.length), SLIDE_MS);
    return () => clearTimeout(t);
  }, [idx]);

  // If already authenticated, redirect away from the login page.
  if (isAuthenticated && user) {
    const defaultRoute = user.role === "admin" ? "/admin" : "/dashboard";
    return <Navigate to={defaultRoute} replace />;
  }

  const isRegister = !isLogin;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      let data;
      if (isLogin) {
        data = await login(email, password);
      } else {
        data = await signup(name, email, password);
      }

      const state = location.state as LocationState;
      if (state?.from) {
        navigate(state.from.pathname);
      } else {
        navigate(data.role === "admin" ? "/admin" : "/dashboard");
      }
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosErr = err as { response?: { data?: { error?: string } } };
        setError(axiosErr.response?.data?.error || "Authentication failed. Please try again.");
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSocial = (provider: OAuthProvider) => {
    setError("");
    // Remember where the user wanted to go so the OAuth callback can honor it.
    const state = location.state as LocationState;
    if (state?.from?.pathname) {
      sessionStorage.setItem("oauth_return_to", state.from.pathname);
    }
    try {
      startOAuth(provider); // redirects the browser to the provider
    } catch {
      setError(
        `${provider[0].toUpperCase() + provider.slice(1)} sign-in isn't configured yet. ` +
          `Add its client ID to the frontend environment to enable it.`,
      );
    }
  };

  const socials: { name: string; key: OAuthProvider; icon: React.ReactNode }[] = [
    { name: "Google", key: "google", icon: <GoogleIcon /> },
    { name: "GitHub", key: "github", icon: <GitHubIcon hovered={hoverSocial === "github"} /> },
    { name: "Facebook", key: "facebook", icon: <FacebookIcon /> },
  ];

  return (
    <div
      className="codex pai-login"
      style={{ minHeight: "100vh", display: "flex", overflow: "hidden", position: "relative", fontFamily: "var(--ff-body)", background: "var(--bg-primary)" }}
    >
      <style>{`
        @keyframes paiSlideRight { from { opacity: 0; transform: translateX(20px) } to { opacity: 1; transform: translateX(0) } }
        @keyframes paiSlideUp { from { opacity: 0; transform: translateY(24px) } to { opacity: 1; transform: translateY(0) } }
        @keyframes paiRiseUp { from { opacity: 0; transform: translateY(8px) } to { opacity: 1; transform: translateY(0) } }
        @keyframes paiGrow { from { transform: scaleX(0) } to { transform: scaleX(1) } }
        .pai-deck { animation: paiSlideUp 500ms cubic-bezier(0.16,1,0.3,1) 300ms both }
        .pai-form { animation: paiSlideRight 300ms cubic-bezier(0.76,0,0.24,1) 300ms both }
        .pai-soc  { animation: paiRiseUp 200ms cubic-bezier(0.16,1,0.3,1) 500ms both }
        .pai-sbtn { transition: border-color 150ms linear }
        .pai-sbtn:hover { border-color: #2563EB !important }
        .pai-sbtn:hover .pai-sname { color: #2563EB !important }

        /* Responsive: collapse the marketing panel on tablet/mobile. */
        @media (max-width: 920px) {
          .pai-login-left, .pai-login-divider { display: none !important; }
          .pai-login-formpad { padding-left: 28px !important; padding-right: 28px !important; }
          .pai-login-tabs { padding-left: 28px !important; padding-right: 28px !important; }
          .pai-login-indicator { left: 28px !important; width: calc(50% - 28px) !important; }
          .pai-login-heading { font-size: 32px !important; }
        }
        @media (max-width: 460px) {
          .pai-login-formpad { padding-left: 18px !important; padding-right: 18px !important; }
          .pai-login-tabs { padding-left: 18px !important; padding-right: 18px !important; }
          .pai-login-indicator { left: 18px !important; width: calc(50% - 18px) !important; }
          .pai-login-soc .pai-sname { display: none; }
        }
      `}</style>

      {/* ── LEFT PANEL ─────────────────────────────────────────── */}
      <div className="pai-login-left" style={{ width: "58%", background: "var(--bg-primary)", position: "relative", overflow: "hidden", flexShrink: 0 }}>
        {/* Fine engineered blueprint grid, radially faded */}
        <div style={{
          position: "absolute", inset: 0, zIndex: 0, pointerEvents: "none",
          backgroundImage:
            "linear-gradient(rgba(58,48,33,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(58,48,33,0.045) 1px, transparent 1px), linear-gradient(rgba(58,48,33,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(58,48,33,0.06) 1px, transparent 1px)",
          backgroundSize: "46px 46px, 46px 46px, 230px 230px, 230px 230px",
          WebkitMaskImage: "radial-gradient(ellipse 82% 74% at 46% 44%, #000 34%, transparent 88%)",
          maskImage: "radial-gradient(ellipse 82% 74% at 46% 44%, #000 34%, transparent 88%)",
        }} />
        {/* Soft blue glows for color + depth */}
        <div style={{
          position: "absolute", inset: 0, zIndex: 0, pointerEvents: "none",
          background:
            "radial-gradient(34% 30% at 80% 74%, rgba(37,99,235,0.08), transparent 72%), radial-gradient(40% 32% at 16% 26%, rgba(37,99,235,0.05), transparent 70%)",
        }} />
        {/* Subtle depth wash */}
        <div style={{ position: "absolute", inset: 0, background: "radial-gradient(120% 80% at 12% -8%, rgba(37,99,235,0.05), transparent 55%)", pointerEvents: "none", zIndex: 1 }} />

        <div style={{ position: "relative", zIndex: 2, minHeight: "calc(100vh - 60px)", display: "flex", flexDirection: "column", paddingLeft: 88, paddingRight: 72, paddingTop: 58, paddingBottom: 36 }}>
          {/* Large logotype */}
          <div style={{ flexShrink: 0 }}>
            <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 48, letterSpacing: "-0.035em", lineHeight: 1, color: "#1A1611" }}>
              Personif<span style={{ color: "#2563EB" }}>AI</span><span style={{ color: "#2563EB" }}>.</span>
            </div>
          </div>

          {/* Tilted auto-advancing preview card */}
          <div className="pai-deck" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", paddingTop: 28, paddingBottom: 8 }}>
            <div style={{ width: "100%", transform: CAROUSEL[idx].tilt, transition: "transform 500ms cubic-bezier(0.16,1,0.3,1)" }}>
              {(() => { const Card = CAROUSEL[idx].Card; return <Card />; })()}
            </div>
          </div>

          {/* Dot-pill progress indicator */}
          <div style={{ flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, paddingBottom: 8 }}>
            {CAROUSEL.map((s, i) => {
              const isActive = i === idx;
              const isDone = i < idx;
              return (
                <button key={s.key} type="button" onClick={() => setIdx(i)} style={{ background: "none", border: "none", cursor: "pointer", padding: 4, display: "flex", alignItems: "center" }}>
                  <div style={{ height: 8, width: isActive ? 36 : 8, borderRadius: 4, background: isDone ? "#2563EB" : "transparent", border: isDone || isActive ? "none" : "1.5px solid #C8C0B0", overflow: "hidden", position: "relative", flexShrink: 0, transition: "width 280ms cubic-bezier(0.16,1,0.3,1)" }}>
                    {isActive && (
                      <div key={`fill-${idx}`} style={{ position: "absolute", inset: 0, background: "#2563EB", transformOrigin: "left", borderRadius: 4, animation: `paiGrow ${SLIDE_MS}ms linear forwards` }} />
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Bottom stat strip */}
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 60, background: "rgba(243,237,227,0.97)", borderTop: "1px solid #D9D3C6", display: "flex", alignItems: "center", zIndex: 3 }}>
          {["1:1 PERSONALIZED", "REAL-TIME ADAPTIVE", "AI-POWERED"].map((label, i) => (
            <div key={i} style={{ flex: 1, paddingLeft: i === 0 ? 88 : 24, borderLeft: i > 0 ? "1px solid #D9D3C6" : "none", display: "flex", alignItems: "center" }}>
              <span style={{ fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 10.5, letterSpacing: "0.16em", textTransform: "uppercase", color: "#6E665A" }}>{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── DIVIDER ────────────────────────────────────────────── */}
      <div className="pai-login-divider" style={{ width: 1, background: "#D9D3C6", flexShrink: 0 }} />

      {/* ── RIGHT PANEL ────────────────────────────────────────── */}
      <div className="pai-form" style={{ flex: 1, minHeight: "100vh", background: "var(--bg-primary)", display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>
        {/* Tab toggle with sliding indicator */}
        <div className="pai-login-tabs" style={{ flexShrink: 0, position: "relative", display: "flex", padding: "32px 72px 0", borderBottom: "1px solid #D9D3C6" }}>
          {([["login", "LOG IN"], ["register", "REGISTER"]] as [string, string][]).map(([m, label]) => {
            const active = (m === "login") === isLogin;
            return (
              <button
                key={m}
                type="button"
                onClick={() => { setIsLogin(m === "login"); setError(""); }}
                style={{ flex: 1, background: "none", border: "none", cursor: "pointer", paddingBottom: 16, fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 11, letterSpacing: "0.15em", color: active ? "#13100D" : "#9CA3AF", transition: "color 220ms ease" }}
              >
                {label}
              </button>
            );
          })}
          <div className="pai-login-indicator" style={{ position: "absolute", bottom: -1, left: 72, width: "calc(50% - 72px)", height: 2, background: "#13100D", transform: isRegister ? "translateX(100%)" : "translateX(0)", transition: "transform 420ms cubic-bezier(0.7,0,0.2,1)", pointerEvents: "none" }} />
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="pai-login-formpad" style={{ flex: 1, padding: "0 72px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div style={{ width: "100%", maxWidth: 460, marginInline: "auto" }}>
            {/* Heading */}
            <div className="t-label" style={{ fontSize: 11, letterSpacing: "0.18em", color: "#4B5563", marginBottom: 10 }}>
              {isRegister ? "JOIN PERSONIFAI" : "WELCOME BACK"}
            </div>
            <div className="pai-login-heading" style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 40, letterSpacing: "-0.025em", color: "#13100D", lineHeight: 1.05, marginBottom: 32 }}>
              {isRegister ? "Begin your course." : "Enter your course."}
            </div>

            {/* Fields */}
            <div style={{ display: "flex", flexDirection: "column" }}>
              {/* Full Name — collapsible animated row */}
              <div style={{ display: "grid", gridTemplateRows: isRegister ? "1fr" : "0fr", transition: "grid-template-rows 420ms cubic-bezier(0.7,0,0.2,1)" }}>
                <div style={{ overflow: "hidden" }}>
                  <div style={{ opacity: isRegister ? 1 : 0, transform: isRegister ? "translateY(0)" : "translateY(-6px)", transition: isRegister ? "opacity 280ms ease 140ms, transform 340ms cubic-bezier(0.16,1,0.3,1) 140ms" : "opacity 180ms ease, transform 180ms ease", paddingBottom: 18 }}>
                    <PaperField
                      label="FULL NAME"
                      placeholder="Avery Okafor"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      autoComplete="name"
                      required={isRegister}
                      tabIndex={isRegister ? 0 : -1}
                    />
                  </div>
                </div>
              </div>
              <div style={{ marginBottom: 18 }}>
                <PaperField
                  label="EMAIL"
                  type={isLogin ? "text" : "email"}
                  placeholder={isLogin ? "you@institution.edu or username" : "you@institution.edu"}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete={isLogin ? "username" : "email"}
                  required
                />
              </div>
              <PaperField
                label="PASSWORD"
                type="password"
                placeholder="••••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={isLogin ? "current-password" : "new-password"}
                required
              />
            </div>

            {/* Error */}
            {error && (
              <div style={{ marginTop: 16, fontFamily: "var(--ff-mono)", fontSize: 12, color: "var(--error-red)", borderLeft: "2px solid var(--error-red)", paddingLeft: 12, lineHeight: 1.5 }}>
                {error}
              </div>
            )}

            {/* Primary button */}
            <button
              type="submit"
              disabled={loading}
              style={{ marginTop: 26, width: "100%", background: "#13100D", color: "var(--bg-primary)", border: "none", borderRadius: 8, padding: "20px", fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 13, letterSpacing: "0.12em", textTransform: "uppercase", cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.7 : 1, display: "flex", alignItems: "center", justifyContent: "center" }}
            >
              {loading
                ? isRegister ? "CREATING ACCOUNT…" : "LOGGING IN…"
                : isRegister ? "CREATE ACCOUNT →" : "LOG IN →"}
            </button>

            {/* OR divider */}
            <div style={{ margin: "22px 0", display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{ flex: 1, height: 1, background: "#D9D3C6" }} />
              <span style={{ fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 10.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "#9CA3AF", whiteSpace: "nowrap" }}>OR CONTINUE WITH</span>
              <div style={{ flex: 1, height: 1, background: "#D9D3C6" }} />
            </div>

            {/* Social login — initiates real OAuth */}
            <div className="pai-soc pai-login-soc" style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 0 }}>
              {socials.map((s, i) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => handleSocial(s.key)}
                  onMouseEnter={() => setHoverSocial(s.key)}
                  onMouseLeave={() => setHoverSocial(null)}
                  className="pai-sbtn"
                  style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, padding: "14px 0", background: "transparent", border: "1px solid #D9D3C6", borderLeft: i > 0 ? "none" : "1px solid #D9D3C6", cursor: "pointer", borderRadius: 0 }}
                >
                  {s.icon}
                  <span className="pai-sname" style={{ fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 13, color: "#13100D", transition: "color 150ms linear" }}>{s.name}</span>
                </button>
              ))}
            </div>
          </div>
        </form>

        {/* Trust strip */}
        <div style={{ height: 44, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <span style={{ fontFamily: "var(--ff-body)", fontWeight: 500, fontSize: 10.5, letterSpacing: "0.14em", textTransform: "uppercase", color: "#9CA3AF" }}>
            YOUR DATA IS USED ONLY TO PERSONALIZE YOUR LEARNING.
          </span>
        </div>
      </div>
    </div>
  );
}
