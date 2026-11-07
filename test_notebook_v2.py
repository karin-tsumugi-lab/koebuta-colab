import io
from pathlib import Path
import tempfile
import unittest
import wave
import zipfile
from notebook.notebook_v2 import CandidateStore, unpack_project, reference_choices


def wav(path):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b'\0\0' * 160)


class Transactions(unittest.TestCase):
    def test_persist_prunes_previous_managed_cache_only(self):
        destination = self.root / 'saved'
        destination.mkdir()
        (destination / 'user.wav').write_bytes(b'user data')
        for seed in range(45):
            self.store.regenerate([dict(self.units[0], seed=seed)], self.generate)
            self.store.discard(['t010#1'])
            self.assertIsNone(self.store.persist(destination))
        self.assertEqual(len(list(destination.glob('*.wav'))), 33)
        self.assertEqual((destination / 'user.wav').read_bytes(), b'user data')

    def test_missing_history_does_not_block_restore_and_copy(self):
        self.store.regenerate(self.units[:1], self.generate)
        self.store.adopt(['t010#1'])
        old = self.store.accepted['t010#1']['file']
        self.store.regenerate(self.units[:1], self.generate)
        self.store.adopt(['t010#1'])
        (self.store.root / old).unlink()
        restored = CandidateStore(self.store.root, self.store.identity)
        restored.restore()
        self.assertTrue(restored.warnings)
        self.assertTrue(restored._valid(restored.accepted['t010#1']))
        self.assertIsNone(restored.persist(self.root / 'recovered'))

    def test_persistence_rejects_other_work(self):
        self.store.regenerate(self.units, self.generate)
        self.store._save(self.store.accepted, self.store.candidates)
        destination = self.root / 'saved'
        self.assertIsNone(self.store.persist(destination))
        before = (destination / 'state.json').read_bytes()
        other = CandidateStore(self.root / 'other', {'model': 'different'})
        other._save({}, {})
        self.assertIn('失敗', other.persist(destination))
        self.assertEqual(before, (destination / 'state.json').read_bytes())

    def test_cache_bound_preserves_accepted_history(self):
        self.store.regenerate(self.units[:1], self.generate)
        self.store.adopt(['t010#1'])
        old = self.store.accepted['t010#1']['file']
        for seed in range(36):
            unit = dict(self.units[0], seed=seed)
            self.store.regenerate([unit], self.generate)
        self.assertLessEqual(len(self.store.cache), 32)
        self.assertTrue((self.store.root / old).is_file())

    def test_reference_uses_global_reading_format(self):
        project = {'reading': 'cast', '_extras': {'koebuta_settings': {'default_text_format': 'aozora'}},
                   'segments': [{'id': str(i), 'role': 'a', 'text': '十分な長さがある通常の文章を参照音声として使用します。'} for i in range(2)]}
        observed = []
        reference_choices(project, lambda text, fmt: (observed.append(fmt) or text, []))
        self.assertEqual(observed, ['aozora', 'aozora'])

    def test_reference_selection_skips_scream_and_single_speaker(self):
        project = {'reading': 'cast', 'segments': [
            {'id': 'a1', 'role': 'a', 'text': 'うわー！'},
            {'id': 'a2', 'role': 'a', 'text': '今日はとてもよい天気ですから、少し遠くの公園まで歩いてみましょう。'},
            {'id': 'b1', 'role': 'b', 'text': '今日はとてもよい天気ですから、少し遠くの公園まで歩いてみましょう。'}]}
        choices = reference_choices(project, lambda text, fmt: (text, []))
        self.assertEqual(choices['a'][0], 'a2')
        self.assertIsNone(choices['b'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ref = self.root / 'reference.wav'
        wav(self.ref)
        self.store = CandidateStore(self.root / 'work', {'model': 'mock', 'revision': '1'})
        self.units = [dict(unit_id=f't010#{i}', segment_id='t010', text=str(i),
                           ref_wav=str(self.ref), seed=314, num_steps=40,
                           caption=None, pause_after_ms=0) for i in (1, 2)]

    def generate(self, unit, path):
        wav(path)

    def test_group_failure_keeps_candidates(self):
        self.store.regenerate(self.units, self.generate)
        before = dict(self.store.candidates)
        def fail(unit, path):
            if unit['unit_id'].endswith('2'):
                raise RuntimeError('mock failure')
            wav(path)
        with self.assertRaises(RuntimeError):
            self.store.regenerate(self.units, fail)
        self.assertEqual(before, self.store.candidates)

    def test_adopt_discard_and_restore(self):
        self.store.regenerate(self.units, self.generate)
        self.store.adopt([u['unit_id'] for u in self.units])
        old = dict(self.store.accepted)
        self.store.regenerate(self.units[:1], self.generate)
        self.assertEqual(old, self.store.accepted)
        self.store.discard(['t010#1'])
        self.assertEqual(old, self.store.accepted)
        restored = CandidateStore(self.store.root, self.store.identity)
        restored.restore()
        self.assertEqual(old, restored.accepted)

    def test_cache_pause_and_forced_generation(self):
        updates = []
        initial = self.store.regenerate(self.units, self.generate,
            progress=lambda value, **kw: updates.append((value, kw['desc'])))
        self.assertEqual(updates[0][0], 0)
        self.assertEqual(updates[-1][0], 1)
        self.assertIn('2/2', updates[-1][1])
        self.units[0]['pause_after_ms'] = 1200
        hit = self.store.regenerate(self.units, lambda *_: self.fail('cache miss'), force=False)
        self.assertEqual(initial, hit)
        fresh = self.store.regenerate(self.units, self.generate)
        self.assertNotEqual(initial['t010#1']['file'], fresh['t010#1']['file'])
        self.units[0]['text'] = 'changed'
        self.assertNotEqual(initial['t010#1']['key'], self.store.key(self.units[0]))

    def test_corrupt_cache_regenerates(self):
        initial = self.store.regenerate(self.units, self.generate)
        (self.store.root / initial['t010#1']['file']).write_bytes(b'broken')
        fresh = self.store.regenerate(self.units, self.generate, force=False)
        self.assertNotEqual(initial['t010#1']['file'], fresh['t010#1']['file'])

    def test_drive_failure_retains_local(self):
        self.store.regenerate(self.units, self.generate)
        blocker = self.root / 'blocker'
        blocker.write_text('file')
        self.assertIn('保持', self.store.persist(blocker / 'state'))
        self.assertTrue(all(self.store._valid(r) for r in self.store.candidates.values()))

    def test_zip_layouts_and_traversal(self):
        for index, prefix in enumerate(('', 'work/')):
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as out:
                out.writestr(prefix + 'scenario.json', '{}')
            archive.seek(0)
            result = unpack_project(archive, self.root / str(index))
            self.assertEqual('{}', (result / 'scenario.json').read_text())
        for index, name in enumerate(('../x', '/x', 'C:/x', 'a\\x')):
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, 'w') as out:
                out.writestr(name, 'bad')
            archive.seek(0)
            with self.assertRaises(ValueError):
                unpack_project(archive, self.root / f'bad{index}')


if __name__ == '__main__':
    unittest.main()
