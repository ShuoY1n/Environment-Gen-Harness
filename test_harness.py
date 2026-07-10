from pathlib import Path

from level_generator import generate_level
from schemas import EntityRequest, GameSpec
from validator import validate_all
from solver import solve_level


def test_top_down_generation_validates():
    spec = top_down_spec()
    level = generate_level(spec, seed=1)
    results = validate_all(spec, level)
    assert all(result.passed for result in results), [r.to_dict() for r in results]


def test_platformer_generation_validates():
    spec = platformer_spec()
    level = generate_level(spec, seed=2)
    results = validate_all(spec, level)
    assert all(result.passed for result in results), [r.to_dict() for r in results]


def test_hard_platformer_generation_validates():
    spec = platformer_spec()
    spec.difficulty = "hard"
    level = generate_level(spec, seed=2)
    results = validate_all(spec, level)
    assert all(result.passed for result in results), [r.to_dict() for r in results]


def test_resource_delivery_generation_validates():
    spec = resource_delivery_spec()
    level = generate_level(spec, seed=3)
    results = validate_all(spec, level)
    assert any(entity.type == "source" for entity in level.entities)
    assert any(entity.type == "container" for entity in level.entities)
    assert all(result.passed for result in results), [r.to_dict() for r in results]


def test_delivery_then_interact_places_container_and_goal():
    spec = GameSpec(
        title="Reactor Protocol",
        genre="top_down_adventure",
        theme="museum",
        difficulty="medium",
        objective="Deposit batteries and activate a control panel.",
        mechanics=["movement", "resource_delivery", "reach_goal"],
        entities=[
            EntityRequest("source", "battery", 3, "interact_produces_resource", {"resource": "battery"}),
            EntityRequest("container", "reactor_display", 1, "deposit_target"),
            EntityRequest("goal", "control_panel", 1, "interact_to_win"),
        ],
        win_condition={"type": "deliver_then_interact"},
    )
    level = generate_level(spec, seed=10)
    results = validate_all(spec, level)
    assert any(entity.type == "container" for entity in level.entities)
    goal = next(entity for entity in level.entities if entity.type == "goal")
    assert goal.name == "control_panel"
    assert goal.behavior == "interact_to_win"
    assert all(result.passed for result in results), [r.to_dict() for r in results]


def test_ordered_workflow_places_all_stations():
    spec = GameSpec(
        title="Kitchen Prep Line",
        genre="top_down_adventure",
        theme="kitchen",
        difficulty="medium",
        objective="Cut, cook, and plate the meat in order.",
        mechanics=["movement", "resource_delivery"],
        entities=[
            EntityRequest("source", "raw_meat", 1, "interact_produces_resource", {"resource": "meat"}),
            EntityRequest("container", "cutting_station", 1, "deposit_target"),
            EntityRequest("container", "cooking_station", 1, "deposit_target"),
            EntityRequest("container", "plating_station", 1, "deposit_target"),
        ],
        win_condition={"type": "deliver_sequentially", "sequence": ["cutting_station", "cooking_station", "plating_station"]},
    )
    level = generate_level(spec, seed=13)
    results = validate_all(spec, level)
    containers = [entity.name for entity in level.entities if entity.type == "container"]
    assert containers == ["cutting_station", "cooking_station", "plating_station"]
    assert all(result.passed for result in results), [r.to_dict() for r in results]


def test_resource_delivery_project_runtime_compiles(tmp_path):
    import importlib.util
    import sys

    from schemas import HarnessState
    from project_generator import generate_project

    spec = resource_delivery_spec()
    level = generate_level(spec, seed=3)
    state = HarnessState(user_prompt="resource delivery test", game_spec=spec, level_spec=level, final_status="success")
    state.test_results = validate_all(spec, level)
    project = generate_project(tmp_path, state, state.test_results)
    source = project / "main.py"
    text = source.read_text()
    compile(text, str(source), "exec")
    assert 'Path(__file__).resolve().parent / "config.json"' in text
    assert (project / "top_down_engine.py").exists()
    sys.path.insert(0, str(project))
    module_spec = importlib.util.spec_from_file_location("generated_resource_main", source)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    game = module.Game(module.load_config())
    assert game.core is not None
    assert game.core.level["genre"] == "top_down_adventure"


def test_platformer_runtime_smoke_updates_enemy_ticks(tmp_path, monkeypatch):
    import importlib.util

    from schemas import HarnessState
    from project_generator import generate_project

    spec = platformer_spec()
    level = generate_level(spec, seed=2)
    state = HarnessState(user_prompt="platformer smoke", game_spec=spec, level_spec=level, final_status="success")
    state.test_results = validate_all(spec, level)
    project = generate_project(tmp_path, state, state.test_results)
    monkeypatch.syspath_prepend(str(project))
    module_spec = importlib.util.spec_from_file_location("generated_platformer_main", project / "main.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)

    class NoKeys:
        def __getitem__(self, _):
            return False

    game = module.Game(module.load_config())
    for _ in range(20):
        game.update(NoKeys())
    assert game.tile_at(-1, 0) == "#"


def test_headless_solver_solves_resource_delivery():
    spec = resource_delivery_spec()
    level = generate_level(spec, seed=3)
    solution = solve_level(level, spec.to_dict())
    assert solution["supported"] is True
    assert solution["success"] is True
    assert solution["actions"]


def test_top_down_engine_detects_enemy_collision():
    from top_down_engine import TopDownState

    config = {
        "game_spec": top_down_spec().to_dict(),
        "level_spec": {
            "genre": "top_down_adventure",
            "width": 5,
            "height": 5,
            "tile_size": 32,
            "layout": [".....", ".....", ".....", ".....", "....."],
            "spawn": [2, 2],
            "goal": [4, 4],
            "entities": [{"id": "enemy_1", "type": "enemy", "name": "guard", "pos": [2, 2], "behavior": "patrol", "properties": {}}],
        },
    }
    state = TopDownState.from_config(config)
    state.check_enemy_collision()
    assert state.failed is True


def test_headless_solver_solves_ordered_workflow():
    spec = GameSpec(
        title="Kitchen Prep Line",
        genre="top_down_adventure",
        theme="kitchen",
        difficulty="medium",
        objective="Cut, cook, and plate the meat in order.",
        mechanics=["movement", "resource_delivery"],
        entities=[
            EntityRequest("source", "raw_meat", 1, "interact_produces_resource", {"resource": "meat"}),
            EntityRequest("container", "cutting_station", 1, "deposit_target"),
            EntityRequest("container", "cooking_station", 1, "deposit_target"),
            EntityRequest("container", "plating_station", 1, "deposit_target"),
        ],
        win_condition={"type": "deliver_sequentially", "sequence": ["cutting_station", "cooking_station", "plating_station"]},
    )
    level = generate_level(spec, seed=13)
    solution = solve_level(level, spec.to_dict())
    assert solution["success"] is True


def test_harness_from_spec_writes_solution(tmp_path):
    from harness import run_harness_from_spec

    state = run_harness_from_spec(resource_delivery_spec(), output_dir=str(tmp_path))
    solution_path = Path(state.project_path) / "solution.json"
    assert state.final_status == "success"
    assert any(result.name == "headless_solution" and result.passed for result in state.test_results)
    assert solution_path.exists()
    assert '"success": true' in solution_path.read_text()


def test_harness_from_spec_seed_depends_on_spec_not_prompt(tmp_path):
    from harness import run_harness_from_spec

    spec = resource_delivery_spec()
    first = run_harness_from_spec(spec, prompt="first filename", output_dir=str(tmp_path / "a"))
    second = run_harness_from_spec(spec, prompt="second filename", output_dir=str(tmp_path / "b"))
    assert first.level_spec.to_dict() == second.level_spec.to_dict()


def test_platformer_harness_does_not_claim_headless_solution(tmp_path):
    from harness import run_harness_from_spec

    state = run_harness_from_spec(platformer_spec(), output_dir=str(tmp_path))
    result = next(test for test in state.test_results if test.name == "headless_solution")
    assert result.passed is False
    assert state.final_status != "success"


def test_validator_rejects_disappearing_platformer_keydoor():
    spec = GameSpec(
        title="Bad Platformer",
        genre="2d_platformer",
        theme="test",
        difficulty="medium",
        objective="Find a key and open a door.",
        mechanics=["movement", "keys", "doors", "reach_goal"],
        entities=[
            EntityRequest("key", "key", 1),
            EntityRequest("door", "door", 1),
            EntityRequest("goal", "exit", 1),
        ],
        win_condition={"type": "reach_goal"},
    )
    level = generate_level(spec, seed=2)
    results = validate_all(spec, level)
    faithfulness = next(result for result in results if result.name == "spec_faithfulness")
    assert not faithfulness.passed


def test_interact_to_win_goal_behavior_preserved():
    spec = GameSpec(
        title="Terminal Lab",
        genre="top_down_adventure",
        theme="lab",
        difficulty="medium",
        objective="Activate the terminal.",
        mechanics=["movement", "reach_goal"],
        entities=[EntityRequest("goal", "terminal", 1, "interact_to_win")],
        win_condition={"type": "interact_with_entity", "target_entity": "terminal"},
    )
    level = generate_level(spec, seed=5)
    goal = next(entity for entity in level.entities if entity.type == "goal")
    assert goal.behavior == "interact_to_win"


def test_schema_normalizes_terminal_and_keycard():
    spec = GameSpec.from_dict(
        {
            "title": "Lab",
            "genre": "top_down_adventure",
            "theme": "lab",
            "difficulty": "medium",
            "objective": "Use a keycard and activate a terminal.",
            "mechanics": ["movement", "keys", "doors", "reach_goal"],
            "entities": [
                {"type": "collectible", "name": "keycard", "count": 1},
                {"type": "terminal", "name": "main terminal", "count": 1, "behavior": "interact_activates"},
            ],
            "win_condition": {"type": "activate_terminal"},
        }
    )
    assert any(entity.type == "key" for entity in spec.entities)
    goal = next(entity for entity in spec.entities if entity.type == "goal")
    assert goal.behavior == "interact_to_win"


def test_schema_normalizes_hazard_to_enemy():
    spec = GameSpec.from_dict(
        {
            "title": "Hazards",
            "genre": "2d_platformer",
            "theme": "factory",
            "difficulty": "medium",
            "objective": "Avoid saws.",
            "mechanics": ["movement", "enemy_patrol", "reach_goal"],
            "entities": [
                {"type": "hazard", "name": "spinning_saw", "count": 2, "behavior": "patrol"},
                {"type": "goal", "name": "exit", "count": 1},
            ],
            "win_condition": {"type": "reach_goal"},
        }
    )
    assert any(entity.type == "enemy" and entity.name == "spinning_saw" for entity in spec.entities)


def test_delivery_normalizes_collectibles_into_sources():
    spec = GameSpec.from_dict(
        {
            "title": "Museum",
            "genre": "top_down_adventure",
            "theme": "museum",
            "difficulty": "medium",
            "objective": "Collect artifacts and deposit them into a display case.",
            "mechanics": ["movement", "collectibles", "resource_delivery"],
            "entities": [
                {"type": "collectible", "name": "artifact", "count": 5},
                {"type": "container", "name": "display case", "count": 1},
            ],
            "win_condition": {"type": "deliver_from_sources"},
        }
    )
    assert "collectibles" not in spec.mechanics
    sources = [entity for entity in spec.entities if entity.type == "source"]
    assert len(sources) == 1
    assert sources[0].name == "artifact"
    assert sources[0].properties["resource"] == "artifact"


def test_delivery_with_sources_drops_collectible_mechanic():
    spec = GameSpec.from_dict(
        {
            "title": "Server Room",
            "genre": "top_down_adventure",
            "theme": "server",
            "difficulty": "medium",
            "objective": "Gather drives and deposit them in a cabinet.",
            "mechanics": ["movement", "collectibles", "resource_delivery"],
            "entities": [
                {"type": "collectible", "name": "backup_drive", "count": 4},
                {"type": "source", "name": "server_rack", "count": 4, "properties": {"resource": "backup_drive"}},
                {"type": "container", "name": "secure_cabinet", "count": 1},
            ],
            "win_condition": {"type": "deliver_from_sources"},
        }
    )
    assert "collectibles" not in spec.mechanics
    assert not any(entity.type == "collectible" for entity in spec.entities)


def test_key_name_is_preserved_in_level():
    spec = GameSpec(
        title="Badge Lab",
        genre="top_down_adventure",
        theme="warehouse",
        difficulty="medium",
        objective="Find a badge, open the office, and reach the console.",
        mechanics=["movement", "keys", "doors", "reach_goal"],
        entities=[
            EntityRequest("key", "badge", 1),
            EntityRequest("door", "office door", 1, "locked"),
            EntityRequest("goal", "console", 1),
        ],
        win_condition={"type": "reach_goal"},
    )
    level = generate_level(spec, seed=6)
    assert next(entity for entity in level.entities if entity.type == "key").name == "badge"
    assert next(entity for entity in level.entities if entity.type == "door").name == "office door"


def test_multiple_keys_are_placed():
    spec = GameSpec(
        title="Hotel Keys",
        genre="top_down_adventure",
        theme="hotel",
        difficulty="medium",
        objective="Gather three room keys and reach the exit.",
        mechanics=["movement", "keys", "doors", "reach_goal"],
        entities=[
            EntityRequest("key", "room_key", 3),
            EntityRequest("door", "lobby_gate", 1, "locked"),
            EntityRequest("goal", "exit_desk", 1),
        ],
        win_condition={"type": "reach_goal", "requires_all_collectibles": True},
    )
    level = generate_level(spec, seed=11)
    keys = [entity for entity in level.entities if entity.type == "key"]
    assert len(keys) == 3
    assert {entity.id for entity in keys} == {"key_1", "key_2", "key_3"}


def test_multiple_doors_are_placed_when_requested():
    spec = GameSpec(
        title="Double Gate",
        genre="top_down_adventure",
        theme="vault",
        difficulty="medium",
        objective="Open two locked gates and reach the exit.",
        mechanics=["movement", "keys", "doors", "reach_goal"],
        entities=[
            EntityRequest("key", "key", 2),
            EntityRequest("door", "security gate", 2, "locked"),
            EntityRequest("goal", "exit", 1),
        ],
        win_condition={"type": "reach_goal", "requires_all_collectibles": True},
    )
    level = generate_level(spec, seed=14)
    results = validate_all(spec, level)
    assert len([entity for entity in level.entities if entity.type == "door"]) == 2
    assert all(result.passed for result in results), [result.to_dict() for result in results]


def test_multiple_key_specs_require_all_pickups():
    spec = GameSpec.from_dict(
        {
            "title": "Hotel Keys",
            "genre": "top_down_adventure",
            "theme": "hotel",
            "difficulty": "medium",
            "objective": "Gather three room keys and reach the exit.",
            "mechanics": ["movement", "keys", "doors", "reach_goal"],
            "entities": [
                {"type": "key", "name": "room_key", "count": 3},
                {"type": "door", "name": "lobby_gate", "count": 1},
                {"type": "goal", "name": "exit_desk", "count": 1},
            ],
            "win_condition": {"type": "reach_goal"},
        }
    )
    assert spec.win_condition["requires_all_collectibles"] is True


def test_key_tasks_do_not_spawn_generic_collectibles():
    spec = GameSpec(
        title="Hotel Keys",
        genre="top_down_adventure",
        theme="hotel",
        difficulty="medium",
        objective="Gather keys and reach the exit.",
        mechanics=["movement", "collectibles", "keys", "doors", "reach_goal"],
        entities=[
            EntityRequest("key", "room_key", 3),
            EntityRequest("door", "lobby_gate", 1),
            EntityRequest("goal", "exit_desk", 1),
        ],
        win_condition={"type": "reach_goal", "requires_all_collectibles": True},
    )
    level = generate_level(spec, seed=12)
    assert not any(entity.type == "collectible" for entity in level.entities)


def test_locked_container_door_does_not_replace_goal():
    spec = GameSpec.from_dict(
        {
            "title": "Arctic Base",
            "genre": "top_down_adventure",
            "theme": "arctic",
            "difficulty": "medium",
            "objective": "Find an access card, open a lab, and activate a terminal.",
            "mechanics": ["movement", "keys", "doors", "reach_goal"],
            "entities": [
                {"type": "key", "name": "access_card", "count": 1},
                {"type": "container", "name": "lab_door", "count": 1, "behavior": "locked_by_key"},
                {"type": "goal", "name": "weather_terminal", "count": 1, "behavior": "interact_to_win"},
            ],
            "win_condition": {"type": "reach_goal"},
        }
    )
    assert any(entity.type == "door" and entity.name == "lab_door" for entity in spec.entities)
    level = generate_level(spec, seed=7)
    assert next(entity for entity in level.entities if entity.type == "goal").name == "weather_terminal"


def test_chase_player_enemy_behavior_is_preserved():
    spec = GameSpec(
        title="Prison Escape",
        genre="top_down_adventure",
        theme="prison",
        difficulty="medium",
        objective="Get the key while a guard follows the agent.",
        mechanics=["movement", "keys", "doors", "enemy_patrol", "reach_goal"],
        entities=[
            EntityRequest("key", "cell_key", 1),
            EntityRequest("door", "locked_door", 1, "locked"),
            EntityRequest("enemy", "prison_guard", 1, "chase_player"),
            EntityRequest("goal", "exit", 1),
        ],
        win_condition={"type": "reach_goal"},
        lose_condition={"type": "enemy_collision"},
    )
    level = generate_level(spec, seed=8)
    enemy = next(entity for entity in level.entities if entity.type == "enemy")
    assert enemy.name == "prison_guard"
    assert enemy.behavior == "chase_player"


def test_multiple_enemy_types_are_preserved():
    spec = GameSpec(
        title="Volcano Escape",
        genre="2d_platformer",
        theme="volcano",
        difficulty="medium",
        objective="Avoid lava and fire spirits.",
        mechanics=["movement", "collectibles", "enemy_patrol", "reach_goal"],
        entities=[
            EntityRequest("collectible", "relic", 3),
            EntityRequest("enemy", "fire_spirit", 2, "chase_player"),
            EntityRequest("enemy", "rising_lava", 1, "patrol"),
            EntityRequest("goal", "escape_portal", 1),
        ],
        win_condition={"type": "reach_goal", "requires_all_collectibles": True},
        lose_condition={"type": "enemy_collision"},
    )
    level = generate_level(spec, seed=9)
    enemies = [(entity.name, entity.behavior) for entity in level.entities if entity.type == "enemy"]
    assert ("fire_spirit", "chase_player") in enemies
    assert ("rising_lava", "patrol") in enemies


def top_down_spec():
    return GameSpec(
        title="Snow Adventure",
        genre="top_down_adventure",
        theme="snow",
        difficulty="medium",
        objective="Find the key, open the door, avoid guards, and reach the exit.",
        mechanics=["movement", "reach_goal", "keys", "doors", "enemy_patrol"],
        entities=[
            EntityRequest("key", "key", 1),
            EntityRequest("door", "locked door", 1),
            EntityRequest("enemy", "guard", 2, "patrol"),
            EntityRequest("goal", "exit", 1),
        ],
        win_condition={"type": "reach_goal", "requires_all_collectibles": False},
        lose_condition={"type": "enemy_collision"},
    )


def platformer_spec():
    return GameSpec(
        title="Cave Platformer",
        genre="2d_platformer",
        theme="cave",
        difficulty="medium",
        objective="Collect crystals, avoid bats, and reach the portal.",
        mechanics=["movement", "reach_goal", "collectibles", "enemy_patrol"],
        entities=[
            EntityRequest("collectible", "crystal", 8),
            EntityRequest("enemy", "bat", 2, "patrol"),
            EntityRequest("goal", "portal", 1),
        ],
        win_condition={"type": "reach_goal", "requires_all_collectibles": True},
        lose_condition={"type": "enemy_collision"},
    )


def resource_delivery_spec():
    return GameSpec(
        title="Farm Adventure",
        genre="top_down_adventure",
        theme="farm",
        difficulty="medium",
        objective="Interact with each source, carry the produced resource, and deposit it.",
        mechanics=["movement", "reach_goal", "resource_delivery"],
        entities=[
            EntityRequest("source", "cow", 5, "interact_produces_resource", {"resource": "milk"}),
            EntityRequest("container", "bucket", 1, "deposit_target"),
        ],
        win_condition={"type": "deliver_from_sources", "source_type": "source", "destination_type": "container"},
    )
