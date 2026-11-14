"""
Automated Verification Suite for Feature 5.5 — CLI Simulated Call Runner & Clinic Scenarios.

Covers:
- Tier 1 (Unit): T1.1 (`ScriptedClinicLLMProvider`), T1.2 (`CLINIC_SCENARIOS`), T1.3 (`test_call.py` parser)
- Tier 2 (Integration): T2.1 (`booking` / `manage` / `knowledge`), T2.2 (`emergency` & `guardrail`),
  T2.3 (`unverified-booking`), T2.4 (`save_session=True` PII-redacted JSON persistence)
- Tier 3 (Error & Edge Cases): T3.1 (`--live` without API keys), T3.2 (`--scenario nonexistent`)
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src.agent.scenarios import (
    CLINIC_SCENARIOS,
    ScriptedClinicLLMProvider,
    ScriptedLLMResponse,
    ScriptedToolCall,
    run_simulated_scenario,
)
from src.ai_core.finops import FinOpsController
from src.ai_core.gateway import LiteLLMProvider, LLMProvider, ModelGateway, Stage
from src.config import Settings

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
TEST_CALL_SCRIPT = WORKSPACE_ROOT / "scripts" / "test_call.py"


def _load_test_call_module():
    """Load `scripts/test_call.py` cleanly as an importable module for unit/CLI checks."""
    spec = importlib.util.spec_from_file_location("test_call_cli", TEST_CALL_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_call_cli"] = module
    spec.loader.exec_module(module)
    return module


# ==============================================================================
# Tier 1: Unit Verification (T1.1, T1.2, T1.3)
# ==============================================================================


@pytest.mark.asyncio
async def test_t1_1_scripted_provider_streams_text_and_integrates_with_model_gateway():
    """T1.1: ScriptedClinicLLMProvider implements LLMProvider.astream and works with ModelGateway."""
    direct_provider = ScriptedClinicLLMProvider(
        steps=[
            ScriptedLLMResponse(
                text="أهلاً بحضرتك في مجمع عيادات النور التخصصي، أقدر أساعد حضرتك إزاي؟",
                prompt_tokens=140,
                completion_tokens=25,
                ttft_ms=12.0,
            )
        ]
    )
    assert isinstance(direct_provider, LLMProvider)
    assert direct_provider.is_configured() is True

    # 1. Verify raw LLMProvider.astream 3-tuple protocol: (text_chunk, tool_calls_delta, metadata)
    raw_chunks: list[str] = []
    raw_last_meta: dict = {}
    async for text_chunk, tool_delta, meta in direct_provider.astream(
        model="groq/llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "السلام عليكم"}],
        temperature=0.2,
        max_tokens=150,
    ):
        assert tool_delta is None
        assert isinstance(meta, dict)
        if text_chunk:
            raw_chunks.append(text_chunk)
        raw_last_meta = meta

    assert "".join(raw_chunks) == "أهلاً بحضرتك في مجمع عيادات النور التخصصي، أقدر أساعد حضرتك إزاي؟"
    assert raw_last_meta["finish_reason"] == "stop"
    assert raw_last_meta["usage"]["total_tokens"] == 165

    # 2. Verify integration through real ModelGateway.astream + FinOpsController
    gw_provider = ScriptedClinicLLMProvider(
        steps=[
            ScriptedLLMResponse(
                text="أهلاً بحضرتك في مجمع عيادات النور التخصصي، أقدر أساعد حضرتك إزاي؟",
                prompt_tokens=140,
                completion_tokens=25,
                ttft_ms=12.0,
            )
        ]
    )
    settings = Settings(_env_file=None, groq_api_key="", gemini_api_key="")
    finops = FinOpsController(settings=settings)
    gateway = ModelGateway(
        settings=settings,
        primary_provider=gw_provider,
        fallback_provider=LiteLLMProvider(name="gemini", api_key=""),
        finops_controller=finops,
    )

    chunks: list[str] = []
    final_res = None
    async for text_chunk, gw_result in gateway.astream(
        stage=Stage.DIALOGUE,
        messages=[{"role": "user", "content": "السلام عليكم"}],
        session_id="test-call-t1-1",
    ):
        if text_chunk:
            chunks.append(text_chunk)
        if gw_result is not None:
            final_res = gw_result

    assert "".join(chunks) == "أهلاً بحضرتك في مجمع عيادات النور التخصصي، أقدر أساعد حضرتك إزاي؟"
    assert final_res is not None
    assert final_res.success is True
    assert final_res.provider == "groq"
    assert len(gw_provider.calls) == 1

    budget_snap = finops.get_session_snapshot("test-call-t1-1")
    assert budget_snap is not None
    assert budget_snap.total_tokens == 165


@pytest.mark.asyncio
async def test_t1_1_scripted_provider_streams_tool_call_deltas_via_model_gateway():
    """T1.1: ScriptedClinicLLMProvider yields tool_calls_delta stitched cleanly by ModelGateway."""
    provider = ScriptedClinicLLMProvider(
        steps=[
            ScriptedLLMResponse(
                tool_calls=[
                    ScriptedToolCall(
                        id="call_avail_99",
                        name="check_doctor_availability",
                        arguments={"specialty": "الباطنة", "date": "2026-11-16"},
                    )
                ],
                prompt_tokens=110,
                completion_tokens=18,
            )
        ]
    )
    settings = Settings(_env_file=None, groq_api_key="", gemini_api_key="")
    gateway = ModelGateway(
        settings=settings,
        primary_provider=provider,
        fallback_provider=LiteLLMProvider(name="gemini", api_key=""),
    )

    final_res = None
    async for _text_chunk, gw_result in gateway.astream(
        stage=Stage.DIALOGUE,
        messages=[{"role": "user", "content": "مواعيد الباطنة"}],
        tools=[{"type": "function", "function": {"name": "check_doctor_availability"}}],
        session_id="test-call-t1-1-tools",
    ):
        if gw_result is not None:
            final_res = gw_result

    assert final_res is not None
    assert final_res.success is True
    assert len(final_res.tool_calls) == 1
    assert final_res.tool_calls[0]["id"] == "call_avail_99"
    assert final_res.tool_calls[0]["function"]["name"] == "check_doctor_availability"
    assert json.loads(final_res.tool_calls[0]["function"]["arguments"]) == {
        "specialty": "الباطنة",
        "date": "2026-11-16",
    }


def test_t1_2_clinic_scenarios_contains_exact_six_required_keys():
    """T1.2: CLINIC_SCENARIOS defines the exact 6 required clinic benchmark scenario keys."""
    expected_keys = {
        "booking",
        "manage",
        "knowledge",
        "emergency",
        "guardrail",
        "unverified-booking",
    }
    assert set(CLINIC_SCENARIOS.keys()) == expected_keys
    assert CLINIC_SCENARIOS["unverified-booking"].caller_identity.caller_phone is None
    assert CLINIC_SCENARIOS["unverified-booking"].caller_identity.is_verified is False
    assert CLINIC_SCENARIOS["booking"].caller_identity.is_verified is True


def test_t1_3_test_call_cli_parser_supports_all_required_flags():
    """T1.3: scripts/test_call.py argument parser parses all required flags and defaults."""
    cli_mod = _load_test_call_module()
    parser = cli_mod.build_arg_parser()

    defaults = parser.parse_args([])
    assert defaults.scenario is None
    assert defaults.live is False
    assert defaults.interactive is False
    assert defaults.phone is None
    assert defaults.lang == "ar"
    assert defaults.save_session is False
    assert defaults.livekit is None

    mock_args = parser.parse_args(
        [
            "--scenario",
            "booking",
            "--mock-llm",
            "--phone",
            "01012345678",
            "--lang",
            "en",
            "--save-session",
        ]
    )
    assert mock_args.scenario == "booking"
    assert mock_args.mock_llm is True
    assert mock_args.live is False
    assert mock_args.phone == "01012345678"
    assert mock_args.lang == "en"
    assert mock_args.save_session is True

    live_args = parser.parse_args(["--live", "--interactive", "--phone", "01122334455"])
    assert live_args.live is True
    assert live_args.interactive is True
    assert live_args.phone == "01122334455"

    for lk_mode in ("console", "dev", "start"):
        lk_args = parser.parse_args(["--livekit", lk_mode])
        assert lk_args.livekit == lk_mode


# ==============================================================================
# Tier 2: Integration Verification (T2.1, T2.2, T2.3, T2.4)
# ==============================================================================


@pytest.mark.asyncio
async def test_t2_1_booking_scenario_executes_availability_and_atomic_booking_with_queue():
    """T2.1: run_simulated_scenario('booking') books appointment with queue number via ClinicTurnEngine."""
    report = await run_simulated_scenario("booking")

    assert report.passed is True
    assert report.mode == "mock-llm"
    assert "check_doctor_availability" in report.tools_invoked
    assert "book_appointment" in report.tools_invoked
    assert len(report.booking_codes) == 1
    assert report.booking_codes[0].startswith("APT-")
    assert report.queue_numbers == [1]
    assert report.db_appointments_count == 1
    assert report.finops_tokens["total_tokens"] > 0
    assert len(report.trace_ids) == 3


@pytest.mark.asyncio
async def test_t2_1_manage_and_knowledge_scenarios_pass_end_to_end():
    """T2.1 (extended R2): manage and knowledge clinic scenarios execute cleanly via ClinicTurnEngine."""
    manage_report = await run_simulated_scenario("manage")
    assert manage_report.passed is True
    assert manage_report.tools_invoked.count("manage_appointment") == 2
    assert manage_report.session.context.bookings[-1].action == "rescheduled"

    kb_report = await run_simulated_scenario("knowledge")
    assert kb_report.passed is True
    assert "search_clinic_knowledge" in kb_report.tools_invoked
    assert len(kb_report.turns) == 2


@pytest.mark.asyncio
async def test_t2_2_emergency_and_guardrail_scenarios_enforce_safety_boundaries():
    """T2.2: emergency escalates immediately; guardrail blocks injection & medical diagnosis."""
    emg_report = await run_simulated_scenario("emergency")
    assert emg_report.passed is True
    assert emg_report.is_emergency is True
    assert emg_report.escalated is True
    assert "transfer_to_receptionist" in emg_report.tools_invoked
    assert "123" in emg_report.turns[0].assistant_response
    assert emg_report.finops_tokens["total_tokens"] == 0

    guard_report = await run_simulated_scenario("guardrail")
    assert guard_report.passed is True
    assert guard_report.tools_invoked == []
    assert guard_report.finops_tokens["total_tokens"] == 0
    assert all("API" not in t.assistant_response for t in guard_report.turns)


@pytest.mark.asyncio
async def test_t2_3_unverified_booking_allows_read_and_blocks_write_with_handoff():
    """T2.3: unverified caller checks availability (read allowed), booking blocked before DB write."""
    report = await run_simulated_scenario("unverified-booking")

    assert report.passed is True
    assert report.turns[0].tools_called == ["check_doctor_availability"]
    assert "book_appointment" not in report.tools_invoked
    assert "transfer_to_receptionist" in report.turns[1].tools_called
    assert report.db_appointments_count == 0
    assert report.booking_codes == []
    assert report.escalated is True


@pytest.mark.asyncio
async def test_t2_4_save_session_persists_pii_redacted_json_artifact(tmp_path: Path):
    """T2.4: save_session=True persists PII-redacted JSON where raw phone numbers are masked."""
    save_dir = tmp_path / "saved_calls"
    report = await run_simulated_scenario(
        "booking",
        save_session=True,
        storage_dir=save_dir,
    )

    assert report.passed is True
    assert report.persisted_session_path is not None
    saved_file = Path(report.persisted_session_path)
    assert saved_file.exists()
    assert saved_file.parent == save_dir

    raw_json_text = saved_file.read_text(encoding="utf-8")
    # Raw Egyptian phone number from booking scenario ("01012345678") must never appear unmasked
    assert "01012345678" not in raw_json_text
    payload = json.loads(raw_json_text)
    redacted_phone = payload["context"].get("patient_phone") or ""
    assert redacted_phone != ""
    assert "01012345678" not in redacted_phone
    assert len(payload["context"]["bookings"]) == 1

    # Verify save_session=False writes zero files to storage_dir
    unsaved_dir = tmp_path / "unsaved_calls"
    unsaved_dir.mkdir()
    unsaved_report = await run_simulated_scenario(
        "emergency",
        save_session=False,
        storage_dir=unsaved_dir,
    )
    assert unsaved_report.persisted_session_path is None
    assert list(unsaved_dir.glob("*.json")) == []


# ==============================================================================
# Tier 3: Error & Edge-Case Verification (T3.1, T3.2)
# ==============================================================================


@pytest.mark.asyncio
async def test_t3_1_live_mode_with_unset_api_keys_exits_cleanly_and_gateway_degrades(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """T3.1: --live without GROQ_API_KEY/GEMINI_API_KEY exits with clear message & zero traceback."""
    cli_mod = _load_test_call_module()

    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    unconfigured_settings = Settings(_env_file=None, groq_api_key="", gemini_api_key="")
    monkeypatch.setattr(cli_mod, "get_settings", lambda: unconfigured_settings)

    exit_code = cli_mod.main(["--live", "--scenario", "booking"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "GROQ_API_KEY" in captured.out
    assert "GEMINI_API_KEY" in captured.out
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err

    # Also verify programmatic live=True degrades gracefully through ModelGateway without traceback
    degraded_report = await run_simulated_scenario(
        "knowledge",
        live=True,
        settings_obj=unconfigured_settings,
    )
    assert len(degraded_report.turns) == 2
    assert all(bool(t.assistant_response.strip()) for t in degraded_report.turns)


def test_t3_2_unknown_scenario_prints_valid_names_and_exits_nonzero(
    capsys: pytest.CaptureFixture[str],
):
    """T3.2: --scenario nonexistent prints valid scenario names and exits with non-zero status code."""
    cli_mod = _load_test_call_module()

    exit_code = cli_mod.main(["--scenario", "nonexistent"])
    captured = capsys.readouterr()

    assert exit_code != 0
    for valid_name in CLINIC_SCENARIOS:
        assert valid_name in captured.out
