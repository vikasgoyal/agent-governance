"""Control 2: limit each Agent Framework execution with AGT KillSwitch."""

from __future__ import annotations

import asyncio
import os
import warnings
from pathlib import Path
from threading import Event

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
    message=r"agent-hypervisor is deprecated. Use agent-governance-toolkit-core instead.*",
    category=DeprecationWarning,
)

from agent_framework import Agent, AgentMiddleware, AgentResponse, FunctionTool, Message
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential
from hypervisor.security.kill_switch import KillReason, KillSwitch


AGENT_DID = "did:example:duration-limited-agent"
SESSION_ID = "session-duration-demo"
POLICY_PATH = Path(__file__).with_name("policies") / "02.yaml"
ENV_PATH = Path(__file__).parents[1] / ".env"


def load_dotenv() -> None:
    """Load local Azure settings without overwriting environment values."""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def load_max_duration_seconds() -> float:
    """Read and validate the per-execution duration from the YAML policy."""
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    max_duration_seconds = float(
        policy["execution_timeout"]["max_duration_seconds"]
    )
    if max_duration_seconds <= 0:
        raise ValueError("max_duration_seconds must be greater than zero")
    return max_duration_seconds


class ExecutionTimeoutMiddleware(AgentMiddleware):
    """Cancel overlong executions and record the termination with AGT."""

    def __init__(
        self,
        *,
        max_duration_seconds: float,
        kill_switch: KillSwitch,
        termination_requested: Event,
        console: Console,
        agent_did: str = AGENT_DID,
        session_id: str = SESSION_ID,
    ) -> None:
        self.max_duration_seconds = max_duration_seconds
        self.kill_switch = kill_switch
        self.termination_requested = termination_requested
        self.console = console
        self.agent_did = agent_did
        self.session_id = session_id

    async def process(self, context, call_next) -> None:
        # KillSwitch invokes this callback when a timeout kill is recorded.
        self.termination_requested.clear()
        self.kill_switch.register_agent(
            self.agent_did,
            self.termination_requested.set,
        )

        try:
            # asyncio.timeout performs the actual cancellation of in-flight work.
            async with asyncio.timeout(self.max_duration_seconds):
                await call_next()
        except TimeoutError:
            details = (
                f"Agent execution exceeded its "
                f"{self.max_duration_seconds:g}s duration limit."
            )
            kill_result = self.kill_switch.kill(
                agent_did=self.agent_did,
                session_id=self.session_id,
                reason=KillReason.SESSION_TIMEOUT,
                details=details,
            )
            self.console.print(
                "[bold red]  execution timed out[/bold red] "
                f"kill_id={kill_result.kill_id} "
                f"terminated={kill_result.terminated}"
            )
            context.result = AgentResponse(
                messages=[
                    Message(
                        "assistant",
                        [f"Blocked by execution-duration policy: {details}"],
                    )
                ]
            )
        finally:
            # kill() also unregisters the agent; this handles successful runs.
            self.kill_switch.unregister_agent(self.agent_did)


def main() -> None:
    """Create the governed agent and demonstrate one timed-out execution."""
    console = Console()
    load_dotenv()
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    deployment_name = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]
    max_duration_seconds = load_max_duration_seconds()

    os.environ.pop("AZURE_OPENAI_ENDPOINT", None)
    os.environ.pop("AZURE_OPENAI_BASE_URL", None)
    os.environ.pop("AZURE_OPENAI_API_VERSION", None)

    kill_switch = KillSwitch()
    termination_requested = Event()
    timeout_middleware = ExecutionTimeoutMiddleware(
        max_duration_seconds=max_duration_seconds,
        kill_switch=kill_switch,
        termination_requested=termination_requested,
        console=console,
    )

    chat_client = OpenAIChatClient(
        model=deployment_name,
        credential=DefaultAzureCredential(),
        base_url=f"{endpoint.rstrip('/')}/openai/v1/",
    )

    async def slow_operation() -> str:
        """Represent governed work that intentionally exceeds the limit."""
        delay_seconds = max_duration_seconds + 5
        console.print(
            f"[yellow]  slow_operation started ({delay_seconds:g}s)[/yellow]"
        )
        await asyncio.sleep(delay_seconds)
        return "slow operation completed"

    agent = Agent(
        client=chat_client,
        name="duration-limited-agent",
        instructions="Answer briefly and follow tool-use instructions exactly.",
        tools=[
            FunctionTool(
                name="slow_operation",
                description="Run a deliberately slow operation",
                func=slow_operation,
            )
        ],
        middleware=[timeout_middleware],
    )

    console.print(
        Panel.fit(
            "[bold cyan]Maximum Agent Execution Duration[/bold cyan]\n"
            "Start -> Enforce Deadline -> Kill and Audit",
            border_style="cyan",
        )
    )
    console.print(f"[dim]Agent:[/dim]      {agent.name} ({agent.id})")
    console.print(f"[dim]Policy:[/dim]     {POLICY_PATH}")
    console.print(
        f"[dim]Deadline:[/dim]   {max_duration_seconds:g} seconds"
    )
    console.print(f"[dim]Deployment:[/dim] {deployment_name}\n")

    async def run_demo() -> list[tuple[int, str, str]]:
        rows: list[tuple[int, str, str]] = []
        kills_before = kill_switch.total_kills
        response = await agent.run(
            "Attempt 1: answer in one short sentence about runtime governance."
        )
        status = (
            "TIMED OUT"
            if kill_switch.total_kills > kills_before
            else "COMPLETED"
        )
        rows.append((1, status, str(response)))

        kills_before = kill_switch.total_kills
        response = await agent.run(
            "Attempt 2: call the slow_operation tool exactly once and report its result."
        )
        status = (
            "TIMED OUT"
            if kill_switch.total_kills > kills_before
            else "COMPLETED"
        )
        rows.append((2, status, str(response)))
        return rows

    rows = asyncio.run(run_demo())
    attempts = Table(
        title="Execution attempts",
        header_style="bold magenta",
        show_lines=True,
    )
    attempts.add_column("Attempt", justify="right")
    attempts.add_column("Result", justify="center")
    attempts.add_column("Agent response")
    for attempt_number, status, response in rows:
        color = "green" if status == "COMPLETED" else "red"
        attempts.add_row(
            str(attempt_number),
            f"[bold {color}]{status}[/bold {color}]",
            response,
        )
    console.print(attempts)

    console.print(
        Panel(
            f"[bold]Kill records:[/bold] {kill_switch.total_kills}\n"
            "[bold]Termination callback invoked:[/bold] "
            f"{termination_requested.is_set()}",
            title="[bold cyan]Timeout summary[/bold cyan]",
            border_style="cyan",
        )
    )


if __name__ == "__main__":
    main()
