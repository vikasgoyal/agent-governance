"""Control 10: cost and resource guardrails with AGT token budget tracking."""


AGENT_ID = "did:example:research-agent"
SESSION_TOKEN_BUDGET = 10_000


def main() -> None:
    try:
        from agent_os.context_budget import BudgetExceeded, ContextPriority, ContextScheduler
        from agent_os.integrations.token_budget import TokenBudgetTracker
    except ImportError as exc:
        raise SystemExit(
            "Install AGT budget packages first: pip install agent-governance-toolkit[full] agent-os-kernel"
        ) from exc

    tracker = TokenBudgetTracker(max_tokens=SESSION_TOKEN_BUDGET, warning_threshold=0.8)
    scheduler = ContextScheduler(total_budget=SESSION_TOKEN_BUDGET, lookup_ratio=0.90, warn_threshold=0.85)

    tasks = [
        ("collect sources", ContextPriority.NORMAL, 1_500, 500),
        ("summarize reports", ContextPriority.HIGH, 3_000, 1_000),
        ("draft appendix", ContextPriority.LOW, 4_500, 1_500),
    ]

    for task_name, priority, prompt_tokens, completion_tokens in tasks:
        status = tracker.check_budget(AGENT_ID)
        if status.is_exceeded:
            print(f"blocked before task={task_name}: session token budget exceeded")
            break

        print(f"task={task_name} before={tracker.format_status(AGENT_ID)}")
        scheduler.allocate(AGENT_ID, task_name, priority=priority)

        try:
            scheduler.record_usage(
                AGENT_ID,
                lookup_tokens=prompt_tokens,
                reasoning_tokens=completion_tokens,
            )
        except BudgetExceeded as exc:
            print(f"context budget stop: agent={exc.agent_id} used={exc.used} budget={exc.budget}")
        finally:
            scheduler.release(AGENT_ID)

        current = tracker.record_usage(AGENT_ID, prompt_tokens, completion_tokens)
        print(
            f"after={tracker.format_status(AGENT_ID)} "
            f"warning={current.is_warning} exceeded={current.is_exceeded}"
        )

    final = tracker.get_usage(AGENT_ID)
    print(f"final used={final.used} remaining={final.remaining} exceeded={final.is_exceeded}")


if __name__ == "__main__":
    main()