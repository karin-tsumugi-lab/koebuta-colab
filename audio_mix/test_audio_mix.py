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
from contextlib import redirect_stdout

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


if __name__ == '__main__':
    unittest.main()
