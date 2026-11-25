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

from yomibuta_cli.core import identifier

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
    src_dir = args.from_out.resolve()
    cand_json = src_dir / "candidates.json"
    if not cand_json.is_file():
        print(f"ERROR: candidates.json が見つかりません: {cand_json}", file=sys.stderr)
        return 1
    meta = json.loads(cand_json.read_text(encoding="utf-8"))
    chosen = next((c for c in meta.get("candidates", []) if c.get("seed") == args.adopt), None)
    if chosen is None:
        print(f"ERROR: シード {args.adopt} が candidates.json に見つかりません", file=sys.stderr)
        return 1
    src_wav = src_dir / chosen["file"]
    if not src_wav.is_file():
        print(f"ERROR: 候補WAVが見つかりません: {src_wav}", file=sys.stderr)
        return 1

    save_to = args.save_to.resolve()
    voice_meta_path = save_to.with_suffix(".voice_meta.json")
    settings_path = args.write_settings.resolve() if args.write_settings else None

    # Pre-check all target paths BEFORE writing any file to avoid partial-apply states.
    if not args.overwrite:
        if save_to.exists():
            print(f"ERROR: 保存先WAVが既に存在します（--overwrite で上書き可）: {save_to}", file=sys.stderr)
            return 1
        if voice_meta_path.exists():
            print(f"ERROR: メタデータが既に存在します（--overwrite で上書き可）: {voice_meta_path}", file=sys.stderr)
            return 1
        if settings_path is not None and settings_path.exists():
            print(f"ERROR: settings.json が既に存在します（--overwrite で上書き可）: {settings_path}", file=sys.stderr)
            return 1

    save_to.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_wav, save_to)

    voice_meta = {
        "engine": "drama3",
        "seed": chosen["seed"],
        "caption": meta.get("caption", ""),
        "transcript": meta.get("text", ""),
        "source_wav": chosen["file"],
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
        settings_doc = {
            "title": args.title or "新しい朗読",
            "ttsEngine": "drama3",
            "ttsModel": "Aratako/Drama-3-Japanese",
            "backend": "speech_cpp_gguf",
            "quant": "IQ3_XXS",
            "sampleRate": 44100,
            "normalizeRmsDb": -18.0,
            "reading": "shared",
            "voiceMode": "clone",
            "cloneCaption": False,
            "voices": {
                args.profile: [
                    {
                        "wav": rel_wav,
                        "transcript": meta.get("text", ""),
                    }
                ]
            },
            "acting": True,
            "emotion": True,
            "narratorEmotion": True,
            "seed": chosen["seed"],
            "pause": 0.28,
            "engineOptions": {
                "temperature": 0.8,
                "top_p": 0.85,
                "top_k": 30,
                "max_seconds": 47.55,
                "max_pause_frames": 36,
                "experts_on_cpu": False,
            },
        }
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
    parser.add_argument("--skip-binary-upload", action="store_true")
    parser.add_argument("--keep-session", action="store_true")
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
    if not caption:
        parser.error("--preset または --caption を指定してください")
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    if not seeds:
        parser.error("--seeds に1つ以上の整数を指定してください")
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
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"ERROR: 出力先フォルダーが空ではありません: {out_dir}", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        sc_path = tmp / "audition_scenario.json"
        st_path = tmp / "audition_settings.json"
        run_out = tmp / "run_batch"
        sc_path.write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")
        st_path.write_text(json.dumps(st_doc, ensure_ascii=False, indent=2), encoding="utf-8")

        cmd = [
            sys.executable, str(CLI_SCRIPT),
            "--scenario", str(sc_path),
            "--settings", str(st_path),
            "--session", args.session,
            "--job", f"{args.job_prefix}batch",
            "--out", str(run_out),
            "--gpu", args.gpu,
        ]
        if args.new:
            cmd.append("--new")
        if args.skip_binary_upload:
            cmd.append("--skip-binary-upload")
        if not args.keep_session:
            cmd.append("--stop-after-download")
        subprocess.run(cmd, check=True)

        # Extract raw per-seed WAVs from segments.zip
        with zipfile.ZipFile(run_out / "segments.zip", "r") as zf:
            names = zf.namelist()
            for idx, seed in enumerate(seeds, 1):
                seg_id = f"cand_{idx:02d}"
                matched = next((n for n in names if n.startswith(f"audio/{seg_id}_") and n.endswith(".wav")), None)
                if matched is None:
                    raise RuntimeError(f"segments.zip 内に {seg_id} が見つかりません")
                cand_name = f"candidate_{idx:02d}_seed{seed}.wav"
                (out_dir / cand_name).write_bytes(zf.read(matched))
                candidates.append({"index": idx, "seed": seed, "file": cand_name})

    (out_dir / "candidates.json").write_text(
        json.dumps({"caption": caption, "text": args.text, "candidates": candidates}, ensure_ascii=False, indent=2) + "\n",
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
