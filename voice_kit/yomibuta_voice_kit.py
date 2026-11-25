#!/usr/bin/env python3
"""Yomibuta (Drama-3) Voice Kit: audition VoiceDesign seeds in a single Colab job
and adopt the chosen raw WAV + transcript into settings.json."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CLI_DIR = REPO_ROOT / "cli"
CLI_SCRIPT = CLI_DIR / "yomibuta_generate.py"
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

from yomibuta_cli.core import identifier, load_json
from yomibuta_cli.drama3_tags import find_forbidden_control_tokens, strip_inline_tags
from yomibuta_cli.plan import ALLOWED_SETTINGS_KEYS

DEFAULT_TEXT = "窓の外では静かに雨が降り続いていた。これからどこへ向かうつもりなのか、落ち着いた声が静かな部屋に柔らかく響く。"

PRESETS: dict[str, dict[str, str]] = {
    "female_narrator": {
        "label": "落ち着いた女性ナレーター",
        "caption": "落ち着いた明瞭な声の成人女性。やや低めで、ゆったりと丁寧に話す。穏やかで自然な朗読。",
    },
    "male_narrator": {
        "label": "深みのある男性ナレーター",
        "caption": "落ち着いた大人の男性。深く響く声で、丁寧かつ明瞭にゆっくりと朗読している。",
    },
    "bright_heroine": {
        "label": "明るく清楚な若い女性",
        "caption": "明るく透明感のある若い女性の声。軽やかで聞き取りやすく、親しみやすい話し方。",
    },
    "gentle_girl": {
        "label": "穏やかで柔らかい少女",
        "caption": "柔らかく穏やかな少女の声。少し高めで優しいトーン、丁寧に話す。",
    },
    "whisper_sister": {
        "label": "包容力のあるお姉さん",
        "caption": "落ち着いた25歳の女性。柔らかく包容力があり、耳元に近い距離感で優しく語りかける。",
    },
    "cool_youth": {
        "label": "クールで知的な青年",
        "caption": "落ち着いた若い男性。知的な印象で、淡々としながらも芯のある明瞭な声。",
    },
    "veteran_butler": {
        "label": "渋い老紳士・執事",
        "caption": "低く渋みのある年配男性の声。礼儀正しく格式高い語り口で、落ち着いて話す。",
    },
}


def _adopt_seed(args: argparse.Namespace) -> int:
    identifier(args.profile, "voice profile", 40)
    if args.profile == "none":
        print("ERROR: 'none' は予約語のためプロファイル名に使用できません", file=sys.stderr)
        return 2
    src_dir = args.from_out.resolve()
    cand_json = src_dir / "candidates.json"
    if not cand_json.is_file():
        print(f"ERROR: candidates.json が見つかりません: {cand_json}", file=sys.stderr)
        return 1
    try:
        meta = load_json(cand_json)
        if not isinstance(meta, dict) or not isinstance(meta.get("candidates"), list):
            raise ValueError("candidates.json の構造が不正です")
    except (OSError, ValueError) as exc:
        print(f"ERROR: candidates.json の読み込みに失敗しました: {exc}", file=sys.stderr)
        return 2

    chosen = next(
        (
            c
            for c in meta["candidates"]
            if isinstance(c, dict) and type(c.get("seed")) is int and c.get("seed") == args.adopt
        ),
        None,
    )
    if chosen is None:
        print(f"ERROR: シード {args.adopt} が candidates.json に見つかりません", file=sys.stderr)
        return 1
    cand_file = chosen.get("file")
    if not isinstance(cand_file, str) or not cand_file.strip():
        print("ERROR: 候補エントリに有効な file 名がありません", file=sys.stderr)
        return 2
    cand_rel = Path(cand_file)
    if cand_rel.is_absolute() or ".." in cand_rel.parts:
        print(f"ERROR: candidates.json 内の不正なファイルパスを拒否しました: {cand_file!r}", file=sys.stderr)
        return 2
    src_wav = (src_dir / cand_rel).resolve()
    if not src_wav.is_relative_to(src_dir) or not src_wav.is_file():
        print(f"ERROR: 候補WAVが見つかりません: {src_wav}", file=sys.stderr)
        return 1

    save_to = args.save_to.resolve()
    if save_to.suffix.lower() != ".wav":
        print(f"ERROR: --save-to には .wav ファイルパスを指定してください: {save_to}", file=sys.stderr)
        return 2
    voice_meta_path = save_to.with_suffix(".voice_meta.json")
    settings_path = args.write_settings.resolve() if args.write_settings else None
    if settings_path is not None and settings_path == save_to:
        print("ERROR: --save-to と --write-settings に同じパスは指定できません", file=sys.stderr)
        return 2

    # Pre-check all target paths (including broken symlinks) BEFORE writing any file.
    if not args.overwrite:
        if save_to.exists() or save_to.is_symlink():
            print(f"ERROR: 保存先WAVが既に存在します（--overwrite で上書き可）: {save_to}", file=sys.stderr)
            return 1
        if voice_meta_path.exists() or voice_meta_path.is_symlink():
            print(f"ERROR: メタデータが既に存在します（--overwrite で上書き可）: {voice_meta_path}", file=sys.stderr)
            return 1
        if settings_path is not None and (settings_path.exists() or settings_path.is_symlink()):
            print(f"ERROR: settings.json が既に存在します（--overwrite で上書き可）: {settings_path}", file=sys.stderr)
            return 1

    clean_transcript = strip_inline_tags(str(meta.get("text") or "")).strip()
    if not clean_transcript:
        print("ERROR: candidates.json の文字起こしテキストが空です", file=sys.stderr)
        return 2

    save_to.parent.mkdir(parents=True, exist_ok=True)
    if save_to.is_symlink():
        save_to.unlink()
    shutil.copy2(src_wav, save_to)

    voice_meta = {
        "engine": "drama3",
        "seed": chosen["seed"],
        "caption": str(meta.get("caption") or ""),
        "transcript": clean_transcript,
        "source_wav": cand_file,
    }
    voice_meta_path.write_text(json.dumps(voice_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ADOPTED_WAV {save_to}")
    print(f"VOICE_META  {voice_meta_path}")

    if settings_path is not None:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            rel_wav = Path(os.path.relpath(save_to, settings_path.parent)).as_posix()
        except ValueError:
            rel_wav = str(save_to)

        prev_doc: dict = {}
        if settings_path.is_file():
            try:
                loaded_prev = load_json(settings_path)
                if isinstance(loaded_prev, dict):
                    prev_doc = {k: v for k, v in loaded_prev.items() if k in ALLOWED_SETTINGS_KEYS}
            except Exception:
                pass
        existing_voices = dict(prev_doc.get("voices")) if isinstance(prev_doc.get("voices"), dict) else {}
        existing_voices[args.profile] = [
            {
                "wav": rel_wav,
                "transcript": clean_transcript,
            }
        ]
        reading_mode = prev_doc.get("reading") if prev_doc.get("reading") in ("shared", "cast") else ("cast" if len(existing_voices) > 1 else "shared")
        if len(existing_voices) > 1:
            reading_mode = "cast"

        settings_doc: dict = {
            "title": args.title or prev_doc.get("title") or "新しい朗読",
            "ttsEngine": "drama3",
            "ttsModel": "Aratako/Drama-3-Japanese",
            "backend": "speech_cpp_gguf",
            "quant": "IQ3_XXS",
            "sampleRate": 44100,
            "normalizeRmsDb": -18.0,
            **prev_doc,
            "reading": reading_mode,
            "voiceMode": "clone",
            "cloneCaption": bool(prev_doc.get("cloneCaption", False)),
            "voices": existing_voices,
            "acting": bool(prev_doc.get("acting", True)),
            "emotion": bool(prev_doc.get("emotion", True)),
            "narratorEmotion": bool(prev_doc.get("narratorEmotion", True)),
            "seed": chosen["seed"],
            "pause": prev_doc.get("pause", 0.28),
        }
        settings_doc.pop("baseCaption", None)
        if reading_mode == "cast":
            prev_sv = dict(prev_doc.get("speakerVoices")) if isinstance(prev_doc.get("speakerVoices"), dict) else {}
            for prof_key in existing_voices:
                prev_sv.setdefault(prof_key, prof_key)
            settings_doc["speakerVoices"] = prev_sv
        settings_path.write_text(json.dumps(settings_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"SETTINGS_WRITTEN {settings_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Yomibuta Drama-3 Voice Kit (single-job audition & adopt with transcript).")
    parser.add_argument("--list-presets", action="store_true", help="List built-in voice presets")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="Use a built-in voice caption preset")
    parser.add_argument("--caption", help="Custom Japanese VoiceDesign caption")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="Audition text (saved as clone transcript)")
    parser.add_argument("--seeds", default="101,202,303,404,505", help="Comma-separated seeds to audition")
    parser.add_argument("--out", type=Path, help="Output directory for candidate WAVs")
    parser.add_argument("--session", default="yomibuta-voicekit")
    parser.add_argument("--job-prefix", default="vk")
    parser.add_argument("--gpu", default="T4")
    parser.add_argument("--new", action="store_true")
    parser.add_argument("--prebuilt-bin", type=Path, help="Optional custom prebuilt speech binary path")
    parser.add_argument("--skip-binary-upload", action="store_true")
    parser.add_argument("--keep-session", action="store_true")
    parser.add_argument("--keep-on-error", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--dry-run", action="store_true")
    # Adopt mode
    parser.add_argument("--from-out", type=Path, help="Audition output directory containing candidates.json")
    parser.add_argument("--adopt", type=int, help="Seed number to adopt")
    parser.add_argument("--save-to", type=Path, help="Destination path for adopted reference WAV")
    parser.add_argument("--write-settings", type=Path, help="Also write ready-to-use Drama-3 settings.json")
    parser.add_argument("--profile", default="narrator", help="Voice profile name in settings.json")
    parser.add_argument("--title", default="新しい朗読")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    if args.list_presets:
        for key, val in PRESETS.items():
            print(f"{key:18s} | {val['label']} : {val['caption']}")
        return 0

    if args.adopt is not None:
        if not args.from_out or not args.save_to:
            parser.error("--adopt には --from-out と --save-to が必要です")
        return _adopt_seed(args)

    identifier(args.session, "session", 60)
    identifier(args.job_prefix, "job-prefix", 40)
    identifier(args.profile, "voice profile", 40)

    caption = args.caption or (PRESETS[args.preset]["caption"] if args.preset else "")
    if not caption or not caption.strip():
        parser.error("--preset または空でない --caption を指定してください")
    if not isinstance(args.text, str) or not strip_inline_tags(args.text).strip():
        parser.error("--text に読み上げ文字を含む試聴セリフを指定してください")
    if find_forbidden_control_tokens(caption) or find_forbidden_control_tokens(args.text):
        parser.error("--caption または --text に使用禁止の制御トークン <|...|> が含まれています")
    try:
        seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    except ValueError:
        parser.error(f"--seeds はカンマ区切りの整数で指定してください: {args.seeds!r}")
    if not seeds:
        parser.error("--seeds に1つ以上の整数を指定してください")
    if len(set(seeds)) != len(seeds):
        parser.error(f"--seeds に重複したシード値が含まれています: {seeds}")
    for s in seeds:
        if not (0 <= s <= 9007199254740991):
            parser.error(f"不正なシード値です: {s}")

    # Build a single multi-segment scenario with per-segment `seed` so all candidates
    # are synthesized in ONE Colab job (one model load, atomic stop-after-download).
    segments = [
        {"id": f"cand_{idx:02d}", "speaker_id": "audition", "text": args.text, "seed": seed, "pause_after_ms": 500}
        for idx, seed in enumerate(seeds, 1)
    ]
    scenario = {
        "schema_version": 2,
        "speakers": {"audition": {"name": "試聴", "kind": "narrator", "voice_caption": caption}},
        "segments": segments,
    }
    # Use `normalizeRmsDb: None` so adopted reference WAVs keep unclipped raw engine dynamics
    st_doc = {
        "title": f"voicekit_{args.job_prefix}",
        "ttsEngine": "drama3",
        "ttsModel": "Aratako/Drama-3-Japanese",
        "backend": "speech_cpp_gguf",
        "quant": "IQ3_XXS",
        "sampleRate": 44100,
        "normalizeRmsDb": None,
        "reading": "shared",
        "voiceMode": "design",
        "baseCaption": caption,
        "seed": seeds[0],
        "pause": 0.5,
    }

    if args.dry_run:
        print(json.dumps({"caption": caption, "text": args.text, "seeds": seeds, "gpu": args.gpu, "scenario": scenario}, ensure_ascii=False, indent=2))
        return 0

    if not args.out:
        parser.error("--out を指定してください")
    out_dir = args.out.resolve()
    if out_dir.exists():
        if not out_dir.is_dir() or any(out_dir.iterdir()):
            print(f"ERROR: 出力先フォルダーが既に存在し空ではありません: {out_dir}", file=sys.stderr)
            return 1

    run_work = out_dir / "_cli_batch"
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = []
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sc_path = tmp / "audition_scenario.json"
            st_path = tmp / "audition_settings.json"
            sc_path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")
            st_path.write_text(json.dumps(st_doc, ensure_ascii=False, indent=2), encoding="utf-8")

            cmd = [
                sys.executable, str(CLI_SCRIPT),
                "--scenario", str(sc_path),
                "--settings", str(st_path),
                "--session", args.session,
                "--job", f"{args.job_prefix}batch",
                "--out", str(run_work),
                "--gpu", args.gpu,
                "--timeout", str(args.timeout),
            ]
            if args.new:
                cmd.append("--new")
            if args.prebuilt_bin:
                cmd.extend(["--prebuilt-bin", str(args.prebuilt_bin)])
            if args.skip_binary_upload:
                cmd.append("--skip-binary-upload")
            if args.keep_on_error:
                cmd.append("--keep-on-error")
            if not args.keep_session:
                cmd.append("--stop-after-download")
            proc = subprocess.run(cmd, check=False)
            if proc.returncode != 0:
                print(f"ERROR: 候補音声の生成に失敗しました (詳細: {run_work / 'pipeline.json'})", file=sys.stderr)
                return proc.returncode

        # Extract raw per-seed WAVs from segments.zip
        with zipfile.ZipFile(run_work / "segments.zip", "r") as zf:
            names = zf.namelist()
            for idx, seed in enumerate(seeds, 1):
                seg_id = f"cand_{idx:02d}"
                matched = next((n for n in names if n.startswith(f"audio/{seg_id}_") and n.endswith(".wav")), None)
                if matched is None:
                    raise RuntimeError(f"segments.zip 内に {seg_id} が見つかりません")
                cand_name = f"candidate_{idx:02d}_seed{seed}.wav"
                (out_dir / cand_name).write_bytes(zf.read(matched))
                candidates.append({"index": idx, "seed": seed, "file": cand_name})
        shutil.rmtree(run_work, ignore_errors=True)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    (out_dir / "candidates.json").write_text(
        json.dumps({"caption": caption, "text": strip_inline_tags(args.text).strip(), "candidates": candidates}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"VOICE_KIT_READY {out_dir} ({len(candidates)} candidates)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
