# experiment. not touching runner.py until this is worth it.
# the planner already emits one line per file. so: give each line to its own
# worker instead of handing the whole plan to one.
import sys

import runner


def worker_call(flow, task, rules):
    prompt = runner.read(flow, "worker.md") + "\n\n" + rules
    prompt = prompt + "\n\nyour task, only this one:\n\n" + task
    return runner.call(prompt)


def main():
    runner.load_env()
    flow = sys.argv[1] if len(sys.argv) > 1 else "weekly-digest"
    rules = runner.read(flow, "instructions.md")

    plan = runner.call(runner.read(flow, "planner.md") + "\n\n" + rules)
    tasks = [l for l in plan.split("\n") if "|" in l]

    parts = []
    for task in tasks[:2]:
        parts.append(worker_call(flow, task, rules))

    print("\n\n".join(parts))


if __name__ == "__main__":
    main()
