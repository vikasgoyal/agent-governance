"""Control 9: external communication policy with AGT policy evaluation."""

from urllib.parse import urlparse


AGENT_ID = "did:example:procurement-agent"


def destination_host(url: str) -> str:
    return urlparse(url).netloc.lower()


def main() -> None:
    try:
        from agent_os.policies import PolicyEvaluator
        from agent_os.policies.schema import (
            PolicyAction,
            PolicyCondition,
            PolicyDefaults,
            PolicyDocument,
            PolicyOperator,
            PolicyRule,
        )
    except ImportError as exc:
        raise SystemExit(
            "Install AGT policy packages first: pip install agent-governance-toolkit[full] agent-os-kernel"
        ) from exc

    approved_hosts = ["api.contoso.com", "mcp.trusted-partner.example"]
    evaluator = PolicyEvaluator(
        policies=[
            PolicyDocument(
                name="external-communication-allowlist",
                version="1.0",
                defaults=PolicyDefaults(action=PolicyAction.DENY),
                rules=[
                    PolicyRule(
                        name="allow-approved-external-hosts",
                        condition=PolicyCondition(
                            field="destination_host",
                            operator=PolicyOperator.IN,
                            value=approved_hosts,
                        ),
                        action=PolicyAction.ALLOW,
                        priority=100,
                        message="Destination is approved for this agent",
                    )
                ],
            )
        ]
    )

    urls = [
        "https://api.contoso.com/purchase-orders",
        "https://unknown.example/upload",
        "https://mcp.trusted-partner.example/tools/search",
    ]

    for url in urls:
        host = destination_host(url)
        decision = evaluator.evaluate(
            {
                "agent_id": AGENT_ID,
                "action": "external_call",
                "destination_host": host,
                "url": url,
            }
        )
        print(f"{url}: {'allowed' if decision.allowed else 'blocked'} - {decision.reason}")


if __name__ == "__main__":
    main()