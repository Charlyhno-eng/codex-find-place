"""Local application preferences; never expose the user's Codex configuration."""
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from .models import Strict

EFFORTS = ["minimal", "low", "medium", "high", "xhigh", "max", "ultra"]


class Settings(Strict):
    model: str = Field(min_length=1, max_length=100)
    reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh", "max", "ultra"] = "high"
    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_rounds(cls, value):
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if k != "research_rounds"}
        return value


    @field_validator("model")
    @classmethod
    def valid_model(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", value):
            raise ValueError("Invalid model identifier")
        return value


def catalog():
    home = Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex")))
    models, configured = [], {}
    try:
        config = tomllib.loads((home / "config.toml").read_text())
        configured = {k: config.get(k) for k in ("model", "model_reasoning_effort")}
    except (OSError, ValueError):
        pass
    try:
        for m in json.loads((home / "models_cache.json").read_text()).get("models", []):
            if m.get("visibility") != "list" or not m.get("slug"):
                continue
            models.append({"id": m["slug"], "name": m.get("display_name", m["slug"]),
                "default_effort": m.get("default_reasoning_level"),
                "efforts": [r["effort"] for r in m.get("supported_reasoning_levels", []) if r.get("effort") in EFFORTS]})
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return models, configured


def load_settings(data):
    try:
        return Settings.model_validate_json((data / "settings.json").read_text())
    except (OSError, ValueError):
        models, config = catalog()
        model = os.getenv("OSINT_CODEX_MODEL") or config.get("model") or (models[0]["id"] if models else None)
        if not model:
            raise ValueError("No model detected. Open Codex to refresh its local catalog.")
        known = next((m for m in models if m["id"] == model), None)
        efforts = known["efforts"] if known else []
        preferred = config.get("model_reasoning_effort")
        effort = preferred if preferred in efforts else "high" if "high" in efforts else efforts[0] if efforts else "high"
        return Settings(model=model, reasoning_effort=effort)


def settings_payload(data):
    models, _ = catalog()
    return {"settings": load_settings(data).model_dump(), "models": models,
        "catalog_source": "Local Codex cache; availability depends on your account.", "efforts": []}


def save_settings(data, settings):
    models, _ = catalog()
    known = next((m for m in models if m["id"] == settings.model), None)
    if not known:
        raise ValueError("This model is not in the local Codex catalog. Refresh Codex and try again.")
    if settings.reasoning_effort not in known["efforts"]:
        raise ValueError("This model does not offer this reasoning level in the Codex catalog.")
    data.mkdir(parents=True, exist_ok=True)
    path = data / "settings.tmp"
    path.write_text(settings.model_dump_json(), encoding="utf-8")
    path.replace(data / "settings.json")
