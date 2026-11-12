# Post-Validation Phase Review: Phase 5 — Real-Time LiveKit Voice Agent Core & Medical Persona

- **Phase branch**: `phase/5-livekit-voice-core`
- **Base branch**: `main` (`7b4d1ba`)
- **Features reviewed**: Feature 5.3, Feature 5.4, Feature 5.5, Feature 5.6 (building on completed Features 5.1 & 5.2)

---

## 1. Validation Results Summary
- **Voice orchestration suite (`Feature 5.6`)**: `19 passed, 0 failed` in `~8s` (`uv run pytest tests/test_agent.py -v`, `< 15s` `NFR1` budget)
- **Voice worker & turn engine suite (`Feature 5.4`)**: `24 passed, 0 failed` (`uv run pytest tests/test_voice_worker.py -v`)
- **Simulated CLI scenarios (`Feature 5.5`)**: `11 passed, 0 failed` (`uv run pytest tests/test_simulated_scenarios.py -v`) and `6/6 scenarios passed` (`uv run python scripts/test_call.py --scenario all`: `booking`, `manage`, `knowledge`, `emergency`, `guardrail`, `unverified-booking`)
- **Golden evaluation & RAGAS gate (`Feature 4.8`)**: `10 passed, 0 failed` (`uv run pytest tests/evals/test_golden_evals.py -v`)
- **Worker offline import check (`PI.8`)**: `ServerType.ROOM` with zero outbound HTTP/network calls (`uv run python -c "import src.agent.voice_agent as va; print(va.get_worker_options().worker_type)"`)
- **Regression (full repository suite, `PI.4` & `PI.5`)**: `594 passed, 0 failed, 0 skipped` (`uv run pytest -v`), with `data/clinic.db` absent and `data/calls/` clean (`0` stray files)
- **Lint (`PI.6`)**: `All checks passed!` (`uv run ruff check .`)
- **Manual / visual (`PI.9`)**: Pending human live voice call at Phase Gate 2 (`scripts/generate_token.py --phone ...` + `python -m src.agent.voice_agent console` / `dev`)
- **Tiers marked N/A**: Type checks (`Not Applicable` — no static type checker is configured in `pyproject.toml`; technical justification recorded in all feature `validation.md` files)

---

## 2. The 5 Core Questions (Phase-Wide)

| # | Question | Verdict | Evidence |
|:---|:---|:---|:---|
| 1 | **Does it work?** | ✅ | `ClinicTurnEngine` (`src/agent/turn_engine.py`) and `ClinicVoiceAgent.llm_node` (`src/agent/voice_agent.py`) execute end-to-end streaming voice turns across `InputGuardrail` -> `FinOpsController` -> `CacheLadder` -> `ModelGateway.astream` -> `AppointmentWorkflowStateMachine` / 5 allowlisted clinic tools -> `OutputGuardrail` -> `HierarchicalTracer` & `CallSession`. All 6 CLI scenarios and 594 automated tests pass with zero mocks faking internal safety boundaries. |
| 2 | **Does it match the spec (all R/NFR/C, no scope creep)?** | ✅ | All shared decisions (`P1`–`P13`) and all feature requirements across Features `5.3`–`5.6` are implemented and traced to passing verification checks. Auto-language switching was properly deferred to `spec/backlog/2026-11-09-deepgram-language-autodetect.md` (`P11`). |
| 3 | **Does it respect the architecture (`tech.md` invariants, ADRs)?** | ✅ | Enforces `tech.md` §2.1 differentiated timeouts (`400ms` read abort vs `400ms` filler + `3,000ms` `asyncio.shield` write cap), §2.3 medical non-diagnosis & emergency `123` + receptionist escalation, §2.4 Silero VAD barge-in shielding, §2.6–§2.7 Presidio + Arabic-Indic PII redaction prior to disk/trace persistence, §2.8 FinOps `150` tok/turn & `8,000` tok/call budgets, §2.9 XML untrusted-input wrapping, §2.10 verified SIP/JWT caller identity & 5-tool allowlist, and `ADR-009` `AppointmentWorkflowStateMachine`. |
| 4 | **Is the diff free of unrelated changes?** | ✅ | Every modified or deleted file maps to Phase 5's legacy purge (`5.3`), voice worker & turn engine (`5.4`), simulated CLI runner (`5.5`), orchestration test suite (`5.6`), or deep-review hardening fixes. Zero scratch files, `.env` secrets, or test SQLite/call artifacts exist in the working tree. |
| 5 | **Is existing behaviour unbroken?** | ✅ | Full suite (`594 passed, 0 failed, 0 skipped`) and golden RAGAS/exact-match suite (`10 passed`) pass cleanly; Phases 1–4 and dashboard tests remain green on pure clinic fixtures. |

### Per-Feature Verdict Summary

| Feature | Title | Commit | Targeted Evidence | Verdict |
|:---|:---|:---|:---|:---|
| **Feature 5.3** | Legacy Restaurant Purge & Codebase Sanitization | `92aac2c` | 9 legacy files deleted, 31 files sanitized, purity guard `test_repository_purity_guard_no_legacy_restaurant_symbols` passing | ✅ Approved |
| **Feature 5.4** | LiveKit Voice Pipeline Worker & Clinic Turn Engine | `d478aa0` | `24 passed` in `tests/test_voice_worker.py`; `ClinicTurnEngine` + `ClinicVoiceAgent` + signed JWT attributes (`--phone`, `--lang`, `--tenant-id`, `--branch-id`) | ✅ Approved |
| **Feature 5.5** | CLI Simulated Call Runner & Clinic Scenarios | `e903cec` | `11 passed` in `tests/test_simulated_scenarios.py`; `6/6` scenarios passing via `scripts/test_call.py --scenario all` | ✅ Approved |
| **Feature 5.6** | Automated Voice Orchestration & Guardrail Test Suite | `b45f66e` | `19 passed` in `tests/test_agent.py` (`< 8s` runtime); `10 passed` in `tests/evals/test_golden_evals.py` | ✅ Approved |

---

## 3. Deep Review (4 Parallel Lenses Across `git diff main...HEAD`)

| Lens | Finding | Severity | Action |
|:---|:---|:---|:---|
| **1. Security & PII** | `src/dashboard/pages/01_calls.py`: Dynamic transcript, caller name, specialty, booking, and tool strings were interpolated into `st.markdown(..., unsafe_allow_html=True)` without HTML escaping (stored XSS risk). | High | **Fixed** — Escaped all dynamic values with `html.escape(..., quote=True)`, switched raw tool fallback to `st.text`, and added `test_calls_page_stored_xss_payload_is_html_escaped`. |
| **1. Security & PII** | `src/agent/voice_agent.py` & `scripts/generate_token.py`: Missing LiveKit credentials silently fell back to hardcoded `devkey` / offline secret even when `settings.environment` was non-dev (`production`/`staging`). | High | **Fixed** — Added `Settings.environment` guard raising `ValueError` outside dev/test/local environments when `livekit_api_key` or `livekit_api_secret` is missing or placeholder (`your_*`); verified in `test_production_livekit_secret_guard_and_non_mobile_sip_caller_id`. |
| **1. Security & PII** | `src/tools/__init__.py`, `appointment_booking.py`, `manage_appointment.py`, `workflow.py`, & `scripts/seed_clinic_db.py`: Exception handlers logged raw tool `arguments` / Pydantic `ValidationError` inputs containing caller PII, and `seed_clinic_db.py` printed raw `database_url`. | High | **Fixed** — Redacted tool `arguments` and exception messages via `get_pii_redactor()` (`exc_info=False`) across all tool/workflow boundaries and masked DB passwords via `make_url(...).render_as_string(hide_password=True)`. |
| **1. Security & PII** | `src/ai_core/guardrails.py` & `src/ai_core/cache.py`: `EgyptianPIIRedactor` and `CacheabilityPolicy` missed Arabic-Indic digits (`٠-٩` / `۰-۹`) and spoken hyphenated/spaced phone & 14-digit National ID groups (`010 - 1234 - 5678`). | High | **Fixed** — Extended `EgyptianPIIRedactor` recognizers and `CacheabilityPolicy` regexes to normalize/match Arabic-Indic digits and grouped mobile/NID patterns; verified in `test_guardrails.py` and `test_cache_ladder.py`. |
| **1. Security & PII** | `src/tools/manage_appointment.py`: Unverified `manage_appointment(action='lookup')` (`R3`) returned `patient_name` and `patient_phone` when queried by `booking_code` without a verified session phone. | High | **Fixed** — Preserved unverified read lookup (`R3`) while masking/omitting `patient_name` and `patient_phone` whenever `phone is None`; verified in `test_async_execute_tool_unverified_lookup_masks_patient_pii`. |
| **1. Security & PII** | `src/agent/turn_engine.py`, `voice_agent.py`, & `scripts/generate_token.py`: Non-mobile SIP caller IDs (`+202...` landlines, `"anonymous"`) survived `_normalize_phone()` and raised `ValueError` in `caller_session_scope`; `extract_verified_caller_identity` preferred mutable `participant.name` and did not slug-validate `tenant_id`/`branch_id`. | Medium | **Fixed** — `_normalize_phone()` now returns `None` on invalid Egyptian mobile strings (routing writes cleanly to receptionist handoff), `generate_token.py` validates `--phone` upfront, signed `caller_name` is preferred, and `tenant_id`/`branch_id` are validated against `^[a-zA-Z0-9_-]{1,64}$`. |
| **1. Security & PII** | `src/agent/session_manager.py` & `src/dashboard/calls_data.py`: `build_context_summary()` interpolated slot strings into prompt context without XML/newline sanitization; `to_persisted_dict()` did not redact `participant_identity`/`room_name` or fail closed on redactor errors; live dashboard sessions bypassed `to_persisted_dict()`. | Medium | **Fixed** — Applied `escape_xml_delimiters()` + control-char stripping in `build_context_summary()`, redacted `participant_identity`/`room_name` with fail-closed regex scrubbing in `to_persisted_dict()`/`to_summary_dict()`, and projected live sessions through `to_persisted_dict()` in `calls_data.py`. |
| **1. Security & PII** | `src/ai_core/gateway.py` & `src/agent/turn_engine.py`: Tier-3 search fallback spoke literal `<retrieved_context>` tags, and zero-tool turns did not pass fee-grounding sentinel to `OutputGuardrail`. | Low | **Fixed** — Stripped `<retrieved_context>` tags from spoken Tier-3 fallback text and wired tool fee outputs + `[NO_TOOL_GROUNDING]` sentinel into `OutputGuardrail.validate()`. |
| **2. Architecture & Invariants** | `src/tools/human_handoff.py`: `ReceptionistHandoffTool` hardcoded `timeout_s = 0.4`, aborting escalation DB writes at 400ms instead of `write_tool_hard_cap_ms` (`3.0s`), and retained `"kitchen_manager"` / `"delivery_dispatch"` keys in `_DEPARTMENT_ALIASES`. | High | **Fixed** — Defaulted `timeout_s` to `get_settings().write_tool_hard_cap_ms / 1000.0` (`3.0s`) and removed legacy restaurant department keys. |
| **2. Architecture & Invariants** | `src/agent/turn_engine.py`: Timed-out `write_task` was not cancelled after `write_tool_hard_cap_ms`, done-callback did not consume background task exceptions, `_invoke_handoff` lacked `language` threading, and `session.metrics.finops_snapshot` was not synced in `finally:`. | Medium | **Fixed** — Added `write_task.cancel()` on hard-cap breach, `_finalize_write_task` exception consumption, localized handoff fallbacks, `finops_snapshot` sync in `finally:`, and `test_max_tool_rounds_per_turn_halts_infinite_tool_loop`. |
| **2. Architecture & Invariants** | `src/tools/__init__.py` & `src/ai_core/workflow.py`: `async_execute_tool` invoked `appointment_booking_tool` / `manage_appointment_tool` directly instead of routing through `AppointmentWorkflowStateMachine` (`ADR-009`). | Medium | **Fixed** — Routed `book_appointment` and `manage_appointment` through `AppointmentWorkflowStateMachine` while preserving custom `session_factory` and clock overrides. |
| **2. Architecture & Invariants** | `src/ai_core/cache.py` & `src/agent/turn_engine.py`: `CacheScope` omitted `tenant_id` and `branch_id` in Tier-1 hash keys and Tier-2 Qdrant payload filters. | Medium | **Fixed** — Added `tenant_id` and `branch_id` to `CacheScope` and `CacheEntry`, wired from `VerifiedCallerIdentity`, and verified in `test_cache_scope_isolates_tenants_and_branches`. |
| **2. Architecture & Invariants** | `scripts/test_call.py` & `src/dashboard/app.py`: Interactive exit referenced `call_session.metrics.turn_count` (`AttributeError`), and `src/dashboard/app.py` rendered hardcoded synthetic KPI strings (`"680 ms"`, `"142"`). | Medium | **Fixed** — Added `CallMetrics.turn_count` property and replaced synthetic landing-page KPIs with live computed metrics (`"0 ms"`, `"0"`, `"0.0%"` on empty state per `P5`). |
| **2. Architecture & Invariants** | `src/agent/__init__.py`, `src/rag/__init__.py`, `retriever.py`, `hybrid_retriever.py`, `embeddings.py`: Eager package imports, non-lazy cloud Qdrant init, `[::1]` `NO_PROXY` FastEmbed `InvalidURL` edge case, and 3 restaurant words in `ARABIC_STOP_WORDS`. | Low | **Fixed** — Converted `src/agent` & `src/rag` exports and `retriever` singletons to PEP 562 lazy `__getattr__`, normalized `[::1]` in `NO_PROXY` before FastEmbed init, and removed `"منيو"`, `"مطعم"`, `"دليفري"` from `ARABIC_STOP_WORDS`. |
| **3. Spec Drift** | `spec/architecture.md`, `phase-overview.md`, `summary_ar.md`, `513/validation.md`, `516/validation.md`, `pyproject.toml`: Phase 5 nodes in `spec/architecture.md` still had `[Planned - Phase 5]`, `phase-overview.md` had pre-amend SHAs and unchecked `PI.1`–`PI.8`, `summary_ar.md` §7 was blank, and minor typos existed in `validation.md` / `pyproject.toml`. | High / Medium | **Fixed** — Promoted Phase 5 components in `spec/architecture.md` (keeping Phase 6/8 `[Planned]` markers intact), updated `phase-overview.md` & `summary_ar.md` statuses, `PI.1`–`PI.8` checkboxes, and exact commit SHAs, and fixed `513`/`516` `validation.md` & `pyproject.toml` descriptions. |
| **4. Test Quality** | `tests/test_tools.py`, `tests/test_clinic_repository.py`, & `src/agent/scenarios.py`: `test_execute_transfer_to_receptionist_success` created `data/clinic.db` on disk without a `tmp_path` fixture, and `spoken_confirmation_includes_queue_and_code` had a tautological `or len(bookings) >= 1` branch. | High / Medium | **Fixed** — Added `isolate_clinic_db_tools` autouse `tmp_path` fixture in `tests/test_tools.py`, passed `tmp_path` DB URL in `test_clinic_repository.py`, and tightened `scenarios.py` assertion to require both `"نمرة"` and `"APT-"` in spoken confirmation. |

---

## 4. Spec Sync
- **Spec files created/updated during Phase 5**:
  - `spec/tech.md` (§1 `livekit-agents >= 1.7.0`, §2.1 differentiated `400ms` read vs `400ms` filler + `3,000ms` shielded write timeout)
  - `spec/roadmap.md` (inserted Feature 5.3, renumbered Features 5.4–5.6, ticked `[x]` on 5.3–5.6)
  - `spec/architecture.md` (promoted Phase 5 LiveKit Voice Worker, `ClinicTurnEngine`, `prompts.py`, `messages.py`, `scenarios.py` from planned to built)
  - `spec/backlog/2026-11-09-deepgram-language-autodetect.md` (captured deferred mid-call Deepgram auto-language detection)
  - `spec/phases/phase-5-livekit-voice-core/{phase-overview.md,summary_ar.md,phase-review.md}`
  - `spec/features/feature-513-legacy-restaurant-purge/{plan.md,requirements.md,validation.md}`
  - `spec/features/feature-514-livekit-voice-worker/{plan.md,requirements.md,validation.md}`
  - `spec/features/feature-515-cli-simulated-call-runner/{plan.md,requirements.md,validation.md}`
  - `spec/features/feature-516-voice-orchestration-test-suite/{plan.md,requirements.md,validation.md}`
- **Drift found and fixed**:
  - Updated `spec/architecture.md` C4 diagrams and directory structure to match implemented Phase 5 modules.
  - Corrected commit SHAs (`92aac2c`, `d478aa0`, `e903cec`, `b45f66e`) and `PI.1`–`PI.8` validation checkboxes in `phase-overview.md` and `summary_ar.md`.
  - Synced test function name in `feature-513/validation.md` and updated test counts (`19 passed`, `594 passed`) in `feature-516/validation.md`.

---

## 5. Verdict
- **Status**: `APPROVED-PENDING-HUMAN`
- **Local commits ready on `phase/5-livekit-voice-core`**:
  1. `2ad640d` — `docs(spec): add Phase 5 specs`
  2. `92aac2c` — `feat(agent): implement Feature 5.3 legacy restaurant purge and codebase sanitization`
  3. `d478aa0` — `feat(agent): implement Feature 5.4 LiveKit voice pipeline worker and clinic turn engine`
  4. `e903cec` — `feat(agent): implement Feature 5.5 CLI simulated call runner and clinic scenarios`
  5. `b45f66e` — `feat(tests): implement Feature 5.6 automated voice orchestration and guardrail test suite`
  6. `fix(phase5): resolve deep-review security, architecture, test isolation, and docs findings`
- **Next step**: **Phase Gate 2** — waiting for human approval (and manual live voice call verification `PI.9`) before running `sdd-changelog`, pushing `phase/5-livekit-voice-core`, and merging to `main`.
