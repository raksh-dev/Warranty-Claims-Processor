# src/tools/label_generator.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.schemas import ClaimExtract


@dataclass(frozen=True)
class LabelGeneratorConfig:
    outbox_dir: Path
    carrier_name: str = "MockShip"
    service_level: str = "Ground"
    from_address: str = "AeroDry Returns Dept, 100 Returns Lane, Newark, NJ 07102"


class LabelGenerator:
    """
    Generates a mocked return shipping label.
    The assignment allows a simple PDF stub, a string, or a file link.
    We'll create a .txt file in data/outbox/ for speed and reliability.
    """

    def __init__(self, config: LabelGeneratorConfig) -> None:
        self.config = config
        self.config.outbox_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, claim: ClaimExtract, email_id: str) -> str:
        """
        Returns a label reference string (filename) that you can include in the approval email.
        """
        label_id = uuid.uuid4().hex[:10]
        filename = f"return_label_{email_id}_{label_id}.txt"
        path = self.config.outbox_dir / filename

        to_address = claim.shipping_address or "CUSTOMER_ADDRESS_MISSING"

        contents = (
            "=== RETURN SHIPPING LABEL (MOCK) ===\n"
            f"Created: {datetime.utcnow().isoformat()}Z\n"
            f"Carrier: {self.config.carrier_name}\n"
            f"Service: {self.config.service_level}\n"
            f"Tracking: {self._mock_tracking_number(label_id)}\n\n"
            "FROM:\n"
            f"{self.config.from_address}\n\n"
            "TO:\n"
            f"{to_address}\n\n"
            f"Item: {claim.product_name or claim.product_model_hint or 'Hair Dryer'}\n"
            "RMA: MOCK-RMA-0001\n"
            "Instructions: Print this label and attach to your package.\n"
        )

        path.write_text(contents, encoding="utf-8")
        return filename

    def _mock_tracking_number(self, seed: str) -> str:
        # Simple deterministic-looking tracking number
        return f"MS{seed.upper()}US"
