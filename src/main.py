# src/main.py
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

# LangChain LLMs (installed via requirements.txt)
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

from src.orchestrator import WarrantyClaimsOrchestrator, OrchestratorConfig
from src.schemas import ReviewPacket
from src.tools import (
    InboxTool,
    InboxPaths,
    TriageTool,
    ExtractionTool,
    ExtractionConfig,
    PolicyRetriever,
    PolicyRetrieverConfig,
    DecisionTool,
    DecisionConfig,
    EmailWriter,
    EmailWriterConfig,
    LabelGenerator,
    LabelGeneratorConfig,
)

console = Console()


# -----------------------------
# LLM Provider Adapter
# -----------------------------
def get_llm() -> Optional[object]:
    """
    Returns a LangChain chat model if an API key is present.
    Priority:
      1) OpenAI (OPENAI_API_KEY)
      2) Anthropic (ANTHROPIC_API_KEY)
    If none are present, returns None (tools fall back to heuristics/templates).
    """
    if os.getenv("OPENAI_API_KEY"):
        # Keep temperature low for consistent extraction/triage
        return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
    if os.getenv("ANTHROPIC_API_KEY"):
        return ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"), temperature=0)
    return None


# -----------------------------
# File helpers
# -----------------------------
def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def print_packet_summary(packet: ReviewPacket) -> None:
    claim = packet.extracted
    lines = [
        f"[bold]Packet:[/bold] {packet.packet_id}",
        f"[bold]Email ID:[/bold] {packet.email_id}",
        f"[bold]Product:[/bold] {claim.product_name or claim.product_model_hint or 'UNKNOWN'}",
        f"[bold]Purchase Date:[/bold] {claim.purchase_date.isoformat() if claim.purchase_date else 'UNKNOWN'}",
        f"[bold]Proof of Purchase:[/bold] {claim.proof_of_purchase_present}",
        f"[bold]Shipping Address:[/bold] {'YES' if claim.shipping_address else 'NO'}",
        f"[bold]Issue:[/bold] {claim.issue_description}",
        "",
        f"[bold]Selected Policy:[/bold] {packet.selected_policy_product_name} ({packet.selected_policy_id})",
        f"[bold]Recommendation:[/bold] {packet.recommendation}  |  [bold]Confidence:[/bold] {packet.confidence}",
    ]
    if claim.missing_fields:
        lines.append("")
        lines.append(f"[bold red]Missing Fields:[/bold red] {', '.join(claim.missing_fields)}")

    console.print(Panel("\n".join(lines), title="Human Review Packet (Summary)", expand=False))


# -----------------------------
# Human in the loop (CLI)
# -----------------------------
def prompt_human_decision() -> str:
    """
    Returns: APPROVED | REJECTED | MORE_INFO_REQUESTED
    """
    choice = Prompt.ask(
        "Human decision",
        choices=["A", "R", "M"],
        default="A",
        show_choices=True,
    )
    if choice == "A":
        return "APPROVED"
    if choice == "R":
        return "REJECTED"
    return "MORE_INFO_REQUESTED"


# -----------------------------
# Main pipeline
# -----------------------------
def run_demo(project_root: Path) -> None:
    data_dir = project_root / "data"

    inbox_dir = data_dir / "inbox"
    triage_rejected_dir = data_dir / "triage_rejected"
    review_queue_dir = data_dir / "review_queue"
    decisions_dir = data_dir / "decisions"
    outbox_dir = data_dir / "outbox"
    policies_dir = data_dir / "policies"

    # Init adapters/tools
    llm = get_llm()
    if llm:
        console.print("[green]LLM enabled.[/green]")
    else:
        console.print("[yellow]LLM not configured. Falling back to heuristics/templates.[/yellow]")
        console.print("Set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable LLM.\n")

    inbox_tool = InboxTool(
        InboxPaths(
            inbox_dir=inbox_dir,
            triage_rejected_dir=triage_rejected_dir,
            review_queue_dir=review_queue_dir,
            processed_dir=None,  # keep simple; can add later
        )
    )

    policy_retriever = PolicyRetriever(PolicyRetrieverConfig(policies_dir=policies_dir))
    known_products = policy_retriever.list_products()

    triage_tool = TriageTool(llm=llm)
    extraction_tool = ExtractionTool(llm=llm, config=ExtractionConfig(known_products=known_products, require_address=False))
    decision_tool = DecisionTool(llm=llm, config=DecisionConfig(warranty_months=3))
    email_writer = EmailWriter(llm=llm, config=EmailWriterConfig())
    label_generator = LabelGenerator(LabelGeneratorConfig(outbox_dir=outbox_dir))

    orchestrator = WarrantyClaimsOrchestrator(
        inbox=inbox_tool,
        triage=triage_tool,
        extraction=extraction_tool,
        policy_retriever=policy_retriever,
        decision=decision_tool,
        email_writer=email_writer,
        label_generator=label_generator,
        config=OrchestratorConfig(auto_archive_processed=False),
    )

    # Load emails
    emails, errors = inbox_tool.load_all_emails()
    if errors:
        console.print("[red]Some inbox files failed to load:[/red]")
        for fp, err in errors:
            console.print(f" - {fp.name}: {err}")
        console.print()

    if not emails:
        console.print("[yellow]No emails found in data/inbox/[/yellow]")
        return

    console.print(f"[bold]Found {len(emails)} inbox email(s). Processing...[/bold]\n")

    # Process each email
    for email in emails:
        console.rule(f"[bold]Processing {email.email_id}[/bold]")

        packet = orchestrator.process_email_to_review_packet(email)
        if packet is None:
            console.print("[cyan]Triage: NON_CLAIM → moved to data/triage_rejected/[/cyan]\n")
            continue

        # Write review packet to review_queue
        packet_path = review_queue_dir / f"review_{packet.packet_id}.json"
        write_json(packet_path, packet.model_dump())
        console.print(f"[green]Created review packet:[/green] {packet_path}")

        # Show summary + ask human decision
        print_packet_summary(packet)
        human_decision = prompt_human_decision()

        # Save decision
        decision_payload = {
            "packet_id": packet.packet_id,
            "email_id": packet.email_id,
            "human_decision": human_decision,
            "decided_at": datetime.utcnow().isoformat() + "Z",
            "notes": "",
        }
        decision_path = decisions_dir / f"decision_{packet.packet_id}.json"
        write_json(decision_path, decision_payload)
        console.print(f"[green]Saved decision:[/green] {decision_path}")

        # Load selected policy for post-actions
        policy = policy_retriever.get_policy_by_product(packet.selected_policy_product_name)
        if policy is None:
            # Extremely unlikely, but keep demo safe
            policy, _ = policy_retriever.select_policy(packet.extracted)

        # Generate outputs to outbox (email draft + optional return label)
        outputs = orchestrator.draft_outputs_after_human_decision(
            packet=packet, policy=policy, human_decision=human_decision
        )

        drafted_email = outputs["drafted_email"]
        label_ref = outputs.get("label_ref")

        # Write email draft to outbox
        email_out_path = outbox_dir / f"email_{packet.email_id}_{human_decision.lower()}.txt"
        write_text(email_out_path, drafted_email)
        console.print(f"[green]Wrote customer email draft:[/green] {email_out_path}")

        if label_ref:
            console.print(f"[green]Return label generated:[/green] {outbox_dir / label_ref}")

        console.print()

    console.print("[bold green]Demo complete.[/bold green]")
    console.print(f"Review packets: {review_queue_dir}")
    console.print(f"Decisions:      {decisions_dir}")
    console.print(f"Outbox:         {outbox_dir}")
    console.print(f"Triage rejects: {triage_rejected_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic AI Warranty Claims Processor (CLI demo)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    demo = sub.add_parser("demo", help="Process all inbox emails once (one-command demo)")
    demo.add_argument("--root", default=".", help="Project root (default: current directory)")

    args = parser.parse_args()

    project_root = Path(args.root).resolve()

    if args.cmd == "demo":
        run_demo(project_root)


if __name__ == "__main__":
    main()
