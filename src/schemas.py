# src/schemas.py
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, EmailStr, ConfigDict


# -------------------------
# Ingestion / Email schema
# -------------------------
class EmailMessage(BaseModel):
    """
    Represents one inbound email-like message from the file-based inbox.
    Keep it close to what the inbox JSON contains, but allow extra fields.
    """
    model_config = ConfigDict(extra="allow")

    email_id: str = Field(..., description="Unique ID for the email/claim file")
    subject: str = Field(..., description="Email subject line")
    body: str = Field(..., description="Email body content (unstructured text)")
    customer_name: Optional[str] = Field(None, description="Name if present in email")
    customer_email: Optional[EmailStr] = Field(None, description="Email if present")
    attachments: List[str] = Field(default_factory=list, description="Attachment filenames/refs")

    received_at: Optional[datetime] = Field(
        None, description="Optional timestamp; can be omitted for mock inbox"
    )


# -------------------------
# Policy schema
# -------------------------
class PolicyDoc(BaseModel):
    """
    Represents one warranty policy for a specific product line.
    """
    model_config = ConfigDict(extra="allow")

    policy_id: str = Field(..., description="Stable identifier, e.g., 'policy_aerodry_pro_1800'")
    product_name: str = Field(..., description="Exact product line name")
    warranty_period_months: int = Field(3, description="Warranty duration in months (default 3)")
    covered_issues: List[str] = Field(default_factory=list)
    exclusions: List[str] = Field(default_factory=list)
    required_proof: List[str] = Field(default_factory=list)

    # Optional extra policy metadata (helpful for future)
    version: Optional[str] = Field(None, description="Policy version or publish date string")
    source_path: Optional[str] = Field(None, description="File path that policy was loaded from")


# -------------------------
# Extraction schema
# -------------------------
class ClaimExtract(BaseModel):
    """
    Structured claim fields extracted from email + attachments.
    Must include the minimum required set per assignment:
    customer identity, product, purchase date, issue, proof of purchase, address.
    """
    model_config = ConfigDict(extra="allow")

    # Identity
    customer_name: Optional[str] = None
    customer_email: Optional[EmailStr] = None
    customer_phone: Optional[str] = None

    # Product
    product_name: Optional[str] = Field(None, description="Matched product line name")
    product_model_hint: Optional[str] = Field(
        None, description="Any ambiguous mention or partial product reference"
    )
    serial_number: Optional[str] = None

    # Purchase
    purchase_date: Optional[date] = None
    order_id: Optional[str] = None
    retailer: Optional[str] = Field(None, description="e.g., Amazon")

    # Issue
    issue_description: str = Field(..., description="Customer-reported issue text")
    evidence_provided: List[str] = Field(
        default_factory=list,
        description="List of evidence items present (invoice, photos, video, etc.)",
    )
    proof_of_purchase_present: bool = Field(
        False, description="True if invoice/order receipt was found or attached"
    )

    # Address (minimum requirement)
    shipping_address: Optional[str] = Field(
        None, description="Return shipping address or customer address if provided"
    )

    # Extraction quality
    missing_fields: List[str] = Field(
        default_factory=list,
        description="Fields that must be requested from customer to proceed confidently",
    )
    extraction_confidence: Literal["high", "medium", "low"] = "medium"


# -------------------------
# Decision / Review packet
# -------------------------
Recommendation = Literal["APPROVE", "REJECT", "NEED_MORE_INFO"]


class PolicyExcerpt(BaseModel):
    """
    Small, referenced excerpts to show policy grounding in the review packet.
    """
    model_config = ConfigDict(extra="allow")

    section: str = Field(..., description="e.g., Covered Issues / Exclusions / Proof Required")
    excerpt: str = Field(..., description="Short excerpt text")
    policy_id: Optional[str] = None


class ReviewPacket(BaseModel):
    """
    Human-in-the-loop review packet required by the assignment.
    Must clearly separate facts, assumptions, reasoning; include evidence checklist,
    selected policy + why, recommendation + confidence.
    """
    model_config = ConfigDict(extra="allow")

    packet_id: str = Field(..., description="Unique ID for the review packet")
    email_id: str = Field(..., description="Source email/claim id")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Extracted claim details
    extracted: ClaimExtract

    # Policy selection + retrieval
    selected_policy_id: str
    selected_policy_product_name: str
    policy_selection_reason: str = Field(..., description="Why this policy was selected")
    referenced_policy_excerpts: List[PolicyExcerpt] = Field(default_factory=list)

    # Evidence checklist (explicitly requested)
    evidence_checklist: Dict[str, bool] = Field(
        default_factory=dict,
        description="e.g., {'proof_of_purchase': True, 'photos': False, 'serial_number': False}",
    )

    # Decision support output (recommendation, confidence)
    recommendation: Recommendation
    confidence: Literal["high", "medium", "low"] = "medium"
    uncertainty_notes: List[str] = Field(default_factory=list)

    # Explicit separation
    facts: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    reasoning: List[str] = Field(default_factory=list)

    # Operational metadata
    triage_label: Literal["WARRANTY_CLAIM", "NON_CLAIM"] = "WARRANTY_CLAIM"
    routing_notes: List[str] = Field(default_factory=list)

    # If we need to ask customer for more info, capture it here
    customer_followup_questions: List[str] = Field(default_factory=list)

    # Optional: human decision later
    human_decision: Optional[Literal["APPROVED", "REJECTED", "MORE_INFO_REQUESTED"]] = None
    human_decision_notes: Optional[str] = None
    human_decision_at: Optional[datetime] = None
