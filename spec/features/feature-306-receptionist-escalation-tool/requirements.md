# Requirements: Feature 3.6 — Human Receptionist Escalation Tool with Dashboard Alert (`src/tools/human_handoff.py`)

## 1. Overview
Requirements for the `transfer_to_receptionist` tool, the persistent `escalations` table and repository API (dashboard alert data layer), the emergency safety net, reception-hours callback logic, and de-duplication.

---

## 2. Functional Requirements

### FR-1: Input
- **FR-1.1**: The tool accepts the fields of `ReceptionistHandoffInput`: `reason`, `caller_name?`, `caller_phone?`, `department` (default `reception`), `urgency` (default `medium`), `summary?`.
- **FR-1.2**: The Python entrypoints additionally accept an optional `session_id` (not part of the LLM-facing schema) which is stored on the ticket.
- **FR-1.3**: `caller_phone` is normalized to the Egyptian format when valid; otherwise kept as given (escalation never fails because of a malformed phone).
- **FR-1.4**: When called directly (bypassing the schema) with an empty/whitespace reason, the tool uses the default reason `"طلب التحدث مع موظف الاستقبال"` and continues (never fails for missing reason).
- **FR-1.5**: Unknown `department` / `urgency` values on direct calls fall back to `reception` / `medium` (logged at WARNING).

### FR-2: Emergency Safety Net
- **FR-2.1**: `detect_emergency(text)` returns `True` when the Arabic-normalized text (reason + summary) contains an emergency indicator, covering at least: chest pain, severe bleeding, difficulty breathing / choking, fainting / loss of consciousness, seizures, stroke / paralysis signs, poisoning / overdose, serious accident / injury, self-harm — in Egyptian colloquial, MSA, and English (e.g. `"ألم في صدري"`, `"وجع جامد في صدري"`, `"مش قادر أتنفس"`, `"بينزف"`, `"أغمى عليه"`, `"تشنجات"`, `"chest pain"`).
- **FR-2.2**: If detected, the effective `urgency` becomes `emergency` and `department` becomes `emergency`, regardless of the LLM's values.
- **FR-2.3**: The safety net only upgrades; it never lowers an `emergency` (or any) value provided by the LLM.
- **FR-2.4**: `data["emergency_detected"]` is `True` when the effective urgency is `emergency` (from the LLM or the safety net), else `False`.

### FR-3: Status, Reception Hours & Wait Estimate
- **FR-3.1**: Settings `reception_open_time` (default `09:00`), `reception_close_time` (default `22:00`), `reception_friday_open_time` (default `14:00`) define reception hours in Cairo time; Friday uses the Friday open time and the common close time.
- **FR-3.2**: Effective urgency `emergency` → `status="transferred"`, `estimated_wait_seconds=0`, at any time of day.
- **FR-3.3**: Non-emergency during reception hours → `status="queued"`, wait = base(urgency) + 30s × (number of open tickets with equal or higher urgency, excluding the current one), capped at 600s. Base: `urgent`=30, `medium`=60, `low`=120.
- **FR-3.4**: Non-emergency outside reception hours → `status="callback"`, `estimated_wait_seconds=0`.
- **FR-3.5**: `data["transfer_requested"]` is `True` for `transferred` and `queued`, `False` for `callback`.
- **FR-3.6**: `callback` without a caller phone → `data["needs_phone"]=True` and the message asks for the caller's mobile number; otherwise `needs_phone=False`.

### FR-4: Persistence & Ticket Identity
- **FR-4.1**: Each new escalation is stored as an `Escalation` row: `ticket_id`, `session_id?`, `caller_name?`, `caller_phone?`, `reason`, `summary?`, `department`, `urgency`, `status`, `estimated_wait_seconds`, `created_at`, `updated_at`, `acknowledged_at?`, `resolved_at?` (UTC timestamps).
- **FR-4.2**: `ticket_id` format `ESC-YYYYMMDD-NNNN` (Cairo date, 4-digit daily sequence starting at `0001`), unique. On a uniqueness collision, retry once with the next number.
- **FR-4.3**: `EscalationStatus` values: `queued`, `transferred`, `callback`, `acknowledged`, `resolved`. Open statuses = `queued`, `transferred`, `callback`.

### FR-5: De-duplication
- **FR-5.1**: If `caller_phone` is present and an open ticket with the same phone was created within the last 10 minutes, the tool reuses it instead of creating a new one, and sets `data["deduplicated"]=True` (else `False`).
- **FR-5.2**: When reusing, if the new effective urgency is higher (`low < medium < urgent < emergency`), the ticket's urgency, department, status and wait are upgraded accordingly; a lower or equal request never downgrades it. The new reason is appended to the ticket summary (bounded to 1000 chars).
- **FR-5.3**: Without a phone, every call creates a new ticket.

### FR-6: Output & Spoken Messages
- **FR-6.1**: The tool returns `ToolResult(success=True, message, data)` where `data` = `ReceptionistHandoffOutput` fields (`ticket_id`, `status`, `urgency`, `department`, `estimated_wait_seconds`, `message`) plus `transfer_requested`, `emergency_detected`, `needs_phone`, `deduplicated`, `persisted`, and `department_ar`.
- **FR-6.2**: Emergency message: tells the caller to call the ambulance `settings.emergency_phone` (123) or go to the nearest emergency department immediately, says they are being transferred to reception now, and states the ticket number. No diagnosis or medical advice.
- **FR-6.3**: Queued message: polite confirmation of transfer to the Arabic department name, approximate wait (seconds under 60, else minutes), ticket number.
- **FR-6.4**: Callback message: reception is closed now, mentions the reception hours, promises a call back on the masked phone (last 3 digits only spoken) as soon as reception opens, ticket number; or asks for the mobile number when unknown.
- **FR-6.5**: Messages greet by caller name when known, contain no markdown, no restaurant concepts, no fake staff names, and are ≤ 300 characters.
- **FR-6.6**: Arabic department labels: `reception`=الاستقبال, `nursing`=التمريض, `billing`=الحسابات, `emergency`=الطوارئ.

### FR-7: Resilience & Latency
- **FR-7.1**: All DB work in `aexecute` runs within a 400ms budget (`timeout_s`, configurable per instance).
- **FR-7.2**: On timeout or any DB exception: `success=True`, the same computed status/message logic applies, `ticket_id="ESC-TMP-<6 hex>"`, `persisted=False`, `deduplicated=False`, wait estimated with 0 open tickets; an ERROR is logged (no PII). The tool never raises.
- **FR-7.3**: `execute` (sync) works both with and without a running event loop (same pattern as 3.4).

### FR-8: Repository API (Dashboard Data Layer)
- **FR-8.1**: `create_escalation(...)` persists and returns an `Escalation` with a generated `ticket_id`.
- **FR-8.2**: `find_recent_open_escalation(phone, since)` returns the newest open ticket for that phone created at/after `since`, else `None`.
- **FR-8.3**: `count_open_escalations(min_urgency=None)` counts open tickets, optionally only those with urgency ≥ `min_urgency`.
- **FR-8.4**: `list_open_escalations(limit=50)` returns open tickets ordered by urgency (emergency first) then `created_at` ascending.
- **FR-8.5**: `update_escalation_status(ticket_id, status)` supports `acknowledged` and `resolved`, setting `acknowledged_at` / `resolved_at` and `updated_at`; unknown ticket → `EscalationNotFoundError`; `resolved` tickets cannot be re-opened (raises `ClinicRepositoryError`).

### FR-9: Registry, Callables & Compatibility
- **FR-9.1**: `transfer_to_receptionist` (sync) and `async_transfer_to_receptionist` (async) return `ToolResult`; class `ReceptionistHandoffTool`, singleton `receptionist_handoff_tool`.
- **FR-9.2**: `TOOL_REGISTRY["transfer_to_receptionist"]` uses `ReceptionistHandoffInput` / `ReceptionistHandoffOutput` with a clinic description that mentions emergencies, explicit human requests, and out-of-scope requests. `escalate_to_human` is removed from the registry.
- **FR-9.3**: Deprecated aliases importable from `src.tools.human_handoff` and `src.tools`: `HumanHandoffTool`, `human_handoff_tool`, `escalate_to_human`, `async_escalate_to_human`. The function aliases accept legacy parameter names (`customer_name`, `customer_phone`, `conversation_summary`) and map legacy values (`high`→`urgent`, `critical`→`emergency`, `customer_support`/`kitchen_manager`/`delivery_dispatch`→`reception`, `billing`→`billing`), returning the clinic `ToolResult`.

---

## 3. Non-Functional Requirements
- **NFR-1 (Latency)**: warm `aexecute` on local SQLite completes well under 400ms (median measured over 10 runs and reported).
- **NFR-2 (Spoken Egyptian Arabic)**: short, calm, reassuring, TTS-friendly; numbers spoken naturally.
- **NFR-3 (Privacy)**: INFO logs contain only `ticket_id`, urgency, department, status, dedup/persisted flags — never phone, name, reason, or summary (DEBUG at most for lengths). Spoken phone is masked.
- **NFR-4 (Determinism)**: no randomness in status, wait time, or wording (except the `ESC-TMP` suffix).
- **NFR-5 (Safety)**: no medical diagnosis or advice in any message; emergency path always mentions 123.

---

## 4. Constraints
- **C-1**: No changes to the 3.1 schemas `ReceptionistHandoffInput`, `ReceptionistHandoffOutput`, `HandoffUrgencyEnum`, `HandoffDepartmentEnum`.
- **C-2**: DB changes are additive only: a new table/model and new repository methods; existing tables, models, and repository behaviour unchanged.
- **C-3**: Do not edit `src/agent/*`, `src/dashboard/*`, or other legacy restaurant tools.
- **C-4**: The tool does not perform the real call transfer, outbound calls, or external notifications.
- **C-5**: No new third-party dependencies.
