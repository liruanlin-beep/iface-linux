from dataclasses import dataclass


SAFE_AUTOMATIC_RETRY_STATES = {"NODE_FAIL", "PREEMPTED", "REQUEUED"}
APPROVAL_REQUIRED_STATES = {"OUT_OF_MEMORY", "TIMEOUT"}
TERMINAL_FAILURE_STATES = {"FAILED", "BOOT_FAIL", "DEADLINE"}


@dataclass(frozen=True)
class AutomationPolicy:
    enabled: bool = False
    max_attempts: int = 3
    auto_retry_node_failure: bool = True
    auto_retry_preempted: bool = True
    require_approval_for_resource_change: bool = True

    @classmethod
    def from_mapping(cls, values=None):
        values = values or {}
        return cls(
            enabled=bool(values.get("enabled", False)),
            max_attempts=max(1, min(10, int(values.get("max_attempts", 3)))),
            auto_retry_node_failure=bool(
                values.get("auto_retry_node_failure", True)
            ),
            auto_retry_preempted=bool(values.get("auto_retry_preempted", True)),
            require_approval_for_resource_change=bool(
                values.get("require_approval_for_resource_change", True)
            ),
        )


@dataclass(frozen=True)
class AutomationDecision:
    action: str
    reason: str
    requires_approval: bool = False


def decide_slurm_action(slurm_state, attempts, policy=None):
    policy = policy or AutomationPolicy()
    state = str(slurm_state or "").strip().upper().split("+", 1)[0]
    attempts = max(0, int(attempts or 0))
    if state in {"PENDING", "CONFIGURING", "RUNNING", "COMPLETING", "COMPLETED"}:
        return AutomationDecision("observe", f'Slurm state: {state}')
    if state in SAFE_AUTOMATIC_RETRY_STATES:
        allowed = (
            policy.enabled
            and attempts < policy.max_attempts
            and (
                (state == "NODE_FAIL" and policy.auto_retry_node_failure)
                or (state in {"PREEMPTED", "REQUEUED"} and policy.auto_retry_preempted)
            )
        )
        if allowed:
            return AutomationDecision(
                "retry",
                f'{state} is a transient infrastructure failure and may be retried with the original parameters',
            )
        return AutomationDecision(
            "stop",
            f'{state} automatic recovery is disabled or the attempt limit has been reached',
        )
    if state in APPROVAL_REQUIRED_STATES:
        return AutomationDecision(
            "diagnose",
            f'{state} may require resource changes; first collect sacct, stderr and resource utilization',
            requires_approval=policy.require_approval_for_resource_change,
        )
    if state in TERMINAL_FAILURE_STATES:
        return AutomationDecision(
            "diagnose",
            f'{state} requires log analysis; unsupported repeated submission is blocked',
            requires_approval=True,
        )
    return AutomationDecision("observe", f"No automatic action for unknown state {state or 'UNKNOWN'}")
