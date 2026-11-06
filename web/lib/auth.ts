// Access-token storage for the single-owner backend (app/auth.py).
//
// sessionStorage, not localStorage: the token should not persist past the
// browser tab closing, and must never be hard-coded into the bundle. The
// user pastes it once per session via the login screen (see
// app/components/LoginScreen.tsx).

const STORAGE_KEY = "inbox-to-action-access-token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(STORAGE_KEY);
}

export function setToken(token: string): void {
  window.sessionStorage.setItem(STORAGE_KEY, token);
}

export function clearToken(): void {
  window.sessionStorage.removeItem(STORAGE_KEY);
}
