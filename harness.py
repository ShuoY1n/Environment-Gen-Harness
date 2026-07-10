from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from level_generator import generate_level
from planner import create_game_spec
from project_generator import generate_project, write_state
from schemas import HarnessState, TestResult
from solver import solve_level
from validator import validate_all


def run_harness(prompt: str, output_dir: str = "generated_games", max_repairs: int = 2) -> HarnessState:
    state = HarnessState(user_prompt=prompt)
    spec, planner_report = create_game_spec(prompt)
    state.game_spec = spec
    state.model_used = planner_report.get("model")
    state.notes.append(json.dumps(planner_report, indent=2))
    return build_project(state, spec, output_dir, max_repairs)


def run_harness_from_spec(spec, prompt: str = "loaded spec", output_dir: str = "generated_games", max_repairs: int = 2) -> HarnessState:
    state = HarnessState(user_prompt=prompt, game_spec=spec, model_used="loaded_spec")
    return build_project(state, spec, output_dir, max_repairs)


def build_project(state: HarnessState, spec, output_dir: str, max_repairs: int) -> HarnessState:
    seed = stable_seed(canonical_spec_json(spec))
    candidate_spec = deepcopy(spec)
    for attempt in range(max_repairs + 1):
        level = generate_level(candidate_spec, seed=seed + attempt)
        tests = validation_with_solution(candidate_spec, level)
        state.game_spec = deepcopy(candidate_spec)
        state.level_spec = level
        state.test_results = tests
        if all(test.passed for test in tests):
            state.final_status = "success"
            break

        failures = [test.to_dict() for test in tests if not test.passed]
        state.notes.append(f"repair_attempt={attempt + 1}; failures={failures}")
        if attempt >= max_repairs:
            break
        state.repair_attempts += 1
        candidate_spec = repaired_copy(candidate_spec)

    project_dir = generate_project(Path(output_dir), state, state.test_results)
    state.project_path = str(project_dir)
    if state.level_spec and state.game_spec:
        write_solution(project_dir, state)
    write_state(project_dir, state)
    return state


def validation_with_solution(spec, level):
    tests = validate_all(spec, level)
    solution = solve_level(level, spec.to_dict())
    if solution.get("supported"):
        tests.append(
            TestResult(
                "headless_solution",
                bool(solution.get("success")),
                None if solution.get("success") else solution.get("reason"),
                {"steps": solution.get("steps", 0)},
            )
        )
    else:
        tests.append(TestResult("headless_solution", False, solution.get("reason", "no solver support for this genre")))
    return tests


def write_solution(project_dir: Path, state: HarnessState) -> None:
    solution = solve_level(state.level_spec, state.game_spec.to_dict())
    (project_dir / "solution.json").write_text(json.dumps(solution, indent=2))


def repaired_copy(spec):
    repaired = deepcopy(spec)
    simplify_for_repair(repaired)
    return repaired


def stable_seed(prompt: str) -> int:
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def canonical_spec_json(spec) -> str:
    return json.dumps(spec.to_dict(), sort_keys=True, separators=(",", ":"))


def simplify_for_repair(spec):
    if spec.difficulty == "hard":
        spec.difficulty = "medium"
    elif spec.difficulty == "medium":
        spec.difficulty = "easy"
    for entity in spec.entities:
        if entity.type == "enemy":
            entity.count = max(1, entity.count - 1)
