"""路径、作用域与检索参数。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_USER = "demo"


@dataclass(frozen=True)
class Settings:
    """一次运行用到的全部位置与阈值。"""

    root: Path = PACKAGE_ROOT
    corpus: Path = PACKAGE_ROOT / "corpus"
    runtime: Path = PACKAGE_ROOT / ".runtime"
    records: Path = PACKAGE_ROOT / "records"
    web: Path = PACKAGE_ROOT / "web"
    user: str = DEFAULT_USER
    top_k: int = 5
    candidates: int = 40
    max_chars: int = 900

    @property
    def database(self) -> Path:
        override = os.environ.get("DUBAN_DB")
        if override:
            return Path(override).expanduser().resolve()
        return self.runtime / "seekdb"

    @property
    def scope(self) -> str:
        override = os.environ.get("DUBAN_SCOPE")
        return override or f"duban:{self.user}"

    @property
    def query_log(self) -> Path:
        return self.records / "db" / "queries.jsonl"

    @property
    def memory_log(self) -> Path:
        return self.records / "memory" / "events.jsonl"

    def ensure_dirs(self) -> None:
        for path in (self.runtime, self.records, self.query_log.parent, self.memory_log.parent):
            path.mkdir(parents=True, exist_ok=True)


def settings_from_env() -> Settings:
    """按文档约定读取环境变量覆盖。"""

    overrides: dict[str, object] = {}
    if os.environ.get("DUBAN_USER"):
        overrides["user"] = os.environ["DUBAN_USER"]
    if os.environ.get("DUBAN_CORPUS"):
        overrides["corpus"] = Path(os.environ["DUBAN_CORPUS"]).expanduser().resolve()
    if os.environ.get("DUBAN_TOP_K"):
        overrides["top_k"] = max(1, int(os.environ["DUBAN_TOP_K"]))
    settings = Settings(**overrides)  # type: ignore[arg-type]
    settings.ensure_dirs()
    return settings
