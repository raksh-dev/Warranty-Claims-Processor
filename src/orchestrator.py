# src/orchestrator.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional, Dict

from src.schemas import ReviewPacket
from src.tools import (
    InboxTool,
    TriageTool,
    ExtractionTool,
    PolicyRetriever,
    DecisionTool,
    EmailWriter,
    LabelGenerator,
)


@dataclass(frozen=True)
class OrchestratorConfig:
    """
    Configuration for orchestration behavior.
    """
    auto_archive_processed: bool = False


class WarrantyClaimsOrchestrator:
    """
    Orchestrates the end-to-end workflow for warranty claims.

    Responsibilities:
    - Triage incoming emails
    - Extract structured claim data
    - Select correct policy + retrieve excerpts
    - Generate a decision-support review packet
    - Handle post-human-decision actions (email + label)
    """

    def __init__(
        self,
        inbox: InboxTool,
        triage: TriageTool,
        extraction: ExtractionTool,
        policy_retriever: PolicyRetriever,
        decision: DecisionTool,
        email_writer: EmailWriter,
        label_generator: LabelGenerator,
        config: Optional[OrchestratorConfig] = None,
    ) -> None:
        self.inbox = inbox
        self.triage = triage
        self.extraction = extraction
        self.policy_retriever = policy_retriever
        self.decision = decision
        self.email_writer = email_writer
        self.label_generator = label_generator
        self.config = config or OrchestratorConfig()

    # -------------------------------------------------
    # Phase 1: From inbox email → review packet
    # -------------------------------------------------
    def process_email_to_review_packet(self, email) -> Optional[ReviewPacket]:
        """
        Process a single email into a ReviewPacket.

        Returns:
          - ReviewPacket if classified as WARRANTY_CLAIM
          - None if classified as NON_CLAIM (file moved to triage_rejected)
        """
        triage_result = self.triage.classify(email)

        if triage_result.label == "NON_CLAIM":
            self.inbox.move_to_triage_rejected(email.email_id)
            return None

        # 1) Extraction
        claim = self.extraction.extract(email)

        # 2) Policy selection + retrieval
        policy, selection_reason = self.policy_retriever.select_policy(claim)
        excerpts = self.policy_retriever.retrieve_excerpts(policy, claim)

        # 3) Decision support packet
        packet_id = f"pkt_{email.email_id}_{uuid.uuid4().hex[:8]}"
        packet = self.decision.build_review_packet(
            packet_id=packet_id,
            email_id=email.email_id,
            claim=claim,
            policy=policy,
            policy_selection_reason=selection_reason,
            referenced_excerpts=excerpts,
        )

        # Add traceability notes
        packet.triage_label = "WARRANTY_CLAIM"
        packet.routing_notes.append(f"Triage reason: {triage_result.reason}")

        return packet

    # -------------------------------------------------
    # Phase 2: After human decision → outputs
    # -------------------------------------------------
    def draft_outputs_after_human_decision(
        self,
        packet: ReviewPacket,
        policy,
        human_decision: str,
    ) -> Dict[str, Optional[str]]:
        """
        Handle post-review actions after a human decision.

        human_decision:
          - "APPROVED"
          - "REJECTED"
          - "MORE_INFO_REQUESTED"

        Rules:
          - Shipping address NEVER blocks recommendation.
          - If APPROVED but address missing:
              → send NEED_MORE_INFO email asking ONLY for address
              → do NOT generate return label yet
          - If APPROVED and address present:
              → generate return label
              → send approval email
        """
        label_ref = None

        if packet.customer_followup_questions is None:
            packet.customer_followup_questions = []

        # -------------------------
        # APPROVED
        # -------------------------
        if human_decision == "APPROVED":
            if not packet.extracted.shipping_address:
                # Approved logically, but cannot proceed operationally
                packet.recommendation = "NEED_MORE_INFO"
                packet.customer_followup_questions = [
                    "Please provide your shipping/return address so we can generate the return label."
                ]

                drafted_email = self.email_writer.draft(
                    packet=packet,
                    policy=policy,
                    return_label_ref=None,
                )
                return {
                    "drafted_email": drafted_email,
                    "label_ref": None,
                }

            # Address present → proceed fully
            packet.recommendation = "APPROVE"
            label_ref = self.label_generator.generate(packet.extracted, packet.email_id)

            drafted_email = self.email_writer.draft(
                packet=packet,
                policy=policy,
                return_label_ref=label_ref,
            )
            return {
                "drafted_email": drafted_email,
                "label_ref": label_ref,
            }

        # -------------------------
        # REJECTED
        # -------------------------
        if human_decision == "REJECTED":
            packet.recommendation = "REJECT"
            drafted_email = self.email_writer.draft(
                packet=packet,
                policy=policy,
                return_label_ref=None,
            )
            return {
                "drafted_email": drafted_email,
                "label_ref": None,
            }

        # -------------------------
        # MORE INFO REQUESTED
        # -------------------------
        packet.recommendation = "NEED_MORE_INFO"
        drafted_email = self.email_writer.draft(
            packet=packet,
            policy=policy,
            return_label_ref=None,
        )
        return {
            "drafted_email": drafted_email,
            "label_ref": None,
        }
