"use client";

// Gate in front of the review UI (security hardening). The backend
// rejects every protected route without a valid bearer token
// (app/auth.py) — this screen collects that token once per browser tab
// (sessionStorage, never hard-coded) and verifies it with a real,
// side-effect-free API call before letting the rest of the app render.

import { useState } from "react";
import { AuthError, apiCall } from "@/lib/api";
import { setToken } from "@/lib/auth";
import styles from "./LoginScreen.module.css";

export default function LoginScreen({ onSuccess }: { onSuccess: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const token = value.trim();
    if (!token) return;

    setChecking(true);
    setError(null);
    setToken(token);
    try {
      // GET /candidates is a safe, read-only call — used purely to confirm
      // the token the backend has is the one just entered.
      await apiCall("/candidates");
      onSuccess();
    } catch (e) {
      setError(e instanceof AuthError ? "Invalid access token" : "Could not reach the API");
    } finally {
      setChecking(false);
    }
  }

  return (
    <main className={styles.main}>
      <form className={styles.form} onSubmit={handleSubmit}>
        <h1 className={styles.title}>Inbox-to-Action</h1>
        <p className={styles.hint}>
          Enter the API access token to continue. Stored only for this browser tab.
        </p>
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Access token"
          autoFocus
        />
        <button className="primary" type="submit" disabled={checking || !value.trim()}>
          {checking ? "Checking…" : "Continue"}
        </button>
        {error && <p className={styles.error}>{error}</p>}
      </form>
    </main>
  );
}
