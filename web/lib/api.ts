// Shared API types and fetch helper, moved out of app/page.tsx (V2.7 —
// Design Decisions V2.7, Decision 8) so page.tsx can shrink to
// orchestration and the new components under app/components/ can import
// these without a circular dependency on the page itself.

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// resolved_meeting_time comes back from the API as a naive ISO string
// (no offset) whose underlying instant is UTC — Postgres TIMESTAMP
// WITHOUT TIME ZONE strips tzinfo on storage, but every value written
// there was converted to UTC first (see app/routes_scheduling.py). A bare
// `new Date("2026-08-21T12:00:00")` would parse that as *browser-local*
// time instead, silently shifting the displayed hour by the browser's
// UTC offset — this was the exact bug behind the "11 AM" deadline
// displaying as "6:00 AM". Appending "Z" tells JS it's UTC, after which
// toLocaleString() correctly converts to the viewer's local time for
// display, same as suggested_meeting_slots below (which already carry a
// real offset and don't need this).
export function formatNaiveUtc(isoString: string): string {
  return new Date(isoString + "Z").toLocaleString();
}

export type Candidate = {
  id: number;
  status: string;
  task: string | null;
  deadline_phrase: string | null;
  resolved_due_date: string | null;
  assignee: string | null;
  confidence: number;
  reason: string;
  created_at: string;
  // Shadow-mode only (V2.3) — informational, nothing acts on this yet.
  policy_decision: "auto_eligible" | "review_required" | null;
  // V2.7 — the raw V2.4 signals behind policy_decision, so the UI can show
  // a distinct "flagged" badge for injection/spoofing specifically,
  // instead of lumping it in with every other review_required candidate.
  injection_suspected: boolean | null;
  sender_trust_signal: "known" | "unknown_domain" | "suspicious" | null;
  // V2.6 Scheduling Agent — read-only info; booking is its own separate
  // action (POST /candidates/{id}/book-calendar), never part of Approve.
  proposed_meeting_phrase: string | null;
  resolved_meeting_time: string | null;
  calendar_status: "free" | "conflict" | "unavailable" | null;
  suggested_meeting_slots: string[] | null;
  // V2.6 scheduling correction: which source resolved_meeting_time came
  // from — an explicit meeting proposal, or a time-bearing deadline when
  // no meeting was proposed. Meeting stays primary when both exist.
  scheduling_source: "meeting" | "deadline" | null;
  calendar_booked: boolean;
  email: {
    subject: string;
    from_address: string;
    received_at: string;
    gmail_link: string;
  };
};

export type EditForm = { task: string; deadline_phrase: string; assignee: string };

export async function apiCall(path: string, options?: RequestInit) {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}
