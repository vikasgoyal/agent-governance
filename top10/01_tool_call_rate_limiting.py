"""Control 1: rate-limit Agent Framework tool calls with AGT and YAML policy."""

from __future__ import annotations

import asyncio
import os
import time
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
from agent_os.integrations.rate_limiter import RateLimiter
from azure.identity import DefaultAzureCredential


AGENT_DID = "did:example:research-agent"

# Resolve configuration relative to this sample instead of the current shell.
POLICY_DIR = Path(__file__).with_name("policies")
POLICY_PATH = POLICY_DIR / "01.yaml"
ENV_PATH = Path(__file__).parents[1] / ".env"


def load_dotenv() -> None:
    """Load local Azure settings without overwriting existing environment values."""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def load_rate_limit_config() -> tuple[str, int, float, bool]:
    """Read the tool-call limit from the YAML governance policy."""
    # Keep governance settings outside the application so they can change
    # without changing the middleware.
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    config = policy["rate_limit"]
    return (
        config["tool_name"],
        int(config["max_calls"]),
        float(config["time_window"]),
        bool(config["per_agent"]),
    )


def main() -> None:
    """Create the governed agent and demonstrate its tool-call limit."""
    console = Console()
    load_dotenv()
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    deployment_name = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

    # Pass an explicit v1 base URL so the chat client uses Azure OpenAI.
    os.environ.pop("AZURE_OPENAI_ENDPOINT", None)
    os.environ.pop("AZURE_OPENAI_BASE_URL", None)
    os.environ.pop("AZURE_OPENAI_API_VERSION", None)

    credential = DefaultAzureCredential()
    chat_client = OpenAIChatClient(
        model=deployment_name,
        credential=credential,
        base_url=f"{endpoint.rstrip('/')}/openai/v1/",
    )

    def record_tool_event(decision: str) -> None:
        tool_events.append((decision, time.monotonic() - demonstration_started_at))

    def web_search(query: str) -> str:
        """Represent the external tool protected by the rate-limit policy."""
        record_tool_event("EXECUTED")
        console.print(f"[green]  web_search executed:[/green] {query}")
        return f"results for {query}"

    rate_limited_tool, max_calls, time_window, per_agent = load_rate_limit_config()
    tool_events: list[tuple[str, float]] = []
    demonstration_started_at = time.monotonic()
    # AGT enforces max_calls within time_window. When per_agent is true,
    # each agent identity receives an independent token bucket.
    limiter = RateLimiter(
        max_calls=max_calls,
        time_window=time_window,
        per_agent=per_agent,
    )

    class ToolRateLimitMiddleware(FunctionMiddleware):
        """Enforce the YAML rate limit before the protected tool runs."""

        async def process(self, context, call_next) -> None:
            tool_name = context.function.name

            # Tools not named by this policy continue through normal execution.
            if tool_name != rate_limited_tool:
                await call_next()
                return

            # A denied call never reaches the tool; return a governed result to
            # the agent instead.
            if not limiter.allow(AGENT_DID):
                record_tool_event("BLOCKED")
                context.result = "Blocked by AGT tool rate limiter"
                console.print(
                    f"[bold red]  {tool_name} blocked by AGT rate limiter[/bold red]"
                )
                return

            await call_next()

    # Attach governance as middleware so the tool itself stays policy-agnostic.
    agent = Agent(
        client=chat_client,
        name="rate-limited-research-agent",
        instructions=(
            "You are a research agent. Use web_search only when allowed "
            "by governance."
        ),
        tools=[
            FunctionTool(
                name="web_search",
                description="Search trusted sources",
                func=web_search,
            )
        ],
        middleware=[ToolRateLimitMiddleware()],
    )

    console.print(
        Panel.fit(
            "[bold cyan]Tool-Call Rate Limiting[/bold cyan]\n"
            "Allow -> Consume Budget -> Block",
            border_style="cyan",
        )
    )
    console.print(f"[dim]Agent:[/dim]      {agent.name} ({agent.id})")
    console.print(f"[dim]Policy:[/dim]     {POLICY_PATH}")
    console.print(
        f"[dim]Limit:[/dim]      {max_calls} calls per "
        f"{time_window:g} seconds"
    )
    console.print(
        f"[dim]Refill:[/dim]     1 call every "
        f"{time_window / max_calls:g} seconds (continuous token bucket)"
    )
    console.print(f"[dim]Deployment:[/dim] {deployment_name}\n")

    async def run_agent_attempt(call_number: int):
        """Ask the agent to invoke the governed tool once."""
        return await agent.run(
            f"Attempt {call_number}: call the web_search tool exactly once "
            "with query 'AGT runtime governance'. "
            "Then answer in one short sentence."
        )

    # Three calls are initially available. Sequential model turns may take long
    # enough for the continuously refilling bucket to grant another call.
    rows: list[tuple[int, float, str, str]] = []
    for attempt_number in range(1, 10):
        event_count = len(tool_events)
        response = asyncio.run(run_agent_attempt(attempt_number))
        event, decision_elapsed = (
            tool_events[-1]
            if len(tool_events) > event_count
            else ("NO TOOL CALL", time.monotonic() - demonstration_started_at)
        )
        rows.append((attempt_number, decision_elapsed, event, str(response)))

    attempts = Table(
        title="Governed tool-call attempts",
        header_style="bold magenta",
        show_lines=True,
    )
    attempts.add_column("Attempt", justify="right")
    attempts.add_column("Decision at", justify="right")
    attempts.add_column("Tool decision", justify="center")
    attempts.add_column("Agent response")
    for attempt_number, decision_elapsed, event, response in rows:
        color = {
            "EXECUTED": "green",
            "BLOCKED": "red",
            "NO TOOL CALL": "yellow",
        }[event]
        attempts.add_row(
            str(attempt_number),
            f"+{decision_elapsed:.2f}s",
            f"[bold {color}]{event}[/bold {color}]",
            response,
        )
    console.print(attempts)

    # check() observes the bucket without consuming another call.
    status = limiter.check(AGENT_DID)
    console.print(
        Panel(
            f"[bold]Remaining calls:[/bold] {status.remaining_calls}\n"
            f"[bold]Wait for next token:[/bold] {status.wait_seconds:.2f}s",
            title="[bold cyan]Rate-limit summary[/bold cyan]",
            border_style="cyan",
        )
    )


if __name__ == "__main__":
    main()