from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Tuple

from schemas import GameSpec


def load_env():
    env_path = Path(".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()


def create_game_spec(prompt: str) -> Tuple[GameSpec, Dict[str, Any]]:
    if not has_key():
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is required. There is no offline fallback.")
    return gemini_spec(prompt)


def has_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def model_cascade() -> list[str]:
    raw = os.environ.get("GEMINI_MODEL_CASCADE", "")
    models = [item.strip() for item in raw.split(",") if item.strip()]
    if models:
        return models
    single = os.environ.get("GEMINI_MODEL")
    if single:
        return [single]
    return ["gemini-2.5-flash"]


def gemini_spec(prompt: str) -> Tuple[GameSpec, Dict[str, Any]]:
    from google import genai

    timeout_ms = int(os.environ.get("GEMINI_TIMEOUT_MS", "20000"))
    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
        http_options={"timeout": timeout_ms},
    )
    errors = []
    for model in model_cascade():
        try:
            response = client.models.generate_content(
                model=model,
                contents=planner_prompt(prompt),
                config={"response_mime_type": "application/json"},
            )
            data = parse_json(response.text)
            spec = GameSpec.from_dict(data)
            return spec, {"mode": "gemini_planner", "model": model, "raw_spec": data, "errors": errors}
        except Exception as exc:
            errors.append({"model": model, "error": f"{type(exc).__name__}: {exc}"})
    raise RuntimeError(f"all planner models failed: {errors}")


def parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("planner returned non-object JSON")
    return data


def planner_prompt(prompt: str) -> str:
    return f"""
You are the planner inside a schema-driven environment-generation harness.
Return JSON only. Do not write code.

The harness supports exactly two genres:
- top_down_adventure: grid movement, walls, rooms/fields, keys, doors, terminals, collectibles, enemies, resource sources, containers, delivery goals.
- 2d_platformer: side view, platforms, gravity, collectibles, patrol enemies, hazards, goal portal.

Convert the user prompt into this JSON object:
{{
  "title": "short game title",
  "genre": "top_down_adventure or 2d_platformer",
  "theme": "short theme",
  "difficulty": "easy, medium, or hard",
  "objective": "one sentence objective",
  "mechanics": ["movement", "collectibles", "keys", "doors", "enemy_patrol", "resource_delivery", "reach_goal"],
  "entities": [
    {{"type": "collectible", "name": "crystal", "count": 8, "behavior": "static"}},
    {{"type": "source", "name": "cow", "count": 5, "behavior": "interact_produces_resource", "properties": {{"resource": "milk"}}}},
    {{"type": "container", "name": "bucket", "count": 1, "behavior": "deposit_target"}},
    {{"type": "enemy", "name": "bat", "count": 3, "behavior": "patrol"}},
    {{"type": "enemy", "name": "guard", "count": 1, "behavior": "chase_player"}},
    {{"type": "goal", "name": "portal", "count": 1, "behavior": "static"}}
  ],
  "win_condition": {{"type": "reach_goal", "requires_all_collectibles": false}},
  "lose_condition": {{"type": "enemy_collision"}},
  "unsupported_features": []
}}

Rules:
- Prefer 2d_platformer for prompts mentioning jumping, platforms, caves, portals, side-scrolling, gravity.
- Prefer top_down_adventure for prompts mentioning rooms, floor plans, mazes, kitchens, keys, doors, guards, delivery, sorting.
- If the user asks for unsupported scope such as multiplayer/MMO/3D, record it in unsupported_features and implement a supported 2D prototype.
- Keep entity counts modest so validation and demo remain reliable.
- Do not add mechanics that the user did not ask for. In particular:
  - Do not add enemies/hazards unless the prompt asks to avoid, chase, patrol, fight, or mentions enemies/guards/bats/drones/etc.
  - If the prompt explicitly says "avoid X", "escape X", or mentions guards/drones/monsters/hazards, you must include "enemy_patrol" and at least one enemy entity whose name is the requested threat (for example falling_rock, guard, drone, bat, slime).
  - If the prompt lists multiple threats to avoid, create a separate enemy entity for each named threat. For example "avoid spinning saws and a chasing bird" needs one enemy named "spinning_saw" and one enemy named "bird".
  - If the prompt says an enemy is following, chasing, pursuing, hunting, or tracking the agent/player, set that enemy's behavior to "chase_player" instead of "patrol".
  - Use "patrol" for enemies that move along routes or create ambient danger. Use "chase_player" only when the user asks for pursuit/following/chasing.
  - Do not add keys or locked doors unless the prompt asks for keys, locks, gates, access cards, or opening locked areas.
  - Do not convert ordinary rooms/floor plans into locked-door puzzles unless requested.
  - For cleaning, sorting, delivery, harvesting, or extraction tasks, focus on source/item/container mechanics.
- Use entity type "source" for prompts where the agent extracts/produces a resource by interacting with a thing:
  milking cows, harvesting crops, mining ore, drawing water, gathering samples, collecting eggs, picking fruit.
- For sources, put the produced carried thing in properties.resource, such as milk, crop, ore, water, sample, egg, fruit.
- Use entity type "container" for prompts where the extracted/carried resource must be deposited somewhere:
  bucket, sink, basket, crate, bin, table, lab station, storage.
- For source/container tasks, set mechanic "resource_delivery" and win_condition like
  {{"type": "deliver_from_sources", "source_type": "source", "destination_type": "container"}}.
- If the prompt requires ordered processing through multiple stations, such as cut then cook then plate, wash then dry then store, refine then assemble then package, include one source and one container entity per station.
  Set win_condition to {{"type": "deliver_sequentially", "sequence": ["first_station", "second_station", "third_station"]}} using the exact container names in order.
  The item should be carried from station to station, and the final station completes the objective.
- If the prompt says to deposit/insert/load items and then activate/use a terminal, console, switch, button, or control panel, include both:
  a container entity for the deposit target and a goal entity with behavior "interact_to_win" for the final activation target.
  Set win_condition to {{"type": "deliver_then_interact", "source_type": "source", "destination_type": "container", "target_type": "goal"}}.
- Use entity type "key" for keys, keycards, badges, passcodes, and access cards.
- Use entity type "goal" with behavior "interact_to_win" for terminals, switches, buttons, consoles, control panels, and lab stations that must be activated.
- Top-down pickup/source/delivery tasks should require interaction. Do not model them as automatic collision collection.
- Do not hardcode any particular example. Interpret this prompt:

{prompt}
""".strip()
