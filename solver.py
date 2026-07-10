from __future__ import annotations

from collections import deque
from copy import deepcopy

from schemas import LevelSpec
from top_down_engine import MOVE_DELTAS, TopDownState


Action = str
Pos = tuple[int, int]


def solve_level(level: LevelSpec, spec: dict) -> dict:
    if level.genre != "top_down_adventure":
        return {"supported": False, "reason": "headless solver currently supports top_down_adventure"}

    state = TopDownState.from_config({"level_spec": level.to_dict(), "game_spec": spec})
    actions: list[Action] = []

    try:
        for entity in entities_of(state, "key"):
            actions += go_interact(state, entity)
        for entity in entities_of(state, "door"):
            actions += go_interact(state, entity)
        for entity in entities_of(state, "collectible"):
            actions += go_interact(state, entity)

        sources = entities_of(state, "source")
        if sources:
            if state.workflow_sequence():
                for source in sources:
                    actions += go_interact(state, source)
                    for station_name in state.workflow_sequence():
                        actions += go_interact(state, find_entity(state, "container", station_name))
            else:
                destination = first_entity(state, "container") or first_entity(state, "goal")
                if destination is None:
                    raise ValueError("delivery task has no destination")
                for source in sources:
                    actions += go_interact(state, source)
                    actions += go_interact(state, destination)

        interactive_goal = next((e for e in entities_of(state, "goal") if state.goal_requires_interaction(e)), None)
        if interactive_goal and not state.done:
            actions += go_interact(state, interactive_goal)

        goal = first_entity(state, "goal")
        if goal and not state.done:
            actions += go_to(state, tuple(goal["pos"]))
            state.check_passive_entities()
    except ValueError as exc:
        return solution(state, actions, success=False, reason=str(exc))

    return solution(state, actions, success=state.done and not state.failed)


def solution(state: TopDownState, actions: list[Action], success: bool, reason: str | None = None) -> dict:
    payload = {
        "supported": True,
        "success": success,
        "steps": len(actions),
        "actions": actions,
        "final": {
            "position": list(state.pos),
            "done": state.done,
            "failed": state.failed,
            "inventory": sorted(state.inventory),
            "collected": sorted(state.collected),
            "delivered_sources": sorted(state.delivered_sources),
            "message": state.message,
        },
    }
    if reason:
        payload["reason"] = reason
    elif state.failed:
        payload["reason"] = state.message
    elif not state.done:
        payload["reason"] = "objective was not completed"
    return payload


def go_interact(state: TopDownState, entity: dict) -> list[Action]:
    actions = go_to_adjacent(state, tuple(entity["pos"]))
    state.apply("interact")
    actions.append("interact")
    return actions


def go_to_adjacent(state: TopDownState, target: Pos) -> list[Action]:
    candidates = [target, (target[0] + 1, target[1]), (target[0] - 1, target[1]), (target[0], target[1] + 1), (target[0], target[1] - 1)]
    for candidate in candidates:
        if state.passable(candidate):
            try:
                return go_to(state, candidate)
            except ValueError:
                pass
    raise ValueError(f"no adjacent path to {target}")


def go_to(state: TopDownState, target: Pos) -> list[Action]:
    path = safe_shortest_path(state, target)
    if path is None:
        raise ValueError(f"no path from {state.pos} to {target}")
    actions: list[Action] = []
    for action in path:
        state.apply(action)
        actions.append(action)
        if state.failed:
            raise ValueError(state.message)
    return actions


def safe_shortest_path(state: TopDownState, target: Pos) -> list[Action] | None:
    queue = deque([(deepcopy(state), [])])
    seen = {state_key(state)}
    while queue:
        current, path = queue.popleft()
        if current.pos == target:
            return path
        if len(path) > 400:
            continue
        for action in MOVE_DELTAS:
            nxt = deepcopy(current)
            nxt.apply(action)
            if nxt.failed:
                continue
            key = state_key(nxt)
            if key in seen:
                continue
            seen.add(key)
            queue.append((nxt, path + [action]))
    return None


def state_key(state: TopDownState):
    enemies = tuple(sorted((entity["id"], tuple(entity["pos"])) for entity in state.entities if entity["type"] == "enemy"))
    return (
        state.pos,
        enemies,
        tuple(sorted(state.open_doors)),
        tuple(sorted(state.collected)),
        tuple(sorted(state.harvested_sources)),
        tuple(sorted(state.delivered_sources)),
        state.carrying["source_id"] if state.carrying else None,
        state.steps % 2,
    )


def entities_of(state: TopDownState, entity_type: str) -> list[dict]:
    return [entity for entity in state.entities if entity["type"] == entity_type]


def first_entity(state: TopDownState, entity_type: str) -> dict | None:
    return next((entity for entity in state.entities if entity["type"] == entity_type), None)


def find_entity(state: TopDownState, entity_type: str, name: str) -> dict:
    from top_down_engine import normalize_name

    normalized = normalize_name(name)
    for entity in state.entities:
        if entity["type"] == entity_type and normalize_name(entity["name"]) == normalized:
            return entity
    raise ValueError(f"missing {entity_type} named {name}")
