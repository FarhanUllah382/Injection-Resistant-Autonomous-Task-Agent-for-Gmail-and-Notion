"use client";

// Review-flow keyboard shortcuts (Design Decisions V2.7, Decision 6):
// j/k move the selected candidate, a=approve, d=dismiss, e=edit. Must not
// fire while the user is typing — checked via document.activeElement,
// which already covers the edit form's inputs/textarea (no separate
// "is editing" flag needed).

import { useEffect } from "react";

type Handlers = {
  candidateIds: number[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onApprove: (id: number) => void;
  onDismiss: (id: number) => void;
  onEdit: (id: number) => void;
  enabled: boolean;
};

function isTypingTarget(el: Element | null): boolean {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (el as HTMLElement).isContentEditable;
}

export function useKeyboardShortcuts({
  candidateIds,
  selectedId,
  onSelect,
  onApprove,
  onDismiss,
  onEdit,
  enabled,
}: Handlers) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (!enabled) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (isTypingTarget(document.activeElement)) return;
      if (candidateIds.length === 0) return;

      const currentIndex = selectedId !== null ? candidateIds.indexOf(selectedId) : -1;

      switch (e.key) {
        case "j": {
          e.preventDefault();
          const next = candidateIds[Math.min(currentIndex + 1, candidateIds.length - 1)] ?? candidateIds[0];
          onSelect(next);
          break;
        }
        case "k": {
          e.preventDefault();
          const prev = candidateIds[Math.max(currentIndex - 1, 0)] ?? candidateIds[0];
          onSelect(prev);
          break;
        }
        case "a":
          if (selectedId !== null) {
            e.preventDefault();
            onApprove(selectedId);
          }
          break;
        case "d":
          if (selectedId !== null) {
            e.preventDefault();
            onDismiss(selectedId);
          }
          break;
        case "e":
          if (selectedId !== null) {
            e.preventDefault();
            onEdit(selectedId);
          }
          break;
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [candidateIds, selectedId, onSelect, onApprove, onDismiss, onEdit, enabled]);
}
