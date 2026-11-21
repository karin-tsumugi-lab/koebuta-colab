import contextlib
import io
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

from irodori_cli.core import atomic_json
from irodori_cli.faithful_worker import execute
from irodori_concat import main
from irodori_generate import load_inputs


class ChapterConcatTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.scenario = self.root / 'scenario.json'
        self.settings = self.root / 'settings.json'
        self.out = self.root / 'joined.wav'

        def speech(sid, text):
            return dict(id=sid, speaker_id='n', text=text, emotion='neutral')

        def separator(sid, pause):
            return dict(id=sid, segment_type='separator', emotion='neutral', pause_after_ms=pause)

        atomic_json(self.scenario, {
            'schema_version': 1,
            'speakers': {'n': {'name': '朗読者', 'kind': 'narrator'}},
            'segments': [separator('start', 20), speech('a', '最初の発話。'),
                         speech('b', '次の発話。'), separator('boundary', 70),
                         speech('c', '次章の発話。'), separator('end', 30)],
        })
        atomic_json(self.settings, {'pause': 0.04})

    def generate(self, name, ids):
        chapter = self.root / name
        chapter.mkdir()
        document, voices, requests = load_inputs(self.scenario, self.settings, selected=ids)

        def infer(request, path):
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, 1000, 0, 'NONE', 'not compressed'))
                output.writeframes(b'\x01\x00' * 10)

        job = chapter / 'job'
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = execute(document, voices, job, infer)
        shutil.copyfile(job / manifest['combined']['file'], chapter / 'result.wav')
        atomic_json(chapter / 'plan.json', {'requests': requests, 'execution': document['execution']})
        atomic_json(chapter / 'pipeline.json', {'status': 'complete', 'execution': document['execution']})
        return chapter

    def concat(self, *chapters):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(['--scenario', str(self.scenario), '--out', str(self.out), *map(str, chapters)])

    def test_matches_full_render_and_preserves_separator_once(self):
        first = self.generate('first', 'a,b')
        last = self.generate('last', 'c')
        full = self.generate('full', None)
        self.assertEqual(self.concat(first, last), 0)
        self.assertEqual(self.out.read_bytes(), (full / 'result.wav').read_bytes())
        with wave.open(str(self.out), 'rb') as audio:
            self.assertEqual(audio.getnframes(), 190)
            frames = audio.readframes(190)
        self.assertEqual(frames[80 * 2:150 * 2], bytes(70 * 2))
        self.assertEqual(frames[150 * 2:160 * 2], b'\x01\x00' * 10)

        original = self.out.read_bytes()
        self.assertEqual(self.concat(first, last), 1)
        self.assertEqual(self.out.read_bytes(), original)

    def test_rejects_wrong_order_missing_or_duplicate_speech(self):
        first = self.generate('first', 'a,b')
        partial = self.generate('partial', 'a')
        last = self.generate('last', 'c')
        for chapters in [(last, first), (partial, last), (first, first, last)]:
            with self.subTest(chapters=chapters):
                self.assertEqual(self.concat(*chapters), 1)
                self.assertFalse(self.out.exists())

    def test_removes_incomplete_output_if_chapter_audio_is_truncated(self):
        first = self.generate('first', 'a,b')
        last = self.generate('last', 'c')
        wav_path = last / 'result.wav'
        wav_path.write_bytes(wav_path.read_bytes()[:-4])
        self.assertEqual(self.concat(first, last), 1)
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
