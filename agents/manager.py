"""Manager of the analysis phase (Google ADK). It hands the PR to the Analysis Agent, validates the
output with plain code, and retries with feedback. After MAX_ATTEMPTS the PR goes to human review.
This is also the root agent for `adk web`: send it "Analyze owner/repo#12"."""
import re
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from .analysis import ANALYSES, analysis_agent
from .events import text_event
from .llm import parse_json

MAX_ATTEMPTS = 3
LABELS = ["Low", "Medium", "High"]
# Words that say nothing about which change is being described, so they do not count as a match.
GENERIC_WORDS = {"this", "that", "with", "from", "have", "been", "will", "they", "their", "only", "file", "files", "code",
                 "line", "lines", "change", "changes", "changed", "test", "tests", "check", "checks", "module", "risk",
                 "label", "score", "small", "large", "size", "http", "https", "github", "null", "true", "false", "none",
                 "return", "value", "values", "repo", "repository", "pull", "request", "requests", "update", "updates"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9_]{3,}", text.lower())} - GENERIC_WORDS


def about_this_change(answer: str, diff: str) -> bool:
    """A model can answer from what it knows about a famous repository instead of reading the diff, so the answer must
    mention something from the changed code. An empty diff has nothing to compare."""
    return not _words(diff) or bool(_words(answer) & _words(diff))


def validate(pr_id: str) -> tuple[dict | None, list[str]]:
    st = ANALYSES[pr_id]
    if st.get("error"):
        return None, [st["error"]]
    try:
        data = parse_json(st["raw"])
    except Exception:
        return None, ["Output is not valid JSON."]
    errs, label = [], st["facts"]["risk_label"]
    reasoning, areas = data.get("reasoning"), data.get("suggested_test_areas")
    if not isinstance(reasoning, str) or len(reasoning.strip()) < 20:
        errs.append("reasoning must be 2-3 sentences.")
    elif any(re.search(rf"\b{o}\b\s+risk|risk\s+(?:label\s+)?(?:is|of)\s+{o}\b", reasoning, re.I)
             for o in LABELS if o != label):
        errs.append(f"reasoning contradicts the risk label, which is {label}.")
    if not isinstance(areas, list) or not 2 <= len(areas) <= 6 or not all(isinstance(a, str) and a.strip() for a in areas):
        errs.append("suggested_test_areas must be a list of 2-6 non-empty strings.")
    if not errs and not about_this_change(reasoning, st["facts"].get("diff_summary", "")):
        errs.append("reasoning does not mention the changed code. Name the changed files or what changed in them.")
    return (None if errs else data), errs


class AnalysisManager(BaseAgent):
    worker: BaseAgent

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        pr_id = ctx.user_content.parts[0].text.removeprefix("Analyze ").strip()
        # Fresh state per run, but the account's GitHub token the caller seeded is kept.
        st = ANALYSES[pr_id] = {"token": (ANALYSES.get(pr_id) or {}).get("token")}
        data, errs = None, []
        for n in range(1, MAX_ATTEMPTS + 1):
            async for ev in self.worker.run_async(ctx):          # hand the task to the Analysis Agent
                yield ev
            data, errs = validate(pr_id)
            if not errs:
                break
            yield text_event(self.name, f"rejected ({'; '.join(errs)}), attempt {n} of {MAX_ATTEMPTS}")
            if not st.get("facts"):                              # PR could not even be read, retrying is pointless
                break
            st["feedback"] = "; ".join(errs)
        facts = st.get("facts") or {}
        if data:
            st["result"] = {"pr_id": pr_id, "status": "approved", "attempts": n, "errors": [],
                            "analysis": {"pr_id": pr_id, "risk_label": facts["risk_label"], "score": facts["score"],
                                         "risk_factors": facts["risk_factors"], "reasoning": data["reasoning"],
                                         "suggested_test_areas": data["suggested_test_areas"], "model": st["model"]}}
        else:
            st["result"] = {"pr_id": pr_id, "status": "needs_human_review", "attempts": n, "errors": errs,
                            "analysis": None, "risk_label": facts.get("risk_label"),
                            "risk_factors": facts.get("risk_factors")}
        yield text_event(self.name, f"{st['result']['status']}: {facts.get('risk_label')} after {n} attempt(s)")


root_agent = AnalysisManager(name="manager_agent", worker=analysis_agent, sub_agents=[analysis_agent],
                             description="Hands PRs to the Analysis Agent, validates the output, retries.")
