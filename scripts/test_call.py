"""
CLI Simulated Call Runner for Egyptian Polyclinic Voice Agent (Feature 5.5).

Executes multi-turn clinic scenarios (`booking`, `manage`, `knowledge`, `emergency`,
`guardrail`, `unverified-booking`) or an interactive console conversation through the
production `ClinicTurnEngine`, or bridges directly to the LiveKit worker CLI.

Usage examples:
    uv run python scripts/test_call.py --scenario booking
    uv run python scripts/test_call.py --scenario emergency
    uv run python scripts/test_call.py --scenario unverified-booking
    uv run python scripts/test_call.py --scenario all
    uv run python scripts/test_call.py --scenario booking --save-session
    uv run python scripts/test_call.py --interactive --phone 01012345678 --lang ar
    uv run python scripts/test_call.py --live --scenario knowledge
    uv run python scripts/test_call.py --livekit console
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from src.agent.prompts import build_greeting_message
from src.agent.scenarios import (
    CLINIC_SCENARIOS,
    ScenarioRunReport,
    build_turn_engine_for_mode,
    is_live_llm_configured,
    isolated_clinic_environment,
    run_all_scenarios,
    run_simulated_scenario,
)
from src.agent.session_manager import CallLifecycle, SessionManager
from src.agent.turn_engine import VerifiedCallerIdentity
from src.agent.voice_agent import handle_session_close, run_worker
from src.config import get_settings


def build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the `scripts/test_call.py` CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="test_call.py",
        description=(
            "Simulated Call Runner & Clinic Benchmark Scenarios for the Egyptian Polyclinic "
            "Voice Agent (powered by ClinicTurnEngine)."
        ),
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=None,
        help=(
            "Benchmark scenario key to execute: "
            f"{', '.join(CLINIC_SCENARIOS.keys())}, or 'all'."
        ),
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--mock-llm",
        dest="mock_llm",
        action="store_true",
        default=False,
        help="Run offline with deterministic ScriptedClinicLLMProvider (default mode).",
    )
    mode_group.add_argument(
        "--live",
        dest="live",
        action="store_true",
        default=False,
        help="Route LLM turns through LiteLLMProvider (Groq primary / Gemini fallback).",
    )

    parser.add_argument(
        "--interactive",
        action="store_true",
        default=False,
        help="Start an interactive terminal chat loop driving ClinicTurnEngine turn-by-turn.",
    )
    parser.add_argument(
        "--phone",
        type=str,
        default=None,
        help="Verified caller phone number for --interactive mode (omit to simulate unverified caller).",
    )
    parser.add_argument(
        "--lang",
        choices=["ar", "en"],
        default="ar",
        help="Conversation language ('ar' or 'en', default: 'ar').",
    )
    parser.add_argument(
        "--save-session",
        dest="save_session",
        action="store_true",
        default=False,
        help="Persist PII-redacted CallSession JSON report via SessionManager.",
    )
    parser.add_argument(
        "--storage-dir",
        dest="storage_dir",
        type=str,
        default=None,
        help="Optional output directory override when --save-session is enabled.",
    )
    parser.add_argument(
        "--use-default-db",
        dest="use_default_db",
        action="store_true",
        default=False,
        help="Use configured SQLite database instead of an isolated seeded temporary DB.",
    )
    parser.add_argument(
        "--livekit",
        choices=["console", "dev", "start"],
        default=None,
        help="Pass control directly to the LiveKit voice worker CLI (src.agent.voice_agent).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Enable INFO-level runtime logs during scenario execution.",
    )
    return parser


def format_scenario_report(report: ScenarioRunReport) -> str:
    """Format a human-readable transcript and assertion block for a single scenario run."""
    status_badge = "PASS" if report.passed else "FAIL"
    lines: list[str] = [
        "=" * 88,
        f"[{status_badge}] Scenario: {report.scenario_key} — {report.title} (mode={report.mode})",
        "-" * 88,
    ]
    for turn in report.turns:
        tools_str = ", ".join(turn.tools_called) if turn.tools_called else "none"
        lines.append(f"  Turn {turn.turn_index} ({turn.latency_ms:.1f} ms | tools: {tools_str})")
        lines.append(f"    Caller : {turn.user_utterance}")
        lines.append(f"    Agent  : {turn.assistant_response}")

    lines.append("-" * 88)
    booking_summary = (
        ", ".join(
            f"{code} (queue #{q})"
            for code, q in zip(report.booking_codes, report.queue_numbers, strict=False)
        )
        if report.booking_codes and report.queue_numbers
        else (", ".join(report.booking_codes) if report.booking_codes else "none")
    )
    lines.append(
        f"  Bookings: {booking_summary} | DB Appointments: {report.db_appointments_count} | "
        f"Emergency: {report.is_emergency} | Escalated: {report.escalated} | "
        f"Lifecycle: {report.lifecycle}"
    )
    if report.persisted_session_path:
        lines.append(f"  Persisted Session JSON: {report.persisted_session_path}")

    lines.append("  Assertions:")
    for assertion in report.assertions:
        mark = "PASS" if assertion.passed else "FAIL"
        lines.append(f"    [{mark}] {assertion.name} ({assertion.detail})")
    return "\n".join(lines)


def format_summary_table(reports: Sequence[ScenarioRunReport]) -> str:
    """Render a compact summary table of latencies, tools executed, and FinOps token usage."""
    header = (
        f"{'Scenario':<20} | {'Status':<6} | {'Turns':>5} | "
        f"{'Avg/Max ms':>14} | {'Tokens':>8} | {'DB Appts':>8} | Tools Executed"
    )
    sep = "-" * max(len(header) + 18, 96)
    rows: list[str] = ["\n" + sep, "CLINIC SCENARIO TELEMETRY SUMMARY", sep, header, sep]
    for rep in reports:
        status = "PASS" if rep.passed else "FAIL"
        avg_ms = rep.latency_summary_ms.get("avg_ms", 0.0)
        max_ms = rep.latency_summary_ms.get("max_ms", 0.0)
        lat_cell = f"{avg_ms:.1f}/{max_ms:.1f}"
        tot_tokens = rep.finops_tokens.get("total_tokens", 0)
        tools_cell = ", ".join(rep.tools_invoked) if rep.tools_invoked else "none"
        rows.append(
            f"{rep.scenario_key:<20} | {status:<6} | {len(rep.turns):>5} | "
            f"{lat_cell:>14} | {tot_tokens:>8} | {rep.db_appointments_count:>8} | {tools_cell}"
        )
    rows.append(sep)
    passed_count = sum(1 for r in reports if r.passed)
    rows.append(f"Total: {passed_count}/{len(reports)} scenarios passed.")
    return "\n".join(rows)


async def _run_interactive_loop(
    *,
    live: bool,
    phone: str | None,
    lang: str,
    save_session: bool,
    storage_dir: str | None,
    use_default_db: bool,
) -> int:
    """Run an interactive terminal chat loop driving `ClinicTurnEngine` turn-by-turn."""
    settings = get_settings()
    identity = VerifiedCallerIdentity(
        caller_phone=phone,
        caller_name=None,
        language=lang,
        source="jwt" if phone else "unverified",
    )

    async with isolated_clinic_environment(use_default_db=use_default_db):
        engine, _ = build_turn_engine_for_mode(live=live, settings_obj=settings)
        with contextlib.ExitStack() as stack:
            if save_session:
                target_dir = (
                    Path(storage_dir)
                    if storage_dir is not None
                    else Path(settings.session_storage_dir)
                )
            else:
                tmp_dir = stack.enter_context(
                    tempfile.TemporaryDirectory(prefix="clinic_interactive_calls_")
                )
                target_dir = Path(tmp_dir)

            session_mgr = SessionManager(storage_dir=target_dir)
            call_session = session_mgr.create_session(
                room_name="interactive-cli",
                participant_identity="cli-caller",
                language=lang,
                patient_phone=phone,
            )
            call_session.transition_to(CallLifecycle.ACTIVE)

            mode_label = "live" if live else "mock-llm"
            phone_label = (
                f"***{identity.caller_phone[-4:]}"
                if identity.is_verified and identity.caller_phone
                else "unverified"
            )
            print(
                f"=== Clinic Interactive Call Simulator (mode={mode_label}, "
                f"caller={phone_label}, lang={lang}) ==="
            )
            print("Type 'exit', 'quit', or 'خروج' to end the call.\n")

            greeting = build_greeting_message(language=lang)
            call_session.add_assistant_message(greeting)
            print(f"Agent  > {greeting}\n")

            while True:
                try:
                    raw = await asyncio.to_thread(input, "Caller > ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break

                utterance = raw.strip()
                if not utterance:
                    continue
                if utterance.lower() in {"exit", "quit", "خروج"}:
                    break

                print("Agent  > ", end="", flush=True)
                async for chunk in engine.run_turn(
                    utterance=utterance,
                    call_session=call_session,
                    caller_identity=identity,
                ):
                    print(chunk, end="", flush=True)
                print("\n")

            engine_snap = engine.finops.get_session_snapshot(call_session.session_id)
            if engine_snap is not None:
                call_session.metrics.finops_snapshot = engine_snap.model_dump()

            if save_session:
                saved = await handle_session_close(call_session, manager=session_mgr)
                if saved is not None:
                    print(f"Saved PII-redacted session report: {saved}")
            else:
                target_lc = (
                    CallLifecycle.ESCALATED
                    if (
                        call_session.lifecycle == CallLifecycle.ESCALATED
                        or call_session.context.escalated
                    )
                    else CallLifecycle.ENDED
                )
                call_session.end_call(status=target_lc)

            snap = (
                (engine_snap.model_dump() if engine_snap is not None else None)
                or call_session.metrics.finops_snapshot
                or call_session.refresh_finops_snapshot()
                or {}
            )
            print(
                f"Call ended ({call_session.lifecycle.value}) | "
                f"turns={getattr(call_session.metrics, 'turn_count', call_session.metrics.total_user_turns)} | "
                f"tools={call_session.metrics.total_tool_calls} | "
                f"tokens={snap.get('total_tokens', 0)}"
            )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint returning `0` on success and non-zero on assertion or argument errors."""
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.ERROR,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.livekit is not None:
        sys.argv = [sys.argv[0], args.livekit]
        run_worker()
        return 0

    use_live = bool(args.live and not args.mock_llm)
    settings = get_settings()

    if use_live and not is_live_llm_configured(settings):
        print(
            "Configuration error: --live mode requires GROQ_API_KEY or GEMINI_API_KEY to be set "
            "in the environment or .env file. Use --mock-llm (default) for offline execution."
        )
        return 2

    if args.interactive:
        return asyncio.run(
            _run_interactive_loop(
                live=use_live,
                phone=args.phone,
                lang=args.lang,
                save_session=args.save_session,
                storage_dir=args.storage_dir,
                use_default_db=args.use_default_db,
            )
        )

    scenario_arg = (args.scenario or "all").strip().lower()
    valid_scenarios = list(CLINIC_SCENARIOS.keys())
    if scenario_arg != "all" and scenario_arg not in CLINIC_SCENARIOS:
        print(
            f"Unknown scenario '{args.scenario}'. "
            f"Valid scenario names: {', '.join(valid_scenarios)}, all"
        )
        return 2

    language_override = args.lang if (argv is not None and "--lang" in argv) or "--lang" in sys.argv[1:] else None

    if scenario_arg == "all":
        reports = asyncio.run(
            run_all_scenarios(
                live=use_live,
                save_session=args.save_session,
                storage_dir=args.storage_dir,
                use_default_db=args.use_default_db,
                language=language_override,
                settings_obj=settings,
            )
        )
    else:
        single_report = asyncio.run(
            run_simulated_scenario(
                scenario_arg,
                live=use_live,
                save_session=args.save_session,
                storage_dir=args.storage_dir,
                use_default_db=args.use_default_db,
                language=language_override,
                settings_obj=settings,
            )
        )
        reports = [single_report]

    for rep in reports:
        print(format_scenario_report(rep))
    print(format_summary_table(reports))

    return 0 if all(rep.passed for rep in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
