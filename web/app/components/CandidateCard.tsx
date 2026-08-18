import type { Candidate, EditForm } from "@/lib/api";
import { formatNaiveUtc } from "@/lib/api";
import { isFlagged } from "@/lib/candidateStatus";
import StatusBadge from "./StatusBadge";
import styles from "./CandidateCard.module.css";

// Card-based candidate — task/deadline/sender/status/actions inline, no
// click-through (Design Decisions V2.7, Decision 6). Preserves, unchanged
// in behavior, the two safety-relevant controls Decision 7 names for this
// component: the separate "Also add to calendar" action (item 2) and a
// visually distinct treatment for flagged candidates (item 3). There is
// no "undo" control to preserve here — it doesn't exist anywhere in this
// codebase yet (AUTO_ACT_ENABLED is False, V2.3's own docstring calls the
// undo mechanism "deliberately deferred").

type Props = {
  candidate: Candidate;
  isSelected: boolean;
  isEditing: boolean;
  isBusy: boolean;
  editForm: EditForm;
  selectedSlot: string | undefined;
  onSelect: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onEditFormChange: (form: EditForm) => void;
  onSaveEdit: () => void;
  onApprove: () => void;
  onDismiss: () => void;
  onBookCalendar: (slot: string) => void;
  onSelectSlot: (slot: string) => void;
};

export default function CandidateCard({
  candidate: c,
  isSelected,
  isEditing,
  isBusy,
  editForm,
  selectedSlot,
  onSelect,
  onStartEdit,
  onCancelEdit,
  onEditFormChange,
  onSaveEdit,
  onApprove,
  onDismiss,
  onBookCalendar,
  onSelectSlot,
}: Props) {
  const cardClassName = [styles.card, isSelected && styles.selected, isFlagged(c) && styles.flagged]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cardClassName} onClick={onSelect}>
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <StatusBadge candidate={c} />
          <span className={styles.sender}>
            {c.email.from_address} — {c.email.subject}
          </span>
        </div>
        <a
          href={c.email.gmail_link}
          target="_blank"
          rel="noopener noreferrer"
          className={styles.gmailLink}
          onClick={(e) => e.stopPropagation()}
        >
          View email ↗
        </a>
      </div>

      {isEditing ? (
        <div className={styles.editForm} onClick={(e) => e.stopPropagation()}>
          <textarea
            value={editForm.task}
            onChange={(e) => onEditFormChange({ ...editForm, task: e.target.value })}
            rows={2}
            placeholder="Task"
          />
          <input
            value={editForm.deadline_phrase}
            onChange={(e) => onEditFormChange({ ...editForm, deadline_phrase: e.target.value })}
            placeholder="Deadline (e.g. Friday, Sept 1st)"
          />
          <input
            value={editForm.assignee}
            onChange={(e) => onEditFormChange({ ...editForm, assignee: e.target.value })}
            placeholder="Assignee (optional)"
          />
          <div className={styles.editButtons}>
            <button className="primary" onClick={onSaveEdit} disabled={isBusy}>
              {isBusy ? "Saving…" : "Save"}
            </button>
            <button onClick={onCancelEdit} disabled={isBusy}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className={styles.task}>{c.task}</p>
          <div className={styles.meta}>
            {c.deadline_phrase && (
              <span>
                Due: {c.deadline_phrase}
                {c.resolved_due_date ? ` (${c.resolved_due_date})` : " (not resolved)"}
              </span>
            )}
            {c.assignee && <span>Assignee: {c.assignee}</span>}
            <span>Confidence: {Math.round(c.confidence * 100)}%</span>
          </div>
          <p className={styles.reason}>{c.reason}</p>

          {/* V2.6 Scheduling Agent — informational only. Booking is
              always a separate click below, never part of Approve. */}
          {c.proposed_meeting_phrase && (
            <div className={styles.schedulingBox}>
              <div>
                {c.scheduling_source === "deadline" ? "Deadline commitment: " : "Proposed meeting: "}
                {c.proposed_meeting_phrase}
                {c.resolved_meeting_time
                  ? ` (${formatNaiveUtc(c.resolved_meeting_time)})`
                  : " (not resolved)"}
              </div>
              {c.calendar_status === "unavailable" && (
                <div className={styles.schedulingNote}>
                  Calendar not connected — grant calendar access to see availability.
                </div>
              )}
              {c.calendar_status === "free" && (
                <div className={styles.schedulingNote}>This time is free on your calendar.</div>
              )}
              {c.calendar_status === "conflict" && (
                <div className={styles.schedulingNote}>
                  {c.scheduling_source === "deadline"
                    ? "You have something else on around this deadline."
                    : "Conflict at the proposed time."}
                  {c.suggested_meeting_slots && c.suggested_meeting_slots.length > 0 ? (
                    <>
                      {" "}
                      {c.scheduling_source === "deadline" ? "Free time nearby:" : "Alternatives:"}{" "}
                      <select
                        value={selectedSlot || c.suggested_meeting_slots[0]}
                        onChange={(e) => onSelectSlot(e.target.value)}
                        onClick={(e) => e.stopPropagation()}
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
                <div className={styles.schedulingNote}>Added to calendar.</div>
              ) : (
                (c.calendar_status === "free" || c.calendar_status === "conflict") && (
                  <div className={styles.calendarAction}>
                    <button
                      disabled={
                        isBusy ||
                        (c.calendar_status === "conflict" &&
                          (!c.suggested_meeting_slots || c.suggested_meeting_slots.length === 0))
                      }
                      onClick={(e) => {
                        e.stopPropagation();
                        const slot =
                          c.calendar_status === "conflict"
                            ? selectedSlot || (c.suggested_meeting_slots || [])[0]
                            : c.resolved_meeting_time;
                        if (slot) onBookCalendar(slot);
                      }}
                    >
                      {isBusy ? "…" : "Also add to calendar"}
                    </button>
                  </div>
                )
              )}
            </div>
          )}

          <div className={styles.actions}>
            <button
              className="primary"
              onClick={(e) => {
                e.stopPropagation();
                onApprove();
              }}
              disabled={isBusy}
            >
              {isBusy ? "…" : "Approve"}
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onStartEdit();
              }}
              disabled={isBusy}
            >
              Edit
            </button>
            <button
              className="danger"
              onClick={(e) => {
                e.stopPropagation();
                onDismiss();
              }}
              disabled={isBusy}
            >
              Dismiss
            </button>
          </div>
        </>
      )}
    </div>
  );
}
