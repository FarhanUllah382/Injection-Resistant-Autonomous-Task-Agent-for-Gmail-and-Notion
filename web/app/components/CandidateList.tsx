import type { Candidate, EditForm } from "@/lib/api";
import CandidateCard from "./CandidateCard";
import EmptyState from "./EmptyState";
import styles from "./CandidateList.module.css";

type Props = {
  candidates: Candidate[];
  loading: boolean;
  selectedId: number | null;
  editingId: number | null;
  busyId: number | null;
  editForm: EditForm;
  selectedSlot: Record<number, string>;
  onSelect: (id: number) => void;
  onStartEdit: (candidate: Candidate) => void;
  onCancelEdit: () => void;
  onEditFormChange: (form: EditForm) => void;
  onSaveEdit: (id: number) => void;
  onApprove: (id: number) => void;
  onDismiss: (id: number) => void;
  onBookCalendar: (id: number, slot: string) => void;
  onSelectSlot: (id: number, slot: string) => void;
};

export default function CandidateList({
  candidates,
  loading,
  selectedId,
  editingId,
  busyId,
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
  if (loading) {
    return <p className={styles.loading}>Loading…</p>;
  }

  if (candidates.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className={styles.list}>
      {candidates.map((c) => (
        <CandidateCard
          key={c.id}
          candidate={c}
          isSelected={selectedId === c.id}
          isEditing={editingId === c.id}
          isBusy={busyId === c.id}
          editForm={editForm}
          selectedSlot={selectedSlot[c.id]}
          onSelect={() => onSelect(c.id)}
          onStartEdit={() => onStartEdit(c)}
          onCancelEdit={onCancelEdit}
          onEditFormChange={onEditFormChange}
          onSaveEdit={() => onSaveEdit(c.id)}
          onApprove={() => onApprove(c.id)}
          onDismiss={() => onDismiss(c.id)}
          onBookCalendar={(slot) => onBookCalendar(c.id, slot)}
          onSelectSlot={(slot) => onSelectSlot(c.id, slot)}
        />
      ))}
    </div>
  );
}
