# src/tools/triage_tool.py
from __future__ import annotations

from typing import Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

from src.schemas import EmailMessage

TriageLabel = Literal["WARRANTY_CLAIM", "NON_CLAIM"]


class TriageResult(BaseModel):
    label: TriageLabel = Field(..., description="WARRANTY_CLAIM or NON_CLAIM")
    reason: str = Field(..., description="Short reason")


class TriageTool:
    """
    LLM-first triage. If LLM fails, a broad heuristic is used.
    Heuristic goal: minimize false NON_CLAIM (better to over-route to claims).
    """

    def __init__(self, llm: Optional[BaseChatModel]) -> None:
        self.llm = llm
        self.parser = JsonOutputParser(pydantic_object=TriageResult)

        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You classify emails for a warranty claims system.\n"
                    "If the email is about a product problem, purchase, return, damage, or warranty, label WARRANTY_CLAIM.\n"
                    "If it's marketing/spam/partnership/sales outreach, label NON_CLAIM.\n"
                    "Return ONLY JSON."
                ),
                (
                    "human",
                    "Subject: {subject}\n\nBody:\n{body}\n\n{format_instructions}"
                ),
            ]
        )

    def classify(self, email: EmailMessage) -> TriageResult:
        if self.llm:
            try:
                chain = self.prompt | self.llm | self.parser
                out = chain.invoke(
                    {
                        "subject": email.subject,
                        "body": email.body,
                        "format_instructions": self.parser.get_format_instructions(),
                    }
                )
                # normalize dict -> model if needed
                return TriageResult.model_validate(out)
            except Exception:
                pass

        return self._heuristic(email)

    def _heuristic(self, email: EmailMessage) -> TriageResult:
        text = f"{email.subject} {email.body}".lower()

        # Strong spam signals
        spam_signals = ["seo", "marketing", "partnership", "promotion", "ads", "advertising", "agency"]
        if any(s in text for s in spam_signals):
            return TriageResult(label="NON_CLAIM", reason="Spam/marketing outreach signals detected")

        # Broad claim signals (include wear/tear, travel damage, cracks, attachments)
        claim_signals = [
            "warranty", "claim", "replace", "replacement", "refund", "return",
            "bought", "purchase", "purchased", "order", "invoice", "receipt",
            "dryer", "hair dryer", "aerodry",
            "stopped", "not working", "won’t", "won't", "doesn't", "no power",
            "overheat", "overheating", "shuts off", "burning", "sparks",
            "touch", "controls", "firmware",
            "attachment", "nozzle", "diffuser", "doesn't fit", "fits securely",
            "cracked", "broken", "dropped",
            "travel", "flight", "suitcase"
        ]

        if any(k in text for k in claim_signals):
            return TriageResult(label="WARRANTY_CLAIM", reason="Product issue/purchase/damage signals detected")

        return TriageResult(label="NON_CLAIM", reason="No product issue/purchase/warranty indicators detected")
