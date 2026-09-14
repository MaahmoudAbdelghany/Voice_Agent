"""
Centralized Tool Registry and Exports for Voice Agent.

Exposes domain tools, Pydantic schemas, and unified execution dispatchers
for real-time LLM function calling (LiveKit Agents, Groq, and OpenAI formats).
"""

import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel

# Schemas
from src.tools.schemas import (
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
    ToolResult,
)

# Tools implementations
from src.tools.knowledge_search import (
    KnowledgeSearchTool,
    async_search_knowledge,
    async_search_restaurant_knowledge,
    knowledge_search_tool,
    search_knowledge,
    search_restaurant_knowledge,
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
from src.tools.human_handoff import (
    HumanHandoffTool,
    async_escalate_to_human,
    escalate_to_human,
    human_handoff_tool,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Metadata and execution bindings for a registered voice tool."""

    name: str
    description: str
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    sync_callable: Callable[..., Any]
    async_callable: Callable[..., Any]

    def to_openai_dict(self) -> Dict[str, Any]:
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

TOOL_REGISTRY: Dict[str, ToolDefinition] = {
    "search_restaurant_knowledge": ToolDefinition(
        name="search_restaurant_knowledge",
        description=(
            "Search restaurant menu items, ingredients, prices, allergens, "
            "operating hours, delivery areas, and branch policies via RAG."
        ),
        input_schema=KnowledgeSearchInput,
        output_schema=KnowledgeSearchOutput,
        sync_callable=search_restaurant_knowledge,
        async_callable=async_search_restaurant_knowledge,
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
}


def get_registered_tools() -> Dict[str, ToolDefinition]:
    """Retrieve all currently registered tools."""
    return TOOL_REGISTRY


def get_tool_definitions() -> List[Dict[str, Any]]:
    """
    Get all tool definitions formatted for OpenAI / Groq function calling.
    """
    return [tool.to_openai_dict() for tool in TOOL_REGISTRY.values()]


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
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

        # Convert tool output to dict payload
        payload = result.model_dump() if hasattr(result, "model_dump") else result
        voice_msg = getattr(result, "message", "تم تنفيذ العملية بنجاح.")

        return ToolResult(
            success=True,
            message=voice_msg,
            data=payload if isinstance(payload, dict) else {"result": payload},
        )
    except Exception as e:
        logger.exception(f"Error executing tool '{tool_name}' with args {arguments}: {e}")
        return ToolResult(
            success=False,
            message="عذراً، حدث خطأ أثناء تنفيذ هذا الإجراء. هل يمكنك إعادة المحاولة؟",
            error=str(e),
        )


async def async_execute_tool(tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
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

        payload = result.model_dump() if hasattr(result, "model_dump") else result
        voice_msg = getattr(result, "message", "تم تنفيذ العملية بنجاح.")

        return ToolResult(
            success=True,
            message=voice_msg,
            data=payload if isinstance(payload, dict) else {"result": payload},
        )
    except Exception as e:
        logger.exception(f"Error in async tool execution '{tool_name}': {e}")
        return ToolResult(
            success=False,
            message="عذراً، حدث خطأ أثناء تنفيذ هذا الإجراء. هل يمكنك إعادة المحاولة؟",
            error=str(e),
        )


__all__ = [
    # Schemas
    "ToolResult",
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
    "KnowledgeSearchTool",
    "knowledge_search_tool",
    "OrderStatusTool",
    "order_status_tool",
    "ReservationTool",
    "reservation_tool",
    "HumanHandoffTool",
    "human_handoff_tool",
    # Functions
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
