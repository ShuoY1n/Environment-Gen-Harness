from __future__ import annotations

from collections import deque
from typing import List, Set, Tuple

from schemas import GameSpec, LevelSpec, TestResult


Pos = Tuple[int, int]


def validate_all(spec: GameSpec, level: LevelSpec) -> List[TestResult]:
    tests = [
        validate_spec(spec),
        validate_spec_faithfulness(spec, level),
        validate_level_bounds(level),
        validate_spawn_and_goal(level),
        validate_entities(level),
        validate_reachability(level),
    ]
    return tests


def validate_spec(spec: GameSpec) -> TestResult:
    errors = []
    if spec.genre not in {"top_down_adventure", "2d_platformer"}:
        errors.append("unsupported genre")
    if not spec.title:
        errors.append("missing title")
    if not spec.win_condition:
        errors.append("missing win condition")
    return TestResult("schema", not errors, "; ".join(errors) or None, {"genre": spec.genre, "mechanics": spec.mechanics})


def validate_spec_faithfulness(spec: GameSpec, level: LevelSpec) -> TestResult:
    errors = []
    supported_mechanics = {"movement", "collectibles", "keys", "doors", "enemy_patrol", "resource_delivery", "reach_goal", "chase_player", "hazards"}
    unsupported = sorted(set(spec.mechanics) - supported_mechanics)
    if unsupported:
        errors.append(f"unsupported mechanics requested: {unsupported}")

    expected = expected_entity_counts(spec)
    actual = entity_counts(level)
    for entity_type, count in expected.items():
        if actual.get(entity_type, 0) < count:
            errors.append(f"missing {entity_type}: expected at least {count}, got {actual.get(entity_type, 0)}")

    for requested in spec.entities:
        if requested.type in {"goal", "container", "source", "enemy", "key", "door", "collectible"}:
            if not any(entity.type == requested.type and normalize_name(entity.name) == normalize_name(requested.name) for entity in level.entities):
                errors.append(f"missing requested {requested.type}: {requested.name}")
        if requested.type == "enemy" and requested.behavior in {"patrol", "chase_player"}:
            if not any(entity.type == "enemy" and normalize_name(entity.name) == normalize_name(requested.name) and entity.behavior == requested.behavior for entity in level.entities):
                errors.append(f"missing enemy behavior: {requested.name}/{requested.behavior}")

    condition = spec.win_condition.get("type")
    supported_conditions = {"reach_goal", "deliver_from_sources", "deliver_then_interact", "deliver_sequentially", "interact_with_entity"}
    if condition not in supported_conditions:
        errors.append(f"unsupported win condition: {condition}")
    if condition in {"deliver_from_sources", "deliver_then_interact", "deliver_sequentially"} and actual.get("source", 0) == 0:
        errors.append("delivery win condition has no source")
    if condition in {"deliver_from_sources", "deliver_then_interact", "deliver_sequentially"} and actual.get("container", 0) == 0:
        errors.append("delivery win condition has no container")
    if condition == "deliver_then_interact" and actual.get("goal", 0) == 0:
        errors.append("deliver_then_interact has no final goal")
    if condition == "deliver_sequentially":
        sequence = [normalize_name(item) for item in spec.win_condition.get("sequence", [])]
        placed = [normalize_name(entity.name) for entity in level.entities if entity.type == "container"]
        missing = [name for name in sequence if name not in placed]
        if missing:
            errors.append(f"sequential stations missing: {missing}")

    lose_type = (spec.lose_condition or {}).get("type")
    if lose_type == "enemy_collision" and actual.get("enemy", 0) == 0:
        errors.append("enemy_collision lose condition has no enemy")

    return TestResult("spec_faithfulness", not errors, "; ".join(errors) or None, {"expected": expected, "actual": actual})


def expected_entity_counts(spec: GameSpec) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in spec.entities:
        counts[entity.type] = counts.get(entity.type, 0) + entity.count
    if "keys" in spec.mechanics or "doors" in spec.mechanics:
        counts["key"] = max(1, counts.get("key", 0))
        counts["door"] = max(1, counts.get("door", 0))
    if "enemy_patrol" in spec.mechanics and counts.get("enemy", 0) == 0:
        counts["enemy"] = 2
    if "resource_delivery" in spec.mechanics:
        counts["source"] = max(1, counts.get("source", 0))
        counts["container"] = max(1, counts.get("container", 0))
    return {key: min(value, 12) for key, value in counts.items() if key != "object"}


def entity_counts(level: LevelSpec) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in level.entities:
        counts[entity.type] = counts.get(entity.type, 0) + 1
    return counts


def validate_level_bounds(level: LevelSpec) -> TestResult:
    errors = []
    if len(level.layout) != level.height:
        errors.append("layout height mismatch")
    if any(len(row) != level.width for row in level.layout):
        errors.append("layout width mismatch")
    if level.width < 8 or level.height < 8:
        errors.append("level too small")
    return TestResult("level_bounds", not errors, "; ".join(errors) or None, {"size": [level.width, level.height]})


def validate_spawn_and_goal(level: LevelSpec) -> TestResult:
    errors = []
    for name, pos in [("spawn", level.spawn), ("goal", level.goal)]:
        if not in_bounds(level, tuple(pos)):
            errors.append(f"{name} out of bounds")
        elif blocked(level, tuple(pos)):
            errors.append(f"{name} blocked")
    return TestResult("spawn_goal", not errors, "; ".join(errors) or None)


def validate_entities(level: LevelSpec) -> TestResult:
    errors = []
    ids = set()
    for entity in level.entities:
        pos = tuple(entity.pos)
        if entity.id in ids:
            errors.append(f"duplicate entity id: {entity.id}")
        ids.add(entity.id)
        if not in_bounds(level, pos):
            errors.append(f"entity out of bounds: {entity.id}")
        if entity.type != "door" and blocked(level, pos):
            errors.append(f"entity on blocked tile: {entity.id}")
    positions = {}
    for entity in level.entities:
        pos = tuple(entity.pos)
        if entity.type == "door":
            continue
        if pos in positions:
            errors.append(f"entity overlap: {positions[pos]} and {entity.id} at {pos}")
        positions[pos] = entity.id
    return TestResult("entity_placement", not errors, "; ".join(errors) or None, {"count": len(level.entities)})


def validate_reachability(level: LevelSpec) -> TestResult:
    if level.genre == "2d_platformer":
        return validate_platformer_reachability(level)
    reachable = bfs(level, tuple(level.spawn))
    goal_ok = tuple(level.goal) in reachable
    unreachable_items = [entity.id for entity in level.entities if entity.type in {"collectible", "key"} and tuple(entity.pos) not in reachable]
    unreachable_sources = [entity.id for entity in level.entities if entity.type == "source" and tuple(entity.pos) not in reachable]
    unreachable_containers = [entity.id for entity in level.entities if entity.type == "container" and tuple(entity.pos) not in reachable]
    errors = []
    if not goal_ok:
        errors.append("goal unreachable")
    if unreachable_items:
        errors.append(f"unreachable items: {unreachable_items}")
    if unreachable_sources:
        errors.append(f"unreachable sources: {unreachable_sources}")
    if unreachable_containers:
        errors.append(f"unreachable containers: {unreachable_containers}")
    locked_doors = [entity for entity in level.entities if entity.type == "door"]
    keys = [entity for entity in level.entities if entity.type == "key"]
    if locked_doors:
        closed_reachable = bfs(level, tuple(level.spawn), {tuple(entity.pos) for entity in locked_doors})
        closed_unreachable_keys = [entity.id for entity in keys if tuple(entity.pos) not in closed_reachable]
        if closed_unreachable_keys:
            errors.append(f"keys unreachable before locked door: {closed_unreachable_keys}")
        if tuple(level.goal) in closed_reachable:
            errors.append("locked door does not gate the goal")
    return TestResult("top_down_reachability", not errors, "; ".join(errors) or None, {"reachable_tiles": len(reachable)})


def validate_platformer_reachability(level: LevelSpec) -> TestResult:
    platforms = platform_segments(level)
    spawn_platform = platform_under(level, tuple(level.spawn))
    goal_platform = platform_under(level, tuple(level.goal))
    errors = []
    if spawn_platform is None:
        errors.append("spawn has no platform beneath it")
    if goal_platform is None:
        errors.append("goal has no platform beneath it")
    if errors:
        return TestResult("platformer_reachability", False, "; ".join(errors))
    graph = platform_graph(platforms)
    reachable = graph_search(graph, spawn_platform)
    goal_ok = goal_platform in reachable
    if not goal_ok:
        errors.append("goal platform unreachable by jump graph")
    return TestResult(
        "platformer_reachability",
        not errors,
        "; ".join(errors) or None,
        {"platforms": len(platforms), "reachable_platforms": len(reachable)},
    )


def bfs(level: LevelSpec, start: Pos, extra_blocked: Set[Pos] | None = None) -> Set[Pos]:
    extra_blocked = extra_blocked or set()
    q = deque([start])
    seen = {start}
    while q:
        x, y = q.popleft()
        for nx, ny in [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]:
            pos = (nx, ny)
            if pos not in seen and pos not in extra_blocked and in_bounds(level, pos) and not blocked(level, pos):
                seen.add(pos)
                q.append(pos)
    return seen


def in_bounds(level: LevelSpec, pos: Pos) -> bool:
    return 0 <= pos[0] < level.width and 0 <= pos[1] < level.height


def blocked(level: LevelSpec, pos: Pos) -> bool:
    return level.layout[pos[1]][pos[0]] == "#"


def platform_segments(level: LevelSpec) -> List[Tuple[int, int, int]]:
    segments = []
    for y, row in enumerate(level.layout):
        x = 0
        while x < len(row):
            if row[x] != "#":
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == "#":
                x += 1
            segments.append((start, x - 1, y))
    return segments


def platform_under(level: LevelSpec, pos: Pos):
    x, y = pos
    target_y = y + 1
    for segment in platform_segments(level):
        start, end, py = segment
        if py == target_y and start <= x <= end:
            return segment
    return None


def platform_graph(platforms: List[Tuple[int, int, int]]):
    graph = {segment: [] for segment in platforms}
    for a in platforms:
        for b in platforms:
            if a == b:
                continue
            if can_jump(a, b):
                graph[a].append(b)
    return graph


def can_jump(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> bool:
    ax = (a[0] + a[1]) / 2
    bx = (b[0] + b[1]) / 2
    dx = abs(ax - bx)
    dy = b[2] - a[2]
    return dx <= 12 and dy >= -5 and dy <= 8


def graph_search(graph, start):
    q = deque([start])
    seen = {start}
    while q:
        node = q.popleft()
        for nxt in graph[node]:
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return seen


def normalize_name(value) -> str:
    return "".join(char.lower() for char in str(value or "") if char.isalnum())
