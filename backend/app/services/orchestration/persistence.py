from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from app.core.config import settings

StateType = TypeVar("StateType", bound=BaseModel)


class StatePersistence:
    def __init__(self, base_path: str | None = None) -> None:
        self.base_path = Path(base_path or settings.state_storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _state_path(self, namespace: str, identifier: str) -> Path:
        namespace_dir = self.base_path / namespace
        namespace_dir.mkdir(parents=True, exist_ok=True)
        return namespace_dir / f"{identifier}.json"

    def save(self, namespace: str, identifier: str, state: BaseModel) -> Path:
        path = self._state_path(namespace, identifier)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, namespace: str, identifier: str, state_cls: type[StateType]) -> StateType | None:
        path = self._state_path(namespace, identifier)
        if not path.exists():
            return None
        return state_cls.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def delete(self, namespace: str, identifier: str) -> None:
        path = self._state_path(namespace, identifier)
        if path.exists():
            path.unlink()
