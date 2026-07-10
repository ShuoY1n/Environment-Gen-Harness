from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any


Action = str
Pos = tuple[int, int]


MOVE_DELTAS: dict[Action, Pos] = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}


@dataclass
class TopDownState:
    level: dict[str, Any]
    spec: dict[str, Any]
    pos: Pos
    entities: list[dict[str, Any]]
    inventory: set[str] = field(default_factory=set)
    collected: set[str] = field(default_factory=set)
    open_doors: set[str] = field(default_factory=set)
    harvested_sources: set[str] = field(default_factory=set)
    delivered_sources: set[str] = field(default_factory=set)
    workflow_steps: dict[str, int] = field(default_factory=dict)
    carrying: dict[str, str] | None = None
    done: bool = False
    failed: bool = False
    steps: int = 0
    message: str = "ready"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "TopDownState":
        level = config["level_spec"]
        return cls(
            level=level,
            spec=config["game_spec"],
            pos=tuple(level["spawn"]),
            entities=[dict(entity) for entity in level["entities"]],
        )

    def apply(self, action: Action) -> None:
        if self.done or self.failed:
            return
        self.steps += 1
        if action in MOVE_DELTAS:
            dx, dy = MOVE_DELTAS[action]
            target = (self.pos[0] + dx, self.pos[1] + dy)
            if self.passable(target):
                self.pos = target
                self.check_passive_entities()
            else:
                self.message = "blocked"
        elif action == "interact":
            self.interact()
        self.update_enemies()
        self.check_enemy_collision()
        if self.steps > 2500:
            self.failed = True

    def passable(self, pos: Pos) -> bool:
        x, y = pos
        if x < 0 or y < 0 or x >= self.level["width"] or y >= self.level["height"]:
            return False
        if self.level["layout"][y][x] == "#":
            return False
        for entity in self.entities:
            if entity["type"] == "door" and entity["id"] not in self.open_doors and tuple(entity["pos"]) == pos:
                return False
        return True

    def interact(self) -> None:
        for entity in self.nearby_entities():
            entity_id = entity["id"]
            if entity_id in self.collected or entity_id in self.delivered_sources:
                continue
            if entity["type"] == "key":
                self.inventory.add(entity_id)
                self.collected.add(entity_id)
                self.message = f"picked up {entity['name']}"
                return
            if entity["type"] == "collectible":
                self.collected.add(entity_id)
                self.message = f"collected {entity['name']}"
                return
            if entity["type"] == "source":
                if entity_id in self.delivered_sources:
                    self.message = f"{entity['name']} already completed"
                    return
                if entity_id in self.harvested_sources:
                    self.message = f"{entity['name']} already harvested"
                    return
                if self.carrying:
                    self.message = f"already carrying {self.carrying['resource']}"
                    return
                resource = entity.get("properties", {}).get("resource", entity["name"])
                self.harvested_sources.add(entity_id)
                self.carrying = {"source_id": entity_id, "resource": resource}
                self.message = f"collected {resource} from {entity['name']}"
                return
            if entity["type"] in {"container", "goal"} and self.carrying:
                if self.workflow_sequence():
                    self.handle_workflow_station(entity)
                else:
                    self.delivered_sources.add(self.carrying["source_id"])
                    self.message = f"deposited {self.carrying['resource']} into {entity['name']}"
                    self.carrying = None
                    if self.all_sources_delivered() and not self.requires_post_delivery_activation():
                        self.done = True
                return
            if entity["type"] == "goal" and self.goal_requires_interaction(entity):
                if self.requires_post_delivery_activation() and not self.all_sources_delivered():
                    self.message = f"{entity['name']} needs all deliveries first"
                    return
                self.done = True
                self.message = f"activated {entity['name']}"
                return
            if entity["type"] == "door":
                needed = entity.get("properties", {}).get("opens_with")
                if not needed or needed in self.inventory:
                    self.open_doors.add(entity_id)
                    self.message = f"opened {entity['name']}"
                    return
                self.message = f"{entity['name']} needs {needed}"
                return
        self.message = "nothing to interact with"

    def nearby_entities(self) -> list[dict[str, Any]]:
        return [entity for entity in self.entities if manhattan(self.pos, tuple(entity["pos"])) <= 1]

    def update_enemies(self) -> None:
        if self.steps % 2 != 0:
            return
        for entity in self.entities:
            if entity["type"] != "enemy":
                continue
            if entity.get("behavior") == "chase_player":
                candidate = self.next_chase_step(entity)
            else:
                candidate = self.next_patrol_step(entity)
            if candidate is not None:
                entity["pos"] = list(candidate)

    def next_patrol_step(self, entity: dict[str, Any]) -> Pos | None:
        props = entity.setdefault("properties", {})
        origin = props.setdefault("origin", list(entity["pos"]))
        direction = props.setdefault("direction", 1)
        axis = props.get("axis", "horizontal")
        patrol_range = int(props.get("range", 3))
        idx = 0 if axis == "horizontal" else 1
        candidate = list(entity["pos"])
        candidate[idx] += direction
        if self.passable(tuple(candidate)) and abs(candidate[idx] - origin[idx]) <= patrol_range:
            return tuple(candidate)
        props["direction"] = -direction
        return None

    def next_chase_step(self, entity: dict[str, Any]) -> Pos | None:
        ex, ey = entity["pos"]
        px, py = self.pos
        candidates = []
        if px != ex:
            candidates.append((ex + (1 if px > ex else -1), ey))
        if py != ey:
            candidates.append((ex, ey + (1 if py > ey else -1)))
        candidates.extend([(ex + 1, ey), (ex - 1, ey), (ex, ey + 1), (ex, ey - 1)])
        current_distance = manhattan((ex, ey), self.pos)
        for candidate in candidates:
            if self.passable(candidate) and manhattan(candidate, self.pos) < current_distance:
                return candidate
        return None

    def check_enemy_collision(self) -> None:
        for entity in self.entities:
            if entity["type"] == "enemy" and tuple(entity["pos"]) == self.pos:
                self.failed = True
                self.message = f"caught by {entity['name']}"

    def check_passive_entities(self) -> None:
        requires_all = self.spec.get("win_condition", {}).get("requires_all_collectibles", False)
        for entity in self.entities:
            if entity["id"] in self.collected:
                continue
            if entity["type"] == "goal" and tuple(entity["pos"]) == self.pos:
                if self.spec.get("win_condition", {}).get("type") == "deliver_from_sources":
                    self.done = self.all_sources_delivered()
                elif not self.goal_requires_interaction(entity) and (not requires_all or self.all_collectibles_collected()):
                    self.done = True
            elif entity["type"] == "container" and tuple(entity["pos"]) == self.pos and self.all_sources_delivered():
                self.done = True

    def all_collectibles_collected(self) -> bool:
        required = [entity["id"] for entity in self.entities if entity["type"] in {"collectible", "key"}]
        return all(entity_id in self.collected for entity_id in required)

    def all_sources_delivered(self) -> bool:
        sources = [entity["id"] for entity in self.entities if entity["type"] == "source"]
        return bool(sources) and all(entity_id in self.delivered_sources for entity_id in sources)

    def workflow_sequence(self) -> list[str]:
        condition = self.spec.get("win_condition", {})
        if condition.get("type") != "deliver_sequentially":
            return []
        return [str(item) for item in condition.get("sequence", [])]

    def handle_workflow_station(self, entity: dict[str, Any]) -> None:
        sequence = self.workflow_sequence()
        source_id = self.carrying["source_id"]
        step = self.workflow_steps.get(source_id, 0)
        expected = sequence[step] if step < len(sequence) else None
        if normalize_name(entity["name"]) != normalize_name(expected):
            self.message = f"next station: {expected}"
            return
        self.workflow_steps[source_id] = step + 1
        if step + 1 >= len(sequence):
            self.delivered_sources.add(source_id)
            self.message = f"completed {self.carrying['resource']} at {entity['name']}"
            self.carrying = None
            if self.all_sources_delivered():
                self.done = True
        else:
            self.carrying["resource"] = f"{self.carrying['resource']}->{entity['name']}"
            self.message = f"processed at {entity['name']}; next: {sequence[step + 1]}"

    def goal_requires_interaction(self, entity: dict[str, Any]) -> bool:
        return self.spec.get("win_condition", {}).get("type") in {"interact_with_entity", "deliver_then_interact"} or entity.get("behavior") == "interact_to_win"

    def requires_post_delivery_activation(self) -> bool:
        has_sources = any(entity["type"] == "source" for entity in self.entities)
        has_interactive_goal = any(entity["type"] == "goal" and self.goal_requires_interaction(entity) for entity in self.entities)
        return has_sources and has_interactive_goal


def shortest_path(state: TopDownState, start: Pos, target: Pos) -> list[Action] | None:
    queue = deque([(start, [])])
    seen = {start}
    while queue:
        pos, path = queue.popleft()
        if pos == target:
            return path
        for action, (dx, dy) in MOVE_DELTAS.items():
            nxt = (pos[0] + dx, pos[1] + dy)
            if nxt not in seen and state.passable(nxt):
                seen.add(nxt)
                queue.append((nxt, path + [action]))
    return None


def manhattan(a: Pos, b: Pos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def normalize_name(value: Any) -> str:
    return "".join(char.lower() for char in str(value or "") if char.isalnum())
