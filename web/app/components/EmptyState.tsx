import styles from "./EmptyState.module.css";

// Designed, not default (Design Decisions V2.7, Decision 6) — an empty
// review queue should read as "you're caught up," not a blank page.
export default function EmptyState() {
  return (
    <div className={styles.wrap}>
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M20 6 9 17l-5-5" />
      </svg>
      <p className={styles.title}>You&apos;re caught up</p>
      <p>No candidates need review right now — new ones will appear here automatically.</p>
    </div>
  );
}
