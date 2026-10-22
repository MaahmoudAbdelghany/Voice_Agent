"""
Centralized Tool Registry and Exports for Voice Agent.

Exposes domain tools, Pydantic schemas, and unified execution dispatchers
for real-time LLM function calling (LiveKit Agents, Groq, and OpenAI formats).
"""

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from src.tools.appointment_booking import (
    AppointmentBookingTool,
    appointment_booking_tool,
    async_book_appointment,
    book_appointment,
)
from src.tools.doctor_availability import (
    DoctorAvailabilityTool,
    async_check_doctor_availability,
    check_doctor_availability,
    doctor_availability_tool,
)
from src.tools.human_handoff import (
    HumanHandoffTool,
    async_escalate_to_human,
    escalate_to_human,
    human_handoff_tool,
)

# Tools implementations
from src.tools.knowledge_search import (
    ClinicKnowledgeSearchTool,
    KnowledgeSearchTool,
    async_search_clinic_knowledge,
    async_search_knowledge,
    async_search_restaurant_knowledge,
    clinic_knowledge_search_tool,
    knowledge_search_tool,
    search_clinic_knowledge,
    search_knowledge,
    search_restaurant_knowledge,
)

# Legacy restaurant schemas (deprecated; removed once Features 3.2-3.6 land)
from src.tools.legacy_schemas import (
    HandoffDepartmentEnum,
    HandoffUrgencyEnum,
    HumanHandoffInput,
    HumanHandoffOutput,
    KnowledgeChunk,
    KnowledgeSearchInput,
    KnowledgeSearchOutput,
    OrderItem,
    OrderStatusEnum,
    OrderStatusInput,
    OrderStatusOutput,
    ReservationInput,
    ReservationOutput,
    ReservationStatusEnum,
)
from src.tools.manage_appointment import (
    ManageAppointmentTool,
    async_manage_appointment,
    manage_appointment,
    manage_appointment_tool,
)
from src.tools.order_status import (
    OrderStatusTool,
    async_get_order_status,
    get_order_status,
    order_status_tool,
)
from src.tools.reservation import (
    ReservationTool,
    async_book_reservation,
    book_reservation,
    reservation_tool,
)

# Clinic domain schemas (Feature 3.1)
from src.tools.schemas import (
    AppointmentBookingInput,
    AppointmentBookingOutput,
    AppointmentCancelInput,
    AppointmentLookupInput,
    AppointmentRescheduleInput,
    ClinicKnowledgeSearchInput,
    ClinicKnowledgeSearchOutput,
    DoctorAvailabilityInput,
    DoctorAvailabilityOutput,
    ManageAppointmentAction,
    ManageAppointmentInput,
    ManageAppointmentOutput,
    ReceptionistHandoffInput,
    ReceptionistHandoffOutput,
    ToolResult,
    parse_colloquial_date,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Metadata and execution bindings for a registered voice tool."""

    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    sync_callable: Callable[..., Any]
    async_callable: Callable[..., Any]

    def to_openai_dict(self) -> dict[str, Any]:
        """Format as OpenAI/Groq function calling schema."""
        parameters = self.input_schema.model_json_schema()
        # Remove top-level title and schema version for compact clean payload
        parameters.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


# ==============================================================================
# Master Tool Registry
# ==============================================================================

TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "search_clinic_knowledge": ToolDefinition(
        name="search_clinic_knowledge",
        description=(
            "Search Egyptian polyclinic medical center knowledge base for specialties, "
            "doctor shifts, diagnostic preparation (fasting, sonar), consultation and "
            "examination fees, accepted health insurance networks, address, and clinic policies."
        ),
        input_schema=ClinicKnowledgeSearchInput,
        output_schema=ClinicKnowledgeSearchOutput,
        sync_callable=search_clinic_knowledge,
        async_callable=async_search_clinic_knowledge,
    ),
    "get_order_status": ToolDefinition(
        name="get_order_status",
        description=(
            "Look up real-time customer order status, delivery driver contact, "
            "and estimated delivery time by order ID (e.g. ORD-1001) or phone number."
        ),
        input_schema=OrderStatusInput,
        output_schema=OrderStatusOutput,
        sync_callable=get_order_status,
        async_callable=async_get_order_status,
    ),
    "book_reservation": ToolDefinition(
        name="book_reservation",
        description=(
            "Check table availability and book table reservations at restaurant "
            "branches for a specific date, time slot, and party size (1-30 guests)."
        ),
        input_schema=ReservationInput,
        output_schema=ReservationOutput,
        sync_callable=book_reservation,
        async_callable=async_book_reservation,
    ),
    "escalate_to_human": ToolDefinition(
        name="escalate_to_human",
        description=(
            "Escalate the call to a live human representative or specialist department "
            "(Customer Support, Kitchen Manager, Delivery Dispatch, Billing) for complex "
            "complaints, critical food allergies, or billing issues."
        ),
        input_schema=HumanHandoffInput,
        output_schema=HumanHandoffOutput,
        sync_callable=escalate_to_human,
        async_callable=async_escalate_to_human,
    ),
    "check_doctor_availability": ToolDefinition(
        name="check_doctor_availability",
        description=(
            "Check doctor availability, weekly shift hours, remaining patient slots, "
            "and examination fees for Egyptian polyclinic doctors and specialties."
        ),
        input_schema=DoctorAvailabilityInput,
        output_schema=DoctorAvailabilityOutput,
        sync_callable=check_doctor_availability,
        async_callable=async_check_doctor_availability,
    ),
    "book_appointment": ToolDefinition(
        name="book_appointment",
        description=(
            "Book a confirmed clinic appointment (queue number) for a patient with a doctor "
            "on a specific date. Requires patient name, Egyptian mobile number, doctor ID or "
            "name, date, and visit type ('examination' or 'consultation'). Never books an "
            "alternative date automatically; confirm with the caller first."
        ),
        input_schema=AppointmentBookingInput,
        output_schema=AppointmentBookingOutput,
        sync_callable=book_appointment,
        async_callable=async_book_appointment,
    ),
    "manage_appointment": ToolDefinition(
        name="manage_appointment",
        description=(
            "Look up, cancel, or reschedule existing patient clinic appointments. "
            "Action 'lookup' queries by booking code or patient mobile phone. "
            "Action 'cancel' cancels an appointment by booking code or phone number. "
            "Action 'reschedule' moves a booking to a new date with the same doctor."
        ),
        input_schema=ManageAppointmentInput,
        output_schema=ManageAppointmentOutput,
        sync_callable=manage_appointment,
        async_callable=async_manage_appointment,
    ),
}


def get_registered_tools() -> dict[str, ToolDefinition]:
    """Retrieve all currently registered tools."""
    return TOOL_REGISTRY


def get_tool_definitions() -> list[dict[str, Any]]:
    """
    Get all tool definitions formatted for OpenAI / Groq function calling.
    """
    return [tool.to_openai_dict() for tool in TOOL_REGISTRY.values()]


def execute_tool(tool_name: str, arguments: dict[str, Any]) -> ToolResult:
    """
    Synchronously execute a registered tool by name with given arguments.

    Args:
        tool_name: Name of tool in registry.
        arguments: Raw or parsed dictionary of input parameters.

    Returns:
        ToolResult with standard envelope.
    """
    tool_def = TOOL_REGISTRY.get(tool_name)
    if not tool_def:
        err_msg = f"Tool '{tool_name}' is not registered. Available tools: {list(TOOL_REGISTRY.keys())}"
        logger.error(err_msg)
        return ToolResult(success=False, message="عذراً، هذه الأداة غير متاحة حالياً.", error=err_msg)

    try:
        # Validate inputs against schema
        validated_args = tool_def.input_schema.model_validate(arguments)
        args_dict = validated_args.model_dump(exclude_unset=True)

        result = tool_def.sync_callable(**args_dict)

        if isinstance(result, ToolResult):
            return result

        # Convert tool output to dict payload
        payload = result.model_dump() if hasattr(result, "model_dump") else result
        voice_msg = getattr(result, "message", "تم تنفيذ العملية بنجاح.")

        return ToolResult(
            success=True,
            message=voice_msg,
            data=payload if isinstance(payload, dict) else {"result": payload},
        )
    except Exception as e:
        logger.exception("Error executing tool '%s' with args %s", tool_name, arguments)
        return ToolResult(
            success=False,
            message="عذراً، حدث خطأ أثناء تنفيذ هذا الإجراء. هل يمكنك إعادة المحاولة؟",
            error=str(e),
        )


async def async_execute_tool(tool_name: str, arguments: dict[str, Any]) -> ToolResult:
    """
    Asynchronously execute a registered tool by name (non-blocking for LiveKit turns).

    Args:
        tool_name: Name of tool in registry.
        arguments: Raw or parsed dictionary of input parameters.

    Returns:
        ToolResult with standard envelope.
    """
    tool_def = TOOL_REGISTRY.get(tool_name)
    if not tool_def:
        err_msg = f"Tool '{tool_name}' is not registered. Available tools: {list(TOOL_REGISTRY.keys())}"
        logger.error(err_msg)
        return ToolResult(success=False, message="عذراً، هذه الأداة غير متاحة حالياً.", error=err_msg)

    try:
        validated_args = tool_def.input_schema.model_validate(arguments)
        args_dict = validated_args.model_dump(exclude_unset=True)

        if inspect.iscoroutinefunction(tool_def.async_callable):
            result = await tool_def.async_callable(**args_dict)
        else:
            result = tool_def.async_callable(**args_dict)

        if isinstance(result, ToolResult):
            return result

        payload = result.model_dump() if hasattr(result, "model_dump") else result
        voice_msg = getattr(result, "message", "تم تنفيذ العملية بنجاح.")

        return ToolResult(
            success=True,
            message=voice_msg,
            data=payload if isinstance(payload, dict) else {"result": payload},
        )
    except Exception as e:
        logger.exception("Error in async tool execution '%s'", tool_name)
        return ToolResult(
            success=False,
            message="عذراً، حدث خطأ أثناء تنفيذ هذا الإجراء. هل يمكنك إعادة المحاولة؟",
            error=str(e),
        )


__all__ = [  # noqa: RUF022
    # Clinic Schemas (Feature 3.1)
    "ToolResult",
    "parse_colloquial_date",
    "DoctorAvailabilityInput",
    "DoctorAvailabilityOutput",
    "AppointmentBookingInput",
    "AppointmentBookingOutput",
    "AppointmentLookupInput",
    "AppointmentCancelInput",
    "AppointmentRescheduleInput",
    "ManageAppointmentAction",
    "ManageAppointmentInput",
    "ManageAppointmentOutput",
    "ClinicKnowledgeSearchInput",
    "ClinicKnowledgeSearchOutput",
    "ReceptionistHandoffInput",
    "ReceptionistHandoffOutput",
    # Legacy Schemas (deprecated)
    "KnowledgeSearchInput",
    "KnowledgeSearchOutput",
    "KnowledgeChunk",
    "OrderStatusInput",
    "OrderStatusOutput",
    "OrderItem",
    "OrderStatusEnum",
    "ReservationInput",
    "ReservationOutput",
    "ReservationStatusEnum",
    "HumanHandoffInput",
    "HumanHandoffOutput",
    "HandoffUrgencyEnum",
    "HandoffDepartmentEnum",
    # Tools Classes & Singletons
    "DoctorAvailabilityTool",
    "doctor_availability_tool",
    "AppointmentBookingTool",
    "appointment_booking_tool",
    "ManageAppointmentTool",
    "manage_appointment_tool",
    "ClinicKnowledgeSearchTool",
    "clinic_knowledge_search_tool",
    "KnowledgeSearchTool",
    "knowledge_search_tool",
    "OrderStatusTool",
    "order_status_tool",
    "ReservationTool",
    "reservation_tool",
    "HumanHandoffTool",
    "human_handoff_tool",
    # Functions
    "check_doctor_availability",
    "async_check_doctor_availability",
    "book_appointment",
    "async_book_appointment",
    "manage_appointment",
    "async_manage_appointment",
    "search_clinic_knowledge",
    "async_search_clinic_knowledge",
    "search_knowledge",
    "async_search_knowledge",
    "search_restaurant_knowledge",
    "async_search_restaurant_knowledge",
    "get_order_status",
    "async_get_order_status",
    "book_reservation",
    "async_book_reservation",
    "escalate_to_human",
    "async_escalate_to_human",
    # Registry & Dispatchers
    "ToolDefinition",
    "TOOL_REGISTRY",
    "get_registered_tools",
    "get_tool_definitions",
    "execute_tool",
    "async_execute_tool",
]
