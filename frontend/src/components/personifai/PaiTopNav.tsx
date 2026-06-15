import { Link, useLocation, useNavigate } from "react-router";
import { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { NotificationBell } from "../NotificationBell";

/* Codex student shell — light/paper only. Admin keeps its own TopNav. */

const NAV = [
  { path: "/dashboard", label: "DASHBOARD" },
  { path: "/courses", label: "COURSES" },
];

export function PaiTopNav() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);

  const isActive = (path: string) =>
    path === "/dashboard"
      ? location.pathname === "/" || location.pathname.startsWith("/dashboard")
      : location.pathname.startsWith(path);

  const name = user?.full_name || user?.username || "Learner";
  const initials = name.slice(0, 2).toUpperCase();
  const handleLogout = () => { logout(); navigate("/login"); };

  return (
    <header className="codex" style={{ position: "relative", zIndex: 50, height: 64, flexShrink: 0, background: "var(--bg-primary)", borderBottom: "1px solid var(--hairline)", display: "flex", alignItems: "center", padding: "0 clamp(16px,4vw,40px)", gap: 16 }}>
      <style>{`
        .pai-nav-link { font-family: var(--ff-body); font-weight:500; font-size:11px; letter-spacing:0.15em; text-transform:uppercase; text-decoration:none; position:relative; padding:4px 0; transition:color 160ms linear; }
        .pai-nav-link::after { content:""; position:absolute; left:0; bottom:-6px; height:2px; width:100%; background:var(--ink-black); transform:scaleX(0); transform-origin:left; transition:transform 240ms cubic-bezier(.7,0,.2,1); }
        .pai-nav-link.is-active::after { transform:scaleX(1); }
        .pai-nav-link:hover { color: var(--ink-black) !important; }
        @media (max-width: 760px){ .pai-nav-desktop{ display:none !important; } }
        @media (min-width: 761px){ .pai-nav-mob{ display:none !important; } }
      `}</style>

      {/* Brand */}
      <Link to="/dashboard" style={{ textDecoration: "none", flexShrink: 0 }}>
        <span style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 19, letterSpacing: "-0.02em", color: "#1A1611" }}>Personif<span style={{ color: "#2563EB" }}>AI</span><span style={{ color: "#2563EB" }}>.</span></span>
      </Link>

      {/* Desktop links */}
      <nav className="pai-nav-desktop" style={{ display: "flex", gap: 28, alignItems: "center", marginLeft: 24 }}>
        {NAV.map((n) => (
          <Link key={n.path} to={n.path} className={`pai-nav-link ${isActive(n.path) ? "is-active" : ""}`} style={{ color: isActive(n.path) ? "var(--ink-black)" : "var(--steel-light)" }}>{n.label}</Link>
        ))}
      </nav>

      <div style={{ flex: 1 }} />

      {/* Right cluster */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-secondary)", flexShrink: 0 }}>
        <NotificationBell />

        <div style={{ position: "relative" }}>
          <button onClick={() => setUserOpen((o) => !o)} style={{ display: "flex", alignItems: "center", gap: 10, background: "transparent", border: "none", cursor: "pointer", padding: 4 }}>
            <span className="pai-nav-desktop t-label" style={{ color: "var(--text-primary)" }}>{name}</span>
            <span style={{ width: 30, height: 30, background: "var(--accent-primary)", color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 600, fontSize: 11, fontFamily: "var(--ff-body)" }}>{initials}</span>
          </button>
          {userOpen && (
            <>
              <div onClick={() => setUserOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
              <div style={{ position: "absolute", right: 0, top: "calc(100% + 12px)", zIndex: 50, minWidth: 184, background: "var(--bg-primary)", border: "1px solid var(--hairline)", borderRadius: 8, boxShadow: "0 16px 40px -16px rgba(26,22,17,0.3)", overflow: "hidden" }}>
                <Link to="/profile" onClick={() => setUserOpen(false)} className="t-label" style={{ display: "block", padding: "14px 16px", color: "var(--text-primary)", textDecoration: "none", borderBottom: "1px solid var(--hairline)" }}>PROFILE</Link>
                <button onClick={handleLogout} className="t-label" style={{ display: "block", width: "100%", textAlign: "left", padding: "14px 16px", color: "var(--error-red)", background: "transparent", border: "none", cursor: "pointer" }}>LOG OUT</button>
              </div>
            </>
          )}
        </div>

        {/* Mobile menu toggle */}
        <button className="pai-nav-mob" onClick={() => setMenuOpen((o) => !o)} aria-label="Menu" style={{ background: "transparent", border: "none", cursor: "pointer", padding: 6, color: "var(--ink-black)", display: "flex" }}>
          <svg width="22" height="22" viewBox="0 0 22 22" fill="none"><path d="M3 6h16M3 11h16M3 16h16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
        </button>
      </div>

      {/* Mobile dropdown panel */}
      {menuOpen && (
        <div className="pai-nav-mob" style={{ position: "absolute", top: 64, left: 0, right: 0, background: "var(--bg-primary)", borderBottom: "1px solid var(--hairline)", flexDirection: "column", padding: "6px 0", zIndex: 49 }}>
          {NAV.map((n) => (
            <Link key={n.path} to={n.path} onClick={() => setMenuOpen(false)} className="t-label" style={{ display: "block", padding: "14px clamp(16px,4vw,40px)", color: isActive(n.path) ? "var(--ink-black)" : "var(--steel-light)", textDecoration: "none" }}>{n.label}</Link>
          ))}
        </div>
      )}
    </header>
  );
}
