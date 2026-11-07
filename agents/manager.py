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
from .trace import trace

MAX_ATTEMPTS = 3
LABELS = ["Low", "Medium", "High"]
# Words that say nothing about which change is being described, so they do not count as a match.
GENERIC_WORDS = {"this", "that", "with", "from", "have", "been", "will", "they", "their", "only", "file", "files", "code",
                 "line", "lines", "change", "changes", "changed", "test", "tests", "check", "checks", "module", "risk",
                 "label", "score", "small", "large", "size", "http", "https", "github", "null", "true", "false", "none",
                 "return", "value", "values", "repo", "repository", "pull", "request", "requests", "update", "updates",
                 "hidden", "secret"}  # the [HIDDEN SECRET] placeholder is ours, not the author's code


# Text that waves a change through. A label comes from rules, so an explanation never gets to say this,
# and it is what an answer looks like when the model has obeyed an instruction hidden in the pull request.
DISMISSALS = re.compile(
    r"\b(?:no|without|skip(?:s|ping)?|not need(?:ed)?(?: any)?)\s+(?:further\s+|additional\s+|any\s+)?(?:test(?:s|ing)?|review)\b"
    r"|\b(?:test(?:s|ing)?|review)\s+(?:is|are)\s+(?:not\s+(?:needed|required)|unnecessary)\b"
    r"|\b(?:completely|totally|perfectly|entirely)\s+safe\b|\bsafe\s+to\s+(?:merge|skip|ignore)\b"
    r"|\bignor(?:e|ing)\s+(?:the\s+|all\s+|any\s+|previous\s+)*(?:checks?|rules?|instructions?|risk)\b", re.I)
MIN_SHARED_WORDS = 2


def _words(text: str) -> set[str]:
    found = re.findall(r"[a-z][a-z0-9_]{3,}", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).lower())
    return {w[:-1] if w.endswith("s") and not w.endswith("ss") else w for w in found} - GENERIC_WORDS


def _changed_files(diff: str) -> list[str]:
    """The file names in a diff summary, whose lines look like: src/a.ts (+1/-2)"""
    return re.findall(r"^(\S.*?) \(\+\d+/-\d+\)$", diff, re.M)


def about_this_change(answer: str, diff: str) -> bool:
    """A model can answer from what it knows about a famous repository instead of reading the diff, so the answer must
    name a changed file or use at least two words from the changed code. One shared word proved too easy to hit by chance.
    This only raises the bar: it cannot prove every claim is true. An empty diff has nothing to compare."""
    if not _words(diff):
        return True
    lowered = answer.lower()
    if any(name.rsplit("/", 1)[-1].lower() in lowered for name in _changed_files(diff)):
        return True
    return len(_words(answer) & _words(diff)) >= MIN_SHARED_WORDS


def areas_about_this_change(areas: list[str], diff: str) -> bool:
    """At least half must use a word from the changed code. Not all, because a good edge case
    ("a declined card leaves no order behind") can rightly name things the diff does not."""
    words = _words(diff)
    return not words or sum(1 for area in areas if _words(area) & words) * 2 >= len(areas)


def contradicts_label(reasoning: str, label: str) -> bool:
    for other in LABELS:
        if other != label and re.search(
                rf"\b{other}\b[\s-]+risk|risk\s+(?:label\s+|level\s+)?(?:is|of|should\s+be)\s+{other}\b"
                rf"|(?<!not )\b(?:treated|classified|rated|marked|labell?ed|considered)\s+(?:as\s+)?{other}\b"
                rf"|\bshould\s+be\s+{other}\b", reasoning, re.I):
            # "raised from Medium risk to High" and "not a Low risk change" do not contradict it
            before = reasoning[:re.search(rf"\b{other}\b", reasoning, re.I).start()].lower()
            if not before.rstrip().endswith(("from", "not", "not a", "not an")):
                return True
    return False


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
    elif contradicts_label(reasoning, label):
        errs.append(f"reasoning contradicts the risk label, which is {label}.")
    if not isinstance(areas, list) or not 2 <= len(areas) <= 6 or not all(isinstance(a, str) and a.strip() for a in areas):
        errs.append("suggested_test_areas must be a list of 2-6 non-empty strings.")
    diff = st["facts"].get("diff_summary", "")
    if not errs and not about_this_change(reasoning, diff):
        errs.append("reasoning does not mention the changed code. Name the changed files or what changed in them.")
    if not errs and not areas_about_this_change(areas, diff):
        errs.append("suggested_test_areas are not about this change. Base them on the changed code.")
    if not errs and DISMISSALS.search(" ".join([reasoning, *areas])):
        errs.append("do not call the change safe or say it needs no testing. Explain the risk and what to test.")
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
            trace("manager.validated", attempt=n, accepted=not errs, problems=errs)
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
        trace("manager.decided", status=st["result"]["status"], risk_label=facts.get("risk_label"),
              head_sha=facts.get("head_sha"), attempts=n, problems=errs)
        yield text_event(self.name, f"{st['result']['status']}: {facts.get('risk_label')} after {n} attempt(s)")


root_agent = AnalysisManager(name="manager_agent", worker=analysis_agent, sub_agents=[analysis_agent],
                             description="Hands PRs to the Analysis Agent, validates the output, retries.")
