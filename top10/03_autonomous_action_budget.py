"""Control 3: autonomous action budget with MAF, AGT, and YAML."""

from __future__ import annotations

import asyncio
import os
import warnings
from pathlib import Path

import yaml


# Hide preview warnings so the sample output focuses on governance decisions.
warnings.filterwarnings(
    "ignore",
    message=r"\[HARNESS\] MemoryStore is experimental and may change or be removed.*",
    category=Warning,
)
warnings.filterwarnings(
    "ignore",
    message=r"\[SKILLS\] SkillResource is experimental and may change or be removed.*",
    category=Warning,
)
warnings.filterwarnings(
    "ignore",
    message=r"agent-os-kernel is deprecated. Use agent-governance-toolkit-core instead.*",
    category=DeprecationWarning,
)

from agent_framework import Agent, FunctionMiddleware, FunctionTool
from agent_framework.openai import OpenAIChatClient
from agent_os.policies.budget import BudgetPolicy, BudgetTracker
from azure.identity import DefaultAzureCredential


POLICY_PATH = Path(__file__).with_name("policies") / "03.yaml"
ENV_PATH = Path(__file__).parents[1] / ".env"


def load_dotenv() -> None:
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def load_action_budget_config() -> tuple[str, int, str]:
    """Read and validate the autonomous action budget from YAML."""
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    config = policy["action_budget"]
    max_tool_calls = int(config["max_tool_calls"])
    if max_tool_calls <= 0:
        raise ValueError("max_tool_calls must be greater than zero")
    return config["tool_name"], max_tool_calls, config["exceeded_message"]


class ActionBudgetMiddleware(FunctionMiddleware):
    """Apply one session-scoped AGT tool-call budget to a governed tool."""

    def __init__(
        self,
        *,
        governed_tool: str,
        tracker: BudgetTracker,
        exceeded_message: str,
    ) -> None:
        self.governed_tool = governed_tool
        self.tracker = tracker
        self.exceeded_message = exceeded_message

    async def process(self, context, call_next) -> None:
        tool_name = context.function.name

        # Only autonomous actions named by this policy consume the budget.
        if tool_name != self.governed_tool:
            await call_next()
            return

        # Record every attempt, including calls made after budget exhaustion.
        self.tracker.record_tool_call()
        if not self.tracker.is_exceeded():
            await call_next()
            return

        reason = ", ".join(self.tracker.exceeded_reasons())
        print(
            f"  {tool_name} blocked at attempt "
            f"{self.tracker.tool_calls_used}: {reason}"
        )
        context.result = (
            f"Blocked by action budget policy: "
            f"{self.exceeded_message} ({reason})"
        )


def main() -> None:
    """Create the governed agent and demonstrate its autonomous action budget."""
    load_dotenv()
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    deployment_name = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

    os.environ.pop("AZURE_OPENAI_ENDPOINT", None)
    os.environ.pop("AZURE_OPENAI_BASE_URL", None)
    os.environ.pop("AZURE_OPENAI_API_VERSION", None)

    governed_tool, max_tool_calls, exceeded_message = load_action_budget_config()
    tracker = BudgetTracker(BudgetPolicy(max_tool_calls=max_tool_calls))

    chat_client = OpenAIChatClient(
        model=deployment_name,
        credential=DefaultAzureCredential(),
        base_url=f"{endpoint.rstrip('/')}/openai/v1/",
    )

    def expense_action(action: str) -> str:
        print(f"  expense_action executed: {action}")
        return f"completed {action}"

    agent = Agent(
        client=chat_client,
        name="budget-governed-expense-agent",
        instructions=(
            "Use expense_action exactly once when asked to perform an "
            "expense workflow step."
        ),
        tools=[
            FunctionTool(
                name="expense_action",
                description="Perform one expense workflow action",
                func=expense_action,
            )
        ],
        middleware=[
            ActionBudgetMiddleware(
                governed_tool=governed_tool,
                tracker=tracker,
                exceeded_message=exceeded_message,
            )
        ],
    )

    print(f"agent framework agent: {agent.name} ({agent.id})")
    print(f"policy file: {POLICY_PATH}")
    print(f"action budget: {max_tool_calls}")
    print(f"azure openai deployment: {deployment_name}")

    async def run_demo() -> None:
        actions = [
            "read_invoice",
            "classify_expense",
            "draft_reimbursement",
            "submit_payment",
            "notify_user",
        ]
        for action_number, action in enumerate(actions, start=1):
            response = await agent.run(
                f"Action {action_number}: call expense_action exactly once with action '{action}'. "
                "Then answer in one short sentence."
            )
            print(f"action {action_number}: agent response: {response}")

    asyncio.run(run_demo())
    remaining_calls = tracker.remaining()["tool_calls"]
    print(
        "summary: "
        f"actions_attempted={tracker.tool_calls_used}, "
        f"budget={max_tool_calls}, "
        f"remaining={max(0, int(remaining_calls or 0))}"
    )


if __name__ == "__main__":
    main()