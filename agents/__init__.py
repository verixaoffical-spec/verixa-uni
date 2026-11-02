"""Verixa agents.

Deliverable 2 scope only: the Analysis Agent (rule-based risk scoring plus a one-call model
explanation) and the Manager that validates its output and retries with feedback.

Reused as-is from the multi-agents repository:
    risk_rules.py     T-031 / T-033  rule-based risk score, size-based scoring  (Farheen)
    analysis.py       T-031          the Analysis Agent worker                  (Farheen)
    manager.py        T-035          validation, retry cap, escalation          (Farheen)
    github_client.py  T-030 / T-032  PR diff fetch, module defect history       (Arisha, Farheen support)
    llm.py, events.py, models.py, runner.py   shared plumbing the agent needs

The Test & Execution Agent is deliberately NOT part of this package: it is still in its testing
phase in the multi-agents repository and sits outside the consolidated scope.
"""
