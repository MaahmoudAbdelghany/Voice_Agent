#!/usr/bin/env python3
"""
CLI Voice Agent Simulation & Live Runner.

Provides:
1. Interactive CLI Call Simulation:
   Direct console conversation with the Voice Agent (Arabic/English),
   simulating caller speech, LLM tool reasoning, real-time RAG retrieval,
   order tracking, table reservation, and human handoff.
2. Automated Test Scenarios:
   Pre-defined benchmark scenarios (menu inquiry, order tracking,
   table reservation, human handoff) to verify agent flow and tool execution.
3. LiveKit Agents Bridge:
   Direct pass-through to LiveKit's CLI console or worker daemon
   (python scripts/test_call.py --livekit console|start|dev).
4. Session Persistence & Analytics:
   Creates CallSession instances, logs turns, records latency,
   and exports call JSON reports to data/calls/ for dashboard analytics.
"""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

# Reconfigure stdout and stderr for UTF-8 on Windows consoles to prevent cp1256/cp1252 errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import settings
from src.agent.prompts import (
    build_error_fallback_message,
    build_greeting_message,
    build_handoff_message,
    get_system_prompt,
)
from src.agent.session_manager import (
    CallSession,
    CallStatus,
    MessageRole,
    session_manager,
)
from src.tools import (
    async_execute_tool,
    get_tool_definitions,
)

# Setup logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_call")


# ==============================================================================
# Terminal Color & Styling Utilities
# ==============================================================================

class Colors:
    """ANSI color codes for formatted terminal output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BG_BLUE = "\033[44m"


def print_banner(mode_name: str, language: str) -> None:
    """Print an attractive ASCII banner in terminal."""
    border = "=" * 76
    print(f"\n{Colors.CYAN}{Colors.BOLD}{border}")
    print(f"       🎙️  VOICE AI AGENT — CLI SIMULATION & TEST RUNNER")
    print(f"       Mode: {mode_name.upper()} | Language: {language.upper()} | Persona: {settings.agent_name}")
    print(f"{border}{Colors.RESET}\n")


# ==============================================================================
# Simulated Reasoning Engine (Rule + Keyword Intent Fallback)
# ==============================================================================

class SimulatedReasoningEngine:
    """
    Intelligent simulated reasoning engine for offline / keyless testing.
    Analyzes caller utterances, determines tool invocations, extracts parameters,
    and synthesizes natural conversational voice responses adhering to style guidelines.
    """

    def __init__(self, language: str = "ar") -> None:
        self.language = language

    async def process_turn(
        self,
        user_input: str,
        session: CallSession,
    ) -> Tuple[str, Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Process a user speech turn, determine tool call, and generate spoken response.

        Returns:
            Tuple of (assistant_spoken_response, tool_name, tool_args, tool_result_data).
        """
        text = user_input.strip()
        lower_text = text.lower()

        # 1. Check for Goodbye / Call Termination (if primarily a farewell)
        if any(w in lower_text for w in ["مع السلامة", "باي", "goodbye", "exit", "quit"]) or (
            any(w in lower_text for w in ["شكرا", "شكراً", "thanks", "thank you"]) and len(text.split()) <= 4
        ):
            if self.language == "ar":
                msg = f"العفو يا فندم! سعدت جداً بخدمتك اليوم في مطعم {settings.restaurant_name}. يومك سعيد وبانتظار زيارتك!"
            else:
                msg = f"You are very welcome! It was a pleasure assisting you today at {settings.restaurant_name}. Have a wonderful day!"
            return msg, None, None, None

        # 2. Check for Human Escalation Intent
        if any(w in lower_text for w in [
            "مشرف", "مدير", "إنسان", "خدمة العملاء", "موظف", "بني آدم", "شكوى", "أشتكي",
            "human", "agent", "manager", "supervisor", "representative", "complaint", "refund", "person"
        ]):
            tool_name = "escalate_to_human"
            dept = "kitchen_manager" if any(w in lower_text for w in ["أكل", "طعام", "سم", "بارد", "food", "kitchen"]) else "customer_support"
            urgency = "high" if any(w in lower_text for w in ["فورا", "فوراً", "ضروري", "urgent", "emergency", "غضبان", "angry"]) else "medium"
            args = {
                "reason": text,
                "department": dept,
                "customer_name": session.context.customer_name,
                "customer_phone": session.context.customer_phone,
                "urgency": urgency,
            }
            res = await async_execute_tool(tool_name, args)
            session.record_tool_call(tool_name, args, res.data or {})
            
            spoken_handoff = build_handoff_message(
                department_name=dept,
                estimated_wait_seconds=45,
                language=self.language,
            )
            response = f"{spoken_handoff} {res.message}"
            return response, tool_name, args, res.data

        # 3. Check for Reservation Intent
        if any(w in lower_text for w in ["حجز", "احجز", "طاولة", "ترابيزة", "reserve", "reservation", "book", "table"]):
            tool_name = "book_reservation"
            
            # Extract guest count
            guests = 2
            party_match = re.search(r"(\d+)\s*(أفراد|أشخاص|guests|people|persons)?", text, re.IGNORECASE)
            if party_match and party_match.group(1):
                try:
                    val = int(party_match.group(1))
                    if 1 <= val <= 30:
                        guests = val
                except ValueError:
                    pass
            elif any(w in lower_text for w in ["فردين", "شخصين", "two"]):
                guests = 2
            elif any(w in lower_text for w in ["أربعة", "أربع", "four"]):
                guests = 4

            # Extract name or default
            name = session.context.customer_name or "أحمد محمود"
            phone = session.context.customer_phone or "+201099887766"
            date_str = "2026-09-27"
            time_str = "20:00"
            
            time_match = re.search(r"(\d{1,2})(:|\s*)(\d{2})?\s*(مساء|صباحا|pm|am|بالليل)?", text, re.IGNORECASE)
            if time_match:
                hr = int(time_match.group(1))
                if ("مساء" in lower_text or "pm" in lower_text or "بالليل" in lower_text) and hr < 12:
                    hr += 12
                time_str = f"{hr:02d}:00"

            args = {
                "customer_name": name,
                "phone_number": phone,
                "party_size": guests,
                "date": date_str,
                "time": time_str,
                "branch": "الفرع الرئيسي",
                "special_requests": "جلسة هادئة",
            }
            res = await async_execute_tool(tool_name, args)
            session.record_tool_call(tool_name, args, res.data or {})
            return res.message, tool_name, args, res.data

        # 4. Check for Order Tracking Intent
        order_match = re.search(r"(ORD-\d{4}|\b\d{4}\b)", text, re.IGNORECASE)
        is_order_query = any(w in lower_text for w in ["طلب", "أوردر", "الطلب", "order", "delivery", "توصيل", "أين طلبي", "دليفري", "طيار", "سائق", "driver"])
        
        if order_match or (is_order_query and not any(w in lower_text for w in ["منيو", "menu", "قائمة", "أسعار", "نباتي"])):
            tool_name = "get_order_status"
            order_id = order_match.group(1).upper() if order_match else None
            if order_id and not order_id.startswith("ORD-"):
                order_id = f"ORD-{order_id}"
            
            phone = session.context.customer_phone or ("+201012345678" if not order_id else None)
            
            args = {
                "order_id": order_id or (session.context.order_id or "ORD-1001"),
                "phone": phone,
            }
            res = await async_execute_tool(tool_name, args)
            session.record_tool_call(tool_name, args, res.data or {})
            return res.message, tool_name, args, res.data

        # 5. Check for Pure Greeting (only if no specific action/item requested)
        is_pure_greeting = (
            len(text.split()) <= 4 and
            any(w in lower_text for w in ["أهلاً", "مرحبا", "سلام", "ازيك", "صباح الخير", "مساء الخير", "hello", "hi", "hey"]) and
            not any(w in lower_text for w in ["بيتزا", "شاورما", "منيو", "menu", "حجز", "طلب", "أوردر", "سعر"])
        )
        if is_pure_greeting:
            if self.language == "ar":
                msg = f"أهلاً بحضرتك يا فندم! معاك {settings.agent_name} من مطعم {settings.restaurant_name}. أقدر أساعدك في حجز طاولة، أو متابعة طلبك، أو استعراض المنيو؟"
            else:
                msg = f"Hello! I am {settings.agent_name} from {settings.restaurant_name}. I can help you with reservations, order tracking, or menu inquiries. How may I assist you?"
            return msg, None, None, None

        # 6. Default to Knowledge Search (Menu, Policies, Ingredients, Allergens, Hours)
        tool_name = "search_restaurant_knowledge"
        args = {"query": text}
        res = await async_execute_tool(tool_name, args)
        session.record_tool_call(tool_name, args, res.data or {})
        
        # Use formatted context or tool message
        msg = res.message
        if res.data and "formatted_context" in res.data and res.data["formatted_context"]:
            raw_ctx = res.data["formatted_context"]
            first_fact = raw_ctx.split("\n\n")[0].replace("#", "").replace("*", "").strip()
            if self.language == "ar":
                msg = f"بناءً على معلومات المنيو: {first_fact}. تحب حضرتك تفاصيل إضافية أو تجرب طبق معين؟"
            else:
                msg = f"According to our menu: {first_fact}. Would you like more details or another recommendation?"

        return msg, tool_name, args, res.data


# ==============================================================================
# Groq Cloud API LLM Reasoning Client
# ==============================================================================

class GroqReasoningClient:
    """
    Direct Groq Cloud API caller with tool-calling support.
    Used when GROQ_API_KEY is configured in settings or environment.
    """

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile") -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"

    async def call_groq(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Make an asynchronous request to Groq Cloud chat completions."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": settings.llm_temperature,
            "max_tokens": 512,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(self.endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def process_turn(
        self,
        user_input: str,
        session: CallSession,
        language: str = "ar",
    ) -> Tuple[str, Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Execute Groq turn with potential tool calling loop.
        """
        system_prompt = get_system_prompt(language=language)
        tool_defs = get_tool_definitions()

        # Build message history
        conversation = [{"role": "system", "content": system_prompt}]
        for m in session.messages[-8:]:
            if m.role in (MessageRole.USER, MessageRole.ASSISTANT):
                conversation.append({"role": m.role.value, "content": m.content})

        conversation.append({"role": "user", "content": user_input})

        try:
            # 1. Initial LLM reasoning
            result = await self.call_groq(conversation, tool_defs)
            choice = result["choices"][0]["message"]
            tool_calls = choice.get("tool_calls", [])

            # 2. Check if LLM requested a function call
            if tool_calls:
                call = tool_calls[0]
                tool_name = call["function"]["name"]
                args_str = call["function"]["arguments"]
                try:
                    args = json.loads(args_str)
                except Exception:
                    args = {"query": user_input}

                # Execute tool
                tool_res = await async_execute_tool(tool_name, args)
                tool_data = tool_res.data or {}
                session.record_tool_call(tool_name, args, tool_data, tool_call_id=call.get("id"))

                # Append tool call & result to conversation for final synthesis
                conversation.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [call],
                })
                conversation.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", "call_1"),
                    "name": tool_name,
                    "content": json.dumps(tool_data, ensure_ascii=False),
                })

                # 3. Final synthesis
                synthesis = await self.call_groq(conversation, tool_defs)
                reply = synthesis["choices"][0]["message"].get("content", "")
                if not reply or not reply.strip():
                    reply = tool_res.message

                return reply.strip(), tool_name, args, tool_data

            else:
                reply = choice.get("content", "")
                return reply.strip(), None, None, None

        except Exception as e:
            logger.error(f"Groq API call error: {e}. Falling back to simulated engine.")
            fallback = SimulatedReasoningEngine(language=language)
            return await fallback.process_turn(user_input, session)


# ==============================================================================
# Interactive Call Simulator Runner
# ==============================================================================

async def run_interactive_call(
    language: str = "ar",
    force_mock: bool = False,
    customer_phone: str = "+201012345678",
) -> CallSession:
    """
    Run an interactive turn-by-turn console telephone simulation.
    """
    print_banner("Interactive Telephone Call", language)

    # 1. Session initialization
    session_id = f"sim-{int(time.time())}"
    session = session_manager.create_session(
        session_id=session_id,
        room_name=f"room-{session_id}",
        participant_identity="cli_tester",
        language=language,
        customer_phone=customer_phone,
    )
    session.status = CallStatus.ACTIVE

    # 2. Reasoning engine selection
    use_groq = bool(settings.groq_api_key) and not force_mock
    if use_groq:
        engine_label = f"Groq Cloud ({settings.groq_model})"
        groq_client = GroqReasoningClient(api_key=settings.groq_api_key)
    else:
        engine_label = "Simulated Hybrid Reasoning Engine (Offline/Mock)"
        mock_engine = SimulatedReasoningEngine(language=language)

    print(f"{Colors.DIM}Connecting caller to voice server...{Colors.RESET}")
    print(f"{Colors.DIM}Engine: {engine_label} | Session ID: {session_id}{Colors.RESET}")
    print(f"{Colors.DIM}Type your message and press ENTER. Type 'exit' or 'bye' to hang up.{Colors.RESET}\n")

    # 3. Spoken greeting
    greeting = build_greeting_message(language=language)
    session.add_assistant_message(content=greeting)
    print(f"{Colors.YELLOW}{Colors.BOLD}🤖 [Agent]:{Colors.RESET} {greeting}\n")

    # 4. Interactive conversational turn loop
    turn_idx = 1
    while session.status not in (CallStatus.ENDED, CallStatus.ESCALATED):
        try:
            print(f"{Colors.GREEN}{Colors.BOLD}👤 [Caller]:{Colors.RESET} ", end="", flush=True)
            user_text = sys.stdin.readline()
            if not user_text:
                break
            user_text = user_text.strip()
            if not user_text:
                continue

            # Record user turn
            session.add_user_message(content=user_text)

            # Check exit
            if user_text.lower() in ["exit", "quit", "q"]:
                print(f"{Colors.DIM}Caller hung up the phone.{Colors.RESET}")
                break

            # Turn timing
            start_t = time.perf_counter()

            # Execute reasoning turn
            if use_groq:
                reply, tool_name, tool_args, tool_data = await groq_client.process_turn(
                    user_text, session, language=language
                )
            else:
                reply, tool_name, tool_args, tool_data = await mock_engine.process_turn(
                    user_text, session
                )

            latency_ms = round((time.perf_counter() - start_t) * 1000, 2)

            # Display tool activity if invoked
            if tool_name:
                print(f"{Colors.BLUE}{Colors.DIM}   ↳ [Tool Executed: {tool_name}] args={json.dumps(tool_args, ensure_ascii=False)}{Colors.RESET}")

            # Record assistant turn
            session.add_assistant_message(content=reply, latency_ms=latency_ms)

            # Display agent response with latency badge
            print(f"{Colors.YELLOW}{Colors.BOLD}🤖 [Agent]:{Colors.RESET} {reply} {Colors.DIM}({latency_ms}ms){Colors.RESET}\n")

            # Check if call was escalated or ended
            if session.context.escalated:
                print(f"{Colors.MAGENTA}{Colors.BOLD}⚠️ [Call Escalated to Human: {session.context.escalation_department}]{Colors.RESET}")
                session.end_call(CallStatus.ESCALATED)
                break

            turn_idx += 1

        except KeyboardInterrupt:
            print(f"\n{Colors.DIM}Call interrupted by user.{Colors.RESET}")
            break

    # 5. Finalize session and persist
    session.end_call()
    saved_path = session_manager.save_session(session.session_id)

    # 6. Display Call Summary
    print_call_summary(session, saved_path)
    return session


# ==============================================================================
# Automated Test Scenarios Runner
# ==============================================================================

SCENARIOS: Dict[str, List[Dict[str, Any]]] = {
    "menu": [
        {
            "user": "السلام عليكم، عندكم بيتزا إيه، وممكن أعرف أسعارها وهل في خيارات نباتية؟",
            "expected_tool": "search_restaurant_knowledge",
            "desc": "Menu inquiry & vegetarian dietary options via RAG",
        },
        {
            "user": "هل عندكم شاورما لحمة بالجبنة؟",
            "expected_tool": "search_restaurant_knowledge",
            "desc": "Specific item ingredient & allergen check",
        },
    ],
    "order": [
        {
            "user": "مساء الخير، لو سمحت عايز أعرف الأوردر بتاعي رقم ORD-1001 فين دلوقتي؟",
            "expected_tool": "get_order_status",
            "desc": "Real-time order lookup by ID",
        },
        {
            "user": "ممكن رقم الطيار اللي معاه الأوردر؟",
            "expected_tool": "get_order_status",
            "desc": "Driver details and ETA query",
        },
    ],
    "reservation": [
        {
            "user": "مساء الخير، عايز أحجز ترابيزة لـ 4 أفراد بكرة الساعة 8 بالليل في فرع وسط البلد باسم أحمد محمود",
            "expected_tool": "book_reservation",
            "desc": "Table booking with party size, date, and branch",
        },
    ],
    "escalation": [
        {
            "user": "الطلب جالي بارد جداً وفيه صنف ناقص وعايز أكلم المدير فوراً أشتكي!",
            "expected_tool": "escalate_to_human",
            "desc": "Urgent complaint escalating to human kitchen supervisor",
        },
    ],
}


async def run_automated_scenarios(
    scenario_name: str = "all",
    language: str = "ar",
    force_mock: bool = True,
) -> bool:
    """
    Run automated multi-turn test scenarios and print test verdict.
    """
    print_banner(f"Automated Scenario Benchmark: {scenario_name}", language)

    target_scenarios = SCENARIOS if scenario_name == "all" else {scenario_name: SCENARIOS.get(scenario_name, [])}
    if not target_scenarios or not any(target_scenarios.values()):
        print(f"{Colors.RED}Unknown scenario '{scenario_name}'. Available: {list(SCENARIOS.keys()) + ['all']}{Colors.RESET}")
        return False

    all_passed = True
    total_turns_tested = 0

    session_id = f"auto-{int(time.time())}"
    session = session_manager.create_session(
        session_id=session_id,
        room_name=f"test-suite-{session_id}",
        participant_identity="automated_tester",
        language=language,
    )
    engine = SimulatedReasoningEngine(language=language)

    greeting = build_greeting_message(language=language)
    session.add_assistant_message(content=greeting)

    print(f"{Colors.DIM}Initial Greeting:{Colors.RESET} {greeting}\n")

    for s_name, turns in target_scenarios.items():
        print(f"{Colors.CYAN}{Colors.BOLD}▶ Running Scenario: [{s_name.upper()}]{Colors.RESET}")
        for i, turn in enumerate(turns, 1):
            total_turns_tested += 1
            user_msg = turn["user"]
            expected_tool = turn["expected_tool"]
            desc = turn["desc"]

            print(f"  {Colors.BOLD}Turn {i}: {desc}{Colors.RESET}")
            print(f"  {Colors.GREEN}👤 [Caller]:{Colors.RESET} {user_msg}")

            session.add_user_message(content=user_msg)
            start_t = time.perf_counter()
            reply, tool_name, tool_args, tool_data = await engine.process_turn(user_msg, session)
            latency_ms = round((time.perf_counter() - start_t) * 1000, 2)

            session.add_assistant_message(content=reply, latency_ms=latency_ms)

            # Check assertion
            tool_match = (tool_name == expected_tool)
            if tool_match:
                status_badge = f"{Colors.GREEN}✔ PASSED{Colors.RESET}"
            else:
                status_badge = f"{Colors.RED}✘ FAILED (Expected {expected_tool}, got {tool_name}){Colors.RESET}"
                all_passed = False

            print(f"  {Colors.YELLOW}🤖 [Agent]:{Colors.RESET} {reply}")
            print(f"  {Colors.BLUE}🛠️  [Tool]: {tool_name} {status_badge} ({latency_ms}ms){Colors.RESET}\n")

    session.end_call()
    saved_path = session_manager.save_session(session.session_id)
    print_call_summary(session, saved_path)

    verdict_color = Colors.GREEN if all_passed else Colors.RED
    print(f"{verdict_color}{Colors.BOLD}Scenarios Execution Finished: {'ALL TESTS PASSED ✔' if all_passed else 'SOME TESTS FAILED ✘'}{Colors.RESET}\n")
    return all_passed


# ==============================================================================
# Summary Reporting Utility
# ==============================================================================

def print_call_summary(session: CallSession, saved_path: Optional[os.PathLike] = None) -> None:
    """Print structured call summary and metrics."""
    metrics = session.metrics
    border = "-" * 76
    print(f"\n{Colors.CYAN}{border}")
    print(f"📊 CALL SESSION SUMMARY & PERFORMANCE METRICS")
    print(border)
    print(f"  • Session ID:            {session.session_id}")
    print(f"  • Status:                {session.status.value.upper()}")
    print(f"  • Duration:              {metrics.duration_seconds:.2f} seconds")
    print(f"  • Total Turns:           {metrics.total_user_turns} Caller / {metrics.total_assistant_turns} Agent")
    print(f"  • Tool Invocations:      {metrics.total_tool_calls}")
    print(f"  • Average Turn Latency:  {metrics.average_latency_ms:.2f} ms (Max: {metrics.max_latency_ms:.2f} ms)")
    print(f"  • Escalated to Human:    {'YES (' + str(session.context.escalation_department) + ')' if session.context.escalated else 'NO'}")
    if saved_path:
        print(f"  • Persisted Artifact:    {saved_path}")
    print(f"{border}{Colors.RESET}\n")


# ==============================================================================
# LiveKit CLI Bridge Pass-through
# ==============================================================================

def run_livekit_bridge(args_list: List[str]) -> None:
    """
    Bridge directly to LiveKit Agents CLI runner (src.agent.voice_agent).
    Allows running: python scripts/test_call.py livekit [console|start|dev].
    """
    from src.agent.voice_agent import run_worker
    print(f"{Colors.CYAN}Delegating to LiveKit Agents CLI runner with arguments: {args_list}{Colors.RESET}")
    # Update sys.argv so livekit.agents.cli parses properly
    sys.argv = ["voice_agent.py"] + args_list
    run_worker()


# ==============================================================================
# CLI Entry Point & Argument Parser
# ==============================================================================

def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Voice AI Agent CLI Simulation & Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 1. Interactive voice agent conversation (default Arabic)
  python scripts/test_call.py

  # 2. Interactive conversation in English
  python scripts/test_call.py --lang en

  # 3. Run automated scenario tests (menu, order, reservation, escalation, or all)
  python scripts/test_call.py --scenario all
  python scripts/test_call.py --scenario menu
  python scripts/test_call.py --scenario order
  python scripts/test_call.py --scenario reservation

  # 4. Bridge to LiveKit CLI console or worker daemon
  python scripts/test_call.py livekit console
  python scripts/test_call.py livekit start
        """,
    )

    parser.add_argument(
        "subcommand",
        nargs="?",
        default="interactive",
        choices=["interactive", "scenario", "livekit"],
        help="Subcommand mode: interactive (default), scenario, or livekit",
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        choices=["all", "menu", "order", "reservation", "escalation"],
        help="Target benchmark scenario for automated testing",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="ar",
        choices=["ar", "en"],
        help="Language for conversation ('ar' for Arabic, 'en' for English)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force simulated offline reasoning engine even if API keys are present",
    )
    parser.add_argument(
        "--phone",
        type=str,
        default="+201012345678",
        help="Caller phone number to simulate for context",
    )
    parser.add_argument(
        "livekit_args",
        nargs="*",
        help="Arguments to pass through when subcommand is 'livekit' (e.g. console, start, dev)",
    )

    args = parser.parse_args()

    # Mode 1: LiveKit CLI bridge
    if args.subcommand == "livekit" or (len(sys.argv) > 1 and sys.argv[1] == "livekit"):
        livekit_cmd = args.livekit_args or ["console"]
        run_livekit_bridge(livekit_cmd)
        return

    # Mode 2: Automated Scenarios
    if args.subcommand == "scenario" or "--scenario" in sys.argv:
        target = args.scenario if args.scenario != "all" else "all"
        success = asyncio.run(
            run_automated_scenarios(scenario_name=target, language=args.lang, force_mock=args.mock)
        )
        sys.exit(0 if success else 1)

    # Mode 3: Interactive Simulation (Default)
    asyncio.run(
        run_interactive_call(
            language=args.lang,
            force_mock=args.mock,
            customer_phone=args.phone,
        )
    )


if __name__ == "__main__":
    main()
