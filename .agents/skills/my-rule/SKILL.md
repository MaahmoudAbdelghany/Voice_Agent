---
name: my-rule
description: Enforces workspace workflow rules: plan persistence, one-step-at-a-time task execution, concise progress explanation, task tracking in TASK_PLAN.md, git commit and push to GitHub repository, and stopping for user approval.
---

# Workspace Execution Rules Skill

Use this skill to guide and enforce step-by-step task execution, git synchronization, and session memory across tasks.

> **Note**: This skill handles task execution flow and git synchronization. It provides a clear, concise summary of changes ("what was done in short and why") and does **not** invoke the separate 6-step AI teaching methodology unless explicitly requested.

---

## 1. Session Memory & Plan Persistence
- **Plan Location & Persistence**: Keep both `implementation_plan.md` and `TASK_PLAN.md` saved directly in the workspace root directory.
- **Plan Verification**: Always read `implementation_plan.md` and `TASK_PLAN.md` by explicit file path from the workspace root (using `view_file`) before starting work or resuming execution.
- **Task Tracking**: After completing each step, update `TASK_PLAN.md` with completed checkboxes `- [x]` and commit the file.

---

## 2. Step-by-Step Task Execution & GitHub Sync
- **One Step at a Time**: Execute only one step of a task plan in a turn. If there is anything external you need, ask the user to provide it.
- **Explain Progress**: After completing each step, explain clearly what was done in short and why.
- **Commit & Push**: Commit all changes for that step with a descriptive commit message and push them to the GitHub repository.
- **Wait for Approval**: Stop and ask the user for explicit permission/approval ("go ahead") before moving to the next step. Do NOT proceed without explicit user approval.
