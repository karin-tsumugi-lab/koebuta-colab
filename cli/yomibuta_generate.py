#!/usr/bin/env python3
"""Host-side CLI for Yomibuta Drama-3-Japanese narration generation on Google Colab."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parent
REPO_ROOT = CLI_DIR.parent
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

from yomibuta_cli.audio import wav_info
from yomibuta_cli.core import (
    CONTRACT,
    PREBUILT_BINARY_NAME,
    PREBUILT_BINARY_SHA256,
    atomic_json,
    file_hash,
    identifier,
    load_json,
)
from yomibuta_cli.plan import PlanError, build_plan

UPLOAD_CHUNK_BYTES = 15 * 1024 * 1024  # Safe under Jupyter Contents API limits


def _run_colab(args: list[str], *, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    cmd = ["colab", *args]
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check, timeout=timeout)


def _safe_stop_session(session: str) -> tuple[bool, bool]:
    """Attempt `colab stop` without letting TimeoutExpired/OSError escape cleanup."""
    try:
        stop_proc = _run_colab(["stop", "-s", session], check=False, timeout=120)
        if stop_proc.returncode == 0:
            return True, False
        print(
            f"SESSION_STOP_FAILED ランタイム '{session}' の停止コマンドが非ゼロ終了しました (rc={stop_proc.returncode})。colab stop -s {session} を確認してください",
            file=sys.stderr,
        )
        return False, True
    except (subprocess.SubprocessError, OSError) as exc:
        print(
            f"SESSION_STOP_FAILED ランタイム '{session}' の停止中に例外が発生しました ({exc})。colab stop -s {session} を確認してください",
            file=sys.stderr,
        )
        return False, True


def _pack_code_zip(dest: Path) -> None:
    pkg_dir = CLI_DIR / "yomibuta_cli"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for py in sorted(pkg_dir.glob("*.py")):
            zf.write(py, f"yomibuta_cli/{py.name}")


def _upload_file_or_chunked(session: str, local_file: Path, remote_target: str, work_dir: Path) -> int:
    size = local_file.stat().st_size
    if size <= 12 * 1024 * 1024:
        _run_colab(["upload", "-s", session, str(local_file), remote_target], timeout=240)
        return 0
    parts = 0
    with local_file.open("rb") as src:
        while True:
            buf = src.read(UPLOAD_CHUNK_BYTES)
            if not buf:
                break
            chunk_file = work_dir / f"_upchunk_{parts:03d}.bin"
            chunk_file.write_bytes(buf)
            try:
                _run_colab(["upload", "-s", session, str(chunk_file), f"{remote_target}.part{parts:02d}"], timeout=240)
            finally:
                chunk_file.unlink(missing_ok=True)
            parts += 1
    return parts


def _download_chunked(session: str, chunks: list[dict], dest: Path) -> None:
    if not isinstance(chunks, list) or not chunks:
        raise RuntimeError(f"ダウンロードチャンク情報が空です: {dest.name}")
    tmp_dest = dest.with_suffix(dest.suffix + ".part_dl")
    try:
        with tmp_dest.open("wb") as out:
            for idx, item in enumerate(chunks):
                if not isinstance(item, dict) or not isinstance(item.get("remote"), str):
                    raise RuntimeError(f"不正なチャンク情報です: {item!r}")
                rem_path = item["remote"]
                if not rem_path.startswith(("/content/", "/tmp/")) or ".." in Path(rem_path).parts:
                    raise RuntimeError(f"許可されていない遠隔チャンクパスです: {rem_path!r}")
                part_local = dest.parent / f"_dlchunk_{idx:03d}.bin"
                try:
                    _run_colab(["download", "-s", session, rem_path, str(part_local)], timeout=300)
                    if file_hash(part_local) != item.get("sha256"):
                        raise RuntimeError(f"ダウンロードチャンクのSHA256不一致: {rem_path}")
                    with part_local.open("rb") as src:
                        shutil.copyfileobj(src, out)
                finally:
                    part_local.unlink(missing_ok=True)
        tmp_dest.replace(dest)
    except BaseException:
        tmp_dest.unlink(missing_ok=True)
        raise


def _verify_and_collect(
    *,
    session: str,
    remote_manifest: str,
    out_dir: Path,
    expected_job: str,
    expected_plan_signature: str,
    expected_sample_rate: int,
    expected_nonce: str,
) -> tuple[str, list[dict], list[dict]]:
    """Download manifest + artifacts and strictly verify identity, signature, hashes, and WAV format.

    Returns `(remote_status, warnings, remote_errors)`.
    """
    if not isinstance(expected_nonce, str) or len(expected_nonce) < 4:
        raise RuntimeError("manifest 照合用の nonce が不正または欠落しています")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_local = out_dir / "manifest.json"
    _run_colab(["download", "-s", session, remote_manifest, str(manifest_local)], timeout=120)
    manifest = load_json(manifest_local)
    if not isinstance(manifest, dict):
        raise RuntimeError("回収した manifest.json がオブジェクトではありません")
    if manifest.get("contract") != CONTRACT:
        raise RuntimeError(f"manifest の契約が一致しません: {manifest.get('contract')!r}")
    if manifest.get("job_id") != expected_job:
        raise RuntimeError(f"manifest の job_id が一致しません (期待={expected_job}, 実体={manifest.get('job_id')})")
    if manifest.get("nonce") != expected_nonce:
        raise RuntimeError(
            "manifest の実行受付ID (nonce) が一致しません（古いジョブ結果の誤回収を防止しました）"
        )
    warnings = manifest.get("warnings") if isinstance(manifest.get("warnings"), list) else []
    remote_errors = manifest.get("errors") if isinstance(manifest.get("errors"), list) else []
    status = str(manifest.get("status") or "unknown")
    if status != "complete":
        return status, warnings, remote_errors
    if manifest.get("plan_signature") != expected_plan_signature:
        raise RuntimeError("manifest の plan_signature が現在の生成計画と一致しません")

    dl_chunks = manifest.get("download_chunks") or {}
    tmp_wav = out_dir / "_verify_result.wav.tmp"
    tmp_zip = out_dir / "_verify_segments.zip.tmp"
    result_wav = out_dir / "result.wav"
    seg_zip = out_dir / "segments.zip"

    try:
        _download_chunked(session, dl_chunks.get("result.wav"), tmp_wav)
        _download_chunked(session, dl_chunks.get("segments.zip"), tmp_zip)

        comb = manifest["combined"]
        actual = wav_info(tmp_wav)
        if (
            actual["sha256"] != comb["sha256"]
            or actual["frames"] != comb["frames"]
            or actual["sample_rate"] != expected_sample_rate
            or actual["channels"] != 1
            or actual["sampwidth"] != 2
        ):
            raise RuntimeError(f"回収した result.wav の検証に失敗しました: {actual}")
        if file_hash(tmp_zip) != manifest["segments_zip"]["sha256"]:
            raise RuntimeError("回収した segments.zip のSHA256が一致しません")

        tmp_wav.replace(result_wav)
        tmp_zip.replace(seg_zip)
    except BaseException:
        tmp_wav.unlink(missing_ok=True)
        tmp_zip.unlink(missing_ok=True)
        raise
    return "complete", warnings, remote_errors


def _write_remote_bootstrap(
    dest: Path,
    *,
    code_zip_remote: str,
    job_id: str,
    nonce: str,
    timeout_sec: int,
    job_dir_remote: str,
    plan_remote: str,
    plan_parts: int,
    bin_gz_remote: str,
    bin_parts: int,
    voice_parts: dict[str, int],
    manifest_remote: str,
) -> None:
    voice_parts_json = json.dumps(voice_parts, ensure_ascii=False)
    script = f"""#!/usr/bin/env python3
import os, shutil, sys, zipfile
from pathlib import Path

code_root = Path('/content/yomibuta_code')
shutil.rmtree(code_root, ignore_errors=True)
code_root.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile({code_zip_remote!r}, 'r') as zf:
    zf.extractall(code_root)
Path({code_zip_remote!r}).unlink(missing_ok=True)

for mod_name in [k for k in list(sys.modules) if k == 'yomibuta_cli' or k.startswith('yomibuta_cli.')]:
    sys.modules.pop(mod_name, None)

os.environ['YOMIBUTA_CODE_ROOT'] = str(code_root)
os.environ['YOMIBUTA_REMOTE_JOB_ID'] = {job_id!r}
os.environ['YOMIBUTA_REMOTE_NONCE'] = {nonce!r}
os.environ['YOMIBUTA_REMOTE_TIMEOUT'] = {str(timeout_sec)!r}
os.environ['YOMIBUTA_REMOTE_JOB_DIR'] = {job_dir_remote!r}
os.environ['YOMIBUTA_REMOTE_PLAN'] = {plan_remote!r}
os.environ['YOMIBUTA_REMOTE_PLAN_PARTS'] = {str(plan_parts)!r}
os.environ['YOMIBUTA_REMOTE_BIN_GZ'] = {bin_gz_remote!r}
os.environ['YOMIBUTA_REMOTE_BIN_PARTS'] = {str(bin_parts)!r}
os.environ['YOMIBUTA_REMOTE_VOICE_PARTS'] = {voice_parts_json!r}
os.environ['YOMIBUTA_REMOTE_MANIFEST'] = {manifest_remote!r}

if str(code_root) not in sys.path:
    sys.path.insert(0, str(code_root))

from yomibuta_cli.remote_worker import main
raise SystemExit(main())
"""
    dest.write_text(script, encoding="utf-8")


def _run_recover_mode(args: argparse.Namespace) -> int:
    out_dir = args.recover.resolve()
    inv_path = out_dir / "invocation.json"
    plan_path = out_dir / "plan.json"
    if not inv_path.is_file() or not plan_path.is_file():
        print(f"ERROR: 回収に必要な invocation.json / plan.json が見つかりません: {out_dir}", file=sys.stderr)
        return 2
    if shutil.which("colab") is None:
        print("ERROR: 'colab' CLI not found in PATH", file=sys.stderr)
        return 1

    try:
        inv = load_json(inv_path)
        plan = load_json(plan_path)
        if not isinstance(inv, dict) or not isinstance(plan, dict):
            raise ValueError("invocation.json または plan.json がオブジェクトではありません")
        if inv.get("contract") != CONTRACT or plan.get("contract") != CONTRACT:
            raise ValueError("契約バージョンが一致しません")
        session = identifier(args.session or inv.get("session"), "session", 60)
        job = identifier(inv.get("job"), "job", 60)
        nonce = inv.get("nonce")
        if not isinstance(nonce, str) or len(nonce) < 4:
            raise ValueError("invocation.json に有効な nonce がありません")
        plan_sig = plan["plan_signature"]
        if inv.get("plan_signature") != plan_sig:
            raise ValueError("invocation.json と plan.json の plan_signature が一致しません")
        remote_manifest = inv.get("remote_manifest") or f"/content/yomibuta_{job}_manifest.json"
        if not isinstance(remote_manifest, str) or not remote_manifest.startswith(("/content/", "/tmp/")) or ".." in Path(remote_manifest).parts:
            raise ValueError(f"不正な remote_manifest パスです: {remote_manifest!r}")
        expected_sr = int(plan["settings"]["sampleRate"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"INPUT_ERROR: {exc}", file=sys.stderr)
        return 2

    remote_status = "unknown"
    verified = False
    error_detail: str | None = None
    warnings_out: list[dict] = []
    remote_errors: list[dict] = []
    try:
        remote_status, warnings_out, remote_errors = _verify_and_collect(
            session=session,
            remote_manifest=remote_manifest,
            out_dir=out_dir,
            expected_job=job,
            expected_plan_signature=plan_sig,
            expected_sample_rate=expected_sr,
            expected_nonce=nonce,
        )
        verified = remote_status == "complete"
    except Exception as exc:
        error_detail = str(exc)
        print(f"ERROR: {exc}", file=sys.stderr)

    # CRITICAL (C-1): Never stop an actively running Colab job during `--recover`!
    if remote_status in ("started", "running"):
        print(
            f"JOB_STILL_RUNNING 遠隔ジョブはまだ推論実行中です (status={remote_status})。ランタイムを維持しましたので、完了後に再度 --recover を実行してください。",
            file=sys.stderr,
        )
        atomic_json(
            out_dir / "pipeline.json",
            {
                "mode": "recover",
                "status": "running",
                "session": session,
                "job": job,
                "nonce": nonce,
                "verified": False,
                "session_stopped": False,
                "stop_failed": False,
            },
        )
        return 1

    for r_err in remote_errors:
        if isinstance(r_err, dict) and r_err.get("error"):
            print(f"[REMOTE_ERROR] {r_err['error']}", file=sys.stderr)
            if not error_detail:
                error_detail = str(r_err["error"])

    stop_failed = False
    session_stopped = False
    if args.stop_after_download and (verified or not args.keep_on_error):
        session_stopped, stop_failed = _safe_stop_session(session)

    for w in warnings_out:
        print(f"[WARNING] {w.get('code')} ({w.get('segment_id')}): {w}", file=sys.stderr)

    pipeline_record: dict[str, object] = {
        "mode": "recover",
        "status": "complete" if (verified and not stop_failed) else "failed",
        "remote_status": remote_status,
        "session": session,
        "job": job,
        "nonce": nonce,
        "verified": verified,
        "session_stopped": session_stopped,
        "stop_failed": stop_failed,
    }
    if error_detail:
        pipeline_record["error"] = error_detail
    if remote_errors:
        pipeline_record["remote_errors"] = [e.get("error") for e in remote_errors if isinstance(e, dict) and e.get("error")]
    atomic_json(out_dir / "pipeline.json", pipeline_record)

    if verified and not stop_failed:
        print(f"AUDIO_READY {out_dir / 'result.wav'}", flush=True)
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yomibuta CLI: Drama-3-Japanese narration generator on Colab.")
    parser.add_argument("--recover", type=Path, help="Recover completed outputs from an existing output folder without re-running synthesis")
    parser.add_argument("--scenario", type=Path, help="Path to scenario.json (schema_version 1 or 2)")
    parser.add_argument("--settings", type=Path, help="Path to settings.json")
    parser.add_argument("--ids", help="Comma-separated utterance IDs for partial synthesis")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print plan JSON without using Colab")
    parser.add_argument("--session", help="Colab session name")
    parser.add_argument("--job", help="Unique job ID")
    parser.add_argument("--out", type=Path, help="New local output directory")
    parser.add_argument("--new", action="store_true", help="Create a new Colab runtime")
    parser.add_argument("--gpu", default="T4", help="Colab GPU type (default: T4)")
    parser.add_argument("--prebuilt-bin", type=Path, default=REPO_ROOT / "bin" / PREBUILT_BINARY_NAME)
    parser.add_argument("--skip-binary-upload", action="store_true", help="Reuse prebuilt binary already on session")
    parser.add_argument("--stop-after-download", action="store_true", help="Stop Colab runtime when finished (also stops on error unless --keep-on-error)")
    parser.add_argument("--keep-on-error", action="store_true", help="Keep Colab runtime alive on error for --recover or inspection")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    if args.recover is not None:
        return _run_recover_mode(args)

    if not args.scenario or not args.settings:
        parser.error("通常実行または --dry-run には --scenario と --settings が必要です")

    try:
        scenario = load_json(args.scenario)
        settings = load_json(args.settings)
    except (OSError, ValueError) as exc:
        print(f"INPUT_ERROR: {exc}", file=sys.stderr)
        return 2

    selected_ids = [s.strip() for s in args.ids.split(",") if s.strip()] if args.ids is not None else None

    try:
        plan = build_plan(
            scenario,
            settings,
            base_dir=args.settings.resolve().parent,
            scenario_base_dir=args.scenario.resolve().parent,
            selected_ids=selected_ids,
        )
    except PlanError as exc:
        print(f"PLAN_ERROR:\n{exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    for d in plan.get("diagnostics", []):
        print(f"[{d['level'].upper()}] {d['code']} ({d.get('segment_id') or 'global'}): {d['message']}", file=sys.stderr)

    if not args.session or not args.job or not args.out:
        parser.error("実行時には --session, --job, --out が必要です")
    if args.timeout < 30:
        print("INPUT_ERROR: --timeout には 30 秒以上を指定してください", file=sys.stderr)
        return 2
    try:
        identifier(args.session, "session", 60)
        identifier(args.job, "job", 60)
    except ValueError as exc:
        print(f"INPUT_ERROR: {exc}", file=sys.stderr)
        return 2

    if shutil.which("colab") is None:
        print("ERROR: 'colab' CLI not found in PATH", file=sys.stderr)
        return 1

    out_dir = args.out.resolve()
    if out_dir.exists():
        if not out_dir.is_dir():
            print(f"ERROR: 出力先パスに通常のファイルが既に存在します: {out_dir}", file=sys.stderr)
            return 1
        if any(out_dir.iterdir()):
            print(f"ERROR: 出力先フォルダーは既に存在し空ではありません（上書き保護）: {out_dir}", file=sys.stderr)
            return 1

    need_prebuilt_bin = (plan["settings"]["backend"] == "speech_cpp_gguf") and (not args.skip_binary_upload)
    if need_prebuilt_bin:
        if not args.prebuilt_bin.is_file():
            print(f"ERROR: 事前ビルド済みバイナリが見つかりません: {args.prebuilt_bin}", file=sys.stderr)
            return 1
        actual_sha = file_hash(args.prebuilt_bin)
        if actual_sha != PREBUILT_BINARY_SHA256:
            print(
                f"ERROR: 事前ビルド済みバイナリのSHA256が一致しません "
                f"(期待={PREBUILT_BINARY_SHA256}, 実体={actual_sha})",
                file=sys.stderr,
            )
            return 1

    nonce = uuid.uuid4().hex
    remote_job_dir = f"/content/yomibuta_jobs/{args.job}"
    remote_code_zip = "/content/yomibuta_code.zip"
    remote_plan = f"/content/yomibuta_{args.job}_plan.json"
    remote_bin_gz = f"/content/{PREBUILT_BINARY_NAME}"
    remote_manifest = f"/content/yomibuta_{args.job}_manifest.json"

    out_dir.mkdir(parents=True, exist_ok=True)
    plan_local = out_dir / "plan.json"
    atomic_json(plan_local, plan)
    atomic_json(
        out_dir / "invocation.json",
        {
            "contract": CONTRACT,
            "session": args.session,
            "job": args.job,
            "nonce": nonce,
            "plan_signature": plan["plan_signature"],
            "remote_manifest": remote_manifest,
        },
    )

    code_zip_local = out_dir / "_code.zip"
    bootstrap_local = out_dir / "_bootstrap.py"
    remote_status = "unknown"
    verified = False
    session_ready = not args.new
    exec_returncode: int | None = None
    error_detail: str | None = None
    warnings_out: list[dict] = []
    remote_errors: list[dict] = []

    try:
        _pack_code_zip(code_zip_local)

        if args.new:
            _run_colab(["new", "-s", args.session, "--gpu", args.gpu], timeout=240)
            session_ready = True

        _run_colab(["upload", "-s", args.session, str(code_zip_local), remote_code_zip], timeout=120)
        plan_parts = _upload_file_or_chunked(args.session, plan_local, remote_plan, out_dir)

        bin_parts = 0
        if need_prebuilt_bin:
            bin_parts = _upload_file_or_chunked(args.session, args.prebuilt_bin, remote_bin_gz, out_dir)

        used_profiles = {
            r["request"]["voice_profile"]
            for r in plan.get("requests", [])
            if r["request"].get("voice_profile") and r["request"]["voice_profile"] != "none"
        }
        voice_parts: dict[str, int] = {}
        for profile, clips in (plan.get("voices") or {}).items():
            if profile not in used_profiles:
                continue
            for idx, clip in enumerate(clips):
                key = f"{profile}_{idx}"
                remote_wav = f"/content/yomibuta_{args.job}_voice_{key}.wav"
                parts = _upload_file_or_chunked(args.session, Path(clip["wav"]), remote_wav, out_dir)
                if parts > 0:
                    voice_parts[key] = parts

        _write_remote_bootstrap(
            bootstrap_local,
            code_zip_remote=remote_code_zip,
            job_id=args.job,
            nonce=nonce,
            timeout_sec=args.timeout,
            job_dir_remote=remote_job_dir,
            plan_remote=remote_plan,
            plan_parts=plan_parts,
            bin_gz_remote=remote_bin_gz,
            bin_parts=bin_parts,
            voice_parts=voice_parts,
            manifest_remote=remote_manifest,
        )

        exec_proc = _run_colab(
            ["exec", "-s", args.session, "--timeout", str(args.timeout), "-f", str(bootstrap_local)],
            check=False,
            timeout=args.timeout + 60,
        )
        exec_returncode = exec_proc.returncode

        remote_status, warnings_out, remote_errors = _verify_and_collect(
            session=args.session,
            remote_manifest=remote_manifest,
            out_dir=out_dir,
            expected_job=args.job,
            expected_plan_signature=plan["plan_signature"],
            expected_sample_rate=int(plan["settings"]["sampleRate"]),
            expected_nonce=nonce,
        )
        verified = remote_status == "complete"
        for r_err in remote_errors:
            if isinstance(r_err, dict) and r_err.get("error"):
                print(f"[REMOTE_ERROR] {r_err['error']}", file=sys.stderr)
                if not error_detail:
                    error_detail = str(r_err["error"])
        if not verified and exec_returncode != 0 and not error_detail:
            error_detail = f"remote worker exited with status={remote_status!r} (rc={exec_returncode})"
    except Exception as exc:
        error_detail = str(exc)
        print(f"ERROR: {exc}", file=sys.stderr)
    finally:
        code_zip_local.unlink(missing_ok=True)
        bootstrap_local.unlink(missing_ok=True)

        stop_failed = False
        session_stopped = False
        should_stop = args.stop_after_download and session_ready and (verified or not args.keep_on_error)
        if should_stop:
            session_stopped, stop_failed = _safe_stop_session(args.session)

        for w in warnings_out:
            print(f"[WARNING] {w.get('code')} ({w.get('segment_id')}): {w}", file=sys.stderr)

        pipeline_record: dict[str, object] = {
            "status": "complete" if (verified and not stop_failed) else "failed",
            "remote_status": remote_status,
            "session": args.session,
            "job": args.job,
            "nonce": nonce,
            "exec_returncode": exec_returncode,
            "verified": verified,
            "session_stopped": session_stopped,
            "stop_failed": stop_failed,
        }
        if error_detail:
            pipeline_record["error"] = error_detail
        if remote_errors:
            pipeline_record["remote_errors"] = [e.get("error") for e in remote_errors if isinstance(e, dict) and e.get("error")]
        if not verified and not session_stopped:
            pipeline_record["recovery_hint"] = f"python3 cli/yomibuta_generate.py --recover {out_dir}"
        atomic_json(out_dir / "pipeline.json", pipeline_record)

    if verified and not stop_failed:
        print(f"AUDIO_READY {out_dir / 'result.wav'}", flush=True)
        return 0
    print(f"JOB_FAILED see {out_dir / 'pipeline.json'}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
