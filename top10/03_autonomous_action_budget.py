"""Control 3: autonomous action budget with MAF, AGT, and YAML."""

from __future__ import annotations

import asyncio
import os
import warnings
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


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
        console: Console,
    ) -> None:
        self.governed_tool = governed_tool
        self.tracker = tracker
        self.exceeded_message = exceeded_message
        self.console = console

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
        self.console.print(
            f"[bold red]  {tool_name} blocked[/bold red] at attempt "
            f"{self.tracker.tool_calls_used}: {reason}"
        )
        context.result = (
            f"Blocked by action budget policy: "
            f"{self.exceeded_message} ({reason})"
        )


def main() -> None:
    """Create the governed agent and demonstrate its autonomous action budget."""
    console = Console()
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
        executed_actions.append(action)
        console.print(f"[green]  expense_action executed:[/green] {action}")
        return f"completed {action}"

    executed_actions: list[str] = []
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
                console=console,
            )
        ],
    )

    console.print(
        Panel.fit(
            "[bold cyan]Autonomous Action Budget[/bold cyan]\n"
            "Attempt Action -> Consume Budget -> Require Approval",
            border_style="cyan",
        )
    )
    console.print(f"[dim]Agent:[/dim]      {agent.name} ({agent.id})")
    console.print(f"[dim]Policy:[/dim]     {POLICY_PATH}")
    console.print(f"[dim]Budget:[/dim]     {max_tool_calls} tool calls")
    console.print(f"[dim]Deployment:[/dim] {deployment_name}\n")

    async def run_demo() -> list[tuple[int, str, str, str]]:
        rows: list[tuple[int, str, str, str]] = []
        actions = [
            "read_invoice",
            "classify_expense",
            "draft_reimbursement",
            "submit_payment",
            "notify_user",
        ]
        for action_number, action in enumerate(actions, start=1):
            execution_count = len(executed_actions)
            response = await agent.run(
                f"Action {action_number}: call expense_action exactly once with action '{action}'. "
                "Then answer in one short sentence."
            )
            decision = (
                "EXECUTED"
                if len(executed_actions) > execution_count
                else "BLOCKED"
            )
            rows.append((action_number, action, decision, str(response)))
        return rows

    rows = asyncio.run(run_demo())
    results = Table(
        title="Autonomous action attempts",
        header_style="bold magenta",
        show_lines=True,
    )
    results.add_column("#", justify="right")
    results.add_column("Action")
    results.add_column("Decision", justify="center")
    results.add_column("Agent response")
    for action_number, action, decision, response in rows:
        color = "green" if decision == "EXECUTED" else "red"
        results.add_row(
            str(action_number),
            action,
            f"[bold {color}]{decision}[/bold {color}]",
            response,
        )
    console.print(results)

    remaining_calls = tracker.remaining()["tool_calls"]
    console.print(
        Panel(
            f"[bold]Attempts:[/bold] {tracker.tool_calls_used}\n"
            f"[bold]Budget:[/bold] {max_tool_calls}\n"
            f"[bold]Remaining:[/bold] {max(0, int(remaining_calls or 0))}",
            title="[bold cyan]Action-budget summary[/bold cyan]",
            border_style="cyan",
        )
    )


if __name__ == "__main__":
    main()