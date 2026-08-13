"""Control 7: tool permission boundary checks with AGT capability guard policy."""


AGENT_ID = "did:example:read-only-agent"


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

    allowed_tools = ["read_ticket", "search_kb", "summarize_case"]
    evaluator = PolicyEvaluator(
        policies=[
            PolicyDocument(
                name="tool-permission-boundary",
                version="1.0",
                defaults=PolicyDefaults(action=PolicyAction.DENY),
                rules=[
                    PolicyRule(
                        name="allow-read-only-capabilities",
                        condition=PolicyCondition(
                            field="tool_name",
                            operator=PolicyOperator.IN,
                            value=allowed_tools,
                        ),
                        action=PolicyAction.ALLOW,
                        priority=100,
                        message="Tool is within this agent identity's capability boundary",
                    )
                ],
            )
        ]
    )

    for tool_name in ["read_ticket", "delete_ticket", "summarize_case", "deploy_prod"]:
        decision = evaluator.evaluate(
            {
                "agent_id": AGENT_ID,
                "tool_name": tool_name,
                "identity_scope": "support.readonly",
            }
        )
        print(f"{tool_name}: {'allowed' if decision.allowed else 'blocked'} - {decision.reason}")


if __name__ == "__main__":
    main()