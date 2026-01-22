# src/tools/decision_tool.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

from src.schemas import ClaimExtract, PolicyDoc, PolicyExcerpt, ReviewPacket


@dataclass(frozen=True)
class DecisionConfig:
    warranty_months: int = 3


class DecisionTool:
    """
    Deterministic, policy-grounded decision support.

    Key corrections implemented:
    - Shipping address NEVER blocks recommendation (only needed post-approval to generate label).
    - Exclusions override approvals (e.g., voltage converter use, travel damage, wear/tear accessories).
    - Always include "Relevant policy sections / referenced excerpts" in the human review packet.
    - Always include reasoning (why recommendation was made).
    - If purchase date is vague ("last month"), recommend APPROVE (medium) but request exact date.
    """

    def __init__(self, llm=None, config: Optional[DecisionConfig] = None) -> None:
        self.llm = llm  # kept for extensibility; not used for logic to avoid inconsistent behavior
        self.config = config or DecisionConfig()

    def build_review_packet(
        self,
        packet_id: str,
        email_id: str,
        claim: ClaimExtract,
        policy: PolicyDoc,
        policy_selection_reason: str,
        referenced_excerpts: List[PolicyExcerpt],
    ) -> ReviewPacket:
        # -----------------------------
        # Evidence checklist (explicit)
        # -----------------------------
        evidence_checklist = {
            "product_name": bool(claim.product_name),
            "purchase_date": bool(claim.purchase_date),
            "proof_of_purchase": bool(claim.proof_of_purchase_present),
            "shipping_address": bool(claim.shipping_address),
        }

        facts: List[str] = []
        assumptions: List[str] = []
        reasoning: List[str] = []
        uncertainty: List[str] = []
        followups: List[str] = []

        issue_lower = (claim.issue_description or "").lower()

        # -----------------------------
        # Facts (claim summary)
        # -----------------------------
        facts.append(f"Issue reported: {claim.issue_description}")
        facts.append(f"Selected policy: {policy.product_name} ({policy.policy_id})")
        facts.append(f"Policy selection reason: {policy_selection_reason}")

        if claim.product_name:
            facts.append(f"Extracted product: {claim.product_name}")
        else:
            facts.append("Product model not confidently identified from the email.")

        if claim.purchase_date:
            facts.append(f"Purchase date provided: {claim.purchase_date.isoformat()}")
        else:
            facts.append("Exact purchase date not provided in the email.")

        facts.append(f"Proof of purchase present: {claim.proof_of_purchase_present}")

        # -----------------------------
        # REQUIRED: Relevant policy sections / excerpts
        # -----------------------------
        if referenced_excerpts:
            facts.append("Relevant policy sections reviewed (referenced excerpts):")
            for ex in referenced_excerpts:
                facts.append(f"- [{ex.section}] {ex.excerpt}")

        # -----------------------------
        # Warranty window check
        # -----------------------------
        in_window: Optional[bool] = None
        if claim.purchase_date:
            days = (date.today() - claim.purchase_date).days
            max_days = policy.warranty_period_months * 30
            in_window = days <= max_days
            reasoning.append(f"Warranty window check: {days} days since purchase (limit ~{max_days} days).")
        else:
            if "last month" in issue_lower:
                assumptions.append("Customer indicates purchase within the last month; likely within warranty window.")
            else:
                assumptions.append("Purchase date missing; cannot confirm warranty window without follow-up.")

        # -----------------------------
        # Exclusion detection (fast, deterministic)
        # -----------------------------
        def hit(*keywords: str) -> bool:
            return any(k in issue_lower for k in keywords)

        exclusion_reason: Optional[str] = None

        # Claim 2 style: voltage converter / international voltage
        if hit("voltage converter", "converter", "240v", "220v", "abroad", "international voltage"):
            exclusion_reason = "Used with a voltage converter / non-standard voltage (excluded)."

        # Claim 8 style: travel damage / airline handling
        if hit("travel", "flight", "airline", "suitcase", "luggage") and hit("crack", "cracked", "broken", "damage", "damaged"):
            exclusion_reason = "Travel / airline handling damage (excluded)."

        # Claim 6 style: wear & tear / accessory fitment issues
        if hit("attachment", "nozzle", "diffuser") and hit("loose", "does not fit", "doesn't fit", "no longer fits", "fits securely"):
            exclusion_reason = "Accessory wear/fitment issue (treated as wear & tear / accessory not covered)."

        # Try to cite a matching exclusion excerpt if we reject
        def find_policy_exclusion_excerpt() -> Optional[str]:
            for ex in referenced_excerpts:
                if ex.section.lower().startswith("exclusion"):
                    return ex.excerpt
            return None

        # -----------------------------
        # Followups (missing info)
        # -----------------------------
        if not claim.product_name:
            followups.append("Please confirm the exact product model name (e.g., AeroDry Pro 1800).")
            uncertainty.append("Product model missing; policy match may be incorrect.")

        if not claim.proof_of_purchase_present:
            followups.append("Please provide proof of purchase (invoice/receipt or order ID).")

        if not claim.purchase_date:
            followups.append("Please confirm the exact purchase date (or share the receipt showing the date).")

        # NOTE: shipping address is NOT required to recommend approve/reject
        # only required AFTER approval to generate return label
        if not claim.shipping_address:
            # Only add as followup if approval is likely (handled later), but safe to include as "operational"
            uncertainty.append("Shipping address missing; required to generate return label after approval.")

        # -----------------------------
        # Recommendation decision rules
        # -----------------------------
        recommendation = "NEED_MORE_INFO"
        confidence = "low"

        if exclusion_reason:
            recommendation = "REJECT"
            confidence = "high"
            reasoning.append(f"Claim matches an exclusion condition: {exclusion_reason}")

            ex_ref = find_policy_exclusion_excerpt()
            if ex_ref:
                reasoning.append(f"Policy basis (exclusion excerpt): {ex_ref}")
            else:
                reasoning.append("Policy basis: exclusion section applies (see referenced excerpts).")

        else:
            # No exclusion detected
            if in_window is True:
                recommendation = "APPROVE"
                # confidence depends on proof-of-purchase
                confidence = "high" if claim.proof_of_purchase_present else "medium"
                reasoning.append("No applicable exclusions found in the referenced policy sections.")
                reasoning.append("Claim is within the warranty window; approval is recommended.")

            elif in_window is False:
                recommendation = "REJECT"
                confidence = "high"
                reasoning.append("Purchase date indicates the claim is outside the warranty window; rejection is recommended.")

            else:
                # Unknown window (no purchase_date)
                if "last month" in issue_lower:
                    recommendation = "APPROVE"
                    confidence = "medium"
                    reasoning.append("Customer indicates purchase was last month; likely within warranty window.")
                    reasoning.append("Approval is recommended, but exact purchase date must be confirmed.")
                else:
                    recommendation = "NEED_MORE_INFO"
                    confidence = "low"
                    reasoning.append("Cannot confirm warranty eligibility without purchase date.")

        # -----------------------------
        # Post-approval operational requirement:
        # If approved but address missing -> ask address (do not downgrade recommendation)
        # -----------------------------
        if recommendation == "APPROVE" and not claim.shipping_address:
            # Keep recommendation APPROVE, but ensure followup contains address request
            followups.append("Please provide your shipping/return address so we can generate the return label.")
            reasoning.append("Shipping address is needed to proceed with logistics after approval (does not affect eligibility).")

        # Ensure we always have reasoning
        if not reasoning:
            reasoning.append("Recommendation based on available claim details and referenced policy sections.")

        # De-duplicate followups (keep order)
        seen = set()
        followups_deduped = []
        for q in followups:
            if q not in seen:
                seen.add(q)
                followups_deduped.append(q)

        return ReviewPacket(
            packet_id=packet_id,
            email_id=email_id,
            created_at=datetime.utcnow(),
            extracted=claim,
            selected_policy_id=policy.policy_id,
            selected_policy_product_name=policy.product_name,
            policy_selection_reason=policy_selection_reason,
            referenced_policy_excerpts=referenced_excerpts,
            evidence_checklist=evidence_checklist,
            recommendation=recommendation,  # APPROVE / REJECT / NEED_MORE_INFO
            confidence=confidence,          # high / medium / low
            uncertainty_notes=uncertainty,
            facts=facts,
            assumptions=assumptions,
            reasoning=reasoning,
            customer_followup_questions=followups_deduped,
        )
