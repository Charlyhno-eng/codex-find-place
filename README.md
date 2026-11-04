![Codex Find Place banner](assets/codex-find-place-banner.png)

# Codex Find Place

A local app that helps locate where a photo was taken using visual clues, metadata, and web research. Explore candidate locations on a map and keep investigation reports on your computer.

## Quick install

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and Codex CLI installed and signed in (`codex login`).

From the project folder:

```sh
uv sync
uv run playwright install chromium
uv run codex-find-place
```

Open http://127.0.0.1:8000 and upload a photo. Codex uses your account; web research requires an Internet connection.

## Examples

![Example 1](assets/example1.png)

![Example 2](assets/example2.png)

## Replacing the AI provider

The Codex adapter lives in `osint_picture/providers/codex.py`. To use another engine, implement the `Provider` contract in `osint_picture/providers/__init__.py`, then run `FIND_PLACE_PROVIDER=my_module:MyProvider uv run codex-find-place`. Its async `analyze` method receives the job, stage, instruction, and image paths, and returns a validated `Report`. The interface settings and connection diagnostics currently remain specific to Codex.
