"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
function formatNaiveUtc(isoString: string): string {
  return new Date(isoString + "Z").toLocaleString();
}

type Candidate = {
  id: number;
  status: string;
  task: string | null;
  deadline_phrase: string | null;
  resolved_due_date: string | null;
  assignee: string | null;
  confidence: number;
  reason: string;
  created_at: string;
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

type EditForm = { task: string; deadline_phrase: string; assignee: string };

async function apiCall(path: string, options?: RequestInit) {
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

export default function ReviewPage() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [scanStatus, setScanStatus] = useState<string | null>(null);
  const [extractStatus, setExtractStatus] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [extracting, setExtracting] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<EditForm>({ task: "", deadline_phrase: "", assignee: "" });
  const [busyId, setBusyId] = useState<number | null>(null);
  const [selectedSlot, setSelectedSlot] = useState<Record<number, string>>({});

  async function loadCandidates() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiCall("/candidates");
      setCandidates(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load candidates");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadCandidates();
  }, []);

  async function handleScan() {
    setScanning(true);
    setScanStatus(null);
    try {
      const result = await apiCall("/scan", { method: "POST" });
      setScanStatus(`Fetched ${result.fetched}, ${result.new} new (${result.skipped} already stored)`);
    } catch (e) {
      setScanStatus(e instanceof Error ? `Error: ${e.message}` : "Scan failed");
    } finally {
      setScanning(false);
    }
  }

  async function handleExtract() {
    setExtracting(true);
    setExtractStatus(null);
    try {
      const result = await apiCall("/extract", { method: "POST" });
      setExtractStatus(
        `Processed ${result.processed}, ${result.candidates_created} candidate(s) created ` +
          `(${result.not_actionable} not actionable, ${result.failed} failed)`
      );
      await loadCandidates();
    } catch (e) {
      setExtractStatus(e instanceof Error ? `Error: ${e.message}` : "Extraction failed");
    } finally {
      setExtracting(false);
    }
  }

  function startEdit(candidate: Candidate) {
    setEditingId(candidate.id);
    setEditForm({
      task: candidate.task || "",
      deadline_phrase: candidate.deadline_phrase || "",
      assignee: candidate.assignee || "",
    });
  }

  function cancelEdit() {
    setEditingId(null);
  }

  async function saveEdit(id: number) {
    setBusyId(id);
    try {
      await apiCall(`/candidates/${id}`, {
        method: "PATCH",
        body: JSON.stringify(editForm),
      });
      setEditingId(null);
      await loadCandidates();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save edit");
    } finally {
      setBusyId(null);
    }
  }

  async function approve(id: number) {
    setBusyId(id);
    try {
      await apiCall(`/candidates/${id}/approve`, { method: "POST" });
      await loadCandidates();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to approve candidate");
    } finally {
      setBusyId(null);
    }
  }

  async function dismiss(id: number) {
    setBusyId(id);
    try {
      await apiCall(`/candidates/${id}/dismiss`, { method: "POST" });
      await loadCandidates();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to dismiss candidate");
    } finally {
      setBusyId(null);
    }
  }

  // Separate, explicit action from Approve — booking a calendar event is a
  // distinct commitment from creating a task (V2.6 Decision 5). Never
  // triggered automatically or bundled into approve().
  async function bookCalendar(id: number, slot: string) {
    setBusyId(id);
    try {
      await apiCall(`/candidates/${id}/book-calendar`, {
        method: "POST",
        body: JSON.stringify({ slot }),
      });
      await loadCandidates();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add to calendar");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "32px 16px" }}>
      <h1 style={{ fontSize: 22, marginBottom: 4 }}>Inbox-to-Action</h1>
      <p className="muted" style={{ marginBottom: 24 }}>
        Review task candidates before they go to Notion. Nothing is written to Notion here.
      </p>

      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: 24,
          paddingBottom: 20,
          borderBottom: "1px solid var(--border)",
        }}
      >
        <button onClick={handleScan} disabled={scanning}>
          {scanning ? "Scanning…" : "Scan Gmail"}
        </button>
        <button onClick={handleExtract} disabled={extracting}>
          {extracting ? "Extracting…" : "Extract Tasks"}
        </button>
        <button onClick={loadCandidates} disabled={loading}>
          Refresh
        </button>
      </div>

      {(scanStatus || extractStatus) && (
        <div className="muted" style={{ fontSize: 13, marginBottom: 20 }}>
          {scanStatus && <div>Scan: {scanStatus}</div>}
          {extractStatus && <div>Extract: {extractStatus}</div>}
        </div>
      )}

      {loading && <p className="muted">Loading…</p>}

      {error && (
        <p style={{ color: "var(--danger)", marginBottom: 16 }}>
          {error}
        </p>
      )}

      {!loading && !error && candidates.length === 0 && (
        <p className="muted">No candidates need review right now.</p>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {candidates.map((c) => {
          const isEditing = editingId === c.id;
          const isBusy = busyId === c.id;

          return (
            <div
              key={c.id}
              style={{
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: 16,
                background: "var(--card-bg)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  marginBottom: 8,
                  fontSize: 13,
                }}
              >
                <span className="muted">
                  {c.email.from_address} — {c.email.subject}
                </span>
                <a href={c.email.gmail_link} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
                  View email ↗
                </a>
              </div>

              {isEditing ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <textarea
                    value={editForm.task}
                    onChange={(e) => setEditForm({ ...editForm, task: e.target.value })}
                    rows={2}
                    placeholder="Task"
                  />
                  <input
                    value={editForm.deadline_phrase}
                    onChange={(e) => setEditForm({ ...editForm, deadline_phrase: e.target.value })}
                    placeholder="Deadline (e.g. Friday, Sept 1st)"
                  />
                  <input
                    value={editForm.assignee}
                    onChange={(e) => setEditForm({ ...editForm, assignee: e.target.value })}
                    placeholder="Assignee (optional)"
                  />
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="primary" onClick={() => saveEdit(c.id)} disabled={isBusy}>
                      {isBusy ? "Saving…" : "Save"}
                    </button>
                    <button onClick={cancelEdit} disabled={isBusy}>
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <p style={{ marginBottom: 8 }}>{c.task}</p>
                  <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
                    {c.deadline_phrase && (
                      <span>
                        Due: {c.deadline_phrase}
                        {c.resolved_due_date ? ` (${c.resolved_due_date})` : " (not resolved)"}
                        {" · "}
                      </span>
                    )}
                    {c.assignee && <span>Assignee: {c.assignee} · </span>}
                    Confidence: {Math.round(c.confidence * 100)}%
                    {c.status === "edited" && " · edited"}
                  </div>
                  <p className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
                    {c.reason}
                  </p>

                  {/* V2.6 Scheduling Agent — informational only. Booking is
                      always a separate click below, never part of Approve. */}
                  {c.proposed_meeting_phrase && (
                    <div
                      className="muted"
                      style={{
                        fontSize: 13,
                        marginBottom: 12,
                        padding: 8,
                        border: "1px solid var(--border)",
                        borderRadius: 6,
                      }}
                    >
                      <div>
                        {c.scheduling_source === "deadline" ? "Deadline commitment: " : "Proposed meeting: "}
                        {c.proposed_meeting_phrase}
                        {c.resolved_meeting_time
                          ? ` (${formatNaiveUtc(c.resolved_meeting_time)})`
                          : " (not resolved)"}
                      </div>
                      {c.calendar_status === "unavailable" && (
                        <div>Calendar not connected — grant calendar access to see availability.</div>
                      )}
                      {c.calendar_status === "free" && <div>This time is free on your calendar.</div>}
                      {c.calendar_status === "conflict" && (
                        <div style={{ marginTop: 4 }}>
                          {c.scheduling_source === "deadline"
                            ? "You have something else on around this deadline."
                            : "Conflict at the proposed time."}
                          {c.suggested_meeting_slots && c.suggested_meeting_slots.length > 0 ? (
                            <>
                              {" "}
                              {c.scheduling_source === "deadline" ? "Free time nearby:" : "Alternatives:"}{" "}
                              <select
                                value={selectedSlot[c.id] || c.suggested_meeting_slots[0]}
                                onChange={(e) =>
                                  setSelectedSlot({ ...selectedSlot, [c.id]: e.target.value })
                                }
                              >
                                {c.suggested_meeting_slots.map((slot) => (
                                  <option key={slot} value={slot}>
                                    {new Date(slot).toLocaleString()}
                                  </option>
                                ))}
                              </select>
                            </>
                          ) : (
                            " No free alternatives found this week."
                          )}
                        </div>
                      )}
                      {c.calendar_booked ? (
                        <div style={{ marginTop: 4 }}>Added to calendar.</div>
                      ) : (
                        (c.calendar_status === "free" || c.calendar_status === "conflict") && (
                          <button
                            style={{ marginTop: 8 }}
                            disabled={
                              isBusy ||
                              (c.calendar_status === "conflict" &&
                                (!c.suggested_meeting_slots || c.suggested_meeting_slots.length === 0))
                            }
                            onClick={() => {
                              const slot =
                                c.calendar_status === "conflict"
                                  ? selectedSlot[c.id] || (c.suggested_meeting_slots || [])[0]
                                  : c.resolved_meeting_time;
                              if (slot) bookCalendar(c.id, slot);
                            }}
                          >
                            {isBusy ? "…" : "Also add to calendar"}
                          </button>
                        )
                      )}
                    </div>
                  )}

                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="primary" onClick={() => approve(c.id)} disabled={isBusy}>
                      {isBusy ? "…" : "Approve"}
                    </button>
                    <button onClick={() => startEdit(c)} disabled={isBusy}>
                      Edit
                    </button>
                    <button className="danger" onClick={() => dismiss(c.id)} disabled={isBusy}>
                      Dismiss
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </div>
    </main>
  );
}
