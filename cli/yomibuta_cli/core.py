"""Core utilities, pinned artifact constants, and deterministic hashing."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

CONTRACT = "yomibuta-drama3-v1"

PREBUILT_BINARY_NAME = "speech_cuda13_sm75_89.gz"
PREBUILT_BINARY_SHA256 = "a2fe66e3de41eba835d48e2be650eb1f46f62ffd99a6000b8b03ea7871508b24"

DEFAULT_MODEL = "Aratako/Drama-3-Japanese"
DEFAULT_BACKEND = "speech_cpp_gguf"
DEFAULT_QUANT = "IQ3_XXS"
DEFAULT_SAMPLE_RATE = 44100

# Exact default PyPI spec for official backend reproducibility (override via engineOptions.sglang_pip_spec)
DEFAULT_SGLANG_PIP_SPEC = "sglang-omni[fishaudio]==0.1.0"

GGUF_SPECS = {
    "IQ3_XXS": {
        "repo": "StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf",
        "gguf_file": "Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf",
        "gguf_sha256": "98edad9311a64ea07524f54f24d6d6db77055a3fe7233f24d3bd4351626d9338",
        "sidecar_file": "Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf.json",
    },
}

_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def identifier(value: object, label: str, max_len: int = 64) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len or not _IDENT_RE.fullmatch(value):
        raise ValueError(f"{label} は1〜{max_len}文字の英数字・_・-で指定してください: {value!r}")
    return value


def load_json(path: str | Path, *, max_bytes: int = 32 * 1024 * 1024) -> object:
    def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        out: dict[str, object] = {}
        for k, v in items:
            if k in out:
                raise ValueError(f"重複したJSONキー: {k}")
            out[k] = v
        return out

    p = Path(path)
    if p.stat().st_size > max_bytes:
        raise ValueError(f"JSONは{max_bytes // (1024 * 1024)}MiB以内にしてください")
    return json.loads(
        p.read_text(encoding="utf-8-sig"),
        object_pairs_hook=_pairs,
        parse_constant=lambda v: (_ for _ in ()).throw(ValueError(f"非有限値: {v}")),
    )


def atomic_json(path: str | Path, value: object) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
