# General Intuition Agent Harness

2D top-down environment-generation harness for turning a text prompt into a validated, playable Pygame project.

```text
prompt -> Gemini GameSpec -> generated LevelSpec -> validation -> headless replay -> playable project
```

This project is meant for top-down grid environments. The validation and headless replay path are built around top-down navigation and interaction tasks.

## Setup

Using conda:

```bash
conda env create -f environment.yml
conda activate gi-true-harness
```

Or with pip:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root and replace `your_key_here` with your Gemini API key:

```bash
GEMINI_API_KEY=your_key_here
GEMINI_MODEL_CASCADE=gemini-3.5-flash,gemini-3-flash,gemini-2.5-flash,gemini-3.1-flash-lite
```

`.env` is ignored by git.

## Generate

Generate a project:

```bash
python main.py generate "create a kitchen where the agent collects dishes and deposits them into the sink"
```

Generate and launch it:

```bash
python main.py generate "create a prison escape with a key, locked door, guard, and exit" --run
```

Print full harness state:

```bash
python main.py generate "create a farm task where the agent gathers milk from cows into a bucket" --print-state
```

Choose an output folder:

```bash
python main.py generate "create a lab cleanup task" --output-dir generated_games/trials
```

Rebuild from a saved spec without calling Gemini:

```bash
python main.py generate --spec generated_games/my_game/state.json --run
```

## CLI Flags

- `generate "prompt"`: call Gemini, build a spec, validate it, generate a playable project.
- `--run`: launch the generated Pygame project after generation.
- `--print-state`: print the full harness state JSON.
- `--output-dir PATH`: write generated projects somewhere other than `generated_games/`.
- `--spec PATH`: load a raw `GameSpec` JSON or saved `state.json` instead of calling Gemini.
- `examples`: print example prompts.

## Generated Files

Each generated project contains:

- `config.json`: game and level data.
- `main.py`: standalone Pygame runner.
- `top_down_engine.py`: shared top-down game rules.
- `solution.json`: headless action replay for supported top-down tasks.
- `state.json`: full harness state.
- `test_report.json`: validation results.
- `README.md`: per-game run notes.

## Controls

Top-down:

- WASD/arrows: move
- E or Space: interact
- R: reset
- Esc: quit
