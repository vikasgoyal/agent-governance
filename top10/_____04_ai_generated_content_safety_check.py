"""Control 4: AI-generated content safety with MAF, AGT, and YAML."""

from __future__ import annotations

import asyncio
import os
import warnings
from pathlib import Path


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
    load_dotenv()
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    deployment_name = os.environ["AZURE_OPENAI_DEPLOYMENT_NAME"]

    os.environ.pop("AZURE_OPENAI_ENDPOINT", None)
    os.environ.pop("AZURE_OPENAI_BASE_URL", None)
    os.environ.pop("AZURE_OPENAI_API_VERSION", None)

    policy = PolicyDocument.from_yaml(POLICY_PATH)
    evaluator = PolicyEvaluator(policies=[policy])

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
                print("  output allowed by content safety policy")
                return

            print(f"  output blocked by content safety policy: {decision.reason}")
            context.result = AgentResponse(
                messages=[Message("assistant", [f"Blocked by content safety policy: {decision.reason}"])]
            )

    agent = Agent(
        client=chat_client,
        name="content-safety-agent",
        instructions="Answer the user's request in one short sentence.",
        middleware=[ContentSafetyMiddleware()],
    )

    print(f"agent framework agent: {agent.name} ({agent.id})")
    print(f"policy file: {POLICY_PATH}")
    print(f"azure openai deployment: {deployment_name}")

    async def run_demo() -> None:
        prompts = [
            "Write a safe status update for a deployment checklist.",
            "Write a sentence that says malware and credential theft are prohibited.",
        ]
        for prompt_number, prompt in enumerate(prompts, start=1):
            response = await agent.run(prompt)
            print(f"prompt {prompt_number}: agent response: {response}")

    asyncio.run(run_demo())


if __name__ == "__main__":
    main()