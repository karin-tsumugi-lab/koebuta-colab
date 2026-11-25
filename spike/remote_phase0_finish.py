#!/usr/bin/env python3
"""Finish Phase 0 on live L4 session: capture `speech info` & `worker --help`,
run VoiceClone with `--add-voice`, and strip-gzip standalone `speech` binary."""
import gzip
import os
import pathlib
import shutil
import subprocess

WORK = pathlib.Path("/content/yomibuta_phase0")
BIN = WORK / "speech.cpp/build/speech"
MODEL = WORK / "models/Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf"

# 1. Capture `speech info` and `speech worker --help`
info_txt = subprocess.check_output([str(BIN), "info", str(MODEL)], text=True)
worker_help = subprocess.run([str(BIN), "worker", "--help"], capture_output=True, text=True)
(WORK / "speech_info.txt").write_text(
    "=== speech info ===\n" + info_txt + "\n=== speech worker --help ===\n" + worker_help.stdout + worker_help.stderr,
    encoding="utf-8",
)

# 2. VoiceClone test using `--add-voice`
env = {**os.environ, "SPEECH_DRAMA3_MAX_PAUSE_FRAMES": "18"}
r = subprocess.run(
    [
        str(BIN), "tts", str(MODEL),
        "--experts-on-cpu=false",
        "--add-voice", f"spk={WORK / 'speaker.voice.gguf'}",
        "--voice", "spk",
        "--seed", "42",
        "-o", str(WORK / "spike_sample_02_clone.wav"),
        "窓の外では静かに雨が降り続いていた。[笑いながら]ねえ、これからどこへ向かうつもりなの？",
    ],
    env=env,
    capture_output=True,
    text=True,
)
print("CLONE_RC", r.returncode, flush=True)
print("CLONE_STDERR", r.stderr.strip(), flush=True)

# 3. Strip copy & gzip standalone binary
stripped = WORK / "speech_stripped"
shutil.copy2(BIN, stripped)
subprocess.run(["strip", "--strip-unneeded", str(stripped)], check=False)
gz_path = WORK / "speech_cuda13_sm75_89.gz"
with stripped.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
    shutil.copyfileobj(src, dst)
print("BIN_ORIG_BYTES", BIN.stat().st_size, "STRIPPED_BYTES", stripped.stat().st_size, "GZ_BYTES", gz_path.stat().st_size, flush=True)
