from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional


Genre = Literal["top_down_adventure", "2d_platformer"]
Difficulty = Literal["easy", "medium", "hard"]


@dataclass
class EntityRequest:
    type: str
    name: str
    count: int = 1
    behavior: str = "static"
    properties: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityRequest":
        raw_type = str(data.get("type", "object"))
        raw_name = str(data.get("name", data.get("type", "object")))
        entity_type = normalize_entity_type(raw_type, raw_name)
        behavior = str(data.get("behavior", "static"))
        if entity_type == "container" and (behavior in {"locked", "locked_by_key"} or "door" in raw_name.lower()):
            entity_type = "door"
            behavior = "locked"
        if entity_type == "goal" and behavior in {"static", "interact_activates"} and str(data.get("type", "")) in INTERACTIVE_GOAL_TYPES:
            behavior = "interact_to_win"
        return cls(
            type=entity_type,
            name=raw_name,
            count=max(1, min(30, int(data.get("count", 1)))),
            behavior=behavior,
            properties=dict(data.get("properties", {})) if isinstance(data.get("properties"), dict) else {},
        )


@dataclass
class GameSpec:
    title: str
    genre: Genre
    theme: str
    difficulty: Difficulty
    objective: str
    mechanics: List[str]
    entities: List[EntityRequest]
    win_condition: Dict[str, Any]
    lose_condition: Optional[Dict[str, Any]] = None
    unsupported_features: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GameSpec":
        genre = str(data.get("genre", "top_down_adventure"))
        if genre not in {"top_down_adventure", "2d_platformer"}:
            genre = "top_down_adventure"
        difficulty = str(data.get("difficulty", "medium"))
        if difficulty not in {"easy", "medium", "hard"}:
            difficulty = "medium"
        entities = [EntityRequest.from_dict(row) for row in data.get("entities", []) if isinstance(row, dict)]
        if not entities:
            entities = [EntityRequest("goal", "exit", 1)]
        win_condition = dict(data.get("win_condition", {"type": "reach_goal"}))
        mechanics = [str(item) for item in data.get("mechanics", ["movement", "goal"])]
        entities = normalize_delivery_entities(entities, mechanics, win_condition)
        normalize_pickup_requirements(entities, win_condition)
        return cls(
            title=clean_title(str(data.get("title", "Generated Environment"))),
            genre=genre,  # type: ignore[arg-type]
            theme=str(data.get("theme", "generic")),
            difficulty=difficulty,  # type: ignore[arg-type]
            objective=str(data.get("objective", "Reach the goal.")),
            mechanics=mechanics,
            entities=entities,
            win_condition=win_condition,
            lose_condition=dict(data["lose_condition"]) if isinstance(data.get("lose_condition"), dict) else None,
            unsupported_features=[str(item) for item in data.get("unsupported_features", [])],
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlacedEntity:
    id: str
    type: str
    name: str
    pos: List[int]
    behavior: str = "static"
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LevelSpec:
    genre: Genre
    width: int
    height: int
    tile_size: int
    layout: List[str]
    spawn: List[int]
    goal: List[int]
    entities: List[PlacedEntity]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TestResult:
    name: str
    passed: bool
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HarnessState:
    user_prompt: str
    game_spec: Optional[GameSpec] = None
    level_spec: Optional[LevelSpec] = None
    project_path: Optional[str] = None
    test_results: List[TestResult] = field(default_factory=list)
    repair_attempts: int = 0
    final_status: str = "pending"
    model_used: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_prompt": self.user_prompt,
            "game_spec": self.game_spec.to_dict() if self.game_spec else None,
            "level_spec": self.level_spec.to_dict() if self.level_spec else None,
            "project_path": self.project_path,
            "test_results": [row.to_dict() for row in self.test_results],
            "repair_attempts": self.repair_attempts,
            "final_status": self.final_status,
            "model_used": self.model_used,
            "notes": list(self.notes),
        }


def clean_title(value: str) -> str:
    cleaned = " ".join(value.replace("_", " ").split()).strip()
    return cleaned[:60] or "Generated Environment"


INTERACTIVE_GOAL_TYPES = {"terminal", "switch", "button", "console", "control_panel", "lab_station"}
KEY_LIKE_NAMES = {"keycard", "key_card", "badge", "access_badge", "access_card", "passcode", "key"}


def normalize_entity_type(entity_type: str, name: str) -> str:
    lower_type = entity_type.lower().strip()
    lower_name = name.lower().strip().replace(" ", "_")
    if lower_type in INTERACTIVE_GOAL_TYPES:
        return "goal"
    if lower_type in {"key", "access_token"} or lower_name in KEY_LIKE_NAMES:
        return "key"
    if lower_type in {"exit", "portal"}:
        return "goal"
    if lower_type in {"hazard", "trap", "obstacle"}:
        return "enemy"
    return lower_type


def normalize_delivery_entities(entities: List[EntityRequest], mechanics: List[str], win_condition: Dict[str, Any]) -> List[EntityRequest]:
    delivery_task = "resource_delivery" in mechanics or win_condition.get("type") in {"deliver_from_sources", "deliver_then_interact", "deliver_sequentially"}
    if delivery_task and "resource_delivery" not in mechanics:
        mechanics.append("resource_delivery")
    has_container = any(entity.type == "container" for entity in entities)
    has_source = any(entity.type == "source" for entity in entities)
    if not delivery_task or not has_container or has_source:
        if delivery_task and has_container and has_source:
            if "collectibles" in mechanics:
                mechanics[:] = [item for item in mechanics if item != "collectibles"]
            entities = [entity for entity in entities if entity.type != "collectible"]
        return entities

    normalized = []
    converted_collectible = False
    for entity in entities:
        if entity.type == "collectible":
            properties = dict(entity.properties)
            properties.setdefault("resource", singular_resource_name(entity.name))
            normalized.append(
                EntityRequest(
                    type="source",
                    name=entity.name,
                    count=entity.count,
                    behavior="interact_produces_resource",
                    properties=properties,
                )
            )
            converted_collectible = True
        else:
            normalized.append(entity)
    if converted_collectible and "collectibles" in mechanics:
        mechanics[:] = [item for item in mechanics if item != "collectibles"]
    return normalized


def normalize_pickup_requirements(entities: List[EntityRequest], win_condition: Dict[str, Any]):
    key_count = sum(entity.count for entity in entities if entity.type == "key")
    collectible_count = sum(entity.count for entity in entities if entity.type == "collectible")
    if win_condition.get("type") == "reach_goal" and key_count + collectible_count > 1:
        win_condition["requires_all_collectibles"] = True


def singular_resource_name(name: str) -> str:
    cleaned = name.lower().strip().replace(" ", "_")
    if cleaned.endswith("s") and len(cleaned) > 1:
        cleaned = cleaned[:-1]
    return cleaned or "resource"
