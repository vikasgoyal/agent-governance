"""Control 4: AI-generated content safety with MAF, AGT, and YAML."""

from __future__ import annotations

import asyncio
import os
import warnings
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


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

from agent_framework import Agent, AgentMiddleware, AgentResponse, Message
from agent_framework.openai import OpenAIChatClient
from agent_os.policies import PolicyEvaluator
from agent_os.policies.schema import PolicyDocument
from azure.identity import DefaultAzureCredential


AGENT_DID = "did:example:communications-agent"
POLICY_PATH = Path(__file__).with_name("policies") / "04.yaml"
ENV_PATH = Path(__file__).parents[1] / ".env"


def load_dotenv() -> None:
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def response_text(response) -> str:
    return getattr(response, "text", None) or str(response)


def main() -> None:
    console = Console()
    load_dotenv()
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    deployment_name = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

    os.environ.pop("AZURE_OPENAI_ENDPOINT", None)
    os.environ.pop("AZURE_OPENAI_BASE_URL", None)
    os.environ.pop("AZURE_OPENAI_API_VERSION", None)

    policy = PolicyDocument.from_yaml(POLICY_PATH)
    evaluator = PolicyEvaluator(policies=[policy])
    safety_events: list[tuple[bool, str]] = []

    chat_client = OpenAIChatClient(
        model=deployment_name,
        credential=DefaultAzureCredential(),
        base_url=f"{endpoint.rstrip('/')}/openai/v1/",
    )

    class ContentSafetyMiddleware(AgentMiddleware):
        async def process(self, context, call_next) -> None:
            await call_next()
            output_text = response_text(context.result)
            decision = evaluator.evaluate(
                {
                    "agent_id": AGENT_DID,
                    "action": "send_response",
                    "output_text": output_text,
                }
            )
            if decision.allowed:
                safety_events.append((True, decision.reason))
                console.print(
                    "[green]  output allowed by content safety policy[/green]"
                )
                return

            safety_events.append((False, decision.reason))
            console.print(
                "[bold red]  output blocked by content safety policy:[/bold red] "
                f"{decision.reason}"
            )
            context.result = AgentResponse(
                messages=[
                    Message(
                        "assistant",
                        [
                            "Blocked by content safety policy: "
                            f"{decision.reason}"
                        ],
                    )
                ]
            )

    agent = Agent(
        client=chat_client,
        name="content-safety-agent",
        instructions="Answer the user's request in one short sentence.",
        middleware=[ContentSafetyMiddleware()],
    )

    console.print(
        Panel.fit(
            "[bold cyan]AI-Generated Content Safety[/bold cyan]\n"
            "Generate -> Evaluate Output -> Allow or Block",
            border_style="cyan",
        )
    )
    console.print(f"[dim]Agent:[/dim]      {agent.name} ({agent.id})")
    console.print(f"[dim]Policy:[/dim]     {POLICY_PATH}")
    console.print(f"[dim]Deployment:[/dim] {deployment_name}\n")

    async def run_demo() -> list[tuple[int, str, bool, str, str]]:
        rows: list[tuple[int, str, bool, str, str]] = []
        prompts = [
            "Write a safe status update for a deployment checklist.",
            "Write a sentence that says malware and credential theft are prohibited.",
        ]
        for prompt_number, prompt in enumerate(prompts, start=1):
            event_count = len(safety_events)
            response = await agent.run(prompt)
            if len(safety_events) == event_count:
                allowed, reason = False, "No policy decision recorded"
            else:
                allowed, reason = safety_events[-1]
            rows.append(
                (prompt_number, prompt, allowed, reason, str(response))
            )
        return rows

    rows = asyncio.run(run_demo())
    results = Table(
        title="Generated-content evaluations",
        header_style="bold magenta",
        show_lines=True,
    )
    results.add_column("#", justify="right")
    results.add_column("Prompt")
    results.add_column("Decision", justify="center")
    results.add_column("Policy reason")
    results.add_column("Agent response")
    for prompt_number, prompt, allowed, reason, response in rows:
        decision = (
            "[bold green]ALLOW[/bold green]"
            if allowed
            else "[bold red]BLOCK[/bold red]"
        )
        results.add_row(
            str(prompt_number),
            prompt,
            decision,
            reason,
            response,
        )
    console.print(results)

    allowed_count = sum(1 for _, _, allowed, _, _ in rows if allowed)
    console.print(
        Panel(
            f"[bold]Outputs evaluated:[/bold] {len(rows)}\n"
            f"[bold green]Allowed:[/bold green] {allowed_count}\n"
            f"[bold red]Blocked:[/bold red] {len(rows) - allowed_count}",
            title="[bold cyan]Content-safety summary[/bold cyan]",
            border_style="cyan",
        )
    )


if __name__ == "__main__":
    main()