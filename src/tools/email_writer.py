# src/tools/email_writer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.schemas import ClaimExtract, PolicyDoc, ReviewPacket


@dataclass(frozen=True)
class EmailWriterConfig:
    company_name: str = "AeroDry Support"
    support_email: str = "support@aerodry.example"
    escalation_line: str = "If you believe this decision is incorrect, reply to this email with additional details and we will review again."
    signature: str = "AeroDry Warranty Team"


class EmailWriter:
    """
    Drafts customer emails for:
      - APPROVE (with next steps + return label reference)
      - REJECT (clear reason + policy reference)
      - NEED_MORE_INFO (request missing info)
    Uses LLM if available; falls back to templated drafts.
    """

    def __init__(self, llm: Optional[BaseChatModel], config: Optional[EmailWriterConfig] = None) -> None:
        self.llm = llm
        self.config = config or EmailWriterConfig()
        self._str_parser = StrOutputParser()

        self._prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You write clear, professional customer support emails for warranty claims.\n"
                    "Constraints:\n"
                    "- Be concise.\n"
                    "- Be polite and specific.\n"
                    "- For rejections, cite the relevant exclusion or requirement.\n"
                    "- For approvals, include next steps.\n"
                    "- If more info is needed, ask targeted questions only.\n"
                    "Return ONLY the email body (no subject line).",
                ),
                (
                    "human",
                    "Company: {company_name}\n"
                    "Decision: {decision}\n"
                    "Customer name: {customer_name}\n"
                    "Product: {product}\n"
                    "Purchase date: {purchase_date}\n"
                    "Issue: {issue}\n"
                    "Policy product: {policy_product}\n"
                    "Policy excerpts:\n{policy_excerpts}\n"
                    "Missing fields: {missing_fields}\n"
                    "Return label reference (if approved): {label_ref}\n\n"
                    "Write the email body.",
                ),
            ]
        )

    # -----------------------------
    # Public API
    # -----------------------------
    def draft(
        self,
        packet: ReviewPacket,
        policy: PolicyDoc,
        return_label_ref: Optional[str] = None,
    ) -> str:
        decision = packet.recommendation  # APPROVE / REJECT / NEED_MORE_INFO

        # Prefer LLM; fallback if unavailable or fails
        if self.llm:
            try:
                return self._draft_with_llm(packet, policy, return_label_ref)
            except Exception:
                pass

        return self._draft_template(packet, policy, return_label_ref)

    # -----------------------------
    # LLM draft
    # -----------------------------
    def _draft_with_llm(
        self,
        packet: ReviewPacket,
        policy: PolicyDoc,
        return_label_ref: Optional[str],
    ) -> str:
        policy_excerpts = "\n".join(
            f"- [{e.section}] {e.excerpt}" for e in packet.referenced_policy_excerpts
        ) or "None"

        claim = packet.extracted
        chain = self._prompt | self.llm | self._str_parser

        text = chain.invoke(
            {
                "company_name": self.config.company_name,
                "decision": packet.recommendation,
                "customer_name": claim.customer_name or "Customer",
                "product": claim.product_name or claim.product_model_hint or "Unknown product",
                "purchase_date": claim.purchase_date.isoformat() if claim.purchase_date else "Unknown",
                "issue": claim.issue_description,
                "policy_product": policy.product_name,
                "policy_excerpts": policy_excerpts,
                "missing_fields": ", ".join(claim.missing_fields) if claim.missing_fields else "None",
                "label_ref": return_label_ref or "N/A",
            }
        )

        return text.strip()

    # -----------------------------
    # Template fallback
    # -----------------------------
    def _draft_template(
        self,
        packet: ReviewPacket,
        policy: PolicyDoc,
        return_label_ref: Optional[str],
    ) -> str:
        claim: ClaimExtract = packet.extracted
        name = claim.customer_name or "Customer"
        product = claim.product_name or claim.product_model_hint or "your AeroDry hair dryer"

        if packet.recommendation == "APPROVE":
            return self._approve_template(name, product, return_label_ref)

        if packet.recommendation == "REJECT":
            # Attempt to find an exclusion excerpt to cite
            exclusion_line = None
            for e in packet.referenced_policy_excerpts:
                if e.section.lower().startswith("exclusion"):
                    exclusion_line = e.excerpt
                    break
            reason = exclusion_line or "the warranty policy terms"
            return self._reject_template(name, product, reason)

        # NEED_MORE_INFO
        questions = packet.customer_followup_questions or []
        if not questions:
            questions = [
                "Please provide your proof of purchase (Amazon invoice or order ID).",
                "Please confirm the purchase date.",
                "Please confirm the exact product model name.",
                "Please provide your shipping address.",
            ]
        return self._more_info_template(name, product, questions)

    # -----------------------------
    # Templates
    # -----------------------------
    def _approve_template(self, name: str, product: str, label_ref: Optional[str]) -> str:
        label_line = (
            f"Return label: {label_ref}" if label_ref else "Return label: (will be provided upon confirmation)"
        )
        return (
            f"Hi {name},\n\n"
            f"Thanks for reaching out. Based on the information provided, we can proceed with your warranty claim for {product}.\n\n"
            "Next steps:\n"
            "1) Please package the item securely.\n"
            f"2) Use the return shipping label below to send it back.\n"
            f"3) Once we receive and inspect the unit, we will ship a replacement.\n\n"
            f"{label_line}\n\n"
            "If you have any questions, just reply to this email.\n\n"
            f"Best regards,\n{self.config.signature}"
        )

    def _reject_template(self, name: str, product: str, reason: str) -> str:
        return (
            f"Hi {name},\n\n"
            f"Thanks for contacting us about your {product}. After reviewing your claim, we’re unable to approve it under the warranty.\n\n"
            f"Reason: This issue falls under an exclusion/requirement in the policy (e.g., {reason}).\n\n"
            f"{self.config.escalation_line}\n\n"
            f"Best regards,\n{self.config.signature}"
        )

    def _more_info_template(self, name: str, product: str, questions: list[str]) -> str:
        questions_text = "\n".join([f"- {q}" for q in questions])
        return (
            f"Hi {name},\n\n"
            f"Thanks for reaching out about your {product}. We can help, but we need a bit more information to continue processing your warranty claim:\n\n"
            f"{questions_text}\n\n"
            "Once you reply with the above details, we’ll review and get back to you quickly.\n\n"
            f"Best regards,\n{self.config.signature}"
        )
