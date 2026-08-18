import styles from "./Toast.module.css";

// Non-interruptive by design (Design Decisions V2.7, Decision 5) — fixed
// position, never blocks the page, never forces navigation. "new_candidate"
// toasts auto-dismiss (handled by the caller's timer); "auth_error" toasts
// are actionable and persist until the user dismisses them or the problem
// resolves — auto-expiring an unresolved "reconnect Gmail" prompt would
// defeat the point of surfacing it at all (Decision 2).

export type ToastItem = {
  id: string;
  message: string;
  kind: "info" | "auth_error";
};

export default function Toast({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;

  return (
    <div className={styles.stack}>
      {toasts.map((t) => (
        <div key={t.id} className={`${styles.toast} ${t.kind === "auth_error" ? styles.authError : ""}`}>
          <span className={styles.message}>{t.message}</span>
          <button className={styles.dismiss} onClick={() => onDismiss(t.id)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
