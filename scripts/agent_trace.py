"""Prints the agents' trace log as a timeline.

    python scripts/agent_trace.py                      the latest run
    python scripts/agent_trace.py --pr owner/repo#10   every run of one pull request
    python scripts/agent_trace.py --run 3f9a1c20d4e7   one run
    python scripts/agent_trace.py --list               the last 20 runs, one line each
"""
import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent.parent / "logs" / "agent_trace.jsonl"


def read(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"No trace yet: {path} does not exist. Analyse a pull request first.")
    lines = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            lines.append(json.loads(raw))
        except ValueError:
            continue
    return lines


def show(line: dict) -> None:
    rest = {k: v for k, v in line.items() if k not in ("at", "run_id", "pr_id", "event")}
    details = "  ".join(f"{k}={json.dumps(v, default=str) if isinstance(v, (list, dict)) else v}" for k, v in rest.items())
    print(f"{line['at'][11:23]}  {line.get('run_id') or '-':12}  {line['event']:24}  {details}".replace("\n", " "))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pr")
    parser.add_argument("--run")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--file", default=os.getenv("AGENT_TRACE_FILE") or str(DEFAULT))
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")  # model answers can hold characters a Windows console cannot print
    lines = read(Path(args.file))

    if args.list:
        for line in [x for x in lines if x["event"] == "run.end"][-20:]:
            print(f"{line['at'][:19]}  {line['run_id']}  {line['pr_id']}  {line.get('status')}  "
                  f"attempts={line.get('attempts')}  {line.get('ms')} ms")
        return
    if args.run:
        chosen = [x for x in lines if x.get("run_id") == args.run or x.get("result_of_run") == args.run]
    elif args.pr:
        chosen = [x for x in lines if x.get("pr_id") == args.pr]
    else:
        runs = [x["run_id"] for x in lines if x.get("run_id")]
        chosen = [x for x in lines if runs and runs[-1] in (x.get("run_id"), x.get("result_of_run"))]
    if not chosen:
        sys.exit("Nothing in the trace matches that.")
    print(chosen[0].get("pr_id"))
    for line in chosen:
        show(line)


if __name__ == "__main__":
    main()
