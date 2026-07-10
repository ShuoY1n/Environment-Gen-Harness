from __future__ import annotations

import random
from typing import List, Tuple

from schemas import GameSpec, LevelSpec, PlacedEntity


Pos = Tuple[int, int]


def generate_level(spec: GameSpec, seed: int = 0) -> LevelSpec:
    rng = random.Random(seed)
    if spec.genre == "2d_platformer":
        return generate_platformer(spec, rng)
    return generate_top_down(spec, rng)


def generate_top_down(spec: GameSpec, rng: random.Random) -> LevelSpec:
    width = rng.choice([26, 28, 30, 32])
    height = rng.choice([17, 18, 19, 20])
    grid = [["#" for _ in range(width)] for _ in range(height)]
    mid_x = width // 2
    mid_y = height // 2
    rooms = [
        (1, 1, rng.randint(8, max(8, mid_x - 2)), rng.randint(5, max(5, mid_y - 2))),
        (mid_x + 1, 1, width - mid_x - 2, rng.randint(5, max(5, mid_y - 2))),
        (1, mid_y + 1, rng.randint(9, max(9, mid_x - 1)), height - mid_y - 2),
        (mid_x + 2, mid_y + 1, width - mid_x - 3, height - mid_y - 2),
    ]
    for x, y, w, h in rooms:
        carve_room(grid, x, y, w, h)
    centers = [room_center(room) for room in rooms]
    carve_corridor(grid, centers[0], centers[1])
    carve_corridor(grid, centers[0], centers[2])
    carve_corridor(grid, centers[1], centers[3])
    carve_corridor(grid, centers[2], centers[3])

    key_door_task = has_entity(spec, "key") or has_entity(spec, "door") or "doors" in spec.mechanics
    door_x = mid_x
    door_count = max(1, entity_count(spec, "door")) if key_door_task else 0
    door_slots = [[door_x, y] for y in evenly_spaced_rows(height, door_count)]
    if key_door_task:
        for y in range(1, height - 1):
            grid[y][door_x] = "#"
        for x, y in door_slots[:door_count]:
            for corridor_x in range(1, width - 1):
                grid[y][corridor_x] = "."
            grid[y][x] = "."

    spawn = list(pick_free(list(centers[0]), walkable_tiles(grid), set()))
    goal = list(pick_free(list(centers[3]), walkable_tiles(grid), {tuple(spawn)}))
    entities: List[PlacedEntity] = []
    delivery_task = "resource_delivery" in spec.mechanics or spec.win_condition.get("type") in {"deliver_from_sources", "deliver_then_interact", "deliver_sequentially"}
    occupied = {tuple(spawn)} if delivery_task else {tuple(spawn), tuple(goal)}
    if delivery_task:
        containers = container_requests(spec)
        has_final_goal = has_entity(spec, "goal") and spec.win_condition.get("type") != "deliver_sequentially"
        container_positions = shuffled_positions(walkable_tiles(grid), rng, preferred=[list(centers[3]), list(centers[1]), list(centers[2])])
        if not containers:
            containers = []
        for i, container in enumerate(containers or []):
            base = container_positions[i % len(container_positions)]
            pos = pick_free(base, walkable_tiles(grid), occupied)
            occupied.add(tuple(pos))
            entities.append(PlacedEntity(f"container_{i+1}", "container", container.name, pos, "deposit_target", dict(container.properties)))
        if not containers:
            destination_name = entity_name(spec, "container", "container")
            container_pos = pick_free(list(centers[3]), walkable_tiles(grid), occupied) if has_final_goal else goal
            entities.append(PlacedEntity("container_1", "container", destination_name, container_pos, "deposit_target"))
            occupied.add(tuple(container_pos))
        if has_final_goal:
            goal_entity = first_entity(spec, "goal")
            behavior = goal_entity.behavior if goal_entity else "interact_to_win"
            properties = dict(goal_entity.properties) if goal_entity else {}
            goal = pick_free(goal, walkable_tiles(grid), occupied)
            occupied.add(tuple(goal))
            entities.append(PlacedEntity("goal", "goal", goal_name(spec), goal, behavior, properties))
    else:
        goal_entity = first_entity(spec, "goal")
        behavior = goal_entity.behavior if goal_entity else "static"
        properties = dict(goal_entity.properties) if goal_entity else {}
        entities.append(PlacedEntity("goal", "goal", goal_name(spec), goal, behavior, properties))

    if key_door_task:
        key_count = max(1, entity_count(spec, "key"))
        key_positions = shuffled_positions(walkable_tiles(grid), rng, preferred=[list(centers[2]), list(centers[0]), list(centers[1])])
        key_name = entity_name(spec, "key", "key")
        for i in range(key_count):
            base = key_positions[i % len(key_positions)]
            pos = pick_free(base, walkable_tiles(grid), occupied)
            occupied.add(tuple(pos))
            entities.append(PlacedEntity(f"key_{i+1}", "key", key_name, pos, "static"))
        for i in range(door_count):
            door_pos = door_slots[i % len(door_slots)]
            entities.append(PlacedEntity(f"door_{i+1}", "door", entity_name(spec, "door", "locked door"), door_pos, "locked", {"opens_with": f"key_{min(i + 1, key_count)}"}))

    open_tiles = walkable_tiles(grid)
    preferred = shuffled_positions(open_tiles, rng, preferred=[list(centers[0]), list(centers[1]), list(centers[2]), list(centers[3])])
    collectible_index = 1
    for collectible in entity_requests(spec, "collectible"):
        for _ in range(collectible.count):
            base = preferred[(collectible_index - 1) % len(preferred)] if collectible_index <= len(preferred) else list(rng.choice(open_tiles))
            pos = pick_free(base, open_tiles, occupied)
            occupied.add(tuple(pos))
            entities.append(PlacedEntity(f"collectible_{collectible_index}", "collectible", collectible.name, pos, "static", dict(collectible.properties)))
            collectible_index += 1
            if collectible_index > 12:
                break

    source_positions = shuffled_positions(open_tiles, rng, preferred=[list(centers[0]), list(centers[1]), list(centers[2]), list(centers[3])])
    source_index = 1
    for source in source_requests(spec):
        for _ in range(source.count):
            base = source_positions[(source_index - 1) % len(source_positions)]
            pos = pick_free(base, open_tiles, occupied)
            occupied.add(tuple(pos))
            resource = source.properties.get("resource")
            entities.append(PlacedEntity(f"source_{source_index}", "source", source.name, pos, "interact_produces_resource", {"resource": resource or resource_name(source.name), "delivered": False}))
            source_index += 1
            if source_index > 12:
                break

    enemy_positions = shuffled_positions(open_tiles, rng, preferred=[list(centers[1]), list(centers[2]), list(centers[3])])
    enemy_index = 1
    for enemy in enemy_requests(spec):
        enemy_behavior = enemy.behavior if enemy.behavior in {"patrol", "chase_player"} else "patrol"
        for _ in range(enemy.count):
            base = enemy_positions[(enemy_index - 1) % len(enemy_positions)]
            pos = pick_free(base, open_tiles, occupied)
            occupied.add(tuple(pos))
            entities.append(PlacedEntity(f"enemy_{enemy_index}", "enemy", enemy.name, pos, enemy_behavior, {"axis": "horizontal", "range": 4}))
            enemy_index += 1
            if enemy_index > 12:
                break
        if enemy_index > 12:
            break

    return LevelSpec(
        genre="top_down_adventure",
        width=width,
        height=height,
        tile_size=32,
        layout=["".join(row) for row in grid],
        spawn=spawn,
        goal=goal,
        entities=entities,
    )


def generate_platformer(spec: GameSpec, rng: random.Random) -> LevelSpec:
    width, height = 48, 18
    grid = [["." for _ in range(width)] for _ in range(height)]
    for x in range(width):
        grid[height - 1][x] = "#"
    platforms = [
        (1, 15, 8),
        (10, 13, 7),
        (19, 11, 7),
        (29, 10, 6),
        (38, 8, 8),
    ]
    if spec.difficulty == "easy":
        platforms.append((18, 14, 5))
    if spec.difficulty == "hard":
        platforms[2] = (20, 10, 5)
        platforms[3] = (30, 8, 5)
    for x, y, w in platforms:
        for px in range(x, min(width, x + w)):
            grid[y][px] = "#"

    spawn = [3, 14]
    goal = [43, 7]
    goal_entity = first_entity(spec, "goal")
    goal_behavior = goal_entity.behavior if goal_entity else "static"
    goal_properties = dict(goal_entity.properties) if goal_entity else {}
    entities: List[PlacedEntity] = [PlacedEntity("goal", "goal", goal_name(spec), goal, goal_behavior, goal_properties)]
    occupied = {tuple(spawn), tuple(goal)}
    valid_entity_tiles = platformer_entity_tiles(grid)

    collectible_positions = [[12, 12], [22, 10], [31, 9], [41, 7], [5, 14], [20, 10], [33, 9], [44, 7]]
    collectible_index = 1
    for collectible in entity_requests(spec, "collectible"):
        for _ in range(collectible.count):
            base = collectible_positions[(collectible_index - 1) % len(collectible_positions)]
            pos = pick_free_platformer(base, valid_entity_tiles, occupied)
            occupied.add(tuple(pos))
            entities.append(PlacedEntity(f"collectible_{collectible_index}", "collectible", collectible.name, pos, "static", dict(collectible.properties)))
            collectible_index += 1
            if collectible_index > 12:
                break

    enemy_positions = [[15, 12], [25, 10], [34, 9], [41, 7]]
    enemy_index = 1
    for enemy in enemy_requests(spec):
        enemy_behavior = enemy.behavior if enemy.behavior in {"patrol", "chase_player"} else "patrol"
        for _ in range(enemy.count):
            base = enemy_positions[(enemy_index - 1) % len(enemy_positions)]
            pos = pick_free_platformer(base, valid_entity_tiles, occupied)
            occupied.add(tuple(pos))
            entities.append(PlacedEntity(f"enemy_{enemy_index}", "enemy", enemy.name, pos, enemy_behavior, {"axis": "horizontal", "range": 3}))
            enemy_index += 1
            if enemy_index > 12:
                break
        if enemy_index > 12:
            break

    return LevelSpec(
        genre="2d_platformer",
        width=width,
        height=height,
        tile_size=32,
        layout=["".join(row) for row in grid],
        spawn=spawn,
        goal=goal,
        entities=entities,
    )


def carve_room(grid: List[List[str]], x: int, y: int, w: int, h: int):
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            grid[yy][xx] = "."


def carve_corridor(grid: List[List[str]], start: Pos, end: Pos):
    x, y = start
    ex, ey = end
    step = 1 if ex >= x else -1
    for xx in range(x, ex + step, step):
        grid[y][xx] = "."
    step = 1 if ey >= y else -1
    for yy in range(y, ey + step, step):
        grid[yy][ex] = "."


def room_center(room: tuple[int, int, int, int]) -> Pos:
    x, y, w, h = room
    return x + w // 2, y + h // 2


def shuffled_positions(candidates: List[List[int]], rng: random.Random, preferred: List[List[int]] | None = None) -> List[List[int]]:
    preferred = [list(pos) for pos in (preferred or []) if list(pos) in candidates]
    remaining = [list(pos) for pos in candidates if list(pos) not in preferred]
    rng.shuffle(remaining)
    return preferred + remaining


def evenly_spaced_rows(height: int, count: int) -> List[int]:
    count = max(1, min(count, height - 4))
    if count == 1:
        return [height // 2]
    start, end = 2, height - 3
    return [round(start + (end - start) * i / (count - 1)) for i in range(count)]


def walkable_tiles(grid: List[List[str]]) -> List[List[int]]:
    out = []
    for y, row in enumerate(grid):
        for x, tile in enumerate(row):
            if tile == ".":
                out.append([x, y])
    return out


def pick_free(base: List[int], candidates: List[List[int]], occupied: set[tuple[int, int]]) -> List[int]:
    if tuple(base) not in occupied:
        return list(base)
    for candidate in candidates:
        if tuple(candidate) not in occupied:
            return list(candidate)
    return list(base)


def pick_free_platformer(base: List[int], candidates: List[List[int]], occupied: set[tuple[int, int]]) -> List[int]:
    if tuple(base) not in occupied and base in candidates:
        return list(base)
    for candidate in candidates:
        if tuple(candidate) not in occupied:
            return list(candidate)
    x, y = base
    for dx in range(-3, 4):
        candidate = [x + dx, y]
        if tuple(candidate) not in occupied:
            return candidate
    return list(base)


def platformer_entity_tiles(grid: List[List[str]]) -> List[List[int]]:
    out = []
    height = len(grid)
    width = len(grid[0]) if height else 0
    for y in range(height - 1):
        for x in range(width):
            if grid[y][x] == "." and grid[y + 1][x] == "#":
                out.append([x, y])
    return out


def has_entity(spec: GameSpec, entity_type: str) -> bool:
    return any(entity.type == entity_type for entity in spec.entities)


def entity_count(spec: GameSpec, entity_type: str) -> int:
    count = sum(entity.count for entity in spec.entities if entity.type == entity_type)
    if entity_type == "collectible" and "collectibles" in spec.mechanics and count == 0:
        if any(entity.type in {"key", "source"} for entity in spec.entities):
            return 0
        return 5
    if entity_type == "enemy" and "enemy_patrol" in spec.mechanics and count == 0:
        return 2
    if entity_type == "source" and "resource_delivery" in spec.mechanics and count == 0:
        return 4
    return min(count, 12)


def entity_name(spec: GameSpec, entity_type: str, fallback: str) -> str:
    for entity in spec.entities:
        if entity.type == entity_type:
            return entity.name
    return fallback


def first_entity(spec: GameSpec, entity_type: str):
    for entity in spec.entities:
        if entity.type == entity_type:
            return entity
    return None


def enemy_requests(spec: GameSpec):
    enemies = [entity for entity in spec.entities if entity.type == "enemy"]
    if enemies:
        return enemies
    if "enemy_patrol" in spec.mechanics:
        from schemas import EntityRequest

        return [EntityRequest("enemy", "enemy", 2, "patrol")]
    return []


def source_requests(spec: GameSpec):
    sources = entity_requests(spec, "source")
    if sources:
        return sources
    if "resource_delivery" in spec.mechanics:
        from schemas import EntityRequest

        return [EntityRequest("source", "source", 4, "interact_produces_resource")]
    return []


def entity_requests(spec: GameSpec, entity_type: str):
    entities = [entity for entity in spec.entities if entity.type == entity_type]
    if entities:
        return entities
    if entity_type == "collectible" and "collectibles" in spec.mechanics and not any(entity.type in {"key", "source"} for entity in spec.entities):
        from schemas import EntityRequest

        return [EntityRequest("collectible", "collectible", 5)]
    return []


def container_requests(spec: GameSpec):
    containers = []
    for entity in spec.entities:
        if entity.type == "container":
            for _ in range(entity.count):
                containers.append(entity)
    return containers


def goal_name(spec: GameSpec) -> str:
    return entity_name(spec, "goal", "exit")


def resource_name(source_name: str) -> str:
    cleaned = source_name.lower().strip()
    if cleaned.endswith("s"):
        cleaned = cleaned[:-1]
    return f"{cleaned}_resource" if cleaned else "resource"
