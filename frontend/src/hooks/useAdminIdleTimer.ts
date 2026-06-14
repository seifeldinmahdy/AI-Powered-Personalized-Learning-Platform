import { useEffect, useRef, useCallback } from "react";
import { useAuth } from "../contexts/AuthContext";

/**
 * Auto-logout hook for admin sessions.
 *
 * Monitors user activity (mouse, keyboard, pointer, scroll) and calls
 * `logout()` after `timeoutMs` milliseconds of inactivity.
 *
 * Default timeout: 20 minutes.
 *
 * Usage:
 *   Place `useAdminIdleTimer()` inside the AdminLayout component so it
 *   runs for every admin page.
 */
export function useAdminIdleTimer(timeoutMs = 20 * 60 * 1000) {
  const { logout } = useAuth();
  const timer = useRef<ReturnType<typeof setTimeout>>();

  const reset = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      logout();
    }, timeoutMs);
  }, [logout, timeoutMs]);

  useEffect(() => {
    const events = ["mousemove", "keydown", "pointerdown", "scroll"] as const;
    events.forEach((e) =>
      window.addEventListener(e, reset, { passive: true })
    );
    reset(); // start the timer immediately

    return () => {
      clearTimeout(timer.current);
      events.forEach((e) => window.removeEventListener(e, reset));
    };
  }, [reset]);
}
