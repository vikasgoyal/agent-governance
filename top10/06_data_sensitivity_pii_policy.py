"""Control 6: classify, redact, and govern sensitive data with AGT."""

from __future__ import annotations

import warnings
from pathlib import Path

import yaml


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


def main() -> None:
    """Demonstrate classify, deny, redact, reclassify, and allow."""
    evaluator, agent_id, placeholder = load_egress_policy()
    outbound_text = (
        "Create a ticket for Jane, SSN 123-45-6789, "
        "api_key=abcdef1234567890."
    )

    # Evaluate the original payload without logging its sensitive contents.
    original_label = classify_sensitive_text(outbound_text)
    original_decision = evaluator.evaluate(agent_id, original_label)
    print(
        "original: "
        f"allowed={original_decision.allowed}, "
        f"classification={original_label.classification.name}, "
        f"categories={original_label.categories}, "
        f"reason={original_decision.reason}"
    )

    if original_decision.allowed:
        print("no redaction required")
        return

    # Redaction changes the data label, so evaluate the sanitized payload again.
    safe_text = redact_sensitive_text(outbound_text, placeholder)
    safe_label = classify_sensitive_text(safe_text)
    safe_decision = evaluator.evaluate(agent_id, safe_label)
    print(
        "redacted: "
        f"allowed={safe_decision.allowed}, "
        f"classification={safe_label.classification.name}, "
        f"categories={safe_label.categories}, "
        f"reason={safe_decision.reason}"
    )
    print(f"safe outbound text: {safe_text}")


if __name__ == "__main__":
    main()
