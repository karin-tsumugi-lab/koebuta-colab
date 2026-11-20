import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

import irodori_voice_kit as vkit


class VoiceKitTests(unittest.TestCase):
    def test_parse_seeds_deduplicates_and_validates(self):
        self.assertEqual(vkit.parse_seeds('101, 202, 101, 303'), [101, 202, 303])
        with self.assertRaises(ValueError):
            vkit.parse_seeds('')
        with self.assertRaises(ValueError):
            vkit.parse_seeds('-1')
        with self.assertRaises(ValueError):
            vkit.parse_seeds('abc')

    def test_resolve_job_prefix_uses_out_dir_when_omitted(self):
        self.assertEqual(vkit.resolve_job_prefix(None, Path('outputs/voice_try02')), 'voice_try02')
        self.assertEqual(vkit.resolve_job_prefix('custom-job', Path('outputs/voice_try02')), 'custom-job')
        self.assertEqual(vkit.resolve_job_prefix(None, None), 'vkit')

    def test_list_presets_outputs_all_12_presets(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = vkit.main(['--list-presets'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertEqual(len(vkit.PRESETS), 12)
        for key in vkit.PRESETS:
            self.assertIn(f'[{key}]', out)

    def test_dry_run_builds_sequential_reuse_plan_with_out_derived_job_prefix(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = vkit.main([
                '--preset', 'female_narrator',
                '--seeds', '10,20,30',
                '--out', 'outputs/voice_try02',
                '--new', '--gpu', 'T4',
                '--dry-run',
            ])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload['status'], 'dry_run_ok')
        self.assertEqual(payload['preset'], 'female_narrator')
        self.assertEqual(payload['job_prefix'], 'voice_try02')
        cands = payload['candidates']
        self.assertEqual(len(cands), 3)
        self.assertEqual(cands[0]['job'], 'voice_try02_01_s10')
        self.assertTrue(cands[0]['new_runtime'])
        self.assertFalse(cands[0]['skip_prepare'])
        self.assertFalse(cands[0]['stop_after_download'])
        self.assertFalse(cands[1]['new_runtime'])
        self.assertTrue(cands[1]['skip_prepare'])
        self.assertFalse(cands[1]['stop_after_download'])
        self.assertFalse(cands[2]['new_runtime'])
        self.assertTrue(cands[2]['skip_prepare'])
        self.assertTrue(cands[2]['stop_after_download'])

    def test_dry_run_rejects_invalid_model_via_faithful_planner(self):
        with self.assertRaises(ValueError):
            vkit.main([
                '--preset', 'female_narrator',
                '--model', 'Invalid/Model-Name',
                '--dry-run',
            ])

    def test_adopt_checks_all_destinations_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sample.wav').write_bytes(b'sample')
            (root / 'candidates.json').write_text(json.dumps({
                'candidates': [{'seed': 3, 'wav': 'sample.wav'}]}), encoding='utf-8')
            wav = root / 'voice.wav'
            meta = wav.with_suffix('.voice_meta.json')
            for settings in (wav, meta):
                for overwrite in (False, True):
                    with self.assertRaises(ValueError):
                        vkit.adopt_candidate(root, 3, wav, write_settings=settings, overwrite=overwrite)
                    self.assertFalse(wav.exists())
            meta.write_bytes(b'previous')
            with self.assertRaises(FileExistsError):
                vkit.adopt_candidate(root, 3, wav, write_settings=root / 'settings.json')
            self.assertFalse(wav.exists())
            self.assertFalse((root / 'settings.json').exists())
            self.assertEqual(meta.read_bytes(), b'previous')

    def test_adopt_copies_wav_writes_settings_and_protects_against_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / 'try01'
            out_dir.mkdir()
            wav_file = out_dir / 'candidate_02_seed202.wav'
            wav_file.write_bytes(b'RIFF_DUMMY_WAV')
            summary = {
                'caption': 'テスト用の声質説明',
                'sample_text': 'テスト試聴文',
                'model': 'Aratako/Irodori-TTS-v4.1-Small',
                'steps': 40,
                'candidates': [
                    {'index': 1, 'seed': 101, 'status': 'complete', 'wav': 'candidate_01_seed101.wav'},
                    {'index': 2, 'seed': 202, 'status': 'complete', 'wav': 'candidate_02_seed202.wav'},
                ],
            }
            (out_dir / 'candidates.json').write_text(json.dumps(summary), encoding='utf-8')
            target_wav = root / 'works' / 'my_book' / 'voices' / 'narrator.wav'
            target_settings = root / 'works' / 'my_book' / 'settings.json'
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = vkit.main([
                    '--from-out', str(out_dir),
                    '--adopt', '202',
                    '--save-to', str(target_wav),
                    '--write-settings', str(target_settings),
                ])
            self.assertEqual(rc, 0)
            self.assertEqual(target_wav.read_bytes(), b'RIFF_DUMMY_WAV')
            meta = json.loads(target_wav.with_suffix('.voice_meta.json').read_text(encoding='utf-8'))
            self.assertEqual(meta['adopted_seed'], 202)
            settings_doc = json.loads(target_settings.read_text(encoding='utf-8'))
            self.assertEqual(settings_doc['voices']['voice_a'], 'voices/narrator.wav')

            # Existing destination must fail without --overwrite
            with self.assertRaises(FileExistsError):
                vkit.main([
                    '--from-out', str(out_dir),
                    '--adopt', '202',
                    '--save-to', str(target_wav),
                ])

            # With --overwrite it succeeds
            with redirect_stdout(io.StringIO()):
                rc2 = vkit.main([
                    '--from-out', str(out_dir),
                    '--adopt', '202',
                    '--save-to', str(target_wav),
                    '--write-settings', str(target_settings),
                    '--overwrite',
                ])
            self.assertEqual(rc2, 0)


if __name__ == '__main__':
    unittest.main()
