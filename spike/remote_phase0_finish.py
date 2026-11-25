#!/usr/bin/env python3
"""Finish Phase 0 on live L4 session: capture `speech info` & `worker --help`,
run VoiceClone with `--add-voice`, and strip-gzip standalone `speech` binary."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import time
import wave

WORK = pathlib.Path("/content/yomibuta_phase0")
BIN = WORK / "speech.cpp/build/speech"
MODEL = WORK / "models/Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf"


def main() -> int:
    # 1. Capture `speech info` and `speech worker --help`
    info_txt = subprocess.check_output([str(BIN), "info", str(MODEL)], text=True, timeout=60)
    worker_help = subprocess.run([str(BIN), "worker", "--help"], capture_output=True, text=True, timeout=30)
    (WORK / "speech_info.txt").write_text(
        "=== speech info ===\n" + info_txt + "\n=== speech worker --help ===\n" + worker_help.stdout + worker_help.stderr,
        encoding="utf-8",
    )

    # 2. VoiceClone test using `--add-voice`
    out_clone = WORK / "spike_sample_02_clone.wav"
    out_clone.unlink(missing_ok=True)
    env = {**os.environ, "SPEECH_DRAMA3_MAX_PAUSE_FRAMES": "18"}
    t0 = time.monotonic()
    r = subprocess.run(
        [
            str(BIN), "tts", str(MODEL),
            "--experts-on-cpu=false",
            "--add-voice", f"spk={WORK / 'speaker.voice.gguf'}",
            "--voice", "spk",
            "--seed", "42",
            "-o", str(out_clone),
            "--",
            "窓の外では静かに雨が降り続いていた。[笑いながら]ねえ、これからどこへ向かうつもりなの？",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    elapsed = round(time.monotonic() - t0, 3)
    print("CLONE_RC", r.returncode, flush=True)
    print("CLONE_STDERR", r.stderr.strip(), flush=True)

    # 3. Strip copy & gzip standalone binary
    stripped = WORK / "speech_stripped"
    gz_path = WORK / "speech_cuda13_sm75_89.gz"
    try:
        shutil.copy2(BIN, stripped)
        subprocess.run(["strip", "--strip-unneeded", str(stripped)], check=False, timeout=60)
        with stripped.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        stripped_bytes = stripped.stat().st_size
    finally:
        stripped.unlink(missing_ok=True)

    gz_sha = hashlib.sha256(gz_path.read_bytes()).hexdigest()
    clone_dur = 0.0
    if r.returncode == 0 and out_clone.is_file():
        with wave.open(str(out_clone), "rb") as wf:
            clone_dur = round(wf.getnframes() / wf.getframerate(), 3) if wf.getframerate() else 0.0
    (WORK / "finish_report.json").write_text(
        json.dumps(
            {
                "script_version": "phase0-finish-v2",
                "clone_returncode": r.returncode,
                "clone_elapsed_sec": elapsed,
                "clone_duration_sec": clone_dur,
                "clone_stderr": r.stderr[-1200:],
                "binary_gz_bytes": gz_path.stat().st_size,
                "binary_gz_sha256": gz_sha,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("BIN_ORIG_BYTES", BIN.stat().st_size, "STRIPPED_BYTES", stripped_bytes, "GZ_BYTES", gz_path.stat().st_size, flush=True)
    return 0 if (r.returncode == 0 and clone_dur > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
