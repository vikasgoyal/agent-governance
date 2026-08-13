"""Control 8: repetition and infinite-loop detection with AGT ring breach detector."""


AGENT_DID = "did:example:looping-agent"
SESSION_ID = "session-loop-demo"


def main() -> None:
    try:
        from hypervisor.models import ExecutionRing
        from hypervisor.rings.breach_detector import BreachSeverity, RingBreachDetector
        from hypervisor.security.kill_switch import KillReason, KillSwitch
    except ImportError as exc:
        raise SystemExit(
            "Install AGT runtime packages first: pip install agent-governance-toolkit[full] agentmesh-runtime"
        ) from exc

    detector = RingBreachDetector(window_seconds=60, baseline_rate=0.05)
    kill_switch = KillSwitch()

    last_breach = None
    for iteration in range(1, 51):
        last_breach = detector.record_call(
            agent_did=AGENT_DID,
            session_id=SESSION_ID,
            agent_ring=ExecutionRing.RING_3_SANDBOX,
            called_ring=ExecutionRing.RING_0_ROOT,
        )
        if detector.is_breaker_tripped(AGENT_DID, SESSION_ID):
            result = kill_switch.kill(
                agent_did=AGENT_DID,
                session_id=SESSION_ID,
                reason=KillReason.RING_BREACH,
                details="Circuit breaker tripped by repeated high-privilege calls",
            )
            print(f"loop blocked at iteration={iteration}; kill_id={result.kill_id}")
            break

    if last_breach:
        print(
            "breach: "
            f"severity={last_breach.severity}, score={last_breach.anomaly_score:.2f}, "
            f"calls={last_breach.call_count_window}"
        )
        if last_breach.severity in (BreachSeverity.HIGH, BreachSeverity.CRITICAL):
            print("policy action: pause, terminate, or require operator review")


if __name__ == "__main__":
    main()