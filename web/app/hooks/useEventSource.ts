"use client";

// Subscribes to the backend's SSE stream (Design Decisions V2.7, Decision
// 5: GET /events). Native EventSource handles reconnect on its own — no
// custom retry logic needed. Two event types today: "new_candidate"
// (non-interruptive toast + badge + refresh) and "auth_error" (a
// persistent "reconnect Gmail" prompt — see app/scheduler.py's Decision 2
// backoff/auth-failure handling).

import { useEffect, useRef, useState } from "react";
import { API_URL } from "@/lib/api";

export type LiveEvent =
  | { type: "new_candidate"; candidate_id: number; task: string | null; email_subject: string }
  | { type: "auth_error"; message: string };

export function useEventSource(onEvent: (event: LiveEvent) => void) {
  const onEventRef = useRef(onEvent);
  const [connected, setConnected] = useState(false);

  // Refs must not be mutated during render (React 19) — keep the latest
  // callback in an effect instead, so the connection-setup effect below
  // (which intentionally only runs once, on mount) can still call the
  // current onEvent without listing it as a dependency.
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    const source = new EventSource(`${API_URL}/events`);

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false); // EventSource auto-reconnects; this just reflects current state

    const handleNewCandidate = (e: MessageEvent) => {
      onEventRef.current({ type: "new_candidate", ...JSON.parse(e.data) });
    };
    const handleAuthError = (e: MessageEvent) => {
      onEventRef.current({ type: "auth_error", ...JSON.parse(e.data) });
    };

    source.addEventListener("new_candidate", handleNewCandidate);
    source.addEventListener("auth_error", handleAuthError);

    return () => {
      source.removeEventListener("new_candidate", handleNewCandidate);
      source.removeEventListener("auth_error", handleAuthError);
      source.close();
    };
  }, []);

  return { connected };
}
