/**
 * OAuth (social sign-in) — frontend half of a backend-mediated
 * authorization-code flow.
 *
 *   1. startOAuth(provider)  → redirect the browser to the provider's
 *      consent screen with our client_id + redirect_uri.
 *   2. provider redirects back to /auth/callback/:provider?code=...&state=...
 *   3. OAuthCallback page verifies `state`, then exchanges the `code`
 *      with our Django backend, which returns the same JWT pair as login.
 *
 * Client IDs are public and read from Vite env (VITE_*_CLIENT_ID).
 * Client secrets live ONLY on the backend. If a client ID is missing,
 * startOAuth throws so the UI can show a "not configured yet" message.
 */

export type OAuthProvider = "google" | "github" | "facebook";

interface ProviderConfig {
  clientId: string | undefined;
  authorizeUrl: string;
  scope: string;
  /** Extra params appended to the authorize URL. */
  extra?: Record<string, string>;
}

const PROVIDERS: Record<OAuthProvider, ProviderConfig> = {
  google: {
    clientId: import.meta.env.VITE_GOOGLE_CLIENT_ID,
    authorizeUrl: "https://accounts.google.com/o/oauth2/v2/auth",
    scope: "openid email profile",
    extra: { access_type: "online", prompt: "select_account" },
  },
  github: {
    clientId: import.meta.env.VITE_GITHUB_CLIENT_ID,
    authorizeUrl: "https://github.com/login/oauth/authorize",
    scope: "read:user user:email",
  },
  facebook: {
    clientId: import.meta.env.VITE_FACEBOOK_CLIENT_ID,
    authorizeUrl: "https://www.facebook.com/v19.0/dialog/oauth",
    scope: "email public_profile",
  },
};

const STATE_KEY = "oauth_state";

export function redirectUriFor(provider: OAuthProvider): string {
  return `${window.location.origin}/auth/callback/${provider}`;
}

function randomState(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Whether a provider has a configured client ID (button can be used). */
export function isOAuthConfigured(provider: OAuthProvider): boolean {
  return Boolean(PROVIDERS[provider].clientId);
}

/** Redirect the browser to the provider's consent screen. Throws if unconfigured. */
export function startOAuth(provider: OAuthProvider): void {
  const cfg = PROVIDERS[provider];
  if (!cfg.clientId) {
    throw new Error(`OAuth provider "${provider}" is not configured`);
  }
  const state = randomState();
  sessionStorage.setItem(STATE_KEY, state);
  sessionStorage.setItem(`${STATE_KEY}_provider`, provider);

  const params = new URLSearchParams({
    client_id: cfg.clientId,
    redirect_uri: redirectUriFor(provider),
    response_type: "code",
    scope: cfg.scope,
    state,
    ...(cfg.extra ?? {}),
  });
  window.location.href = `${cfg.authorizeUrl}?${params.toString()}`;
}

/** Validate the `state` returned by the provider against what we stored. */
export function consumeOAuthState(returnedState: string | null): boolean {
  const stored = sessionStorage.getItem(STATE_KEY);
  sessionStorage.removeItem(STATE_KEY);
  sessionStorage.removeItem(`${STATE_KEY}_provider`);
  return Boolean(stored) && stored === returnedState;
}
