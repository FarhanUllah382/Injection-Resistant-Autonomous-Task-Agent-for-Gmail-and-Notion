# Inbox-to-Action — Product Specification

## 1. Core Problem

Knowledge workers don't lack task managers. They lack the bridge between where work arrives (email, Slack, docs) and where work is tracked.

For the MVP, we focus on Gmail.

Example:

A client emails:
"Can you also update the pricing page by Friday?"

The action is buried inside the email. The user may forget it or manually copy it into their task manager.

Inbox-to-Action solves this by:

Gmail → find things I need to do → show them to me → I approve → put them into Notion.

The product is not a task manager. Gmail and Notion remain the existing tools. Inbox-to-Action is the intelligence layer between them.

## 2. Initial Users

The first target users are:

- Freelancers/consultants juggling multiple clients over email
- Founders/small team leads
- Small agencies/account managers

The MVP should start narrow rather than attempting to serve everyone.

## 3. MVP User Flow

1. User connects Gmail using OAuth.
2. The application reads Gmail emails using read-only access.
3. New/relevant emails are fetched.
4. Email content is preprocessed:
   - remove HTML
   - remove signatures
   - remove unnecessary quoted replies
5. Claude analyzes the cleaned email.
6. Claude determines whether the email contains an actionable task for the logged-in user.
7. If actionable, Claude extracts:
   - task
   - deadline phrase
   - assignee/context when appropriate
   - reason
   - confidence
8. The application stores the result as a task candidate.
9. The candidate is shown to the user.
10. The user can:
   - approve
   - edit
   - dismiss
11. Only after explicit approval does the application create the task in Notion.
12. The application stores the resulting Notion page ID.
13. The task should retain a link back to the original Gmail message/thread.

The critical safety rule is:

Nothing is written to Notion without explicit human approval.

## 4. Core MVP Architecture

Gmail
→ fetch emails
→ preprocess
→ Claude extraction
→ task candidate
→ PostgreSQL
→ review UI
→ user approval/edit/dismiss
→ Notion

The MVP should use one FastAPI application/process.

The pipeline is a sequence of Python modules/functions, not separate services.

## 5. AI Responsibility

Claude is the language-understanding component.

Claude should determine whether an email contains an actionable request and extract the relevant information.

Claude should NOT:

- create Notion tasks directly
- generate Gmail URLs
- invent deadlines
- invent people's identities
- make irreversible changes
- bypass human approval

The application owns business logic and deterministic operations.

## 6. Actionability

Not every email contains a task.

Example of actionable:

"Can you send the revised proposal by Friday?"

Example of non-actionable:

"Thanks for sending the proposal."

The extraction should be conservative.

Precision is more important than recall for V1.

Missing a task is preferable to repeatedly showing users false-positive tasks.

## 7. Deadline Handling

Claude extracts the natural-language deadline phrase.

Example:

"Please finish this by Friday."

Claude may return:

"Friday"

The application, not Claude, is responsible for resolving relative dates into a calendar date using:

- the email timestamp
- the user's timezone

Do not build a complex date system for V1.

The task candidate should distinguish between:

- deadline_phrase — what Claude extracted, e.g. "Friday"
- resolved_due_date — the application-resolved calendar date, if safely resolvable

Claude must never invent a deadline that is not supported by the email.

## 8. Email Thread Handling

The system should distinguish between:

- a new request
- a follow-up to an existing request
- an action that has already been completed
- ordinary information/discussion

For V1, do not build a sophisticated conversation-state engine.

Use the latest email plus enough recent thread context to avoid obvious mistakes.

## 9. Human Review and Learning

A task candidate is an AI suggestion, not yet a real task.

Example:

Claude thinks:
"Update pricing page — Friday"

The candidate is shown to the user.

The user decides:

Approve → create Notion task
Edit → modify the candidate, then create the approved version
Dismiss → do not create a Notion task

The system should separately record the AI candidate and the user's decision.

This allows future evaluation/model improvement.

## 10. Source Context

Every candidate must retain the Gmail message ID and thread ID associated with the source email.

The backend/application generates the Gmail link from these identifiers.

Claude must never generate or invent Gmail URLs.

## 11. MVP Scope

Build only:

- Gmail
- Claude extraction
- PostgreSQL
- FastAPI
- minimal Next.js review UI
- Notion integration

Do not build yet:

- Slack
- Google Docs
- Teams
- meetings
- multi-agent architecture
- RAG
- vector databases
- semantic deduplication
- fine-tuned models
- team collaboration
- AI chief-of-staff features
- automatic task creation
- complex background infrastructure

These are future possibilities, not V1 requirements.

## 12. Validation Strategy

The biggest early risk is extraction accuracy.

Before building the complete application, test Claude against a small hand-labeled set of real emails.

The extraction experiment should be standalone.

It should:

- take real email examples
- send them to Claude
- receive structured output
- compare Claude's output with human labels
- measure the results
- identify false positives and false negatives

Do not build Gmail OAuth, PostgreSQL, FastAPI, Next.js, or Notion as part of this first experiment.

## 13. Long-Term Vision

If the MVP works, future possibilities include:

- Slack and Google Docs ingestion
- meeting transcripts
- team-wide commitment tracking
- proactive reminders
- detection of promised-but-not-completed work
- cheaper/faster specialized models trained from accumulated user feedback
- broader AI chief-of-staff functionality

These are explicitly future scope and should not be implemented in V1.

## 14. MVP Success Criteria

The MVP is successful when this real end-to-end loop works reliably:

A real Gmail email arrives
→ the system identifies the correct action
→ creates a task candidate
→ the user reviews it
→ the user approves it
→ the task appears in Notion
→ the task retains the correct context/link to the original Gmail email.

That is the MVP.
