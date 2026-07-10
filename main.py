from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from harness import run_harness, run_harness_from_spec
from schemas import GameSpec


def parse_args():
    parser = argparse.ArgumentParser(description="Schema-driven LLM environment harness.")
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate", help="Generate a playable environment project from a prompt.")
    gen.add_argument("prompt", nargs="?")
    gen.add_argument("--spec", help="Load a GameSpec JSON file instead of calling Gemini.")
    gen.add_argument("--output-dir", default="generated_games")
    gen.add_argument("--run", action="store_true", help="Launch the generated Pygame project after generation.")
    gen.add_argument("--print-state", action="store_true")

    sub.add_parser("examples", help="Print example prompts.")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.command == "examples":
        print_examples()
        return 0
    if args.command != "generate":
        print_examples()
        return 0
    if args.spec:
        state = run_from_spec_arg(args)
    else:
        if not args.prompt:
            raise SystemExit("generate requires a prompt unless --spec is provided")
        state = run_harness(args.prompt, output_dir=args.output_dir)
    print(f"status: {state.final_status}")
    print(f"project: {state.project_path}")
    print("tests:")
    for test in state.test_results:
        mark = "PASS" if test.passed else "FAIL"
        print(f"  [{mark}] {test.name}{': ' + test.error if test.error else ''}")
    if args.print_state:
        print(json.dumps(state.to_dict(), indent=2))
    if args.run and state.project_path:
        subprocess.run([sys.executable, "main.py"], cwd=Path(state.project_path), check=False)
    return 0 if state.final_status == "success" else 1


def run_from_spec_arg(args):
    path = Path(args.spec)
    data = json.loads(path.read_text())
    spec_data = data.get("game_spec", data)
    spec = GameSpec.from_dict(spec_data)
    prompt = args.prompt or f"loaded spec: {path.name}"
    return run_harness_from_spec(spec, prompt=prompt, output_dir=args.output_dir)


def print_examples():
    examples = [
        "Make a snowy top-down maze where the player finds a key, opens a locked door, and reaches the cabin exit.",
        "Create a dungeon adventure where the agent collects coins, avoids guards, and reaches the exit.",
        "Create a kitchen workflow where the agent collects raw meat, processes it at a cutting station, cooks it, and plates it in order.",
        "Create a farm task where the agent gathers milk from cows and deposits each load into a bucket.",
    ]
    print("Example prompts:")
    for prompt in examples:
        print(f"- {prompt}")


if __name__ == "__main__":
    raise SystemExit(main())
