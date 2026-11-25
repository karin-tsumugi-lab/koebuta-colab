#!/usr/bin/env python3
"""Colab-side worker for Yomibuta Drama-3-Japanese narration synthesis.

Safety & recovery guarantees:
- Writes `status="started"` manifest with `job_id`, `nonce`, and `plan_signature` immediately at startup.
- Persists per-utterance completion (`takes_state.json`) incrementally and reuses verified WAVs on resume.
- Preserves `plan.json`, `manifest.json`, and generated utterance WAVs on failure for inspection/recovery.
- Enforces the host's deadline (`YOMIBUTA_REMOTE_TIMEOUT`) across downloads and synthesis calls.
"""
from __future__ import annotations

import gzip
import importlib.metadata
import json
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO

from yomibuta_cli.audio import assemble_wavs, pack_segments_zip, wav_info
from yomibuta_cli.core import (
    CONTRACT,
    DEFAULT_SAMPLE_RATE,
    DEFAULT_SGLANG_PIP_SPEC,
    GGUF_SPECS,
    PREBUILT_BINARY_SHA256,
    atomic_json,
    digest,
    file_hash,
    load_json,
)

OUT_CHUNK_BYTES = 40 * 1024 * 1024  # 40 MiB per download chunk
MAX_SAFE_SEED = 9007199254740991


class _DeadlineExceeded(RuntimeError):
    """Raised strictly when the overall job deadline (`YOMIBUTA_REMOTE_TIMEOUT`) is exhausted."""


def _remaining_sec(deadline: float, cap: float) -> float:
    rem = deadline - time.monotonic()
    if rem <= 1.0:
        raise _DeadlineExceeded("遠隔ワーカーの実行制限時間（timeout）を超過しました")
    return min(cap, rem)


def _reassemble_if_chunked(target_path: Path, num_parts: int) -> None:
    if num_parts <= 0:
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("wb") as dst:
        for idx in range(num_parts):
            part_path = Path(f"{target_path}.part{idx:02d}")
            if not part_path.is_file():
                raise RuntimeError(f"アップロードチャンクが見つかりません: {part_path}")
            with part_path.open("rb") as src:
                shutil.copyfileobj(src, dst)
            part_path.unlink(missing_ok=True)


def _split_for_download(src_path: Path, remote_prefix: str) -> list[dict]:
    """Split output artifact into bounded chunks for reliable download (replacing only this job's chunks)."""
    for old in Path(remote_prefix).parent.glob(f"{Path(remote_prefix).name}.part*"):
        old.unlink(missing_ok=True)
    chunks: list[dict] = []
    idx = 0
    with src_path.open("rb") as src:
        while True:
            buf = src.read(OUT_CHUNK_BYTES)
            if not buf:
                break
            cpath = Path(f"{remote_prefix}.part{idx:03d}")
            cpath.write_bytes(buf)
            chunks.append({"remote": str(cpath), "bytes": len(buf), "sha256": file_hash(cpath)})
            idx += 1
    return chunks


def _ensure_speech_binary(runtime_root: Path, bin_gz_path: Path, bin_parts: int) -> Path:
    bin_dir = runtime_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    speech_bin = bin_dir / "speech"
    stamp = bin_dir / "speech.sha256"

    if speech_bin.is_file() and stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == PREBUILT_BINARY_SHA256:
        for idx in range(bin_parts):
            Path(f"{bin_gz_path}.part{idx:02d}").unlink(missing_ok=True)
        print("PROGRESS Reusing verified prebuilt speech binary.", flush=True)
        return speech_bin

    if bin_parts > 0:
        print(f"PROGRESS Reassembling prebuilt binary from {bin_parts} chunks...", flush=True)
        _reassemble_if_chunked(bin_gz_path, bin_parts)

    if not bin_gz_path.is_file():
        raise RuntimeError(f"事前ビルド済みバイナリが見つかりません: {bin_gz_path}")
    actual_gz_sha = file_hash(bin_gz_path)
    if actual_gz_sha != PREBUILT_BINARY_SHA256:
        raise RuntimeError(
            f"事前ビルド済みバイナリのSHA256が一致しません "
            f"(期待={PREBUILT_BINARY_SHA256}, 実体={actual_gz_sha})"
        )

    print("PROGRESS Unpacking prebuilt speech binary...", flush=True)
    tmp_bin = bin_dir / "speech.tmp"
    with gzip.open(bin_gz_path, "rb") as src, tmp_bin.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    tmp_bin.chmod(tmp_bin.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(tmp_bin, speech_bin)
    stamp.write_text(PREBUILT_BINARY_SHA256 + "\n", encoding="utf-8")
    bin_gz_path.unlink(missing_ok=True)
    return speech_bin


def _ensure_gguf_model(runtime_root: Path, quant: str) -> Path:
    spec = GGUF_SPECS[quant]
    model_dir = runtime_root / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    gguf_link = model_dir / spec["gguf_file"]
    sidecar_link = model_dir / spec["sidecar_file"]
    stamp = model_dir / f"{spec['gguf_file']}.sha256"
    expected_sha = spec.get("gguf_sha256")

    if (
        gguf_link.is_file()
        and sidecar_link.is_file()
        and (not expected_sha or (stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == expected_sha))
    ):
        print(f"PROGRESS Reusing verified GGUF model: {spec['gguf_file']}", flush=True)
        return gguf_link

    print(f"PROGRESS Downloading GGUF model ({quant}): {spec['gguf_file']}...", flush=True)
    from huggingface_hub import hf_hub_download

    gguf_cached = Path(hf_hub_download(spec["repo"], spec["gguf_file"]))
    sidecar_cached = Path(hf_hub_download(spec["repo"], spec["sidecar_file"]))
    if not isinstance(load_json(sidecar_cached), dict):
        raise RuntimeError(f"GGUF sidecar JSON が不正です: {sidecar_cached}")
    if expected_sha:
        print("PROGRESS Verifying GGUF SHA-256...", flush=True)
        actual_sha = file_hash(gguf_cached)
        if actual_sha != expected_sha:
            raise RuntimeError(f"GGUFのSHA256が一致しません (期待={expected_sha}, 実体={actual_sha})")
        stamp.write_text(expected_sha + "\n", encoding="utf-8")

    if gguf_link.exists() or gguf_link.is_symlink():
        gguf_link.unlink()
    if sidecar_link.exists() or sidecar_link.is_symlink():
        sidecar_link.unlink()
    os.symlink(gguf_cached, gguf_link)
    os.symlink(sidecar_cached, sidecar_link)
    return gguf_link


def _prepare_voice_profiles(
    runtime_root: Path,
    job_name: str,
    speech_bin: Path,
    model_path: Path,
    voices: dict[str, list[dict]],
    used_profiles: set[str],
    voice_parts_map: dict[str, int],
    deadline: float,
) -> dict[str, Path]:
    cache_dir = runtime_root / "voice_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    built: dict[str, Path] = {}

    for profile, clips in voices.items():
        if profile not in used_profiles:
            continue
        cache_key = digest(
            {
                "binary_sha256": PREBUILT_BINARY_SHA256,
                "model_file": model_path.name,
                "profile": profile,
                "clips": [{"sha256": c["wav_sha256"], "transcript": c["transcript"]} for c in clips],
            }
        )[:24]
        out_voice = cache_dir / f"{profile}_{cache_key}.voice.gguf"
        tmp_voice = cache_dir / f"{profile}_{cache_key}.tmp.voice.gguf"

        staged_wavs: list[Path] = []
        for idx, clip in enumerate(clips):
            key = f"{profile}_{idx}"
            flat_wav = Path(f"/content/yomibuta_{job_name}_voice_{key}.wav")
            parts = int(voice_parts_map.get(key, 0))
            if parts > 0:
                _reassemble_if_chunked(flat_wav, parts)
            staged_wavs.append(flat_wav)

        if out_voice.is_file() and out_voice.stat().st_size > 0:
            for w in staged_wavs:
                w.unlink(missing_ok=True)
            print(f"PROGRESS Reusing cached voice profile: {profile}", flush=True)
            built[profile] = out_voice
            continue

        cmd = [str(speech_bin), "voice", str(model_path)]
        for clip, local_wav in zip(clips, staged_wavs):
            if not local_wav.is_file():
                raise RuntimeError(f"アップロード済み参照WAVが見つかりません: {local_wav}")
            if file_hash(local_wav) != clip["wav_sha256"]:
                raise RuntimeError(f"参照WAVのSHA256が一致しません: {local_wav}")
            cmd.append(str(local_wav))
        cmd.append(str(tmp_voice))
        for clip in clips:
            cmd.extend(["--transcript", clip["transcript"]])

        print(f"PROGRESS Extracting voice profile '{profile}' ({len(clips)} clip(s))...", flush=True)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=_remaining_sec(deadline, 300.0),
            )
            if proc.returncode != 0 or not tmp_voice.is_file() or tmp_voice.stat().st_size == 0:
                raise RuntimeError(f"speech voice 失敗 ({profile}): {proc.stderr[-1000:]}")
            os.replace(tmp_voice, out_voice)
        finally:
            tmp_voice.unlink(missing_ok=True)
            for w in staged_wavs:
                w.unlink(missing_ok=True)
        built[profile] = out_voice

    return built


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _ResidentSpeechServer:
    def __init__(
        self,
        speech_bin: Path,
        model_path: Path,
        voice_files: dict[str, Path],
        seed: int,
        eo: dict,
        log_path: Path,
    ):
        self.speech_bin = speech_bin
        self.model_path = model_path
        self.voice_files = voice_files
        self.seed = seed
        self.eo = eo
        self.log_path = log_path
        self.port = _find_free_port()
        self.proc: subprocess.Popen | None = None
        self._log_fh: IO[str] | None = None
        self.model_name = "Drama-3-Japanese"
        self.env = {
            **os.environ,
            "SPEECH_DRAMA3_MAX_PAUSE_FRAMES": str(eo["max_pause_frames"]),
        }

    def start(self, deadline: float, startup_timeout: float = 120.0) -> bool:
        self.stop()
        self.port = _find_free_port()
        cmd = [
            str(self.speech_bin), "serve", str(self.model_path),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "--no-warmup",
            f"--experts-on-cpu={'true' if self.eo['experts_on_cpu'] else 'false'}",
            "--top-k", str(self.eo["top_k"]),
            "--top-p", str(self.eo["top_p"]),
            "--temperature", str(self.eo["temperature"]),
            "--max-seconds", str(self.eo["max_seconds"]),
            "--seed", str(self.seed),
        ]
        for name, vpath in self.voice_files.items():
            cmd.extend(["--add-voice", f"{name}={vpath}"])

        print(f"PROGRESS Starting resident speech server on 127.0.0.1:{self.port}...", flush=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_fh = self.log_path.open("a", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, env=self.env, stdout=subprocess.DEVNULL, stderr=self._log_fh, text=True)
        wait_until = time.monotonic() + _remaining_sec(deadline, startup_timeout)
        health_url = f"http://127.0.0.1:{self.port}/health"
        while time.monotonic() < wait_until:
            if self.proc.poll() is not None:
                self.stop()
                return False
            try:
                with urllib.request.urlopen(health_url, timeout=2) as resp:
                    if resp.status == 200:
                        try:
                            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/v1/models", timeout=5) as mr:
                                data = json.loads(mr.read().decode("utf-8"))
                                items = data.get("data") or []
                                if items and isinstance(items[0], dict) and items[0].get("id"):
                                    self.model_name = items[0]["id"]
                        except Exception:
                            pass
                        print(f"PROGRESS Resident server ready (model={self.model_name}).", flush=True)
                        return True
            except Exception:
                time.sleep(0.5)
        self.stop()
        return False

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def synthesize(self, prompt: str, voice_profile: str, out_wav: Path, seed: int, deadline: float) -> bool:
        if not self.is_alive():
            return False
        url = f"http://127.0.0.1:{self.port}/v1/audio/speech"
        payload = json.dumps(
            {
                "model": self.model_name,
                "input": prompt,
                "voice": voice_profile,
                "seed": int(seed),
                "response_format": "wav",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=_remaining_sec(deadline, 300.0)) as resp:
                if resp.status != 200:
                    return False
                raw = resp.read()
            if not raw.startswith(b"RIFF"):
                return False
            out_wav.write_bytes(raw)
            return True
        except _DeadlineExceeded:
            raise
        except Exception as exc:
            print(f"WARNING Resident server request failed ({exc}); falling back to CLI.", flush=True)
            return False

    def stop(self) -> None:
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
            self.proc = None
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None


class _OfficialSglangServer:
    """Resident SGLang-Omni server adapter for official unquantized Drama-3-Japanese on A100/G4."""

    def __init__(self, model_id: str, job_dir: Path, seed: int, eo: dict, quant: str | None = None):
        self.model_id = model_id
        self.log_path = job_dir / "sgl_omni_serve.log"
        self.seed = seed
        self.eo = eo
        self.quant = quant
        self.port = _find_free_port()
        self.proc: subprocess.Popen | None = None
        self._log_fh: IO[str] | None = None

    def _ensure_installed(self, deadline: float) -> str:
        exe = shutil.which("sgl-omni")
        if exe:
            return exe
        pip_spec = str(self.eo.get("sglang_pip_spec") or DEFAULT_SGLANG_PIP_SPEC).strip()
        print(f"PROGRESS Installing {pip_spec} for official Drama-3 backend...", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--", pip_spec],
            check=True,
            timeout=_remaining_sec(deadline, 900.0),
        )
        exe = shutil.which("sgl-omni")
        if not exe:
            raise RuntimeError("sgl-omni のインストール後に実行ファイルが見つかりません")
        return exe

    def is_healthy(self) -> bool:
        if self.proc is None or self.proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start(self, deadline: float, startup_timeout: float = 420.0) -> bool:
        self.stop()
        exe = self._ensure_installed(deadline)
        self.port = _find_free_port()
        cmd = [exe, "serve", "--model-path", self.model_id, "--host", "127.0.0.1", "--port", str(self.port)]
        if self.quant == "fp8":
            cmd.extend(["--quantization", "fp8"])
        print(f"PROGRESS Starting official sgl-omni server ({self.model_id}) on 127.0.0.1:{self.port}...", flush=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_fh = self.log_path.open("a", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=self._log_fh, text=True)
        wait_until = time.monotonic() + _remaining_sec(deadline, startup_timeout)
        while time.monotonic() < wait_until:
            if self.proc.poll() is not None:
                self.stop()
                return False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as resp:
                    if resp.status == 200:
                        print("PROGRESS Official sgl-omni server ready.", flush=True)
                        return True
            except Exception:
                time.sleep(1.0)
        self.stop()
        return False

    def synthesize(self, prompt: str, voice_clips: list[dict], out_wav: Path, seed: int, deadline: float) -> bool:
        if self.proc is None or self.proc.poll() is not None:
            return False
        body: dict = {
            "model": self.model_id,
            "input": prompt,
            "voice": "default",
            "response_format": "wav",
            "stream": False,
            "temperature": float(self.eo["temperature"]),
            "top_p": float(self.eo["top_p"]),
            "top_k": int(self.eo["top_k"]),
            "max_new_tokens": max(64, int(round(float(self.eo["max_seconds"]) * 25))),
            "seed": int(seed),
        }
        if self.eo.get("repetition_penalty") is not None:
            body["repetition_penalty"] = float(self.eo["repetition_penalty"])
        if voice_clips:
            body["references"] = [
                {
                    "audio_path": str(Path(clip["local_wav"]).resolve()),
                    "text": clip["transcript"],
                }
                for clip in voice_clips
            ]
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1/audio/speech",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_remaining_sec(deadline, 300.0)) as resp:
                if resp.status != 200:
                    return False
                raw = resp.read()
            if not raw.startswith(b"RIFF"):
                return False
            out_wav.write_bytes(raw)
            return True
        except _DeadlineExceeded:
            raise
        except Exception as exc:
            print(f"WARNING Official server request failed ({exc}).", flush=True)
            return False

    def stop(self) -> None:
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
            self.proc = None
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except Exception:
                pass
            self._log_fh = None


def _synthesize_cli(
    speech_bin: Path,
    model_path: Path,
    voice_files: dict[str, Path],
    prompt: str,
    voice_profile: str,
    seed: int,
    eo: dict,
    out_wav: Path,
    deadline: float,
) -> tuple[bool, bool]:
    """Run single-shot `speech tts`. Returns `(ok, hit_max_seconds)`."""
    env = {**os.environ, "SPEECH_DRAMA3_MAX_PAUSE_FRAMES": str(eo["max_pause_frames"])}
    cmd = [
        str(speech_bin), "tts", str(model_path),
        f"--experts-on-cpu={'true' if eo['experts_on_cpu'] else 'false'}",
        "--top-k", str(eo["top_k"]),
        "--top-p", str(eo["top_p"]),
        "--temperature", str(eo["temperature"]),
        "--max-seconds", str(eo["max_seconds"]),
        "--seed", str(seed),
    ]
    if voice_profile != "none":
        cmd.extend(["--add-voice", f"{voice_profile}={voice_files[voice_profile]}"])
    # `--` prevents prompts starting with `-` from being parsed as CLI flags (`speech tts --help`).
    cmd.extend(["--voice", voice_profile, "-o", str(out_wav), "--", prompt])

    proc = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_remaining_sec(deadline, 600.0),
    )
    if proc.returncode == 0 and out_wav.is_file():
        return True, False
    # `speech tts` exits with code 3 when generation hit `--max-seconds`
    if proc.returncode == 3 and out_wav.is_file():
        return True, True
    out_wav.unlink(missing_ok=True)
    print(f"WARNING speech tts failed (rc={proc.returncode}): {proc.stderr[-400:]}", flush=True)
    return False, False


def _restore_take_warnings(rec: dict, warnings_out: list[dict]) -> None:
    sid = rec.get("segment_id")
    if rec.get("early_eos_suspected"):
        warnings_out.append(
            {
                "code": "W_EARLY_EOS_SUSPECTED",
                "segment_id": sid,
                "seconds": rec.get("seconds"),
                "min_expected_sec": rec.get("min_expected_sec"),
            }
        )
    if rec.get("max_seconds_truncated"):
        warnings_out.append(
            {
                "code": "W_MAX_SECONDS_TRUNCATED",
                "segment_id": sid,
                "seconds": rec.get("seconds"),
                "max_seconds": rec.get("max_seconds"),
            }
        )


def _run_utterance_with_retries(
    *,
    idx: int,
    total: int,
    row: dict,
    audio_dir: Path,
    sample_rate: int,
    max_seconds: float,
    attempt_fn,
) -> tuple[dict, list[dict]]:
    """Shared retry + WAV format validation + early-EOS / max_seconds detection across backends."""
    sid = row["segment_id"]
    filename = f"{sid}_{row['fingerprint'][:12]}.wav"
    out_wav = audio_dir / filename
    req = row["request"]
    spoken_chars = int(row["spoken_chars"])
    min_expected_sec = round(spoken_chars * 0.12, 3) if spoken_chars >= 6 else 0.0
    max_attempts = 3

    best_wav_bytes: bytes | None = None
    best_meta: dict | None = None
    best_mode = "serve"
    best_elapsed = 0.0
    best_hit_max = False
    attempts_used = 0
    warnings: list[dict] = []

    for attempt in range(max_attempts):
        attempts_used = attempt + 1
        try_seed = (int(req["seed"]) + attempt * 9973) % (MAX_SAFE_SEED + 1)
        t0 = time.monotonic()
        if attempt == 0:
            print(f"PROGRESS [{idx}/{total}] Synthesizing {sid} ({spoken_chars} chars)...", flush=True)
        else:
            print(
                f"PROGRESS [{idx}/{total}] Retrying {sid} (attempt {attempts_used}/{max_attempts}, seed={try_seed})...",
                flush=True,
            )

        tmp_wav = audio_dir / f"{sid}_try{attempt}.wav"
        attempt_res = attempt_fn(attempt, try_seed, tmp_wav)
        if isinstance(attempt_res, tuple):
            used_mode, cli_hit_max = attempt_res
        else:
            used_mode, cli_hit_max = attempt_res, False
        if used_mode is None:
            tmp_wav.unlink(missing_ok=True)
            continue

        elapsed = round(time.monotonic() - t0, 3)
        try:
            meta = wav_info(tmp_wav)
        except Exception as exc:
            tmp_wav.unlink(missing_ok=True)
            print(f"WARNING {sid}: invalid WAV output ({exc}); retrying.", flush=True)
            continue
        if meta["sample_rate"] != sample_rate or meta["channels"] != 1 or meta["sampwidth"] != 2:
            tmp_wav.unlink(missing_ok=True)
            raise RuntimeError(f"{sid}: 予期しないWAV形式 {meta}")

        hit_max = cli_hit_max or (max_seconds > 0 and meta["seconds"] >= max_seconds - 0.15)
        # Prefer a non-truncated take over a max_seconds-truncated runaway take
        take_better = (
            best_meta is None
            or (best_hit_max and not hit_max)
            or (best_hit_max == hit_max and meta["seconds"] > best_meta["seconds"])
        )
        if take_better:
            best_wav_bytes = tmp_wav.read_bytes()
            best_meta = meta
            best_mode = used_mode
            best_elapsed = elapsed
            best_hit_max = hit_max
        tmp_wav.unlink(missing_ok=True)

        if meta["seconds"] >= min_expected_sec and not hit_max:
            break

    if best_wav_bytes is None or best_meta is None:
        raise RuntimeError(f"発話推論が全試行失敗しました: {sid}")

    out_wav.write_bytes(best_wav_bytes)
    early_eos = min_expected_sec > 0 and best_meta["seconds"] < min_expected_sec
    rec_clean = {
        "segment_id": sid,
        "filename": filename,
        "pause_after_ms": int(row["pause_after_ms"]),
        "spoken_chars": spoken_chars,
        "min_expected_sec": min_expected_sec,
        "max_seconds": max_seconds,
        "early_eos_suspected": early_eos,
        "max_seconds_truncated": best_hit_max,
        "mode": best_mode,
        "attempts": attempts_used,
        "elapsed_sec": best_elapsed,
        "rtfx": round(best_meta["seconds"] / best_elapsed, 3) if best_elapsed > 0 else 0.0,
        **best_meta,
    }
    _restore_take_warnings(rec_clean, warnings)
    return rec_clean, warnings


def _load_saved_takes(state_path: Path, audio_dir: Path, sample_rate: int) -> dict[str, dict]:
    if not state_path.is_file():
        return {}
    try:
        raw = load_json(state_path)
        if not isinstance(raw, dict):
            return {}
        reusable: dict[str, dict] = {}
        for filename, rec in raw.items():
            if not isinstance(rec, dict):
                continue
            wav_path = audio_dir / filename
            if not wav_path.is_file():
                continue
            actual = wav_info(wav_path)
            if (
                actual["sha256"] == rec.get("sha256")
                and actual["frames"] == rec.get("frames")
                and actual["sample_rate"] == sample_rate
                and actual["channels"] == 1
                and actual["sampwidth"] == 2
            ):
                reusable[filename] = rec
        return reusable
    except Exception:
        return {}


def main() -> int:
    started_all = time.monotonic()
    remote_timeout = float(os.environ.get("YOMIBUTA_REMOTE_TIMEOUT", "1800") or "1800")
    deadline = started_all + remote_timeout

    runtime_root = Path(os.environ.get("YOMIBUTA_RUNTIME_ROOT", "/content/yomibuta_runtime"))
    job_dir = Path(os.environ.get("YOMIBUTA_REMOTE_JOB_DIR", "/content/yomibuta_job"))
    job_id = os.environ.get("YOMIBUTA_REMOTE_JOB_ID", job_dir.name)
    nonce = os.environ.get("YOMIBUTA_REMOTE_NONCE", "")
    plan_path = Path(os.environ.get("YOMIBUTA_REMOTE_PLAN", str(job_dir / "plan.json")))
    plan_parts = int(os.environ.get("YOMIBUTA_REMOTE_PLAN_PARTS", "0") or "0")
    bin_gz_path = Path(os.environ.get("YOMIBUTA_REMOTE_BIN_GZ", str(runtime_root / "speech_cuda13_sm75_89.gz")))
    bin_parts = int(os.environ.get("YOMIBUTA_REMOTE_BIN_PARTS", "0") or "0")
    voice_parts_map = json.loads(os.environ.get("YOMIBUTA_REMOTE_VOICE_PARTS", "{}") or "{}")
    manifest_remote = Path(os.environ.get("YOMIBUTA_REMOTE_MANIFEST", f"/content/yomibuta_{job_id}_manifest.json"))
    artifact_prefix = os.environ.get("YOMIBUTA_REMOTE_ARTIFACT_PREFIX", f"/content/yomibuta_{job_id}")

    job_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = job_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    takes_state_path = job_dir / "takes_state.json"

    manifest: dict = {
        "contract": CONTRACT,
        "job_id": job_id,
        "nonce": nonce,
        "plan_signature": None,
        "status": "started",
        "takes": [],
        "warnings": [],
        "errors": [],
        "download_chunks": {},
    }

    def _flush_manifest() -> None:
        atomic_json(job_dir / "manifest.json", manifest)
        atomic_json(manifest_remote, manifest)

    # CRITICAL (Review #1): Immediately overwrite any stale `complete` manifest before doing work
    _flush_manifest()

    try:
        if plan_parts > 0:
            _reassemble_if_chunked(plan_path, plan_parts)
        plan = load_json(plan_path)
        if not isinstance(plan, dict) or plan.get("contract") != CONTRACT:
            raise ValueError("無効な実行計画契約です")
        # Persist a copy inside job_dir so failed/interrupted jobs retain their exact plan
        atomic_json(job_dir / "plan.json", plan)

        manifest["plan_signature"] = plan["plan_signature"]
        manifest["environment"] = {
            "python": platform.python_version(),
            "backend": plan["settings"].get("backend", "speech_cpp_gguf"),
        }
        manifest["status"] = "running"
        _flush_manifest()

        settings = plan["settings"]
        requests = plan["requests"]
        sample_rate = int(settings.get("sampleRate", DEFAULT_SAMPLE_RATE))
        eo = settings["engineOptions"]
        max_seconds = float(eo["max_seconds"])
        seed = int(settings["seed"])
        backend = settings.get("backend", "speech_cpp_gguf")
        used_profiles = {
            r["request"]["voice_profile"]
            for r in requests
            if r["request"].get("voice_profile") and r["request"]["voice_profile"] != "none"
        }

        saved_takes = _load_saved_takes(takes_state_path, audio_dir, sample_rate)
        takes: list[dict] = []

        # Determine whether all requested utterances are already cached from a prior interrupted run
        need_synthesis = any(f"{r['segment_id']}_{r['fingerprint'][:12]}.wav" not in saved_takes for r in requests)

        if not need_synthesis:
            print("PROGRESS All utterances already synthesized and verified; reusing cached takes.", flush=True)
            for idx_b in range(bin_parts):
                Path(f"{bin_gz_path}.part{idx_b:02d}").unlink(missing_ok=True)
            for stale_v in Path("/content").glob(f"yomibuta_{job_id}_voice_*.wav*"):
                stale_v.unlink(missing_ok=True)
            for row in requests:
                sid = row["segment_id"]
                filename = f"{sid}_{row['fingerprint'][:12]}.wav"
                rec = {**saved_takes[filename], "mode": "reused", "pause_after_ms": int(row["pause_after_ms"])}
                _restore_take_warnings(rec, manifest["warnings"])
                takes.append({**rec, "path": str(audio_dir / filename)})
                manifest["takes"].append(rec)
        elif backend == "official":
            staged_refs: dict[str, list[dict]] = {}
            official_srv = _OfficialSglangServer(settings["ttsModel"], job_dir, seed, eo, settings.get("quant"))
            try:
                for profile, clips in (plan.get("voices") or {}).items():
                    if profile not in used_profiles:
                        continue
                    staged_refs[profile] = []
                    for idx_c, clip in enumerate(clips):
                        key = f"{profile}_{idx_c}"
                        flat_wav = Path(f"/content/yomibuta_{job_id}_voice_{key}.wav")
                        parts = int(voice_parts_map.get(key, 0))
                        if parts > 0:
                            _reassemble_if_chunked(flat_wav, parts)
                        if not flat_wav.is_file() or file_hash(flat_wav) != clip["wav_sha256"]:
                            raise RuntimeError(f"参照WAVの検証に失敗しました: {flat_wav}")
                        staged_refs[profile].append({"local_wav": str(flat_wav), "transcript": clip["transcript"]})

                if not official_srv.start(deadline):
                    raise RuntimeError(f"公式推論サーバーの起動に失敗しました（ログ: {official_srv.log_path}）")
                try:
                    sgl_ver = importlib.metadata.version("sglang-omni")
                except importlib.metadata.PackageNotFoundError:
                    sgl_ver = "unknown"
                manifest["environment"]["sglang_omni_version"] = sgl_ver
                manifest["environment"]["sglang_pip_spec"] = eo.get("sglang_pip_spec")
                _flush_manifest()

                official_restarts = 0
                total = len(requests)
                for idx, row in enumerate(requests, 1):
                    sid = row["segment_id"]
                    filename = f"{sid}_{row['fingerprint'][:12]}.wav"
                    out_wav = audio_dir / filename
                    if filename in saved_takes:
                        print(f"PROGRESS [{idx}/{total}] Reusing verified {sid}.", flush=True)
                        rec = {**saved_takes[filename], "mode": "reused", "pause_after_ms": int(row["pause_after_ms"])}
                        _restore_take_warnings(rec, manifest["warnings"])
                        takes.append({**rec, "path": str(out_wav)})
                        manifest["takes"].append(rec)
                        continue

                    req = row["request"]
                    clips_for_req = staged_refs.get(req["voice_profile"], []) if req["voice_profile"] != "none" else []

                    def _official_attempt(_attempt: int, try_seed: int, tmp_wav: Path) -> tuple[str | None, bool]:
                        nonlocal official_restarts
                        ok = official_srv.synthesize(req["prompt"], clips_for_req, tmp_wav, try_seed, deadline)
                        if ok:
                            return "official", False
                        if not official_srv.is_healthy() and official_restarts < 1:
                            official_restarts += 1
                            official_srv.start(deadline)
                        return None, False

                    rec_clean, utt_warns = _run_utterance_with_retries(
                        idx=idx,
                        total=total,
                        row=row,
                        audio_dir=audio_dir,
                        sample_rate=sample_rate,
                        max_seconds=max_seconds,
                        attempt_fn=_official_attempt,
                    )
                    manifest["warnings"].extend(utt_warns)
                    saved_takes[filename] = rec_clean
                    atomic_json(takes_state_path, saved_takes)
                    takes.append({**rec_clean, "path": str(out_wav)})
                    manifest["takes"].append(rec_clean)
                    _flush_manifest()
            finally:
                official_srv.stop()
                for clips in staged_refs.values():
                    for c in clips:
                        Path(c["local_wav"]).unlink(missing_ok=True)
                for leftover in Path("/content").glob(f"yomibuta_{job_id}_voice_*.wav*"):
                    leftover.unlink(missing_ok=True)
        else:
            speech_bin = _ensure_speech_binary(runtime_root, bin_gz_path, bin_parts)
            model_path = _ensure_gguf_model(runtime_root, settings["quant"])
            manifest["environment"]["speech_binary_sha256"] = PREBUILT_BINARY_SHA256
            manifest["environment"]["gguf_file"] = model_path.name
            _flush_manifest()

            voice_files = _prepare_voice_profiles(
                runtime_root,
                job_id,
                speech_bin,
                model_path,
                plan.get("voices") or {},
                used_profiles,
                voice_parts_map,
                deadline,
            )

            server = _ResidentSpeechServer(speech_bin, model_path, voice_files, seed, eo, job_dir / "speech_serve.log")
            # Review N-01: Bound server startup attempts so an unstartable/hung server never spins 120s per retry!
            serve_disabled = not server.start(deadline)
            serve_restarts = 0

            try:
                total = len(requests)
                for idx, row in enumerate(requests, 1):
                    sid = row["segment_id"]
                    filename = f"{sid}_{row['fingerprint'][:12]}.wav"
                    out_wav = audio_dir / filename
                    if filename in saved_takes:
                        print(f"PROGRESS [{idx}/{total}] Reusing verified {sid}.", flush=True)
                        rec = {**saved_takes[filename], "mode": "reused", "pause_after_ms": int(row["pause_after_ms"])}
                        _restore_take_warnings(rec, manifest["warnings"])
                        takes.append({**rec, "path": str(out_wav)})
                        manifest["takes"].append(rec)
                        continue

                    req = row["request"]
                    req_eo = req.get("engine_options") or eo

                    def _gguf_attempt(_attempt: int, try_seed: int, tmp_wav: Path) -> tuple[str | None, bool]:
                        nonlocal serve_disabled, serve_restarts
                        if not serve_disabled and not server.is_alive():
                            if serve_restarts < 1:
                                serve_restarts += 1
                                if not server.start(deadline):
                                    serve_disabled = True
                            else:
                                serve_disabled = True
                        if not serve_disabled and server.is_alive():
                            if server.synthesize(req["prompt"], req["voice_profile"], tmp_wav, try_seed, deadline):
                                return "serve", False
                            # Server failed mid-request; stop it to free VRAM before CLI fallback
                            server.stop()
                            if serve_restarts >= 1:
                                serve_disabled = True
                        ok_cli, hit_max_cli = _synthesize_cli(
                            speech_bin,
                            model_path,
                            voice_files,
                            req["prompt"],
                            req["voice_profile"],
                            try_seed,
                            req_eo,
                            tmp_wav,
                            deadline,
                        )
                        return ("cli" if ok_cli else None), hit_max_cli

                    rec_clean, utt_warns = _run_utterance_with_retries(
                        idx=idx,
                        total=total,
                        row=row,
                        audio_dir=audio_dir,
                        sample_rate=sample_rate,
                        max_seconds=max_seconds,
                        attempt_fn=_gguf_attempt,
                    )
                    manifest["warnings"].extend(utt_warns)
                    saved_takes[filename] = rec_clean
                    atomic_json(takes_state_path, saved_takes)
                    takes.append({**rec_clean, "path": str(out_wav)})
                    manifest["takes"].append(rec_clean)
                    _flush_manifest()
            finally:
                server.stop()

        result_wav = job_dir / "result.wav"
        segments_zip = job_dir / "segments.zip"
        norm_rms_db = settings.get("normalizeRmsDb")
        combined_meta = assemble_wavs(
            takes,
            result_wav,
            expected_sample_rate=sample_rate,
            normalize_rms_db=norm_rms_db,
        )
        zip_meta = pack_segments_zip(takes, segments_zip)

        manifest["download_chunks"] = {
            "result.wav": _split_for_download(result_wav, f"{artifact_prefix}_result"),
            "segments.zip": _split_for_download(segments_zip, f"{artifact_prefix}_segments"),
        }
        manifest["status"] = "complete"
        manifest["combined"] = {"file": "result.wav", **combined_meta}
        manifest["segments_zip"] = zip_meta
        manifest["elapsed_total_sec"] = round(time.monotonic() - started_all, 3)
        plan_path.unlink(missing_ok=True)

    except Exception as exc:
        manifest["status"] = "failed"
        manifest["elapsed_total_sec"] = round(time.monotonic() - started_all, 3)
        manifest["errors"].append({"error": str(exc), "traceback": traceback.format_exc()})
    finally:
        _flush_manifest()
        print(f"YOMIBUTA_STATUS {manifest['status']}", flush=True)
        print(f"YOMIBUTA_MANIFEST {manifest_remote}", flush=True)

    return 0 if manifest["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
