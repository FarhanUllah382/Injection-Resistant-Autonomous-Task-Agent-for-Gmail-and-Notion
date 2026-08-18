import type { Candidate } from "@/lib/api";
import styles from "./DashboardSummary.module.css";

// Design Decisions V2.7, Decision 6 — "at-a-glance sense of backlog
// without opening anything." Counts are derived from the same
// GET /candidates payload the review queue already fetches (default
// query: pending + edited candidates above the confidence threshold —
// see app/routes_candidates.py), not a separate historical query, so
// "new today" reflects today's arrivals still awaiting review, not every
// candidate ever created today.
function isToday(isoDate: string): boolean {
  const d = new Date(isoDate);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

export default function DashboardSummary({ candidates }: { candidates: Candidate[] }) {
  const newToday = candidates.filter((c) => isToday(c.created_at)).length;
  const pendingReview = candidates.filter((c) => c.status === "pending" || c.status === "edited").length;
  // Shadow mode only (V2.3) — informational, nothing auto-acts on this yet.
  const autoEligible = candidates.filter(
    (c) => c.policy_decision === "auto_eligible" && c.status === "pending"
  ).length;
  const meetingsToConfirm = candidates.filter(
    (c) =>
      (c.calendar_status === "free" || c.calendar_status === "conflict") && !c.calendar_booked
  ).length;

  const stats: { label: string; count: number }[] = [
    { label: "New today", count: newToday },
    { label: "Pending review", count: pendingReview },
    { label: "Auto-eligible (awaiting your click)", count: autoEligible },
    { label: "Meetings to confirm", count: meetingsToConfirm },
  ];

  return (
    <div className={styles.strip}>
      {stats.map((s) => (
        <div key={s.label} className={styles.stat}>
          <span className={styles.count}>{s.count}</span>
          <span className={styles.label}>{s.label}</span>
        </div>
      ))}
    </div>
  );
}
