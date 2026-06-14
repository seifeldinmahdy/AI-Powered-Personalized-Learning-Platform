import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { useAuth } from "../../contexts/AuthContext";
import { consumeOAuthState, redirectUriFor, type OAuthProvider } from "../../services/oauth";

/**
 * Landing route for provider redirects: /auth/callback/:provider?code=&state=
 * Verifies `state`, exchanges the code for our JWT via the backend, then
 * routes the user onward (honoring any pre-login `from` destination).
 */
export default function OAuthCallback() {
  const { provider } = useParams<{ provider: string }>();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { oauthLogin } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return; // guard against double-invoke in StrictMode
    ran.current = true;

    const code = params.get("code");
    const returnedState = params.get("state");
    const providerError = params.get("error_description") || params.get("error");

    async function run() {
      if (providerError) {
        setError(providerError);
        return;
      }
      if (!provider || !code) {
        setError("Missing authorization code from provider.");
        return;
      }
      if (!consumeOAuthState(returnedState)) {
        setError("Security check failed (state mismatch). Please try signing in again.");
        return;
      }
      try {
        const data = await oauthLogin(provider, code, redirectUriFor(provider as OAuthProvider));
        const returnTo = sessionStorage.getItem("oauth_return_to");
        sessionStorage.removeItem("oauth_return_to");
        navigate(returnTo || (data.role === "admin" ? "/admin" : "/dashboard"), { replace: true });
      } catch (err: unknown) {
        let msg = "Sign-in failed. Please try again.";
        if (err && typeof err === "object" && "response" in err) {
          const axiosErr = err as { response?: { data?: { error?: string } } };
          msg = axiosErr.response?.data?.error || msg;
        }
        setError(msg);
      }
    }
    run();
  }, [provider, params, oauthLogin, navigate]);

  return (
    <div
      className="codex"
      style={{ minHeight: "100vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 24, background: "var(--bg-primary)", padding: 24, textAlign: "center" }}
    >
      <div style={{ fontFamily: "var(--ff-display)", fontWeight: 700, fontSize: 28, letterSpacing: "-0.02em", color: "#1A1611" }}>
        Personif<span style={{ color: "#2563EB" }}>AI</span><span style={{ color: "#2563EB" }}>.</span>
      </div>

      {error ? (
        <>
          <div style={{ fontFamily: "var(--ff-mono)", fontSize: 13, color: "var(--error-red)", borderLeft: "2px solid var(--error-red)", paddingLeft: 14, maxWidth: 420, textAlign: "left", lineHeight: 1.6 }}>
            {error}
          </div>
          <button
            type="button"
            onClick={() => navigate("/login", { replace: true })}
            className="btn btn-primary"
          >
            BACK TO LOGIN →
          </button>
        </>
      ) : (
        <div className="t-label" style={{ color: "var(--accent-primary)", display: "flex", alignItems: "center", gap: 10 }}>
          <span className="dot-green" style={{ width: 8, height: 8 }} />
          COMPLETING SIGN-IN…
        </div>
      )}
    </div>
  );
}
