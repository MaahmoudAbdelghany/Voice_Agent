---
name: sdd-replan
description: Replanning step of Spec-Driven Development, done between features and phases. Use for a quick check before the next feature (mode A), adding or reordering roadmap phases and features, including breaking down big features (mode B), changing project direction or the constitution (mission/tech) with an impact analysis (mode C), closing a phase and merging its branch to main (mode D), or improving the SDD process and skills themselves (mode E). Works on replan/<topic> branches, and always analyses before editing.
---

# sdd-replan — Run Slow to Run Fast

Shared rules: [`.agents/sdd/conventions.md`](../../sdd/conventions.md).

> Most of the developer's work is now planning and validation. Make time between features to step back: revise the constitution, the roadmap, and the process itself.

## Pick the Mode
| Mode | Trigger | Branch | Edits allowed before approval? |
|:---|:---|:---|:---|
| **A — Quick check** | Gate 3, start of a feature | none (read-only) | No |
| **B — Roadmap change** | Big feature breakdown, merge/split/reorder features, schedule a backlog item | `replan/<topic>` | No, propose first |
| **C — Change direction / constitution** | New product direction, stakeholder feedback, tech-stack change (e.g. new framework, testing tool, responsive/mobile need) | `replan/<topic>` | **No.** Impact analysis first |
| **D — Phase close** | Last feature of a phase committed | `phase/<N>-…` → `main` | No, merge only after approval |
| **E — Process improvement** | Repeated friction, a new skill idea, a gate tweak | `replan/sdd-process-<topic>` | No, propose first |

Always load from disk first: `spec/mission.md`, `spec/tech.md`, `spec/roadmap.md`, `spec/architecture.md`, `spec/adr/`, `spec/backlog/`, and recent `spec/features/*/review.md`.

---

## Mode A — Quick Check (read-only)
Answer in Egyptian Arabic, briefly:
1. Is the next unchecked roadmap item still the right next step? Should adjacent items be merged into one feature (or split)?
2. Did the last review or backlog reveal anything that should come first?
3. Is the working tree clean, and is the branch right for the next feature?
Recommend: continue / switch to mode B, C, or D.

## Mode B — Roadmap Change
1. Propose the change as a diff-style list: new phase name and goal, features `Feature X.Y` with titles and main paths, order, and dependencies. Keep features small (each reviewable in one sitting).
2. For a Big-feature breakdown: one phase per independent deliverable, and each feature sized Small/Medium.
3. For a backlog item: link `spec/backlog/<file>.md` from the roadmap line and set the backlog item's Status to `Scheduled`.
4. Wait for approval, then edit `spec/roadmap.md` on `replan/<topic>`, commit `docs(roadmap): …`, and ask before merging to `main`.

## Mode C — Change Direction / Constitution Update
**Do not modify code or specs yet.** Produce an impact analysis that separates **verified facts** (with file references), **assumptions**, and **recommendations**:
1. Which existing decisions remain valid?
2. Which decisions conflict with the new direction?
3. Which completed features can be reused as-is?
4. Which features or specs must be modified, postponed, or dropped?
5. Architectural, data, API, security, PII, latency, and cost risks.
6. Which project-level specs must change (`mission.md`, `tech.md`, `architecture.md`, a new ADR)?
7. New roadmap phases or features needed.
8. Missing information and decisions → ask the human (3–6 questions, each with a recommended answer).

After approval:
- Update the constitution files on `replan/<topic>`, and add an ADR in `spec/adr/` (from `spec/adr/template.md`) for significant technical decisions.
- **Propagate**: update affected existing feature specs and code so everything stays consistent (no drift). **Small** propagation → do it in this replan. **Large** → schedule it as its own roadmap feature (mode B) instead.
- Validate (`uv run pytest -v`, `uv run ruff check .`), present the diff, and commit after approval.

## Mode D — Phase Close
> In phase mode, `sdd-phase` Steps 7–9 already cover validation, deep review, changelog, and merge. Use only the **retrospective** (item 3) and the next-phase proposal (item 6) from here.

1. Verify every feature of the phase is `- [x]` and has a committed `review.md` (feature mode) or a row in `phase-review.md` (phase mode).
2. Run a **deep review** across the whole phase (`sdd-review` Step 3 lenses) and the full validation suite.
3. Phase retrospective (short, in Egyptian Arabic): what went well, spec gaps found, process friction → candidates for mode E.
4. Ensure `CHANGELOG.md` covers the phase (`sdd-changelog`, phase summary).
5. 🛑 Ask for approval, then merge: open a PR from `phase/<N>-<slug>` to `main` (preferred), or after explicit approval:
   ```powershell
   git checkout main; git pull
   git merge --no-ff phase/<N>-<slug> -m "merge: Phase <N> <title>"
   git push origin main
   ```
6. Propose the next phase branch name.

## Mode E — Process Improvement
1. Describe the friction (with evidence from reviews and conversations).
2. Propose edits to `.agents/sdd/conventions.md`, templates, or `sdd-*` skills, or a new skill. Decide together whether it is **project-specific** (`.agents/skills/`) or **global** (the user's global skills folder).
3. After approval, edit on `replan/sdd-process-<topic>`. Keep skills in English with valid `name`/`description` frontmatter and kebab-case folder names.

---

## Rules
- Constitution changes never ride on a feature commit. Only a roadmap tick may live on a phase branch.
- Every change to intent goes into the spec. Code alone is never enough.
- Prefer small replans often over big rewrites rarely.

