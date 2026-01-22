# src/tools/extraction_tool.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

from dateutil import parser as dateparser
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, ValidationError

from src.schemas import ClaimExtract, EmailMessage


# -----------------------------
# LLM output schema (JSON)
# -----------------------------
class _LLMExtract(BaseModel):
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None

    product_name: Optional[str] = None
    product_model_hint: Optional[str] = None
    serial_number: Optional[str] = None

    purchase_date: Optional[str] = Field(
        None, description="Purchase date as an ISO string YYYY-MM-DD if known"
    )
    order_id: Optional[str] = None
    retailer: Optional[str] = None

    issue_description: str = Field(..., description="Concise description of the issue")
    shipping_address: Optional[str] = None

    evidence_provided: List[str] = Field(default_factory=list)
    proof_of_purchase_present: bool = False


@dataclass(frozen=True)
class ExtractionConfig:
    """
    Fast demo config: provide known product names to help normalization.
    """
    known_products: List[str]
    require_address: bool = False


class ExtractionTool:
    """
    Extracts structured claim fields from an unstructured email (and mocked attachments references).
    Uses LLM first; falls back to basic regex/heuristics so the demo won't break.
    """

    def __init__(self, llm: Optional[BaseChatModel], config: ExtractionConfig) -> None:
        self.llm = llm
        self.config = config

        self.parser = JsonOutputParser(pydantic_object=_LLMExtract)
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You extract structured fields from warranty claim emails.\n"
                    "Return ONLY valid JSON.\n"
                    "If a field is not present, set it to null.\n"
                    "Normalize product_name to match one of these known products when possible:\n"
                    "{known_products}\n"
                    "purchase_date must be in ISO format YYYY-MM-DD if present.\n"
                ),
                (
                    "human",
                    "Subject: {subject}\n\n"
                    "Body:\n{body}\n\n"
                    "Attachments (filenames only): {attachments}\n\n"
                    "{format_instructions}"
                ),
            ]
        )

    def extract(self, email: EmailMessage) -> ClaimExtract:
        """
        1) Try LLM extraction
        2) Fallback to heuristic extraction
        3) Post-process: parse dates, infer proof_of_purchase from attachments, fill missing_fields
        """
        llm_data: Optional[_LLMExtract] = None

        if self.llm:
            try:
                chain = self.prompt | self.llm | self.parser
                result = chain.invoke(
                    {
                        "subject": email.subject,
                        "body": email.body,
                        "attachments": email.attachments,
                        "known_products": ", ".join(self.config.known_products),
                        "format_instructions": self.parser.get_format_instructions(),
                    }
                )
                llm_data = _LLMExtract.model_validate_json(result.content)
            except Exception:
                llm_data = None

        if llm_data is None:
            llm_data = self._heuristic_extract(email)

        # Convert LLM extract -> ClaimExtract with post-processing
        return self._to_claim_extract(email, llm_data)

    # -----------------------------
    # Post-processing / validation
    # -----------------------------
    def _to_claim_extract(self, email: EmailMessage, data: _LLMExtract) -> ClaimExtract:
        # Parse purchase date if present
        parsed_purchase_date: Optional[date] = None
        if data.purchase_date:
            parsed_purchase_date = self._parse_date_safe(data.purchase_date)

        # Infer proof_of_purchase_present: either model said true OR attachments look like invoices
        proof_from_attachments = any(
            a.lower().endswith((".pdf", ".png", ".jpg", ".jpeg"))
            and ("invoice" in a.lower() or "receipt" in a.lower() or "order" in a.lower())
            for a in email.attachments
        )
        proof_present = bool(data.proof_of_purchase_present or proof_from_attachments)

        # Normalize product name if possible
        product_name = self._normalize_product(data.product_name or data.product_model_hint or "")

        # Build missing fields list (minimum required set per assignment)
        missing: List[str] = []
        if not (data.customer_name or email.customer_name):
            missing.append("customer_name")
        if not (data.customer_email or email.customer_email):
            # Not strictly required by the PDF, but useful; keep it optional.
            pass
        if not product_name:
            missing.append("product_name")
        if parsed_purchase_date is None:
            missing.append("purchase_date")
        if not data.issue_description or not data.issue_description.strip():
            missing.append("issue_description")
        if not proof_present:
            missing.append("proof_of_purchase")
        if self.config.require_address and not data.shipping_address:
            missing.append("shipping_address")

        confidence = "high"
        if len(missing) >= 3:
            confidence = "low"
        elif len(missing) >= 1:
            confidence = "medium"

        return ClaimExtract(
            customer_name=data.customer_name or email.customer_name,
            customer_email=data.customer_email or email.customer_email,
            customer_phone=data.customer_phone,

            product_name=product_name or None,
            product_model_hint=data.product_model_hint,
            serial_number=data.serial_number,

            purchase_date=parsed_purchase_date,
            order_id=data.order_id,
            retailer=data.retailer or "Amazon",

            issue_description=data.issue_description.strip(),
            evidence_provided=data.evidence_provided or [],
            proof_of_purchase_present=proof_present,

            shipping_address=data.shipping_address,

            missing_fields=missing,
            extraction_confidence=confidence,
        )

    def _parse_date_safe(self, s: str) -> Optional[date]:
        try:
            dt = dateparser.parse(s, fuzzy=True)
            if not dt:
                return None
            return dt.date()
        except Exception:
            return None

    def _normalize_product(self, raw: str) -> str:
        """
        Normalize to the closest known product by simple substring matching.
        Fast + good enough for a demo.
        """
        if not raw:
            return ""
        raw_l = raw.lower()

        # Exact/substring match
        for p in self.config.known_products:
            if p.lower() in raw_l or raw_l in p.lower():
                return p

        # Try to match by removing non-alphanumerics
        raw_clean = re.sub(r"[^a-z0-9]+", "", raw_l)
        best = ""
        for p in self.config.known_products:
            p_clean = re.sub(r"[^a-z0-9]+", "", p.lower())
            if raw_clean and raw_clean in p_clean:
                best = p
                break
        return best or ""

    # -----------------------------
    # Heuristic fallback extraction
    # -----------------------------
    def _heuristic_extract(self, email: EmailMessage) -> _LLMExtract:
        text = f"{email.subject}\n{email.body}"

        # Product guess: match any known product string in the text
        product_guess = None
        low = text.lower()
        for p in self.config.known_products:
            if p.lower() in low:
                product_guess = p
                break

        # Order ID guess: common patterns like "Order ID", "Order#", etc.
        order_id = None
        m = re.search(r"(order\s*(id|#)\s*[:\-]?\s*)([A-Za-z0-9\-]+)", text, re.IGNORECASE)
        if m:
            order_id = m.group(3)

        # Purchase date guess: look for a date-like substring
        purchase_date_iso = None
        date_match = re.search(
            r"(\b\d{4}-\d{2}-\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b)",
            text,
            re.IGNORECASE,
        )
        if date_match:
            d = self._parse_date_safe(date_match.group(1))
            if d:
                purchase_date_iso = d.isoformat()

        # Proof of purchase from attachments
        proof = any(
            "invoice" in a.lower() or "receipt" in a.lower() or "order" in a.lower()
            for a in email.attachments
        )

        # Issue: just use the body trimmed
        issue_desc = email.body.strip()
        if len(issue_desc) > 400:
            issue_desc = issue_desc[:400] + "..."

        return _LLMExtract(
            customer_name=email.customer_name,
            product_name=product_guess,
            purchase_date=purchase_date_iso,
            order_id=order_id,
            retailer="Amazon",
            issue_description=issue_desc,
            evidence_provided=["attachments_present"] if email.attachments else [],
            proof_of_purchase_present=proof,
            shipping_address=None,
        )
