// Authenticated fetch for the AI service (port 8001).
//
// The tutor SSE and live-session endpoints are now verified (Track 2): the
// browser presents its Django access token directly and the AI service verifies
// it locally (HS256, shared SECRET_KEY). This helper attaches the Bearer token
// and — because those calls use raw `fetch`, not the axios `api` client — it
// also handles the one thing the axios client gives us for free: refreshing the
// access token on a 401 and retrying ONCE. Without it a tutor session longer
// than the access-token lifetime would start failing mid-lecture.

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

// De-dupe concurrent refreshes: many tutor/PATCH calls can 401 at once, but we
// only want a single round-trip to /users/refresh/.
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refresh = localStorage.getItem('refresh_token');
  if (!refresh) return null;
  if (!refreshPromise) {
    refreshPromise = fetch(`${API_URL}/users/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    })
      .then(async (r) => {
        if (!r.ok) return null;
        const data = await r.json();
        if (data.access) localStorage.setItem('access_token', data.access);
        // SimpleJWT rotates the refresh token — persist the new one too.
        if (data.refresh) localStorage.setItem('refresh_token', data.refresh);
        return (data.access as string) ?? null;
      })
      .catch(() => null)
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

/**
 * fetch() against the AI service with the student's Bearer token attached and a
 * single refresh-and-retry on 401. The success path (including SSE streams) is
 * returned untouched — only a 401 error response is ever consumed for retry.
 */
export async function aiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const withAuth = (token: string | null): RequestInit => ({
    ...init,
    headers: {
      ...(init.headers as Record<string, string> | undefined),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  let res = await fetch(input, withAuth(localStorage.getItem('access_token')));
  if (res.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      res = await fetch(input, withAuth(newToken));
    }
  }
  return res;
}
