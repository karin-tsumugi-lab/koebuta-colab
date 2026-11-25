#!/usr/bin/env python3
"""Host-side runner for Yomibuta Phase 0 Drama-3 spike on Google Colab."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REMOTE_SCRIPT = HERE / "remote_phase0_spike.py"
REMOTE_ZIP = "/content/yomibuta_phase0_artifacts.zip"


def run_colab(args: list[str], *, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    cmd = ["colab", *args]
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check, timeout=timeout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 0 Drama-3 spike on Colab GPU.")
    parser.add_argument("--session", default="yomibuta-phase0", help="Colab session name")
    parser.add_argument("--gpu", default="T4", help="Colab GPU type (e.g. T4, L4)")
    parser.add_argument("--new", action="store_true", help="Create a new Colab runtime")
    parser.add_argument("--out", type=Path, default=HERE / "out_phase0", help="Local output directory")
    parser.add_argument("--gguf-repo", default="StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf")
    parser.add_argument("--quant", default="IQ3_XXS")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--keep-session", action="store_true", help="Do not stop Colab runtime after download")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without calling Colab")
    args = parser.parse_args(argv)

    if not REMOTE_SCRIPT.is_file():
        print(f"ERROR: missing {REMOTE_SCRIPT}", file=sys.stderr)
        return 1

    if not args.dry_run and shutil.which("colab") is None:
        print("ERROR: 'colab' CLI not found in PATH", file=sys.stderr)
        return 1

    out_dir = args.out.resolve()
    local_zip = out_dir / "phase0_artifacts.zip"

    exec_args = [
        "exec", "-s", args.session,
        "--timeout", str(args.timeout),
        "--env", f"YOMIBUTA_GGUF_REPO={args.gguf_repo}",
        "--env", f"YOMIBUTA_QUANT_PATTERN={args.quant}",
        "--env", f"YOMIBUTA_PHASE0_ZIP={REMOTE_ZIP}",
        "-f", str(REMOTE_SCRIPT),
    ]

    if args.dry_run:
        print("DRY_RUN planned commands:")
        if args.new:
            print("  colab", " ".join(["new", "-s", args.session, "--gpu", args.gpu]))
        print("  colab", " ".join(exec_args))
        print("  colab", " ".join(["download", "-s", args.session, REMOTE_ZIP, str(local_zip)]))
        if not args.keep_session:
            print("  colab", " ".join(["stop", "-s", args.session]))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    if args.new:
        run_colab(["new", "-s", args.session, "--gpu", args.gpu], timeout=240)

    exec_proc = run_colab(exec_args, check=False, timeout=args.timeout + 60)

    downloaded = False
    try:
        run_colab(["download", "-s", args.session, REMOTE_ZIP, str(local_zip)], timeout=300)
        downloaded = local_zip.is_file()
    except subprocess.SubprocessError as exc:
        print(f"WARNING: failed to download artifacts: {exc}", file=sys.stderr)

    if downloaded:
        with zipfile.ZipFile(local_zip, "r") as zf:
            zf.extractall(out_dir)
        report_path = out_dir / "spike_report.json"
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            print("\n=== Phase 0 Summary ===", flush=True)
            print("status:", report.get("status"))
            steps = report.get("steps", {})
            if "cmake_build" in steps:
                print("cmake_build:", steps["cmake_build"].get("returncode"), f"{steps['cmake_build'].get('elapsed_sec')}s")
            if "gguf_download" in steps:
                dl = steps["gguf_download"]
                print("gguf:", dl.get("filename"), f"{dl.get('bytes', 0) / (1024**3):.2f} GiB", f"{dl.get('elapsed_sec')}s")
            if "tts_test_1" in steps:
                t1 = steps["tts_test_1"]
                print("tts_test_1:", "rc=", t1.get("returncode"), f"elapsed={t1.get('elapsed_sec')}s", f"peak_vram={t1.get('peak_vram_mb')}MB")
                if "wav" in t1:
                    w = t1["wav"]
                    print("wav:", f"{w.get('sample_rate')}Hz {w.get('channels')}ch", f"dur={w.get('duration_sec')}s", f"rtfx={w.get('rtfx')}", f"rms_active={w.get('rms_active_dbfs')}dBFS")
            if "tts_test_2_clone" in steps:
                t2 = steps["tts_test_2_clone"]
                w2 = t2.get("wav") or {}
                print("tts_test_2_clone:", "rc=", t2.get("returncode"), f"dur={w2.get('duration_sec')}s", f"rtfx={w2.get('rtfx')}")
            print("outputs:", out_dir)

    if not args.keep_session:
        if downloaded:
            run_colab(["stop", "-s", args.session], check=False, timeout=120)
        else:
            print("NOTE: Artifacts were not downloaded; keeping Colab session alive for inspection.", file=sys.stderr)

    return 0 if (downloaded and exec_proc.returncode == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
