"""
Pydantic Schemas for Voice Agent Tools.

Defines strongly-typed input and output contracts for:
1. Knowledge Search (RAG)
2. Order Status & Live Tracking
3. Table Reservation & Availability
4. Human Escalation & Supervisor Handoff
5. Generic Tool Execution Results
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


# ==============================================================================
# Common & Base Tool Models
# ==============================================================================

class ToolResult(BaseModel):
    """Generic execution envelope for any tool response."""
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(
        default=True,
        description="Whether the tool execution succeeded.",
    )
    message: str = Field(
        ...,
        description="Voice-friendly natural language response message.",
    )
    data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured payload data returned by the tool.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error details if tool execution failed.",
    )


# ==============================================================================
# 1. Knowledge Search Tool Schemas
# ==============================================================================

class KnowledgeSearchInput(BaseModel):
    """Input parameters for searching the restaurant knowledge base (RAG)."""
    model_config = ConfigDict(extra="ignore")

    query: str = Field(
        ...,
        min_length=2,
        max_length=500,
        description="Search query regarding menu items, ingredients, allergens, prices, delivery zones, or hours.",
    )
    limit: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of relevant knowledge snippets to retrieve.",
    )
    score_threshold: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Minimum vector similarity score required.",
    )


class KnowledgeChunk(BaseModel):
    """Individual chunk retrieved from the vector store."""
    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Unique chunk identifier.")
    content: str = Field(description="Text content of the knowledge chunk.")
    score: float = Field(description="Similarity score of the match.")
    section: Optional[str] = Field(default=None, description="Header section name.")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional chunk metadata.",
    )


class KnowledgeSearchOutput(BaseModel):
    """Output payload from knowledge base retrieval."""
    model_config = ConfigDict(extra="ignore")

    query: str = Field(description="Original search query.")
    found: bool = Field(description="True if matching knowledge snippets were found.")
    total_results: int = Field(default=0, description="Number of results found.")
    chunks: List[KnowledgeChunk] = Field(
        default_factory=list,
        description="List of matching knowledge chunks.",
    )
    context_text: str = Field(
        default="",
        description="Formatted text context ready for LLM synthesis.",
    )
    message: str = Field(
        description="Natural language summary for voice playback.",
    )


# ==============================================================================
# 2. Order Status & Tracking Tool Schemas
# ==============================================================================

class OrderStatusEnum(str, Enum):
    """Order fulfillment status states."""
    RECEIVED = "received"
    PREPARING = "preparing"
    READY_FOR_PICKUP = "ready_for_pickup"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class OrderItem(BaseModel):
    """An individual item within a customer order."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Item name (e.g., 'شاورما دجاج عربي', 'سلطة تبولة').")
    quantity: int = Field(default=1, ge=1, description="Quantity ordered.")
    unit_price: float = Field(default=0.0, ge=0.0, description="Price per unit in local currency.")
    notes: Optional[str] = Field(default=None, description="Item customizations or dietary notes.")


class OrderStatusInput(BaseModel):
    """Input parameters to look up and track an order."""
    model_config = ConfigDict(extra="ignore")

    order_id: str = Field(
        ...,
        min_length=2,
        description="Unique order number (e.g., 'ORD-1001', 'ORD-2045') or caller phone number.",
    )
    phone_number: Optional[str] = Field(
        default=None,
        description="Optional phone number for caller verification.",
    )


class OrderStatusOutput(BaseModel):
    """Output response detailing the current status of an order."""
    model_config = ConfigDict(extra="ignore")

    order_id: str = Field(description="Order identifier.")
    customer_name: str = Field(description="Customer name on the order.")
    status: OrderStatusEnum = Field(description="Standardized status code.")
    status_arabic: str = Field(description="Human-friendly Arabic status for voice response.")
    items: List[OrderItem] = Field(
        default_factory=list,
        description="List of items in the order.",
    )
    total_amount: float = Field(description="Total price including delivery.")
    estimated_delivery_time_minutes: Optional[int] = Field(
        default=None,
        description="Estimated remaining minutes until delivery.",
    )
    driver_name: Optional[str] = Field(
        default=None,
        description="Name of delivery driver if dispatched.",
    )
    driver_phone: Optional[str] = Field(
        default=None,
        description="Contact phone for the driver.",
    )
    delivery_address: Optional[str] = Field(
        default=None,
        description="Destination delivery address.",
    )
    created_at: str = Field(description="Order creation timestamp string.")
    message: str = Field(description="Concise, natural voice-friendly summary.")


# ==============================================================================
# 3. Table Reservation Tool Schemas
# ==============================================================================

class ReservationStatusEnum(str, Enum):
    """Status outcomes for a reservation request."""
    CONFIRMED = "confirmed"
    WAITLISTED = "waitlisted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ReservationInput(BaseModel):
    """Input parameters for booking a restaurant table."""
    model_config = ConfigDict(extra="ignore")

    customer_name: str = Field(
        ...,
        min_length=2,
        description="Full name of customer booking the reservation.",
    )
    phone_number: str = Field(
        ...,
        min_length=5,
        description="Contact phone number for booking confirmation.",
    )
    party_size: int = Field(
        ...,
        ge=1,
        le=30,
        description="Number of people/seats requested (1-30).",
    )
    date: str = Field(
        ...,
        description="Date of reservation in YYYY-MM-DD format (or descriptive like 'today', 'tomorrow').",
    )
    time: str = Field(
        ...,
        description="Requested time slot (e.g., '19:30', '8:00 PM', '14:00').",
    )
    special_requests: Optional[str] = Field(
        default=None,
        description="Special requests like outdoor table, high chair, birthday, or quiet booth.",
    )


class ReservationOutput(BaseModel):
    """Output confirmation details for a table reservation."""
    model_config = ConfigDict(extra="ignore")

    reservation_id: str = Field(description="Unique reservation reference number.")
    customer_name: str = Field(description="Customer name.")
    party_size: int = Field(description="Number of guests booked.")
    date: str = Field(description="Confirmed date.")
    time: str = Field(description="Confirmed time slot.")
    status: ReservationStatusEnum = Field(description="Reservation status.")
    status_arabic: str = Field(description="Arabic status description.")
    table_number: Optional[int] = Field(
        default=None,
        description="Assigned table number if available.",
    )
    confirmation_code: str = Field(description="Short verification code (e.g. 'RES-742').")
    special_requests: Optional[str] = Field(
        default=None,
        description="Confirmed special requests.",
    )
    message: str = Field(description="Spoken confirmation message for the caller.")


# ==============================================================================
# 4. Human Handoff & Escalation Schemas
# ==============================================================================

class HandoffUrgencyEnum(str, Enum):
    """Urgency level for human agent escalation."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class HandoffDepartmentEnum(str, Enum):
    """Department for call transfer."""
    CUSTOMER_SUPPORT = "customer_support"
    KITCHEN_MANAGER = "kitchen_manager"
    DELIVERY_DISPATCH = "delivery_dispatch"
    BILLING = "billing"


class HumanHandoffInput(BaseModel):
    """Input parameters for triggering human agent escalation."""
    model_config = ConfigDict(extra="ignore")

    reason: str = Field(
        ...,
        min_length=3,
        description="Reason for escalation (e.g., customer complaint, complex allergy, explicit human request).",
    )
    customer_phone: Optional[str] = Field(
        default=None,
        description="Caller's phone number for callback or SIP routing.",
    )
    customer_name: Optional[str] = Field(
        default=None,
        description="Caller's name if identified during the call.",
    )
    urgency: HandoffUrgencyEnum = Field(
        default=HandoffUrgencyEnum.MEDIUM,
        description="Urgency priority of the escalation.",
    )
    department: HandoffDepartmentEnum = Field(
        default=HandoffDepartmentEnum.CUSTOMER_SUPPORT,
        description="Destination department for the transfer.",
    )
    conversation_summary: Optional[str] = Field(
        default=None,
        description="Brief summary of conversation context prior to handoff.",
    )


class HumanHandoffOutput(BaseModel):
    """Output confirmation when call is routed to a human representative."""
    model_config = ConfigDict(extra="ignore")

    handoff_id: str = Field(description="Unique escalation reference ID.")
    status: str = Field(
        default="queued",
        description="Transfer status: 'queued', 'transferred', or 'callback_scheduled'.",
    )
    department: str = Field(description="Assigned department name.")
    urgency: HandoffUrgencyEnum = Field(description="Urgency priority.")
    assigned_agent: Optional[str] = Field(
        default=None,
        description="Representative name or agent ID if immediately assigned.",
    )
    estimated_wait_seconds: int = Field(
        default=45,
        description="Estimated queue wait time in seconds.",
    )
    message: str = Field(description="Spoken message informing caller of the transfer.")
