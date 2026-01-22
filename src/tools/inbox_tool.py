# src/tools/inbox_tool.py
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import ValidationError

from src.schemas import EmailMessage


@dataclass(frozen=True)
class InboxPaths:
    inbox_dir: Path
    triage_rejected_dir: Path
    review_queue_dir: Path
    processed_dir: Optional[Path] = None  # optional if you want to archive processed emails


class InboxTool:
    """
    File-based inbox adapter.

    Responsibilities:
    - List inbound email JSON files in data/inbox/
    - Load + validate as EmailMessage
    - Move files to other folders (triage_rejected, processed, etc.)
    """

    def __init__(self, paths: InboxPaths) -> None:
        self.paths = paths
        self.paths.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.paths.triage_rejected_dir.mkdir(parents=True, exist_ok=True)
        self.paths.review_queue_dir.mkdir(parents=True, exist_ok=True)
        if self.paths.processed_dir:
            self.paths.processed_dir.mkdir(parents=True, exist_ok=True)

    def list_email_files(self) -> List[Path]:
        """Return all JSON files in inbox, sorted for deterministic runs."""
        return sorted(self.paths.inbox_dir.glob("*.json"))

    def load_email(self, file_path: Path) -> EmailMessage:
        """Load a single inbox JSON file into EmailMessage."""
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        # Allow simple fallback: if email_id is missing, derive from filename
        raw.setdefault("email_id", file_path.stem)
        try:
            return EmailMessage.model_validate(raw)
        except ValidationError as e:
            raise ValueError(f"Invalid email JSON in {file_path.name}: {e}") from e

    def load_all_emails(self) -> Tuple[List[EmailMessage], List[Tuple[Path, str]]]:
        """
        Load all emails in inbox.
        Returns: (valid_emails, errors)
        errors = list of (file_path, error_string)
        """
        emails: List[EmailMessage] = []
        errors: List[Tuple[Path, str]] = []
        for fp in self.list_email_files():
            try:
                emails.append(self.load_email(fp))
            except Exception as e:
                errors.append((fp, str(e)))
        return emails, errors

    def move_to_triage_rejected(self, email_id: str) -> Path:
        """Move the inbox file to triage_rejected/ and return new path."""
        src = self.paths.inbox_dir / f"{email_id}.json"
        dst = self.paths.triage_rejected_dir / f"{email_id}.json"
        if not src.exists():
            raise FileNotFoundError(f"Cannot move; inbox file not found: {src}")
        return Path(shutil.move(str(src), str(dst)))

    def move_to_processed(self, email_id: str) -> Optional[Path]:
        """
        Move the inbox file to processed/ if configured.
        If processed_dir is None, this is a no-op.
        """
        if not self.paths.processed_dir:
            return None
        src = self.paths.inbox_dir / f"{email_id}.json"
        dst = self.paths.processed_dir / f"{email_id}.json"
        if not src.exists():
            raise FileNotFoundError(f"Cannot move; inbox file not found: {src}")
        return Path(shutil.move(str(src), str(dst)))

    def peek_raw(self, email_id: str) -> dict:
        """Read raw JSON dict without validation (useful for debugging)."""
        fp = self.paths.inbox_dir / f"{email_id}.json"
        if not fp.exists():
            raise FileNotFoundError(fp)
        return json.loads(fp.read_text(encoding="utf-8"))
