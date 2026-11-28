from array import array
import io
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
import wave
import zipfile
from contextlib import redirect_stderr, redirect_stdout

import irodori_mix as amix


def make_pcm16_wav_bytes(sr: int, ch: int, duration_s: float, freq: float, amp: float) -> bytes:
    n = int(sr * duration_s)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            val = int(round(math.sin(2.0 * math.pi * freq * i / sr) * amp * 32767.0))
            val = max(-32768, min(32767, val))
            for _ in range(ch):
                frames += struct.pack('<h', val)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def make_float32_wav_bytes(sr: int, ch: int, duration_s: float, freq: float, amp: float) -> bytes:
    n = int(sr * duration_s)
    pcm = bytearray()
    for i in range(n):
        v = math.sin(2.0 * math.pi * freq * i / sr) * amp
        for _ in range(ch):
            pcm += struct.pack('<f', v)
    fmt_chunk = struct.pack('<HHIIHH', 3, ch, sr, sr * ch * 4, ch * 4, 32)
    data_chunk = b'data' + struct.pack('<I', len(pcm)) + pcm
    riff_size = 4 + 8 + len(fmt_chunk) + len(data_chunk)
    return b'RIFF' + struct.pack('<I', riff_size) + b'WAVEfmt ' + struct.pack('<I', len(fmt_chunk)) + fmt_chunk + data_chunk


class AudioMixTests(unittest.TestCase):
    def test_existing_output_is_rejected_before_reading_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / 'result.wav'
            original = make_pcm16_wav_bytes(48000, 1, 0.01, 440.0, 0.5)
            out.write_bytes(original)

            with self.assertRaises(FileExistsError):
                amix.run_mix(root / 'missing_plan.json', out)
            self.assertEqual(out.read_bytes(), original)

    def test_wav_writer_does_not_overwrite_an_output_created_during_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'mixed.wav'
            original = make_pcm16_wav_bytes(48000, 1, 0.01, 440.0, 0.5)
            out.write_bytes(original)
            silence = array('f', [0.0])

            with self.assertRaises(FileExistsError):
                amix.write_stereo_wav16(out, silence, silence, 48000)
            self.assertEqual(out.read_bytes(), original)

    def test_read_16bit_and_32bit_float_wav(self):
        raw16 = make_pcm16_wav_bytes(48000, 1, 0.25, 440.0, 0.5)
        sr, ch, l16, r16, desc = amix.read_wav_bytes(raw16, 'test16.wav')
        self.assertEqual((sr, ch), (48000, 1))
        self.assertEqual(len(l16), len(r16))
        self.assertIn('16bit-PCM', desc)

        raw32f = make_float32_wav_bytes(44100, 2, 0.25, 440.0, 0.01)
        sr2, ch2, l32, r32, desc2 = amix.read_wav_bytes(raw32f, 'test32f.wav')
        self.assertEqual((sr2, ch2), (44100, 2))
        self.assertIn('32bit-float', desc2)
        stats = amix.measure_levels(l32, r32, sr2)
        self.assertAlmostEqual(stats['peak_db'], -40.0, delta=0.5)

    def test_category_gain_respects_max_gain_cap(self):
        # Very quiet foley (-60 dBFS) must be capped at +24 dB instead of boosting noise by +26 dB
        quiet_stats = {'peak_db': -50.0, 'rms_db': -62.0, 'active_rms_db': -60.0, 'max_200ms_db': -58.0}
        gain_db, capped = amix.compute_category_gain(quiet_stats, 'foley', target_tts_rms_db=-18.0)
        self.assertEqual(gain_db, 24.0)
        self.assertTrue(capped)

    def test_init_plan_and_full_mix_with_insert_and_ducked_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / 'run01'
            run_dir.mkdir()
            with zipfile.ZipFile(run_dir / 'segments.zip', 'w') as zf:
                zf.writestr('audio/t0010_extra_def_2.wav', make_pcm16_wav_bytes(48000, 1, 0.4, 350.0, 0.5))
                zf.writestr('audio/t0010_abc_1.wav', make_pcm16_wav_bytes(48000, 1, 0.4, 300.0, 0.5))
            (run_dir / 'plan.json').write_text(json.dumps({
                'requests': [
                    {'id': 't0010', 'segment_id': 't0010', 'pause_after_ms': 280},
                    {'id': 't0010_extra', 'segment_id': 't0010_extra', 'pause_after_ms': 0},
                ],
                'execution': {'leading_pause_ms': 0, 'trailing_pause_ms': 0},
            }), encoding='utf-8')
            scenario_path = root / 'scenario.json'
            scenario_path.write_text(json.dumps({
                'schema_version': 1,
                'speakers': {'n': {'name': '語り手', 'kind': 'narrator'}},
                'segments': [
                    {'id': 't0010', 'speaker_id': 'n', 'text': '一文目。', 'emotion': 'neutral',
                     'notes': ['[効果音] 直後にノック音']},
                    {'id': 't0010_extra', 'speaker_id': 'n', 'text': '二文目。', 'emotion': 'neutral'},
                ],
            }), encoding='utf-8')

            # Create 32-bit float SE and 44.1kHz stereo ambience
            sfx_dir = root / 'sfx'
            sfx_dir.mkdir()
            (sfx_dir / 'knock.wav').write_bytes(make_float32_wav_bytes(48000, 1, 0.2, 800.0, 0.05))
            (sfx_dir / 'rain.wav').write_bytes(make_float32_wav_bytes(44100, 2, 0.3, 220.0, 0.02))

            plan_path = root / 'mix_plan.json'
            with redirect_stdout(io.StringIO()):
                rc = amix.main([
                    '--init-plan', str(plan_path),
                    '--run-dir', str(run_dir),
                    '--scenario', str(scenario_path),
                ])
            self.assertEqual(rc, 0)
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
            self.assertEqual(plan['utterances'][0]['notes'], ['[効果音] 直後にノック音'])
            self.assertEqual(plan['utterances'][0]['file'], 'audio/t0010_abc_1.wav')
            self.assertEqual(plan['utterances'][1]['file'], 'audio/t0010_extra_def_2.wav')

            # Add an inserted SE and a ducked ambience overlay
            plan['utterances'][0]['insert_after'] = [
                {'wav': 'sfx/knock.wav', 'category': 'action', 'pre_gap_ms': 100, 'post_gap_ms': 100}
            ]
            plan['overlays'] = [
                {'wav': 'sfx/rain.wav', 'category': 'ambience', 'start_id': 't0010', 'end_id': 't0010_extra',
                 'loop': True, 'duck_db': -4.0, 'fade_in_ms': 50, 'fade_out_ms': 50}
            ]
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')

            # Dry-run
            dry_buf = io.StringIO()
            with redirect_stdout(dry_buf):
                rc_dry = amix.main(['--plan', str(plan_path), '--dry-run'])
            self.assertEqual(rc_dry, 0)
            dry_out = json.loads(dry_buf.getvalue())
            self.assertEqual(dry_out['status'], 'dry_run_ok')
            self.assertEqual(len(dry_out['tracks']), 2)
            self.assertEqual(dry_out['total_duration_seconds'], 1.2)

            # Full mix
            out_wav = root / 'mixed.wav'
            mix_buf = io.StringIO()
            with redirect_stdout(mix_buf):
                rc_mix = amix.main(['--plan', str(plan_path), '--out', str(out_wav)])
            self.assertEqual(rc_mix, 0)
            self.assertTrue(out_wav.is_file())
            with wave.open(str(out_wav), 'rb') as w:
                self.assertEqual(w.getnchannels(), 2)
                self.assertEqual(w.getframerate(), 48000)
                self.assertAlmostEqual(w.getnframes() / 48000, 1.2, delta=0.05)

    def test_binaural_spatial_creates_ild_itd_and_movement(self):
        raw = make_pcm16_wav_bytes(48000, 1, 0.2, 1000.0, 0.5)
        sr, _, l_in, r_in, _ = amix.read_wav_bytes(raw, 'tone.wav')

        # right_close: right ear must be significantly louder than left ear (ILD + head shadow)
        l_rc, r_rc = amix.apply_binaural_spatial(l_in, r_in, sr, 'right_close')
        rms_l = math.sqrt(sum(v * v for v in l_rc) / len(l_rc))
        rms_r = math.sqrt(sum(v * v for v in r_rc) / len(r_rc))
        self.assertGreater(amix.lin_to_db(rms_r) - amix.lin_to_db(rms_l), 8.0)

        # move_left_to_right: first quarter louder on left, last quarter louder on right
        l_mv, r_mv = amix.apply_binaural_spatial(l_in, r_in, sr, 'move_left_to_right')
        q = len(l_mv) // 4
        self.assertGreater(sum(v * v for v in l_mv[:q]), sum(v * v for v in r_mv[:q]))
        self.assertGreater(sum(v * v for v in r_mv[-q:]), sum(v * v for v in l_mv[-q:]))

    def test_head_shadow_has_monotonic_rolloff_without_comb_notch(self):
        sr = 48000
        far_rms_by_freq: list[float] = []
        # Test intermediate pan ('left_mid' -> right ear is far ear) where dry+2nd-order LPF previously notched
        for freq in (400.0, 1500.0, 3200.0, 7000.0):
            raw = make_pcm16_wav_bytes(sr, 1, 0.15, freq, 0.5)
            _, _, l_in, r_in, _ = amix.read_wav_bytes(raw, f'{freq}.wav')
            # Zero proximity so we measure pure head-shadow frequency response
            _, r_far = amix.apply_binaural_spatial(
                l_in, r_in, sr, {'pan_start': -0.60, 'pan_end': -0.60, 'proximity': 0.0}
            )
            steady = r_far[200:]
            rms = math.sqrt(sum(v * v for v in steady) / len(steady))
            far_rms_by_freq.append(rms)

        self.assertGreater(far_rms_by_freq[0], far_rms_by_freq[1])
        self.assertGreater(far_rms_by_freq[1], far_rms_by_freq[2])
        self.assertGreater(far_rms_by_freq[2], far_rms_by_freq[3])

    def test_equal_power_movement_has_no_center_loudness_bulge(self):
        sr = 48000
        raw = make_pcm16_wav_bytes(sr, 1, 0.4, 440.0, 0.5)
        _, _, l_in, r_in, _ = amix.read_wav_bytes(raw, 'move440.wav')
        l_mv, r_mv = amix.apply_binaural_spatial(
            l_in, r_in, sr, {'pan_start': 0.85, 'pan_end': -0.85, 'proximity': 0.0}
        )
        n = len(l_mv)
        edge_slice = range(64, int(n * 0.15))
        center_slice = range(int(n * 0.45), int(n * 0.55))
        edge_power = sum(0.5 * (l_mv[i] ** 2 + r_mv[i] ** 2) for i in edge_slice) / len(edge_slice)
        center_power = sum(0.5 * (l_mv[i] ** 2 + r_mv[i] ** 2) for i in center_slice) / len(center_slice)
        diff_db = abs(10.0 * math.log10(center_power / edge_power))
        self.assertLess(diff_db, 0.4)

    def test_true_stereo_input_preserves_phase_without_mono_collapse(self):
        sr = 48000
        n = int(sr * 0.1)
        # Anti-phase stereo signal: 0.5*(L+R) would annihilate to 0.0 if collapsed to mono
        l_in = array('f', (0.5 * math.sin(2.0 * math.pi * 440.0 * i / sr) for i in range(n)))
        r_in = array('f', (-v for v in l_in))
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            out_l, out_r = amix.apply_binaural_spatial(l_in, r_in, sr, 'right_close')
        self.assertIn('WARNING', err_buf.getvalue())
        rms_l = math.sqrt(sum(v * v for v in out_l) / n)
        rms_r = math.sqrt(sum(v * v for v in out_r) / n)
        self.assertGreater(rms_r, 0.25)
        self.assertGreater(rms_l, 0.10)

    def test_strict_spatial_validation_and_dry_run_reporting(self):
        with self.assertRaises(ValueError):
            amix.parse_spatial_spec('unknown_preset')
        with self.assertRaises(ValueError):
            amix.parse_spatial_spec({'pan_start': 0.5, 'typo_key': 1.0})
        with self.assertRaises(ValueError):
            amix.parse_spatial_spec({'pan_start': True})

        # Single pan_start without pan_end or preset should stay static at pan_start
        cfg = amix.parse_spatial_spec({'pan_start': 0.75})
        self.assertEqual(cfg['pan_start'], 0.75)
        self.assertEqual(cfg['pan_end'], 0.75)

        # Idempotency check: re-parsing an already normalized spec must succeed and return identical values
        for preset_name in amix.SPATIAL_PRESETS:
            once = amix.parse_spatial_spec(preset_name)
            twice = amix.parse_spatial_spec(once)
            self.assertEqual(once, twice)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wav_path = root / 'u1.wav'
            se_path = root / 'se1.wav'
            wav_path.write_bytes(make_pcm16_wav_bytes(48000, 1, 0.2, 440.0, 0.4))
            se_path.write_bytes(make_pcm16_wav_bytes(48000, 1, 0.15, 800.0, 0.3))
            bad_plan = root / 'bad_plan.json'
            bad_plan.write_text(json.dumps({
                'utterances': [{'id': 't0010', 'file': str(wav_path), 'position': {'bad_key': 1}}],
            }), encoding='utf-8')
            with self.assertRaises(ValueError):
                amix.run_mix(bad_plan, None, dry_run=True)

            good_plan = root / 'good_plan.json'
            good_plan.write_text(json.dumps({
                'utterances': [
                    {
                        'id': 't0010',
                        'file': str(wav_path),
                        'position': 'right_close',
                        'insert_after': [
                            {'wav': str(se_path), 'category': 'foley', 'position': 'left_mid'},
                        ],
                    },
                    {
                        'id': 't0020',
                        'file': str(wav_path),
                        'position': {'preset': 'left_close', 'pan_start': -0.80},
                    },
                ],
            }), encoding='utf-8')
            dry_buf = io.StringIO()
            with redirect_stdout(dry_buf):
                rc = amix.run_mix(good_plan, None, dry_run=True)
            self.assertEqual(rc, 0)
            rep = json.loads(dry_buf.getvalue())
            self.assertEqual(
                rep['utterance_positions'],
                {'t0010': 'right_close', 't0020': {'preset': 'left_close', 'pan_start': -0.80}},
            )

            # Full non-dry-run mix path must also succeed without double-parse errors
            out_wav = root / 'spatial_mixed.wav'
            mix_buf = io.StringIO()
            with redirect_stdout(mix_buf):
                rc_full = amix.run_mix(good_plan, out_wav, dry_run=False)
            self.assertEqual(rc_full, 0)
            self.assertTrue(out_wav.is_file())

    def test_close_preset_applies_front_pinna_presence_and_micro_motion(self):
        sr = 48000
        # 1. Near-ear 3.2 kHz frontal pinna presence boost on right_close vs 1.0 kHz
        raw_1k = make_pcm16_wav_bytes(sr, 1, 0.2, 1000.0, 0.4)
        raw_3k2 = make_pcm16_wav_bytes(sr, 1, 0.2, 3200.0, 0.4)
        _, _, l1, r1, _ = amix.read_wav_bytes(raw_1k, '1k.wav')
        _, _, l3, r3, _ = amix.read_wav_bytes(raw_3k2, '3k2.wav')
        _, out_r1 = amix.apply_binaural_spatial(l1, r1, sr, 'right_close')
        _, out_r3 = amix.apply_binaural_spatial(l3, r3, sr, 'right_close')
        rms_1k = math.sqrt(sum(v * v for v in out_r1[400:]) / (len(out_r1) - 400))
        rms_3k2 = math.sqrt(sum(v * v for v in out_r3[400:]) / (len(out_r3) - 400))
        self.assertGreater(amix.lin_to_db(rms_3k2) - amix.lin_to_db(rms_1k), 1.5)

        # 2. Micro-motion gently modulates far/near ratio over 1.2s, while micro_motion=0.0 stays strictly static
        raw_long = make_pcm16_wav_bytes(sr, 1, 1.2, 600.0, 0.4)
        _, _, ll, rl, _ = amix.read_wav_bytes(raw_long, 'long.wav')
        ml, mr = amix.apply_binaural_spatial(ll, rl, sr, 'right_close')
        sl, sr_fixed = amix.apply_binaural_spatial(ll, rl, sr, {'preset': 'right_close', 'micro_motion': 0.0})

        def ild_db_in(l_ch: array, r_ch: array, slc: slice) -> float:
            rms_l = math.sqrt(sum(v * v for v in l_ch[slc]) / (slc.stop - slc.start))
            rms_r = math.sqrt(sum(v * v for v in r_ch[slc]) / (slc.stop - slc.start))
            return amix.lin_to_db(rms_r) - amix.lin_to_db(rms_l)

        w_start = slice(int(sr * 0.05), int(sr * 0.20))
        w_peak = slice(int(sr * 0.82), int(sr * 0.97))
        self.assertGreater(abs(ild_db_in(ml, mr, w_peak) - ild_db_in(ml, mr, w_start)), 0.30)
        self.assertLess(abs(ild_db_in(sl, sr_fixed, w_peak) - ild_db_in(sl, sr_fixed, w_start)), 0.01)

        # 3. Crossing pan=0 with high proximity ('move_right_to_left') has no step discontinuity
        raw_cross = make_pcm16_wav_bytes(sr, 1, 0.3, 3200.0, 0.4)
        _, _, lc, rc, _ = amix.read_wav_bytes(raw_cross, 'cross.wav')
        cl, cr = amix.apply_binaural_spatial(lc, rc, sr, 'move_right_to_left')
        mid = len(cl) // 2
        max_step_l = max(abs(cl[i] - cl[i - 1]) for i in range(mid - 200, mid + 200))
        max_step_r = max(abs(cr[i] - cr[i - 1]) for i in range(mid - 200, mid + 200))
        # Pure 3.2 kHz sine at amp ~0.55 has max natural sample-to-sample step ~ 0.55 * 2*pi*3200/48000 ≈ 0.23
        self.assertLess(max_step_l, 0.30)
        self.assertLess(max_step_r, 0.30)


if __name__ == '__main__':
    unittest.main()
