
### 1. Read `spec/` Folder in Root Directory
- Always read the project constitution files using `view_file`:
 - `implementation_plan.md`: Understand the implementation plan
  - `spec/mission.md`: Understand the WHAT, WHY, target users, and boundaries or scope
  - `spec/tech.md`: Verify architectural invariants, tech stack selections
  - `spec/roadmap.md`: Understand completed milestones and current project trajectory.

  
### 2. Identify Next Feature in `roadmap.md`
- Inspect `spec/roadmap.md` to locate the next feature
- Confirm that all prerequisite phases and foundational components are satisfied.






### 3. Generate Feature Plan (`plan.md`)
- Create `spec/features/feature-XXX-<feature-name>/plan.md`.


- Objective and why.
- Scope and exclusions.
- Relevant existing architecture.
- Proposed approach at an appropriate level.
- Components/boundaries/data flow.
- Expected files or areas affected.
- Manageable execution groups.
- Risks and trade-offs.

  - **Execution Breakdown**: Atomic sub-steps for implementation. if feature is big we well make it in multiple features each feature in execution group.


### 4. Generate Requirements (`requirements.md`)
- Create `spec/features/feature-XXX-<feature-name>/requirements.md`.
- Write testable, clear requirements:
  - **Functional Requirements (R1, R2, ...)**: What the system must do.
  - **Non-Functional Requirements**: Latency budgets, responsiveness, accessibility, theme consistency.
  - **Constraints**: What the feature must *not* do or change.
- **Rule**: Document decisions and behaviors, NOT trivial implementation micro-details (e.g. variable names).


### 5. Generate Validation Criteria (`validation.md`) with 3-Tier Testing
- Create `spec/features/feature-XXX-<feature-name>/validation.md`. based on the rules in the validation skill in validation folder in workspace root `
- Always use the `view_file` to read the validation skill in validation folder in workspace this path root Voice_Agent\.agents\skills\validation\SKILL.md




### 6. Wait for Human Review (Mandatory Gate) 🛑
- **Halt all coding activity immediately.**
- Present the generated specification files (`plan.md`, `requirements.md`, `validation.md`) to the human supervisor.
- Highlight key decisions, trade-offs, and open questions.
- **Strict Prohibition**: Never write application code or make edits before receiving explicit approval (e.g., *"go ahead"*, *"approved"*, *"اعتمد"*).

### 8 when human approved the spec feature :

- Always read using `view_file`

 plan.md for the current feature and requirements.md


and i want you working on the feature based on the cuurent plan.md  feature and requirements.md and explain to me what you done , and why you done this  and wait to give you approval to make validation



###  7 after done working on the feature :

- Always read using `view_file`

 validation.md for the current feature

 explain to me what you done , and why you done this  and wait to give you approval to make the next step .

### 8 after done working on the validation of the feature :

commit the changes in git and push into my repo on github and update the roadmap.md file to mark this feature as completed  .

and wait to give you approval to make the next feature .



make sure to make conversation between us in arabic with good format  from right to left 





