"""
Manual-only correction-note curation CLI (Design Decisions V2.5, Decision 3).

Run on demand by a human. This is the only place a correction note can
become active — there is no scheduler, cron, or background worker anywhere
in this project, and this script does not add one. Nothing here runs
unless a human explicitly invokes it.

Usage:
    python scripts/propose_correction_notes.py propose
        Reviews recent edited/dismissed candidates and prints candidate
        notes for a human to read. Writes nothing to the database.

    python scripts/propose_correction_notes.py approve --text "..." --source-decisions 1,4
        Explicit approval of one note, with the exact wording the human
        wants active (may differ from a proposal's wording — this is the
        "edit" path from Decision 3, same command as "accept" when the
        text is passed through unchanged). The only command that ever
        writes an active row.

    python scripts/propose_correction_notes.py list
        Shows all correction notes and their active/inactive status.

    python scripts/propose_correction_notes.py deactivate --id 3
        Explicit, manual deactivation. Never happens automatically.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session, select

from app.config import DATABASE_URL
from app.correction_note_proposals import get_recent_correction_decisions, propose_notes
from app.correction_notes import deactivate_note, insert_active_note
from app.models import CorrectionNote
from sqlmodel import create_engine

engine = create_engine(DATABASE_URL)


def cmd_propose(args):
    with Session(engine) as session:
        decisions = get_recent_correction_decisions(session)
        if not decisions:
            print("No edited/dismissed candidates found — nothing to review yet.")
            return
        proposals, excluded = propose_notes(session, decisions)

    print(f"Reviewed {len(decisions)} edited/dismissed decision(s).")
    if not proposals and not excluded:
        print("No stable, generalizable, safe-to-propose pattern found. "
              "Nothing was proposed — this is a correct outcome when the evidence doesn't support a rule.")
        return

    if proposals:
        print(f"{len(proposals)} candidate note(s) proposed — nothing has been written to the database.\n")
        for i, p in enumerate(proposals, 1):
            print(f"[{i}] rule_text: {p.rule_text!r}")
            print(f"    source_decision_ids: {p.source_decision_ids}")
            print(f"    reasoning: {p.reasoning}")
            print()
        print("To approve one, run:")
        print('  python scripts/propose_correction_notes.py approve --text "<rule text>" '
              '--source-decisions <comma-separated ids>')
    else:
        print("No candidate notes proposed from the reviewed cases.")

    if excluded:
        print(f"\n{len(excluded)} case(s) explicitly excluded (not proposed as notes):")
        for e in excluded:
            print(f"  decision_id={e.decision_id}: {e.reason}")


def cmd_approve(args):
    source_ids = [int(x) for x in args.source_decisions.split(",") if x.strip()]
    with Session(engine) as session:
        note = insert_active_note(session, rule_text=args.text, source_decision_ids=source_ids)
    print(f"Approved and activated note id={note.id}: {note.rule_text!r}")


def cmd_list(args):
    with Session(engine) as session:
        notes = session.exec(select(CorrectionNote).order_by(CorrectionNote.approved_at.desc())).all()
    if not notes:
        print("No correction notes exist yet.")
        return
    for n in notes:
        print(f"[id={n.id}] active={n.active} approved_at={n.approved_at} "
              f"source_decisions={n.source_decision_ids}")
        print(f"    {n.rule_text!r}")


def cmd_deactivate(args):
    with Session(engine) as session:
        note = deactivate_note(session, args.id)
    if note is None:
        print(f"No note with id={args.id}")
    else:
        print(f"Deactivated note id={note.id}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("propose", help="Review recent corrections, print candidate notes")

    approve_parser = subparsers.add_parser("approve", help="Explicitly approve one note")
    approve_parser.add_argument("--text", required=True)
    approve_parser.add_argument("--source-decisions", required=True)

    subparsers.add_parser("list", help="List all correction notes")

    deactivate_parser = subparsers.add_parser("deactivate", help="Deactivate a note")
    deactivate_parser.add_argument("--id", type=int, required=True)

    args = parser.parse_args()
    {
        "propose": cmd_propose,
        "approve": cmd_approve,
        "list": cmd_list,
        "deactivate": cmd_deactivate,
    }[args.command](args)


if __name__ == "__main__":
    main()
