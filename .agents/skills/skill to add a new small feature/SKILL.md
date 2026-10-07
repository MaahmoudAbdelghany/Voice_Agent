We are going to add a new small feature, the feature is: [FEATURE NAME]


### 1. Read `spec/` Folder in Root Directory to make a new feature  matching the spec mission , spec tech and roadmap . and not effect on the architecture of the project
- Always read the project constitution files using `view_file`:
  - `spec/mission.md`: Understand the WHAT, WHY, target users, and boundaries or scope
  - `spec/tech.md`: Verify architectural invariants, tech stack selections
  - `spec/roadmap.md`: Understand completed milestones and current project trajectory.

  
### 3. Ask Clarification Questions
- Analyze potential ambiguities, design trade-offs, and underspecified requirements.
- Formulate clear, concise questions for the human supervisor:
  - Scope boundaries (what is in/out of scope for this specific feature).
  -
- **Do not guess or assume intent.** Wait for human input when ambiguity exists.



### 4. Generate Feature Plan (`plan.md`)
- Create `spec/features/feature-XXX-<feature-name>/plan.md`.


- Objective and why.
- Scope and exclusions.
- Relevant existing architecture.
- Proposed approach at an appropriate level.
- Components/boundaries/data flow.
- Expected files or areas affected.
- Manageable execution groups.
- Risks and trade-offs.

  - **Execution Breakdown**: Atomic sub-steps for implementation.


### 5. Generate Requirements (`requirements.md`)
- Create `spec/features/feature-XXX-<feature-name>/requirements.md`.
- Write testable, clear requirements:
  - **Functional Requirements (R1, R2, ...)**: What the system must do.
  - **Non-Functional Requirements**: Latency budgets, responsiveness, accessibility, theme consistency.
  - **Constraints**: What the feature must *not* do or change.
- **Rule**: Document decisions and behaviors, NOT trivial implementation micro-details (e.g. variable names).


### 6. Generate Validation Criteria (`validation.md`) with 3-Tier Testing
- Create `spec/features/feature-XXX-<feature-name>/validation.md`. based on the rules in the validation skill in validation folder in workspace root `
- Always use the `view_file` to read the validation skill in validation folder in workspace root


### 6. Wait for Human Review (Mandatory Gate) 🛑
- **Halt all coding activity immediately.**
- Present the generated specification files (`plan.md`, `requirements.md`) to the human supervisor.
- Highlight key decisions, trade-offs, and open questions.
- **Strict Prohibition**: Never write application code or make edits before receiving explicit approval (e.g., *"go ahead"*, *"approved"*, *"اعتمد"*).
