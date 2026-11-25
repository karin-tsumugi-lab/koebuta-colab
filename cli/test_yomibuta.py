#!/usr/bin/env python3
"""Comprehensive CPU-only unit tests for Yomibuta Drama-3 CLI, ruby, worker recovery, voice_kit, and Inspector."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import wave
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parent
REPO_ROOT = CLI_DIR.parent
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import yomibuta_generate
from yomibuta_cli.audio import assemble_wavs, pack_segments_zip, wav_info
from yomibuta_cli.core import CONTRACT, atomic_json, file_hash, load_json
from yomibuta_cli.plan import PlanError, build_plan
from yomibuta_cli import remote_worker
from yomibuta_cli.ruby import apply_added_ruby, expand_inline_ruby


def _make_wav(path: Path, frames: int = 4410, sr: int = 44100, channels: int = 1, sampwidth: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sr)
        sample = b"\x10\x00" if sampwidth == 2 else b"\x80"
        wf.writeframes(sample * frames * channels)


class TestYomibutaPlanAndValidation(unittest.TestCase):
    def _base_settings(self, **overrides):
        s = {
            "title": "テスト朗読",
            "ttsEngine": "drama3",
            "ttsModel": "Aratako/Drama-3-Japanese",
            "backend": "speech_cpp_gguf",
            "quant": "IQ3_XXS",
            "sampleRate": 44100,
            "reading": "shared",
            "voiceMode": "design",
            "baseCaption": "落ち着いた大人の女性。",
            "seed": 42,
            "pause": 0.28,
        }
        s.update(overrides)
        return s

    def test_schema_v2_basic_and_scene_caption_in_design_mode(self):
        scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {
                    "id": "t0010",
                    "speaker_id": "narrator",
                    "text": "井戸から冷い水をくんだ。",
                    "tts_text": "[囁き]井戸から｜冷い《つめたい》水をくんだ。[吐息]",
                    "scene_caption": "静かな部屋、耳元に近い距離感。",
                    "acting_description": "優しく語りかける",
                    "pause_after_ms": 350,
                }
            ],
        }
        plan = build_plan(scenario, self._base_settings())
        self.assertEqual(plan["schema_version"], 2)
        self.assertEqual(plan["diagnostics"], [])
        req = plan["requests"][0]
        self.assertEqual(req["pause_after_ms"], 350)
        self.assertIn("つめたい", req["request"]["spoken_text"])
        self.assertIn("[囁き]", req["request"]["spoken_text"])
        self.assertIn("静かな部屋", req["request"]["caption"])
        self.assertTrue(req["request"]["prompt"].startswith("["))

    def test_clone_mode_suppresses_freeform_caption_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_wav(tmp / "ref.wav")
            scenario = {
                "schema_version": 2,
                "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
                "segments": [
                    {
                        "id": "t0040",
                        "speaker_id": "narrator",
                        "text": "「明日には晴れるといいですね」",
                        "tts_text": "[笑いながら]明日には晴れるといいですね。",
                        "scene_caption": "静かな部屋",
                        "acting_description": "穏やかに微笑みながら",
                    }
                ],
            }
            plan = build_plan(
                scenario,
                self._base_settings(
                    voiceMode="clone",
                    voices={"narrator": [{"wav": "ref.wav", "transcript": "別の参照音声テキストです。"}]},
                ),
                base_dir=tmp,
            )
            req = plan["requests"][0]["request"]
            self.assertEqual(req["caption"], "")
            self.assertEqual(req["prompt"], "[笑いながら]明日には晴れるといいですね。")

    def test_clone_mode_bridges_inspector_speaker_reference_clips(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_wav(tmp / "voices" / "aoi.wav")
            scenario = {
                "schema_version": 2,
                "speakers": {
                    "aoi": {
                        "name": "葵",
                        "kind": "character",
                        "reference_clips": [{"wav": "voices/aoi.wav", "transcript": "参照の台詞です。"}],
                    }
                },
                "segments": [{"id": "t0010", "speaker_id": "aoi", "text": "本番の台詞です。"}],
            }
            plan = build_plan(
                scenario,
                self._base_settings(voiceMode="clone", reading="cast"),
                base_dir=tmp,
            )
            self.assertIn("aoi", plan["voices"])
            self.assertEqual(plan["requests"][0]["request"]["voice_profile"], "aoi")

    def test_unknown_inline_tag_and_duplicate_transcript_warnings(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            _make_wav(tmp / "ref.wav")
            scenario = {
                "schema_version": 2,
                "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
                "segments": [
                    {
                        "id": "t0020",
                        "speaker_id": "narrator",
                        "text": "ねえ、そんなに急がないで。",
                        "tts_text": "[未学習の謎タグ][囁き]ねえ、そんなに急がないで。",
                    }
                ],
            }
            plan = build_plan(
                scenario,
                self._base_settings(
                    voiceMode="clone",
                    voices={"narrator": [{"wav": "ref.wav", "transcript": "ねえ、そんなに急がないで。"}]},
                ),
                base_dir=tmp,
            )
            codes = [d["code"] for d in plan["diagnostics"]]
            self.assertIn("W_UNKNOWN_INLINE_TAG", codes)
            self.assertIn("W_SAME_AS_REFERENCE_TRANSCRIPT", codes)

    def test_bool_rejected_where_int_expected(self):
        scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {"id": "t0001", "speaker_id": "narrator", "text": "テストです。", "pause_after_ms": True}
            ],
        }
        with self.assertRaises(PlanError):
            build_plan(scenario, self._base_settings())
        with self.assertRaises(PlanError):
            build_plan(
                {
                    "schema_version": 2,
                    "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
                    "segments": [{"id": "t0001", "speaker_id": "narrator", "text": "テストです。"}],
                },
                self._base_settings(seed=True),
            )

    def test_schema_v1_backward_compat_emoji_and_ruby_auto_deferred(self):
        scenario = {
            "schema_version": 1,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {
                    "id": "t0001",
                    "speaker_id": "narrator",
                    "text": "😆井戸から冷い水をくんだ。",
                    "emotion": "whisper",
                    "koebuta_added_ruby": [
                        {"start": 5, "end": 7, "surface": "冷い", "reading": "つめたい", "selection": "auto"}
                    ],
                }
            ],
        }
        plan = build_plan(scenario, self._base_settings())
        req = plan["requests"][0]
        self.assertIn("[嬉しそうに]", req["request"]["spoken_text"])
        self.assertIn("冷い", req["request"]["spoken_text"])
        codes = [d["code"] for d in plan["diagnostics"]]
        self.assertIn("W_RUBY_AUTO_DEFERRED", codes)
        self.assertIn("W_V1_EMOJI_CONVERTED", codes)

    def test_non_dict_speaker_raises_plan_error_not_attribute_error(self):
        scenario = {
            "schema_version": 2,
            "speakers": {"narrator": "not_a_dict"},
            "segments": [{"id": "t0001", "speaker_id": "narrator", "text": "テストです。"}],
        }
        with self.assertRaises(PlanError) as ctx:
            build_plan(scenario, self._base_settings())
        self.assertIn("speakers", str(ctx.exception))

    def test_invalid_text_format_raises_e_settings_not_value_error(self):
        scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {"id": "t0001", "speaker_id": "narrator", "text": "テスト。", "text_format": "markdown"}
            ],
        }
        with self.assertRaises(PlanError) as ctx:
            build_plan(scenario, self._base_settings())
        self.assertIn("E_SETTINGS", str(ctx.exception))

        scenario2 = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [{"id": "t0001", "speaker_id": "narrator", "text": "テスト。"}],
        }
        with self.assertRaises(PlanError) as ctx2:
            build_plan(scenario2, self._base_settings(textOptions={"format": "html"}))
        self.assertIn("E_SETTINGS", str(ctx2.exception))

    def test_unknown_emotion_id_rejected(self):
        scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {"id": "t0001", "speaker_id": "narrator", "text": "テストです。", "emotion": "super_happy"}
            ],
        }
        with self.assertRaises(PlanError) as ctx:
            build_plan(scenario, self._base_settings())
        self.assertIn("E_EMOTION", str(ctx.exception))

    def test_forbidden_control_token_rejected_in_text_and_captions(self):
        for field_override in (
            {"tts_text": "<|speaker:0|>こんにちは。"},
            {"scene_caption": "静かな部屋 <|speaker:1|>"},
            {"acting_description": "<|im_end|>優しく"},
        ):
            seg = {"id": "t0001", "speaker_id": "narrator", "text": "こんにちは。", **field_override}
            scenario = {
                "schema_version": 2,
                "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
                "segments": [seg],
            }
            with self.assertRaises(PlanError) as ctx:
                build_plan(scenario, self._base_settings(reading="cast"))
            self.assertIn("E_FORBIDDEN_CONTROL_TOKEN", str(ctx.exception))

        scenario_vc = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator", "voice_caption": "女性 <|speaker:2|>"}},
            "segments": [{"id": "t0001", "speaker_id": "narrator", "text": "こんにちは。"}],
        }
        with self.assertRaises(PlanError) as ctx_vc:
            build_plan(scenario_vc, self._base_settings(reading="cast"))
        self.assertIn("E_FORBIDDEN_CONTROL_TOKEN", str(ctx_vc.exception))

    def test_unknown_segment_key_typo_rejected(self):
        scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {"id": "t0001", "speaker_id": "narrator", "text": "テストです。", "pause_after_mss": 500}
            ],
        }
        with self.assertRaises(PlanError) as ctx:
            build_plan(scenario, self._base_settings())
        self.assertIn("pause_after_mss", str(ctx.exception))

    def test_added_ruby_validated_and_warned_when_tts_text_present(self):
        # Invalid out-of-range added_ruby must still fail even if tts_text is present
        bad_scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {
                    "id": "t0001",
                    "speaker_id": "narrator",
                    "text": "短い文。",
                    "tts_text": "みじかいぶん。",
                    "koebuta_added_ruby": [
                        {"start": 0, "end": 99, "surface": "短い", "reading": "みじかい", "selection": "kana"}
                    ],
                }
            ],
        }
        with self.assertRaises(PlanError) as ctx:
            build_plan(bad_scenario, self._base_settings())
        self.assertIn("E_RUBY", str(ctx.exception))

        # Valid added_ruby alongside tts_text emits W_ADDED_RUBY_IGNORED_BY_TTS_TEXT
        ok_scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {
                    "id": "t0001",
                    "speaker_id": "narrator",
                    "text": "短い文。",
                    "tts_text": "みじかいぶん。",
                    "koebuta_added_ruby": [
                        {"start": 0, "end": 2, "surface": "短い", "reading": "みじかい", "selection": "kana"}
                    ],
                }
            ],
        }
        plan = build_plan(ok_scenario, self._base_settings())
        codes = [d["code"] for d in plan["diagnostics"]]
        self.assertIn("W_ADDED_RUBY_IGNORED_BY_TTS_TEXT", codes)

    def test_ruby_formats_narou_kakuyomu_pixiv_and_added_ruby_modes(self):
        narou_out, nw = expand_inline_ruby("彼は聖剣(エクス・カリバー)と｜（括弧）を抜いた。", "narou")
        self.assertEqual(narou_out, "彼はエクス・カリバーと（括弧）を抜いた。")
        self.assertEqual(nw, [])

        kaku_out, kw = expand_inline_ruby("《《強調》》と｜《エスケープと｜硝子《ガラス》。", "kakuyomu")
        self.assertEqual(kaku_out, "強調と《エスケープとガラス。")
        self.assertEqual(kw, [])

        pixiv_out, pw = expand_inline_ruby("これは[[rb:運命 > さだめ]]だ。", "pixiv")
        self.assertEqual(pixiv_out, "これはさだめだ。")
        self.assertEqual(pw, [])
        _, pw_bad = expand_inline_ruby("壊れた[[rb:記法", "pixiv")
        self.assertTrue(len(pw_bad) > 0)

        text = "風と硝子の音。"
        kana_res, diags_k = apply_added_ruby(
            text,
            [
                {"start": 0, "end": 1, "surface": "風", "reading": "かぜ", "selection": "surface"},
                {"start": 2, "end": 4, "surface": "硝子", "reading": "ガラス", "selection": "kana"},
            ],
            sid="t1",
            fmt="none",
        )
        self.assertEqual(kana_res, "風とガラスの音。")
        self.assertEqual(diags_k, [])

        with self.assertRaises(ValueError):
            apply_added_ruby(text, "not_a_list", sid="t1")

    def test_separator_pause_inheritance_blank_lines_and_ids_filter(self):
        scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {"id": "t0010", "speaker_id": "narrator", "text": "第一段落です。"},
                {"id": "sep01", "segment_type": "separator", "pause_after_ms": 1500},
                {"id": "t0015", "speaker_id": "narrator", "text": "短い区切りです。"},
                {"id": "sep_short", "segment_type": "separator", "pause_after_ms": 100},
                {"id": "t0018", "speaker_id": "narrator", "text": "省略区切りです。"},
                {"id": "sep_default", "segment_type": "separator"},
                {"id": "t0020", "speaker_id": "narrator", "text": "第二段落です。", "blank_lines_after": 1},
                {"id": "t0030", "speaker_id": "narrator", "text": "第三段落です。"},
            ],
        }
        # Default (faithful.py strict compat): omitted separator & blank_lines_after stay 280ms; explicit short 100ms honored
        plan_default = build_plan(scenario, self._base_settings())
        pauses_def = {r["segment_id"]: r["pause_after_ms"] for r in plan_default["requests"]}
        self.assertEqual(pauses_def["t0010"], 1500)
        self.assertEqual(pauses_def["t0015"], 100)
        self.assertEqual(pauses_def["t0018"], 280)
        self.assertEqual(pauses_def["t0020"], 280)

        # Opt-in blankLinePauseMs activates blank_lines_after
        plan = build_plan(scenario, self._base_settings(blankLinePauseMs=1100))
        pauses_opt = {r["segment_id"]: r["pause_after_ms"] for r in plan["requests"]}
        self.assertEqual(pauses_opt["t0020"], 1100)
        self.assertEqual(pauses_opt["t0030"], 280)

        sub_plan = build_plan(scenario, self._base_settings(), selected_ids=["t0030"])
        self.assertEqual([r["segment_id"] for r in sub_plan["requests"]], ["t0030"])

        with self.assertRaises(PlanError) as ctx:
            build_plan(scenario, self._base_settings(), selected_ids=["missing_id"])
        self.assertIn("E_SELECTION", str(ctx.exception))

    def test_unhashable_speaker_id_temperature_upper_bound_and_shared_caption_warning(self):
        # R1: array/dict speaker_id or segment_type must raise PlanError, never TypeError
        for bad_seg in (
            {"id": "t0001", "speaker_id": ["arr"], "text": "テスト。"},
            {"id": "t0001", "speaker_id": "narrator", "segment_type": ["bad"], "text": "テスト。"},
        ):
            with self.assertRaises(PlanError):
                build_plan(
                    {
                        "schema_version": 2,
                        "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
                        "segments": [bad_seg],
                    },
                    self._base_settings(),
                )

        # R3: temperature > 2.0 rejected
        with self.assertRaises(PlanError) as ctx_t:
            build_plan(
                {
                    "schema_version": 2,
                    "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
                    "segments": [{"id": "t0001", "speaker_id": "narrator", "text": "テスト。"}],
                },
                self._base_settings(engineOptions={"temperature": 5.0}),
            )
        self.assertIn("temperature", str(ctx_t.exception))

        # F13: shared + design warns when speaker voice_caption is ignored
        plan_w = build_plan(
            {
                "schema_version": 2,
                "speakers": {"narrator": {"name": "語り手", "kind": "narrator", "voice_caption": "固有の声"}},
                "segments": [{"id": "t0001", "speaker_id": "narrator", "text": "テスト。"}],
            },
            self._base_settings(reading="shared", voiceMode="design"),
        )
        self.assertIn("W_SPEAKER_VOICE_CAPTION_IGNORED", [d["code"] for d in plan_w["diagnostics"]])

    def test_sglang_pip_spec_rejects_unpinned_git_branch(self):
        scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [{"id": "t0001", "speaker_id": "narrator", "text": "テストです。"}],
        }
        with self.assertRaises(PlanError) as ctx:
            build_plan(
                scenario,
                self._base_settings(
                    backend="official",
                    quant="none",
                    engineOptions={"sglang_pip_spec": "git+https://github.com/sgl-project/sglang-omni.git@main"},
                ),
            )
        self.assertIn("sglang_pip_spec", str(ctx.exception))

        pinned_sha = "0123456789abcdef0123456789abcdef01234567"
        ok_plan = build_plan(
            scenario,
            self._base_settings(
                backend="official",
                quant="none",
                engineOptions={"sglang_pip_spec": f"git+https://github.com/sgl-project/sglang-omni.git@{pinned_sha}"},
            ),
        )
        self.assertIn(pinned_sha, ok_plan["settings"]["engineOptions"]["sglang_pip_spec"])

    def test_load_json_rejects_duplicate_keys_and_nan(self):
        with tempfile.TemporaryDirectory() as td:
            p_dup = Path(td) / "dup.json"
            p_dup.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_json(p_dup)

            p_nan = Path(td) / "nan.json"
            p_nan.write_text('{"a": NaN}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_json(p_nan)

    def test_raw_bracket_warning_and_clone_max_3_clips(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for i in range(4):
                _make_wav(tmp / f"ref{i}.wav")
            scenario = {
                "schema_version": 2,
                "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
                "segments": [{"id": "t0001", "speaker_id": "narrator", "text": "これは[注]テストです。"}],
            }
            plan = build_plan(scenario, self._base_settings())
            self.assertIn("W_RAW_BRACKET_IN_TEXT", [d["code"] for d in plan["diagnostics"]])

            with self.assertRaises(PlanError) as ctx:
                build_plan(scenario, self._base_settings(voiceMode="clone", voices={"v1": "ref0.wav"}), base_dir=tmp)
            self.assertIn("E_REFERENCE_TRANSCRIPT_REQUIRED", str(ctx.exception))

            clips4 = [{"wav": f"ref{i}.wav", "transcript": f"台詞{i}"} for i in range(4)]
            with self.assertRaises(PlanError) as ctx2:
                build_plan(scenario, self._base_settings(voiceMode="clone", voices={"v1": clips4}), base_dir=tmp)
            self.assertIn("E_REFERENCE", str(ctx2.exception))

    def test_author_ruby_overlap_with_added_ruby_rejected(self):
        scenario = {
            "schema_version": 2,
            "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
            "segments": [
                {
                    "id": "t0001",
                    "speaker_id": "narrator",
                    "text": "これは｜硝子《ガラス》の器だ。",
                    "koebuta_added_ruby": [
                        {"start": 4, "end": 6, "surface": "硝子", "reading": "しょうし", "selection": "kana"}
                    ],
                }
            ],
        }
        with self.assertRaises(PlanError) as ctx:
            build_plan(scenario, self._base_settings())
        self.assertIn("E_RUBY", str(ctx.exception))

    def test_wav_assembly_rms_normalization_and_chunk_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            w_quiet = tmp / "quiet.wav"
            w_loud = tmp / "loud.wav"
            for path, amp in ((w_quiet, 1000), (w_loud, 16000)):
                with wave.open(str(path), "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(44100)
                    wf.writeframes((amp.to_bytes(2, "little", signed=True) + (-amp).to_bytes(2, "little", signed=True)) * 2205)
            takes = [
                {"segment_id": "t0001", "filename": "t0001.wav", "path": str(w_quiet), "pause_after_ms": 500},
                {"segment_id": "t0002", "filename": "t0002.wav", "path": str(w_loud), "pause_after_ms": 0},
            ]
            out_wav = tmp / "norm.wav"
            meta = assemble_wavs(takes, out_wav, expected_sample_rate=44100, normalize_rms_db=-18.0)
            self.assertGreater(meta["applied_gains_db"]["t0001"], 0.0)
            self.assertLess(meta["applied_gains_db"]["t0002"], 0.0)
            self.assertLessEqual(meta["peak_dbfs"], -0.9)
            zmeta = pack_segments_zip(takes, tmp / "segments.zip")
            self.assertGreater(zmeta["bytes"], 0)

            payload = b"ABCD1234" * 1024
            src = tmp / "orig.bin"
            src.write_bytes(payload)
            chunks = remote_worker._split_for_download(src, str(tmp / "dl"))
            self.assertEqual(len(chunks), 1)
            target = tmp / "restored.bin"
            (tmp / "restored.bin.part00").write_bytes(payload[:1000])
            (tmp / "restored.bin.part01").write_bytes(payload[1000:])
            remote_worker._reassemble_if_chunked(target, 2)
            self.assertEqual(target.read_bytes(), payload)


class TestCliRecoveryManifestAndStopSafety(unittest.TestCase):
    def _write_scenario_and_settings(self, tmp: Path) -> tuple[Path, Path]:
        sc = tmp / "scenario.json"
        st = tmp / "settings.json"
        atomic_json(
            sc,
            {
                "schema_version": 2,
                "speakers": {"narrator": {"name": "語り手", "kind": "narrator"}},
                "segments": [{"id": "t0010", "speaker_id": "narrator", "text": "深夜の図書館は静かで、ページをめくる音が響く。"}],
            },
        )
        atomic_json(
            st,
            {
                "title": "テスト",
                "ttsEngine": "drama3",
                "backend": "speech_cpp_gguf",
                "quant": "IQ3_XXS",
                "sampleRate": 44100,
                "voiceMode": "design",
                "baseCaption": "落ち着いた女性。",
                "seed": 42,
                "pause": 0.28,
            },
        )
        return sc, st

    def test_cli_exit_code_2_on_bad_json_and_bad_identifier(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            bad_json = tmp / "bad.json"
            bad_json.write_text("{broken json", encoding="utf-8")
            _, st = self._write_scenario_and_settings(tmp)
            stderr = io.StringIO()
            with mock.patch("sys.stderr", stderr):
                rc = yomibuta_generate.main(["--scenario", str(bad_json), "--settings", str(st), "--dry-run"])
            self.assertEqual(rc, 2)

            sc, st = self._write_scenario_and_settings(tmp)
            with mock.patch("sys.stderr", io.StringIO()):
                rc2 = yomibuta_generate.main(
                    [
                        "--scenario", str(sc),
                        "--settings", str(st),
                        "--session", "../bad_session",
                        "--job", "run01",
                        "--out", str(tmp / "out"),
                    ]
                )
            self.assertEqual(rc2, 2)

    def test_verify_and_collect_rejects_stale_nonce_signature_and_wrong_wav_format(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            remote_dir = tmp / "remote"
            remote_dir.mkdir()
            valid_wav = remote_dir / "res.part000"
            _make_wav(valid_wav, frames=4410, sr=44100)
            seg_zip = remote_dir / "seg.part000"
            seg_zip.write_bytes(b"PK\x05\x06" + b"\x00" * 18)

            w_meta = wav_info(valid_wav)
            base_manifest = {
                "contract": CONTRACT,
                "job_id": "run01",
                "nonce": "nonce_good",
                "plan_signature": "sig_good",
                "status": "complete",
                "warnings": [],
                "download_chunks": {
                    "result.wav": [{"remote": str(valid_wav), "bytes": w_meta["bytes"], "sha256": w_meta["sha256"]}],
                    "segments.zip": [{"remote": str(seg_zip), "bytes": seg_zip.stat().st_size, "sha256": file_hash(seg_zip)}],
                },
                "combined": {"file": "result.wav", **w_meta},
                "segments_zip": {"file": "segments.zip", "bytes": seg_zip.stat().st_size, "sha256": file_hash(seg_zip)},
            }
            manifest_remote = remote_dir / "manifest.json"

            def fake_colab(args, *, check=True, timeout=None):
                if args[0] == "download":
                    shutil.copy2(args[3], args[4])
                return subprocess.CompletedProcess(["colab", *args], 0)

            with mock.patch.object(yomibuta_generate, "_run_colab", side_effect=fake_colab):
                # 1. Stale nonce rejected
                (tmp / "o1").mkdir()
                atomic_json(manifest_remote, {**base_manifest, "nonce": "nonce_stale"})
                with self.assertRaisesRegex(RuntimeError, "nonce"):
                    yomibuta_generate._verify_and_collect(
                        session="s1",
                        remote_manifest=str(manifest_remote),
                        out_dir=tmp / "o1",
                        expected_job="run01",
                        expected_plan_signature="sig_good",
                        expected_sample_rate=44100,
                        expected_nonce="nonce_good",
                    )

                # 2. Stale plan_signature rejected
                atomic_json(manifest_remote, {**base_manifest, "plan_signature": "sig_other"})
                (tmp / "o2").mkdir()
                with self.assertRaisesRegex(RuntimeError, "plan_signature"):
                    yomibuta_generate._verify_and_collect(
                        session="s1",
                        remote_manifest=str(manifest_remote),
                        out_dir=tmp / "o2",
                        expected_job="run01",
                        expected_plan_signature="sig_good",
                        expected_sample_rate=44100,
                        expected_nonce="nonce_good",
                    )

                # 3. Wrong WAV sample rate (48kHz instead of 44.1kHz) rejected
                bad_sr_wav = remote_dir / "res48k.part000"
                _make_wav(bad_sr_wav, frames=4800, sr=48000)
                bad_meta = wav_info(bad_sr_wav)
                atomic_json(
                    manifest_remote,
                    {
                        **base_manifest,
                        "download_chunks": {
                            **base_manifest["download_chunks"],
                            "result.wav": [{"remote": str(bad_sr_wav), "bytes": bad_meta["bytes"], "sha256": bad_meta["sha256"]}],
                        },
                        "combined": {"file": "result.wav", **bad_meta},
                    },
                )
                (tmp / "o3").mkdir()
                with self.assertRaisesRegex(RuntimeError, "result.wav"):
                    yomibuta_generate._verify_and_collect(
                        session="s1",
                        remote_manifest=str(manifest_remote),
                        out_dir=tmp / "o3",
                        expected_job="run01",
                        expected_plan_signature="sig_good",
                        expected_sample_rate=44100,
                        expected_nonce="nonce_good",
                    )

                # 4. Exact match succeeds
                atomic_json(manifest_remote, base_manifest)
                (tmp / "o4").mkdir()
                ok, _ = yomibuta_generate._verify_and_collect(
                    session="s1",
                    remote_manifest=str(manifest_remote),
                    out_dir=tmp / "o4",
                    expected_job="run01",
                    expected_plan_signature="sig_good",
                    expected_sample_rate=44100,
                    expected_nonce="nonce_good",
                )
                self.assertTrue(ok)

    def test_stop_after_download_stops_session_on_worker_failure_and_recover_works(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sc, st = self._write_scenario_and_settings(tmp)
            out_dir = tmp / "out_fail"
            calls: list[list[str]] = []

            def fake_colab_fail(args, *, check=True, timeout=None):
                calls.append(args)
                if args[0] == "exec":
                    return subprocess.CompletedProcess(["colab", *args], 1)
                if args[0] == "download":
                    # Simulate status='failed' manifest written by remote_worker
                    inv = load_json(out_dir / "invocation.json")
                    atomic_json(
                        Path(args[4]),
                        {
                            "contract": CONTRACT,
                            "job_id": inv["job"],
                            "nonce": inv["nonce"],
                            "plan_signature": inv["plan_signature"],
                            "status": "failed",
                            "warnings": [],
                        },
                    )
                return subprocess.CompletedProcess(["colab", *args], 0)

            with (
                mock.patch("shutil.which", return_value="/usr/bin/colab"),
                mock.patch.object(yomibuta_generate, "_run_colab", side_effect=fake_colab_fail),
                mock.patch("sys.stderr", io.StringIO()),
            ):
                rc = yomibuta_generate.main(
                    [
                        "--scenario", str(sc),
                        "--settings", str(st),
                        "--session", "sess01",
                        "--job", "job01",
                        "--out", str(out_dir),
                        "--skip-binary-upload",
                        "--stop-after-download",
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertTrue(any(c[0] == "stop" for c in calls))
            pipe = load_json(out_dir / "pipeline.json")
            self.assertTrue(pipe["session_stopped"])
            self.assertEqual(pipe["status"], "failed")

    def test_stop_timeout_is_caught_and_pipeline_json_is_still_written(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sc, st = self._write_scenario_and_settings(tmp)
            out_dir = tmp / "out_stop_timeout"

            def fake_colab_stop_timeout(args, *, check=True, timeout=None):
                if args[0] == "stop":
                    raise subprocess.TimeoutExpired(cmd=["colab", *args], timeout=120)
                if args[0] == "exec":
                    return subprocess.CompletedProcess(["colab", *args], 1)
                if args[0] == "download":
                    inv = load_json(out_dir / "invocation.json")
                    atomic_json(
                        Path(args[4]),
                        {
                            "contract": CONTRACT,
                            "job_id": inv["job"],
                            "nonce": inv["nonce"],
                            "plan_signature": inv["plan_signature"],
                            "status": "failed",
                            "warnings": [],
                        },
                    )
                return subprocess.CompletedProcess(["colab", *args], 0)

            with (
                mock.patch("shutil.which", return_value="/usr/bin/colab"),
                mock.patch.object(yomibuta_generate, "_run_colab", side_effect=fake_colab_stop_timeout),
                mock.patch("sys.stderr", io.StringIO()),
            ):
                rc = yomibuta_generate.main(
                    [
                        "--scenario", str(sc),
                        "--settings", str(st),
                        "--session", "sess01",
                        "--job", "job01",
                        "--out", str(out_dir),
                        "--skip-binary-upload",
                        "--stop-after-download",
                    ]
                )
            self.assertEqual(rc, 1)
            pipe = load_json(out_dir / "pipeline.json")
            self.assertTrue(pipe["stop_failed"])
            self.assertFalse(pipe["session_stopped"])

    def test_remote_worker_incremental_resume_and_early_eos_warning(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            sc, st = self._write_scenario_and_settings(tmp)
            plan = build_plan(load_json(sc), load_json(st))
            job_dir = tmp / "job"
            plan_file = tmp / "plan_in.json"
            manifest_out = tmp / "manifest_out.json"
            atomic_json(plan_file, plan)

            # Synthesize short WAV (0.1s < min_expected_sec) so early EOS warning is recorded
            def fake_cli_synth(speech_bin, model_path, voice_files, prompt, voice_profile, seed, eo, out_wav, deadline):
                _make_wav(out_wav, frames=4410, sr=44100)  # 0.10s for >20 spoken chars

            env_vars = {
                "YOMIBUTA_RUNTIME_ROOT": str(tmp / "rt"),
                "YOMIBUTA_REMOTE_JOB_DIR": str(job_dir),
                "YOMIBUTA_REMOTE_JOB_ID": "job_resume",
                "YOMIBUTA_REMOTE_NONCE": "nonce_123",
                "YOMIBUTA_REMOTE_PLAN": str(plan_file),
                "YOMIBUTA_REMOTE_MANIFEST": str(manifest_out),
                "YOMIBUTA_REMOTE_TIMEOUT": "120",
            }
            with (
                mock.patch.dict(os.environ, env_vars, clear=False),
                mock.patch.object(remote_worker, "_ensure_speech_binary", return_value=tmp / "speech"),
                mock.patch.object(remote_worker, "_ensure_gguf_model", return_value=tmp / "m.gguf"),
                mock.patch.object(remote_worker, "_prepare_voice_profiles", return_value={}),
                mock.patch.object(remote_worker._ResidentSpeechServer, "start", return_value=False) as srv_start_mock,
                mock.patch.object(remote_worker._ResidentSpeechServer, "is_alive", return_value=False),
                mock.patch.object(remote_worker, "_synthesize_cli", side_effect=fake_cli_synth) as synth_mock,
                mock.patch.object(remote_worker, "_split_for_download", return_value=[]),
            ):
                rc1 = remote_worker.main()
                self.assertEqual(rc1, 0)
                # N-01: initial server.start() failed once, so it must NOT spin server.start() on each of the 3 retries!
                self.assertEqual(srv_start_mock.call_count, 1)
                self.assertEqual(synth_mock.call_count, 3)  # Retried 3 times due to short audio
                mf1 = load_json(manifest_out)
                self.assertEqual(mf1["nonce"], "nonce_123")
                self.assertTrue(mf1["takes"][0]["early_eos_suspected"])
                self.assertEqual(mf1["warnings"][0]["code"], "W_EARLY_EOS_SUSPECTED")

                # Second run with same plan reuses takes_state.json with 0 synthesis calls!
                atomic_json(plan_file, plan)
                synth_mock.reset_mock()
                rc2 = remote_worker.main()
                self.assertEqual(rc2, 0)
                self.assertEqual(synth_mock.call_count, 0)
                mf2 = load_json(manifest_out)
                self.assertEqual(mf2["takes"][0]["mode"], "reused")


class TestVoiceKitAndInspectorHygiene(unittest.TestCase):
    def test_voice_kit_adopt_atomic_precheck_when_settings_exists(self):
        vk_dir = REPO_ROOT / "voice_kit"
        if str(vk_dir) not in sys.path:
            sys.path.insert(0, str(vk_dir))
        import yomibuta_voice_kit as vk

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            try_dir = tmp / "try01"
            try_dir.mkdir()
            _make_wav(try_dir / "candidate_01_seed303.wav")
            atomic_json(
                try_dir / "candidates.json",
                {
                    "caption": "落ち着いた女性",
                    "text": "試聴用の参照セリフです。",
                    "candidates": [{"index": 1, "seed": 303, "file": "candidate_01_seed303.wav"}],
                },
            )
            save_wav = tmp / "work" / "voices" / "narrator.wav"
            settings_out = tmp / "work" / "settings.json"
            settings_out.parent.mkdir(parents=True, exist_ok=True)
            settings_out.write_text('{"existing": true}\n', encoding="utf-8")

            # Must fail BEFORE copying save_wav or writing .voice_meta.json!
            with mock.patch("sys.stderr", io.StringIO()):
                rc_fail = vk.main(
                    [
                        "--from-out", str(try_dir),
                        "--adopt", "303",
                        "--save-to", str(save_wav),
                        "--write-settings", str(settings_out),
                    ]
                )
            self.assertEqual(rc_fail, 1)
            self.assertFalse(save_wav.exists())
            self.assertFalse(save_wav.with_suffix(".voice_meta.json").exists())

            # With --overwrite (or fresh settings), succeeds cleanly
            rc_ok = vk.main(
                [
                    "--from-out", str(try_dir),
                    "--adopt", "303",
                    "--save-to", str(save_wav),
                    "--write-settings", str(settings_out),
                    "--overwrite",
                ]
            )
            self.assertEqual(rc_ok, 0)
            self.assertTrue(save_wav.is_file())
            written = load_json(settings_out)
            self.assertEqual(written["voices"]["narrator"][0]["transcript"], "試聴用の参照セリフです。")

    def test_inspector_html_guards_and_cli_export_present(self):
        html_text = (REPO_ROOT / "Yomibuta_Scenario_Inspector_v4.html").read_text(encoding="utf-8")
        self.assertIn("if(Object.hasOwn(s,'koebuta_tts_parts'))throw Error", html_text)
        self.assertIn("function buildCliSettings(doc)", html_text)
        self.assertIn("exportCliSettingsBtn", html_text)


if __name__ == "__main__":
    unittest.main()
