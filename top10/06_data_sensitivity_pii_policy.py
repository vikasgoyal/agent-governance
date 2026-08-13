"""Control 6: classify, redact, and govern sensitive data with AGT."""

from __future__ import annotations

import warnings
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


warnings.filterwarnings(
    "ignore",
    message=r"agent-os-kernel is deprecated. Use agent-governance-toolkit-core instead.*",
    category=DeprecationWarning,
)

from agent_os.credential_redactor import CredentialRedactor
from agent_os.policies.data_classification import (
    ABACPolicy,
    DataAccessEvaluator,
    DataClassification,
    DataLabel,
    classify_text,
)


POLICY_PATH = Path(__file__).with_name("policies") / "06.yaml"


def load_egress_policy() -> tuple[DataAccessEvaluator, str, str]:
    """Load the governed agent, ABAC policy, and redaction placeholder."""
    document = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    config = document["egress_policy"]

    classification_name = str(config["max_classification"]).upper()
    try:
        max_classification = DataClassification[classification_name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown data classification: {classification_name}"
        ) from exc

    agent_id = str(config["agent_id"])
    policy = ABACPolicy(
        agent_id=agent_id,
        max_classification=max_classification,
        denied_categories=list(config["denied_categories"]),
    )

    placeholder = str(document["redaction"]["placeholder"])
    if not placeholder:
        raise ValueError("redaction placeholder must not be empty")

    return DataAccessEvaluator([policy]), agent_id, placeholder


def classify_sensitive_text(text: str) -> DataLabel:
    """Classify PII/PHI/PCI and add a restricted credential category."""
    label = classify_text(text)
    if not CredentialRedactor.contains_credentials(text):
        return label

    categories = list(dict.fromkeys([*label.categories, "CREDENTIAL"]))
    return label.model_copy(
        update={
            "classification": max(
                label.classification,
                DataClassification.RESTRICTED,
            ),
            "categories": categories,
        }
    )


def redact_sensitive_text(text: str, placeholder: str) -> str:
    """Redact credentials and AGT's PII patterns."""
    redacted = CredentialRedactor.redact(text)
    for pii_pattern in CredentialRedactor.PII_PATTERNS:
        redacted = pii_pattern.pattern.sub(placeholder, redacted)
    return redacted


def add_decision_row(
    table: Table,
    *,
    stage: str,
    label: DataLabel,
    allowed: bool,
    reason: str,
) -> None:
    """Add one color-coded governance decision to the output table."""
    decision = (
        "[bold green]ALLOW[/bold green]"
        if allowed
        else "[bold red]DENY[/bold red]"
    )
    classification_color = {
        DataClassification.PUBLIC: "green",
        DataClassification.INTERNAL: "cyan",
        DataClassification.CONFIDENTIAL: "yellow",
        DataClassification.RESTRICTED: "red",
        DataClassification.TOP_SECRET: "bold red",
    }[label.classification]
    categories = ", ".join(label.categories) or "-"
    table.add_row(
        stage,
        decision,
        f"[{classification_color}]{label.classification.name}"
        f"[/{classification_color}]",
        categories,
        reason,
    )


def main() -> None:
    """Demonstrate classify, deny, redact, reclassify, and allow."""
    console = Console()
    evaluator, agent_id, placeholder = load_egress_policy()
    outbound_text = (
        "Create a ticket for Jane, SSN 123-45-6789, "
        "api_key=abcdef1234567890."
    )

    console.print(
        Panel.fit(
            "[bold cyan]Sensitive Data Egress Governance[/bold cyan]\n"
            "Classify -> Deny -> Redact -> Reclassify -> Allow",
            border_style="cyan",
        )
    )
    console.print(f"[dim]Policy:[/dim] {POLICY_PATH}")
    console.print(f"[dim]Agent:[/dim]  {agent_id}\n")
    console.print(
        Panel(
            outbound_text,
            title="[bold red]Original outbound payload (unsafe)[/bold red]",
            border_style="red",
        )
    )

    decisions = Table(
        title="Egress decisions",
        header_style="bold magenta",
        show_lines=True,
    )
    decisions.add_column("Stage", style="bold")
    decisions.add_column("Decision", justify="center")
    decisions.add_column("Classification")
    decisions.add_column("Categories")
    decisions.add_column("Reason")

    # Evaluate the original payload without logging its sensitive contents.
    original_label = classify_sensitive_text(outbound_text)
    original_decision = evaluator.evaluate(agent_id, original_label)
    add_decision_row(
        decisions,
        stage="Original",
        label=original_label,
        allowed=original_decision.allowed,
        reason=original_decision.reason,
    )

    if original_decision.allowed:
        console.print(decisions)
        console.print("[bold green]No redaction required.[/bold green]")
        return

    # Redaction changes the data label, so evaluate the sanitized payload again.
    safe_text = redact_sensitive_text(outbound_text, placeholder)
    safe_label = classify_sensitive_text(safe_text)
    safe_decision = evaluator.evaluate(agent_id, safe_label)
    add_decision_row(
        decisions,
        stage="Redacted",
        label=safe_label,
        allowed=safe_decision.allowed,
        reason=safe_decision.reason,
    )

    console.print(decisions)
    console.print(
        Panel(
            safe_text,
            title="[bold green]Safe outbound payload[/bold green]",
            border_style="green" if safe_decision.allowed else "red",
        )
    )


if __name__ == "__main__":
    main()
