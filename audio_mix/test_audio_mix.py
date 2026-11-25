#!/usr/bin/env python3
"""CPU-only unit tests for Yomibuta audio_mix (true peak, bounded TTS gain, trim/ID/category errors, fades & loops)."""
from __future__ import annotations

from array import array
import io
import json
import math
import struct
import sys
import tempfile
import unittest
from unittest import mock
import wave
import zipfile
from pathlib import Path

MIX_DIR = Path(__file__).resolve().parent
if str(MIX_DIR) not in sys.path:
    sys.path.insert(0, str(MIX_DIR))

import yomibuta_mix as ym


def _write_pcm16_wav(path: Path, samples_l: list[int], samples_r: list[int] | None = None, sr: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        if samples_r is None:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(samples_l)}h", *samples_l))
        else:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            interleaved = [v for pair in zip(samples_l, samples_r) for v in pair]
            wf.writeframes(struct.pack(f"<{len(interleaved)}h", *interleaved))


class TestAudioMix(unittest.TestCase):
    def test_measure_levels_detects_single_sample_impulse_at_any_offset(self):
        # Stride-3 subsampling previously missed impulses at index 1 or 2 completely.
        for impulse_idx in (1, 2, 5, 17):
            left = array("f", [0.0]) * 4410
            right = array("f", [0.0]) * 4410
            left[impulse_idx] = 0.5  # -6.02 dBFS
            stats = ym.measure_levels(left, right, 44100)
            self.assertAlmostEqual(stats["peak_db"], -6.02, delta=0.05)

    def test_tts_gain_is_power_weighted_and_capped(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # Utterance 1: normal speech (~ -18 dBFS), Utterance 2: near-silent whisper (-75 dBFS)
            u1 = tmp / "u1.wav"
            u2 = tmp / "u2.wav"
            _write_pcm16_wav(u1, [4120, -4120] * 4410)  # ~ -18.0 dBFS
            _write_pcm16_wav(u2, [2, -2] * 4410)        # ~ -84 dBFS
            plan = tmp / "mix_plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "target_tts_rms_db": -18.0,
                        "sample_rate": 44100,
                        "utterances": [
                            {"id": "t0010", "file": str(u1), "pause_after_ms": 100},
                            {"id": "t0020", "file": str(u2), "pause_after_ms": 100},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = ym.run_mix(plan, None, dry_run=True)
            self.assertEqual(rc, 0)
            rep = json.loads(buf.getvalue())
            # Must NOT jump to +33 dB! Should stay ~0 dB because u1 is already -18 dBFS.
            self.assertLessEqual(abs(rep["applied_tts_gain_db"]), 1.0)

            # Even when ALL utterances are very quiet (-42 dBFS), boost is capped at +12.0 dB
            u_quiet = tmp / "quiet.wav"
            _write_pcm16_wav(u_quiet, [260, -260] * 4410)
            plan_q = tmp / "mix_quiet.json"
            plan_q.write_text(
                json.dumps(
                    {
                        "target_tts_rms_db": -18.0,
                        "sample_rate": 44100,
                        "utterances": [{"id": "t0010", "file": str(u_quiet), "pause_after_ms": 0}],
                    }
                ),
                encoding="utf-8",
            )
            buf2 = io.StringIO()
            with mock.patch("sys.stdout", buf2):
                ym.run_mix(plan_q, None, dry_run=True)
            rep2 = json.loads(buf2.getvalue())
            self.assertEqual(rep2["applied_tts_gain_db"], ym.MAX_TTS_GAIN_DB)
            self.assertTrue(rep2["tts_gain_capped"])

    def test_inverted_or_empty_trim_duplicate_id_unknown_category_and_bad_zip_raise_value_error(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            u1 = tmp / "u1.wav"
            se = tmp / "se.wav"
            _write_pcm16_wav(u1, [3000, -3000] * 4410)
            _write_pcm16_wav(se, [3000, -3000] * 4410)  # 200ms

            # 1. Duplicate utterance ID
            p_dup = tmp / "dup.json"
            p_dup.write_text(
                json.dumps(
                    {
                        "utterances": [
                            {"id": "t0010", "file": str(u1)},
                            {"id": "t0010", "file": str(u1)},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "重複"):
                ym.run_mix(p_dup, None, dry_run=True)

            # 2. Inverted trim (start >= end)
            p_trim = tmp / "trim.json"
            p_trim.write_text(
                json.dumps(
                    {
                        "utterances": [
                            {
                                "id": "t0010",
                                "file": str(u1),
                                "insert_after": [{"wav": str(se), "trim_start_ms": 150, "trim_end_ms": 100}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "trim_start_ms"):
                ym.run_mix(p_trim, None, dry_run=True)

            # 3. Trim beyond clip duration (empty slice)
            p_empty = tmp / "empty_trim.json"
            p_empty.write_text(
                json.dumps(
                    {
                        "utterances": [
                            {
                                "id": "t0010",
                                "file": str(u1),
                                "insert_after": [{"wav": str(se), "trim_start_ms": 5000}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "トリム後の音声が空"):
                ym.run_mix(p_empty, None, dry_run=True)

            # 4. Unknown category raises ValueError with cue context (not KeyError)
            p_cat = tmp / "cat.json"
            p_cat.write_text(
                json.dumps(
                    {
                        "utterances": [
                            {
                                "id": "t0010",
                                "file": str(u1),
                                "insert_after": [{"wav": str(se), "category": "explosion_unknown"}],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "t0010.*未対応のカテゴリ"):
                ym.run_mix(p_cat, None, dry_run=True)

            # 5. Corrupt segments.zip raises ValueError (not unhandled BadZipFile)
            bad_zip = tmp / "corrupt.zip"
            bad_zip.write_bytes(b"NOT_A_ZIP_FILE")
            p_zip = tmp / "badzip.json"
            p_zip.write_text(
                json.dumps(
                    {
                        "segments_zip": "corrupt.zip",
                        "utterances": [{"id": "t0010", "file": "audio/t0010.wav"}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "破損"):
                ym.run_mix(p_zip, None, dry_run=True)

    def test_short_non_loop_overlay_fades_out_cleanly_and_loop_crossfades_without_step(self):
        # Verify loop crossfade on constant DC produces zero step/dip
        dc = array("f", [0.5]) * 4410
        loop_l, _ = ym.render_looped_stereo(dc, array("f", dc), 12000, 44100, crossfade_ms=15)
        self.assertEqual(len(loop_l), 12000)
        for v in loop_l:
            self.assertAlmostEqual(v, 0.5, places=5)

        # Verify non-loop short overlay fades out at the end of the clip (before trailing silence)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            # Silent 1.0s utterance so output contains only the short 0.2s non-loop overlay
            u_silent = tmp / "silent_utt.wav"
            _write_pcm16_wav(u_silent, [0] * 44100)
            ov_short = tmp / "short_ov.wav"
            _write_pcm16_wav(ov_short, [16000] * 8820)  # 200ms constant signal

            plan = tmp / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "sample_rate": 44100,
                        "tts_gain_db": 0.0,
                        "utterances": [{"id": "t0010", "file": str(u_silent), "pause_after_ms": 0}],
                        "overlays": [
                            {
                                "wav": str(ov_short),
                                "category": "ambience",
                                "hpf_hz": 0.0,
                                "duck_db": 0.0,
                                "loop": False,
                                "fade_in_ms": 0,
                                "fade_out_ms": 50,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out_wav = tmp / "mixed.wav"
            with mock.patch("sys.stdout", io.StringIO()):
                rc = ym.run_mix(plan, out_wav, dry_run=False)
            self.assertEqual(rc, 0)
            _, _, out_l, _, _ = ym.read_wav_file(out_wav)
            # Sample at 50ms (well before fade-out) should be non-zero, while sample 8819 (end of 200ms clip) must be near 0!
            self.assertGreater(abs(out_l[2205]), 0.005)
            self.assertLess(abs(out_l[8819]), 0.001)

    def test_init_plan_and_stereo_linked_limiter_preserve_balance(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run_dir = tmp / "run01"
            run_dir.mkdir()
            u_wav = tmp / "t0010_abcdef123456.wav"
            _write_pcm16_wav(u_wav, [4000, -4000] * 2205)
            with zipfile.ZipFile(run_dir / "segments.zip", "w") as zf:
                zf.write(u_wav, "audio/t0010_abcdef123456.wav")
            (run_dir / "plan.json").write_text(
                json.dumps(
                    {
                        "settings": {"sampleRate": 44100},
                        "requests": [{"segment_id": "t0010", "pause_after_ms": 300}],
                    }
                ),
                encoding="utf-8",
            )
            mix_plan = tmp / "mix_plan.json"
            with mock.patch("sys.stdout", io.StringIO()):
                ym.init_plan(mix_plan, run_dir)
            doc = json.loads(mix_plan.read_text(encoding="utf-8"))
            self.assertEqual(doc["sample_rate"], 44100)
            self.assertEqual(doc["utterances"][0]["file"], "audio/t0010_abcdef123456.wav")

            # Check stereo-linked limiter preserves L/R ratio (2:1) when limiting loud transients
            lim_wav = tmp / "limited.wav"
            loud_l = array("f", [1.6]) * 100
            loud_r = array("f", [0.8]) * 100
            info = ym.write_stereo_wav16(lim_wav, loud_l, loud_r, 44100, ceiling_db=-1.0)
            self.assertGreater(info["limited_samples"], 0)
            _, _, rd_l, rd_r, _ = ym.read_wav_file(lim_wav)
            self.assertAlmostEqual(rd_l[10] / rd_r[10], 2.0, delta=0.01)

    def test_malformed_wav_bits_zero_strict_init_plan_and_antialias_phase_seam(self):
        # 1. bits=0 malformed WAV header must raise ValueError, never ZeroDivisionError
        bad_fmt = struct.pack("<HHIIHH", 1, 1, 44100, 0, 0, 0)
        bad_wav = b"RIFF" + struct.pack("<I", 36) + b"WAVEfmt " + struct.pack("<I", 16) + bad_fmt + b"data" + struct.pack("<I", 4) + b"\x00\x00\x00\x00"
        with self.assertRaises(ValueError):
            ym.read_wav_bytes(bad_wav, "bits0.wav")

        # 2. Strict init_plan matching must not confuse `t001_part2_<hex>.wav` with `t001`
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            run_dir = tmp / "run_part"
            run_dir.mkdir()
            u_wav = tmp / "dummy.wav"
            _write_pcm16_wav(u_wav, [2000, -2000] * 1000)
            with zipfile.ZipFile(run_dir / "segments.zip", "w") as zf:
                zf.write(u_wav, "audio/t001_part2_abcdef123456.wav")
                zf.write(u_wav, "audio/t001_111111222222.wav")
            (run_dir / "plan.json").write_text(
                json.dumps(
                    {
                        "settings": {"sampleRate": 44100},
                        "requests": [{"segment_id": "t001", "pause_after_ms": 280}],
                    }
                ),
                encoding="utf-8",
            )
            out_plan = tmp / "mp.json"
            with mock.patch("sys.stdout", io.StringIO()):
                ym.init_plan(out_plan, run_dir)
            doc = json.loads(out_plan.read_text(encoding="utf-8"))
            self.assertEqual(doc["utterances"][0]["file"], "audio/t001_111111222222.wav")

        # 3. Downsampling 48kHz -> 44.1kHz attenuates near-Nyquist 23kHz tone
        hi_tone = array("f", [math.sin(2.0 * math.pi * 23000 * i / 48000) for i in range(4800)])
        down = ym.resample_channel(hi_tone, 48000, 44100)
        self.assertLess(max(abs(x) for x in down[100:]), 0.85)

        # 4. Out-of-phase sinusoidal loop seam eliminates hard step jump at seam
        # Construct clip ending at +0.8 and starting at -0.8 (worst-case 1.6 step without crossfade)
        n_clip = 4410
        clip = array("f", [-0.8 * math.cos(math.pi * i / (n_clip - 1)) for i in range(n_clip)])
        loop_l, _ = ym.render_looped_stereo(clip, array("f", clip), 10000, 44100, crossfade_ms=15)
        max_step = max(abs(loop_l[i] - loop_l[i - 1]) for i in range(1, len(loop_l)))
        self.assertLess(max_step, 0.02)


if __name__ == "__main__":
    unittest.main()
