#!/usr/bin/env python3
"""Colab-side Phase 0 spike for Drama-3-Japanese (speech.cpp v0.11.2 + fast patch + IQ3_XXS).

Measures targeted build time (`--target speech`), GGUF download time, VRAM usage,
CLI help/flags, VoiceDesign synthesis, and VoiceClone (`speech voice`) metrics.
Always writes `phase0_artifacts.zip` even if a later step fails.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import traceback
import wave
import zipfile
from pathlib import Path

WORK = Path(os.environ.get("YOMIBUTA_PHASE0_WORK", "/content/yomibuta_phase0"))
SPEECH_REPO = os.environ.get("YOMIBUTA_SPEECH_CPP_REPO", "https://github.com/nyosegawa/speech.cpp.git")
SPEECH_TAG = os.environ.get("YOMIBUTA_SPEECH_CPP_TAG", "v0.11.2")
GGUF_REPO = os.environ.get("YOMIBUTA_GGUF_REPO", "StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf")
_QUANT_PAT = os.environ.get("YOMIBUTA_QUANT_PATTERN", "IQ3_XXS")
GGUF_FILE = os.environ.get(
    "YOMIBUTA_GGUF_FILE",
    "Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf"
    if _QUANT_PAT == "IQ3_XXS"
    else f"Drama-35B-A3B-Japanese-v3-{_QUANT_PAT}.gguf",
)
PATCH_FILE = os.environ.get("YOMIBUTA_PATCH_FILE", "drama3-speechcpp-fast.patch")
CUDA_ARCHS = os.environ.get("YOMIBUTA_CUDA_ARCHS", "75;89")
TEST_TEXT = os.environ.get(
    "YOMIBUTA_TEST_TEXT",
    "[落ち着いた25歳の女性。親密な相手に耳元で優しく囁く。] [囁き]ねえ、そんなに急がないで。[吐息]ちゃんと、こっち見ててね。",
)
CLONE_TRANSCRIPT = os.environ.get(
    "YOMIBUTA_CLONE_TRANSCRIPT",
    "ねえ、そんなに急がないで。ちゃんと、こっち見ててね。",
)
CLONE_TEXT = os.environ.get(
    "YOMIBUTA_CLONE_TEXT",
    "窓の外では静かに雨が降り続いていた。[笑いながら]ねえ、これからどこへ向かうつもりなの？",
)
OUT_ZIP = Path(os.environ.get("YOMIBUTA_PHASE0_ZIP", "/content/yomibuta_phase0_artifacts.zip"))


def run_capture(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: int = 1200,
    extra_env: dict[str, str] | None = None,
) -> dict:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    elapsed = round(time.monotonic() - started, 3)
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "elapsed_sec": elapsed,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def query_gpu_mem_mb() -> int | None:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
            timeout=5,
        ).strip()
        vals = [int(line.strip()) for line in out.splitlines() if line.strip().isdigit()]
        return max(vals) if vals else None
    except Exception:
        return None


def run_with_vram_monitor(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: int = 600,
    extra_env: dict[str, str] | None = None,
) -> dict:
    peak_mb = query_gpu_mem_mb() or 0
    stop_event = threading.Event()

    def _poll() -> None:
        nonlocal peak_mb
        while not stop_event.is_set():
            val = query_gpu_mem_mb()
            if val is not None and val > peak_mb:
                peak_mb = val
            stop_event.wait(0.25)

    t = threading.Thread(target=_poll, daemon=True)
    t.start()
    try:
        res = run_capture(cmd, cwd=cwd, timeout=timeout, extra_env=extra_env)
    finally:
        stop_event.set()
        t.join(timeout=2)
    res["peak_vram_mb"] = peak_mb
    return res


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def analyze_wav(path: Path) -> dict:
    with wave.open(str(path), "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        sr = wf.getframerate()
        frames = wf.getnframes()
        raw = wf.readframes(frames)
    duration = frames / sr if sr else 0.0
    info = {
        "path": str(path),
        "bytes": path.stat().st_size,
        "channels": ch,
        "sampwidth": sw,
        "sample_rate": sr,
        "frames": frames,
        "duration_sec": round(duration, 3),
        "sha256": sha256_file(path),
    }
    if sw == 2 and frames > 0 and len(raw) == frames * ch * 2:
        samples = struct.unpack(f"<{frames * ch}h", raw)
        peak = max(abs(s) for s in samples) / 32768.0
        active = [s / 32768.0 for s in samples if abs(s) >= 184]
        rms_all = math.sqrt(sum((s / 32768.0) ** 2 for s in samples) / len(samples))
        rms_active = math.sqrt(sum(v * v for v in active) / len(active)) if active else 0.0
        info["peak_dbfs"] = round(20 * math.log10(peak), 2) if peak > 0 else -120.0
        info["rms_all_dbfs"] = round(20 * math.log10(rms_all), 2) if rms_all > 0 else -120.0
        info["rms_active_dbfs"] = round(20 * math.log10(rms_active), 2) if rms_active > 0 else -120.0
    return info


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "script_version": "phase0-spike-v2",
        "status": "started",
        "speech_repo": SPEECH_REPO,
        "speech_tag": SPEECH_TAG,
        "gguf_repo": GGUF_REPO,
        "gguf_file": GGUF_FILE,
        "patch_file": PATCH_FILE,
        "steps": {},
    }
    collected_files: list[tuple[Path, str]] = []

    try:
        # 1. Environment probe
        print("PROGRESS [1/7] Checking GPU and build tools...", flush=True)
        env_info = {}
        for name, cmd in [
            ("nvidia_smi", ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader"]),
            ("nproc", ["nproc"]),
            ("disk_df", ["df", "-h", "/content"]),
        ]:
            r = run_capture(cmd, timeout=30)
            env_info[name] = r["stdout"].strip() or r["stderr"].strip()
        report["steps"]["env"] = env_info

        # 2. Fetch patch & TAG_LIST.md from HF
        print("PROGRESS [2/7] Fetching fast patch and TAG_LIST.md...", flush=True)
        from huggingface_hub import hf_hub_download

        patch_local = Path(hf_hub_download(GGUF_REPO, PATCH_FILE))
        tag_list_local = Path(hf_hub_download(GGUF_REPO, "TAG_LIST.md"))
        collected_files.append((tag_list_local, "TAG_LIST.md"))

        # 3. Clone speech.cpp v0.11.2, apply fast patch, build `--target speech` only
        print(f"PROGRESS [3/7] Cloning speech.cpp ({SPEECH_TAG}) and applying {PATCH_FILE}...", flush=True)
        src_dir = WORK / "speech.cpp"
        if src_dir.exists():
            shutil.rmtree(src_dir)
        r_clone = run_capture(
            ["git", "clone", "--depth", "1", "--branch", SPEECH_TAG, "--recurse-submodules", SPEECH_REPO, str(src_dir)],
            timeout=300,
        )
        report["steps"]["git_clone"] = {"returncode": r_clone["returncode"], "elapsed_sec": r_clone["elapsed_sec"]}
        if r_clone["returncode"] != 0:
            raise RuntimeError(f"git clone failed: {r_clone['stderr'][-1000:]}")

        r_apply = run_capture(["git", "apply", str(patch_local)], cwd=src_dir, timeout=30)
        report["steps"]["patch_apply"] = {
            "file": PATCH_FILE,
            "returncode": r_apply["returncode"],
            "stderr": r_apply["stderr"][-500:],
        }
        if r_apply["returncode"] != 0:
            raise RuntimeError(f"git apply failed: {r_apply['stderr'][-1000:]}")

        build_dir = src_dir / "build"
        cmake_cmd = [
            "cmake", "-S", str(src_dir), "-B", str(build_dir),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DGGML_CUDA=ON",
            "-DGGML_CUDA_GRAPHS=ON",
        ]
        if CUDA_ARCHS:
            cmake_cmd.append(f"-DCMAKE_CUDA_ARCHITECTURES={CUDA_ARCHS}")
        r_cfg = run_capture(cmake_cmd, timeout=300)
        report["steps"]["cmake_configure"] = {
            "returncode": r_cfg["returncode"],
            "elapsed_sec": r_cfg["elapsed_sec"],
            "cuda_archs": CUDA_ARCHS,
            "tail_stderr": r_cfg["stderr"][-1000:],
        }
        if r_cfg["returncode"] != 0:
            raise RuntimeError("cmake configure failed")

        nproc = str(os.cpu_count() or 2)
        print(f"PROGRESS [4/7] Building targets 'speech speech-cli' with -j {nproc} (archs={CUDA_ARCHS})...", flush=True)
        r_bld = run_capture(
            ["cmake", "--build", str(build_dir), "--target", "speech", "speech-cli", "--config", "Release", "-j", nproc],
            timeout=1500,
        )
        report["steps"]["cmake_build"] = {
            "returncode": r_bld["returncode"],
            "elapsed_sec": r_bld["elapsed_sec"],
            "nproc": nproc,
            "tail_stdout": r_bld["stdout"][-1500:],
            "tail_stderr": r_bld["stderr"][-1500:],
        }
        if r_bld["returncode"] != 0:
            raise RuntimeError("cmake build failed")

        speech_bin = None
        for cand in (build_dir / "speech", build_dir / "bin" / "speech", build_dir / "speech-cli", build_dir / "bin" / "speech-cli"):
            if cand.is_file() and os.access(cand, os.X_OK):
                speech_bin = cand
                break
        if speech_bin is None:
            raise RuntimeError(f"speech CLI binary not found under {build_dir}")
        report["steps"]["speech_binary"] = str(speech_bin)

        # Package built binary and any build-local shared libs for reuse on T4/L4
        import tarfile

        prebuilt_tar = WORK / "speech_prebuilt_cuda13_sm75_89.tar.gz"
        packaged = []
        with tarfile.open(prebuilt_tar, "w:gz") as tf:
            tf.add(speech_bin, arcname="bin/speech")
            packaged.append("bin/speech")
            for so in sorted(build_dir.rglob("*.so*")):
                if so.is_file() or so.is_symlink():
                    arc = f"lib/{so.name}"
                    if arc not in packaged:
                        tf.add(so, arcname=arc)
                        packaged.append(arc)
        r_ldd = run_capture(["ldd", str(speech_bin)], timeout=30)
        report["steps"]["prebuilt_package"] = {
            "archive": prebuilt_tar.name,
            "bytes": prebuilt_tar.stat().st_size,
            "files": packaged,
            "ldd": r_ldd["stdout"],
        }
        collected_files.append((prebuilt_tar, prebuilt_tar.name))

        # 4. Capture CLI help
        print("PROGRESS [5/7] Capturing speech CLI --help...", flush=True)
        help_dump = []
        for sub in ([], ["tts"], ["voice"], ["serve"]):
            rh = run_capture([str(speech_bin), *sub, "--help"], timeout=30)
            title = " ".join(["speech", *sub, "--help"])
            help_dump.append(f"=== {title} (rc={rh['returncode']}) ===\n{rh['stdout']}\n{rh['stderr']}\n")
        help_path = WORK / "speech_help.txt"
        help_path.write_text("\n".join(help_dump), encoding="utf-8")
        collected_files.append((help_path, "speech_help.txt"))

        # 5. Download GGUF + sidecar .gguf.json into same folder
        print(f"PROGRESS [6/7] Downloading {GGUF_FILE} + sidecar .gguf.json...", flush=True)
        model_dir = WORK / "models"
        model_dir.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        gguf_cached = Path(hf_hub_download(GGUF_REPO, GGUF_FILE))
        sidecar_cached = Path(hf_hub_download(GGUF_REPO, GGUF_FILE + ".json"))
        dl_sec = round(time.monotonic() - t0, 3)

        gguf_path = model_dir / GGUF_FILE
        sidecar_path = model_dir / (GGUF_FILE + ".json")
        if gguf_path.exists() or gguf_path.is_symlink():
            gguf_path.unlink()
        if sidecar_path.exists() or sidecar_path.is_symlink():
            sidecar_path.unlink()
        os.symlink(gguf_cached, gguf_path)
        os.symlink(sidecar_cached, sidecar_path)
        collected_files.append((sidecar_cached, GGUF_FILE + ".json"))

        report["steps"]["gguf_download"] = {
            "filename": GGUF_FILE,
            "bytes": gguf_cached.stat().st_size,
            "elapsed_sec": dl_sec,
        }

        # 6. Test 1: VoiceDesign + Inline Tags
        print("PROGRESS [7/7] Running TTS (VoiceDesign) and VoiceClone tests...", flush=True)
        out_wav1 = WORK / "spike_sample_01_design.wav"
        tts_env = {"SPEECH_DRAMA3_MAX_PAUSE_FRAMES": "18"}
        cmd1 = [
            str(speech_bin), "tts", str(gguf_path),
            "--experts-on-cpu=false", "--voice", "none", "--seed", "42",
            "-o", str(out_wav1), TEST_TEXT,
        ]
        r1 = run_with_vram_monitor(cmd1, timeout=600, extra_env=tts_env)
        t1_rec = {
            "cmd": cmd1,
            "returncode": r1["returncode"],
            "elapsed_sec": r1["elapsed_sec"],
            "peak_vram_mb": r1["peak_vram_mb"],
            "tail_stdout": r1["stdout"][-1200:],
            "tail_stderr": r1["stderr"][-1200:],
        }
        t1_ok = False
        if r1["returncode"] == 0 and out_wav1.is_file():
            w1 = analyze_wav(out_wav1)
            if w1["duration_sec"] > 0 and r1["elapsed_sec"] > 0:
                w1["rtfx"] = round(w1["duration_sec"] / r1["elapsed_sec"], 3)
                t1_ok = True
            t1_rec["wav"] = w1
            collected_files.append((out_wav1, "spike_sample_01_design.wav"))
        report["steps"]["tts_test_1"] = t1_rec

        # 7. Test 2: Extract voice prompt & VoiceClone
        clone_ok = False
        if t1_ok:
            voice_gguf = WORK / "speaker.voice.gguf"
            cmd_v = [
                str(speech_bin), "voice", str(gguf_path), str(out_wav1),
                "--transcript", CLONE_TRANSCRIPT, str(voice_gguf),
            ]
            rv = run_with_vram_monitor(cmd_v, timeout=300, extra_env=tts_env)
            report["steps"]["voice_extract"] = {
                "cmd": cmd_v,
                "returncode": rv["returncode"],
                "elapsed_sec": rv["elapsed_sec"],
                "peak_vram_mb": rv["peak_vram_mb"],
                "tail_stderr": rv["stderr"][-800:],
            }
            if rv["returncode"] == 0 and voice_gguf.is_file():
                out_wav2 = WORK / "spike_sample_02_clone.wav"
                cmd2 = [
                    str(speech_bin), "tts", str(gguf_path),
                    "--experts-on-cpu=false",
                    "--add-voice", f"spk={voice_gguf}",
                    "--voice", "spk",
                    "--seed", "42",
                    "-o", str(out_wav2), CLONE_TEXT,
                ]
                r2 = run_with_vram_monitor(cmd2, timeout=600, extra_env=tts_env)
                t2_rec = {
                    "cmd": cmd2,
                    "returncode": r2["returncode"],
                    "elapsed_sec": r2["elapsed_sec"],
                    "peak_vram_mb": r2["peak_vram_mb"],
                    "tail_stdout": r2["stdout"][-1200:],
                    "tail_stderr": r2["stderr"][-1200:],
                }
                if r2["returncode"] == 0 and out_wav2.is_file():
                    w2 = analyze_wav(out_wav2)
                    if w2["duration_sec"] > 0 and r2["elapsed_sec"] > 0:
                        w2["rtfx"] = round(w2["duration_sec"] / r2["elapsed_sec"], 3)
                        clone_ok = True
                    t2_rec["wav"] = w2
                    collected_files.append((out_wav2, "spike_sample_02_clone.wav"))
                report["steps"]["tts_test_2_clone"] = t2_rec

        if not t1_ok:
            report["status"] = "tts_failed"
        elif not clone_ok:
            report["status"] = "clone_failed"
        else:
            report["status"] = "complete"

    except Exception as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        report["traceback"] = traceback.format_exc()
    finally:
        report_path = WORK / "spike_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        collected_files.append((report_path, "spike_report.json"))
        with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
            seen = set()
            for src, arc in collected_files:
                if src.is_file() and arc not in seen:
                    zf.write(src, arc)
                    seen.add(arc)
        print(f"PHASE0_STATUS {report['status']}", flush=True)
        print(f"PHASE0_ZIP {OUT_ZIP}", flush=True)

    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
