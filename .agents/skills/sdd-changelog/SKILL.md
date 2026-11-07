---
name: sdd-changelog
description: Updates CHANGELOG.md in plain, stakeholder-friendly language after a feature is approved at Gate 2 (called by sdd-review), or summarises a whole phase at phase close (called by sdd-replan mode D). Use when the user says "update the changelog" or "write release notes". Reads the feature spec and diff, not chat memory.
---

# sdd-changelog — Talk to Stakeholders

Shared rules: [`.agents/sdd/conventions.md`](../../sdd/conventions.md).

> The changelog is how non-technical stakeholders (clinic owners, product, management) and future agents learn what changed and why.

## File & Format
`CHANGELOG.md` at the project root (`Voice_Agent/CHANGELOG.md`), in [Keep a Changelog](https://keepachangelog.com) style and English. Create it if it doesn't exist:

```markdown
# Changelog
All notable changes to the Voice AI Agent for Egyptian Clinics.
Format: Keep a Changelog. Features reference the roadmap (spec/roadmap.md).

## [Unreleased]

### Phase 5 — Real-Time LiveKit Voice Agent Core
#### Added
- **Feature 5.3 — LiveKit voice worker**: Callers can now speak to the assistant in real time … ([spec](spec/features/feature-513-livekit-voice-pipeline-worker/plan.md))
#### Changed
#### Fixed
#### Security
```

## Steps (per feature)
1. Read `plan.md` §1 Objective, `requirements.md`, `review.md`, and `git diff --stat` for the feature.
2. Write **1–3 bullets** under `[Unreleased]` → the current phase → the right category (`Added` / `Changed` / `Fixed` / `Security` / `Removed`).
3. Plain language: describe the **user or clinic impact** first ("Patients can cancel an appointment by voice"), then optionally a short technical note. No internal jargon without explanation. Never include secrets, PII, or internal URLs.
4. Link the feature spec folder.
5. The changelog change is part of the same feature commit (see `sdd-review` Step 6).

## Phase Summary (mode D)
At phase close, add a 2–4 sentence summary under the phase heading: what the phase delivered for clinics, plus known limitations. When the human tags a release, move `[Unreleased]` content under `## [x.y.z] - YYYY-MM-DD`.

## Self-Check
- [ ] Understandable by a non-developer.
- [ ] Matches what was actually built (review.md), not what was planned.
- [ ] No duplicate entries for the same feature.

