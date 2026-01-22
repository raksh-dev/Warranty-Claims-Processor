# src/tools/policy_retriever.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import ValidationError

from src.schemas import ClaimExtract, PolicyDoc, PolicyExcerpt


@dataclass(frozen=True)
class PolicyRetrieverConfig:
    policies_dir: Path


class PolicyRetriever:
    """
    Policy selection + lightweight retrieval (RAG-lite).

    - Loads 10 product policies from JSON files in data/policies/
    - Selects the best matching policy for a claim (by product_name or fuzzy match)
    - Returns short "excerpts" (covered, exclusions, required proof) for grounding
    """

    def __init__(self, config: PolicyRetrieverConfig) -> None:
        self.config = config
        self.config.policies_dir.mkdir(parents=True, exist_ok=True)
        self._policies: List[PolicyDoc] = []
        self._load_policies()

    # -----------------------------
    # Public API
    # -----------------------------
    def list_products(self) -> List[str]:
        return [p.product_name for p in self._policies]

    def get_policy_by_product(self, product_name: str) -> Optional[PolicyDoc]:
        for p in self._policies:
            if p.product_name.strip().lower() == product_name.strip().lower():
                return p
        return None

    def select_policy(self, claim: ClaimExtract) -> Tuple[PolicyDoc, str]:
        """
        Returns (policy, reason).
        Selection order:
          1) Exact match on extracted claim.product_name
          2) Substring / normalized match on claim.product_model_hint
          3) Fuzzy-ish best score across all policies (token overlap)
        """
        if not self._policies:
            raise RuntimeError(f"No policies loaded from {self.config.policies_dir}")

        # 1) Exact match
        if claim.product_name:
            exact = self.get_policy_by_product(claim.product_name)
            if exact:
                return exact, f"Exact match on product_name='{claim.product_name}'."

        # 2) Try product_model_hint
        hint = (claim.product_model_hint or "").strip()
        if hint:
            match = self._best_match_from_text(hint)
            if match:
                return match, f"Matched policy using product_model_hint='{hint}'."

        # 3) Fallback: best match using issue text + product tokens (if any)
        combined = " ".join(
            [claim.product_name or "", claim.product_model_hint or "", claim.issue_description or ""]
        ).strip()
        best = self._best_match_from_text(combined)
        if best:
            return best, "Selected best-matching policy using token overlap on claim text."

        # Absolute fallback: first policy
        return self._policies[0], "Fallback: defaulted to first policy (no match found)."

    def retrieve_excerpts(self, policy: PolicyDoc, claim: ClaimExtract) -> List[PolicyExcerpt]:
        """
        Lightweight retrieval: return the most relevant policy sections.
        This is deliberately simple for a 48h exercise but still provides grounded references.
        """
        issue = (claim.issue_description or "").lower()

        excerpts: List[PolicyExcerpt] = []

        # Always include warranty period summary
        excerpts.append(
            PolicyExcerpt(
                section="Warranty Period",
                excerpt=f"{policy.warranty_period_months} months from purchase date",
                policy_id=policy.policy_id,
            )
        )

        # Covered issues: include all, but prioritize those matching issue tokens
        covered_sorted = self._rank_clauses(policy.covered_issues, issue)
        for c in covered_sorted[:3]:
            excerpts.append(
                PolicyExcerpt(section="Covered Issues", excerpt=c, policy_id=policy.policy_id)
            )

        # Exclusions: include top matches; always include at least 1-2 exclusions for reviewer context
        exclusions_sorted = self._rank_clauses(policy.exclusions, issue)
        for e in (exclusions_sorted[:3] if exclusions_sorted else policy.exclusions[:2]):
            excerpts.append(
                PolicyExcerpt(section="Exclusions", excerpt=e, policy_id=policy.policy_id)
            )

        # Required proof
        for r in policy.required_proof:
            excerpts.append(
                PolicyExcerpt(section="Required Proof", excerpt=r, policy_id=policy.policy_id)
            )

        return excerpts

    # -----------------------------
    # Internal: load + matching
    # -----------------------------
    def _load_policies(self) -> None:
        self._policies.clear()
        for fp in sorted(self.config.policies_dir.glob("*.json")):
            raw = json.loads(fp.read_text(encoding="utf-8"))

            # Ensure policy_id exists (derive from filename if missing)
            raw.setdefault("policy_id", fp.stem)
            raw.setdefault("source_path", str(fp))

            try:
                policy = PolicyDoc.model_validate(raw)
                self._policies.append(policy)
            except ValidationError as e:
                raise ValueError(f"Invalid policy JSON in {fp.name}: {e}") from e

        if not self._policies:
            raise RuntimeError(
                f"No policy .json files found in {self.config.policies_dir}. "
                "Add 10 policy files like policy_aerodry_pro_1800.json"
            )

    def _best_match_from_text(self, text: str) -> Optional[PolicyDoc]:
        if not text:
            return None
        text_tokens = self._tokenize(text)
        if not text_tokens:
            return None

        best: Optional[PolicyDoc] = None
        best_score = 0

        for p in self._policies:
            p_tokens = self._tokenize(p.product_name)
            score = len(text_tokens.intersection(p_tokens))

            # Small boost if whole product name appears as substring
            if p.product_name.lower() in text.lower():
                score += 3

            if score > best_score:
                best_score = score
                best = p

        return best if best_score > 0 else None

    def _rank_clauses(self, clauses: List[str], issue_text_lower: str) -> List[str]:
        """
        Rank policy clauses by overlap with issue text keywords.
        """
        issue_tokens = self._tokenize(issue_text_lower)
        scored: List[Tuple[int, str]] = []
        for c in clauses:
            c_tokens = self._tokenize(c)
            overlap = len(issue_tokens.intersection(c_tokens))
            scored.append((overlap, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored]

    def _tokenize(self, s: str) -> set:
        s = s.lower()
        s = re.sub(r"[^a-z0-9\s]+", " ", s)
        toks = {t for t in s.split() if len(t) >= 3}
        return toks
