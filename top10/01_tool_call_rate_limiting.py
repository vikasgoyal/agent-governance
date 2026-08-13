"""Control 1: rate-limit Agent Framework tool calls with AGT and YAML policy."""

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

    def web_search(query: str) -> str:
        """Represent the external tool protected by the rate-limit policy."""
        print(f"\033[32m  web_search executed with query: {query}\033[0m")
        return f"results for {query}"

    rate_limited_tool, max_calls, time_window, per_agent = load_rate_limit_config()
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
                context.result = "Blocked by AGT tool rate limiter"
                print(f"\033[31m  {tool_name} blocked by AGT tool rate limiter\033[0m")
                return

            await call_next()

    # Attach governance as middleware so the tool itself stays policy-agnostic.
    agent = Agent(
        client=chat_client,
        name="rate-limited-research-agent",
        instructions="You are a research agent. Use web_search only when allowed by governance.",
        tools=[FunctionTool(name="web_search", description="Search trusted sources", func=web_search)],
        middleware=[ToolRateLimitMiddleware()],
    )

    print(f"agent framework agent: {agent.name} ({agent.id})")
    print(f"policy directory: {POLICY_DIR}")
    print(f"rate limit: {rate_limited_tool} > {max_calls} calls per {time_window:g} seconds")
    print(f"azure openai deployment: {deployment_name}")

    async def run_agent_attempt(call_number: int):
        """Ask the agent to invoke the governed tool once."""
        return await agent.run(
            f"Attempt {call_number}: call the web_search tool exactly once with query 'AGT runtime governance'. "
            "Then answer in one short sentence."
        )

    # The YAML policy allows three immediate calls, so later attempts are blocked.
    for attempt_number in range(1, 6):
        response = asyncio.run(run_agent_attempt(attempt_number))
        print(f"attempt {attempt_number}: agent response: {response}")

    # check() observes the bucket without consuming another call.
    status = limiter.check(AGENT_DID)
    print(f"summary: remaining_calls={status.remaining_calls}, wait_seconds={status.wait_seconds:.2f}")


if __name__ == "__main__":
    main()