"""非GPUの回帰テスト。python3 -m unittest discover -s tests -v"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import speak_pipeline as p


class ScenarioTests(unittest.TestCase):
    def test_standard_output(self):
        sc = p.load_scenario('[tease / 優しく]\nやれやれですね。\n\n[neutral]\nでは始めます。')
        self.assertEqual(sc['schema_version'], 1)
        self.assertEqual(sc['speakers']['assistant']['kind'], 'character')
        self.assertEqual([x['id'] for x in sc['segments']], ['t0001','t0002'])
        self.assertEqual(sc['segments'][0]['acting_description'], '優しく')
        self.assertNotIn('source', sc)
        self.assertEqual(sc['segments'][1]['emotion'], 'neutral')

    def test_unknown_header_uses_neutral_without_spoken_header(self):
        parts = p.parse_script('[surprize / 驚いて]\nそうですか。それは初耳でした。')
        self.assertEqual(parts[0]['emotion'], 'neutral')
        self.assertEqual(parts[0]['acting'], '驚いて')
        self.assertEqual(parts[0]['text'], 'そうですか。それは初耳でした。')

    def test_plain_text_and_embedded_lines(self):
        self.assertEqual(p.parse_script('こんにちは。\n次の行です。')[0]['text'],
                         'こんにちは。\n次の行です。')
        self.assertEqual(p.parse_script('普通の文章。')[0]['emotion'], 'neutral')

    def test_json_input_keeps_original(self):
        sc = p.script_to_scenario('[surprise]\nえっ！\n\n[sad]\nそんなことになっていたのですね。')
        copied = json.dumps(sc, ensure_ascii=False)
        units = p.plan_units(sc)
        self.assertEqual(json.dumps(sc, ensure_ascii=False), copied)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['emotion'], 'sad')
        self.assertIn('驚き', units[0]['acting'])
        self.assertIn('悲しみ', units[0]['acting'])
        self.assertEqual(units[0]['text'], ''.join(s['text'] for s in sc['segments']))

    def test_long_split_is_lossless(self):
        text = 'あいうえお。' * 33
        parts = p.split_text(text)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(len(a) <= p.MAX_CHARS for a in parts))
        self.assertTrue(len(parts) >= 3)

    def test_short_merge_prefers_same_emotion(self):
        sc = p.script_to_scenario('[sad]\nなんと。\n\n[joy]\nおめでとうございます。\n\n[sad]\nそれは残念でしたね。')
        units = p.plan_units(sc)
        self.assertTrue(all(len(u['text']) >= 10 for u in units))
        self.assertEqual(''.join(u['text'] for u in units),
                         ''.join(s['text'] for s in sc['segments']))

    def test_punctuation_spaces_preserved(self):
        text = ('雨が降りました。\n' * 11) + ' そして、終わり。'
        self.assertEqual(''.join(p.split_text(text)), text)

    def test_cannot_merge_over_explicit_pause(self):
        sc = p.script_to_scenario('[surprise]\nえっ！\n\n[neutral]\nそのようですね。')
        sc['segments'][0]['pause_after_ms'] = 0
        units = p.plan_units(sc)
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0]['pause_after_ms'], 0)

    def test_separator_is_barrier(self):
        sc = p.script_to_scenario('[neutral]\nはい。\n\n[neutral]\n進めます。')
        sc['segments'].insert(1, {'id': 'sep', 'segment_type': 'separator', 'pause_after_ms': 900})
        units = p.plan_units(sc)
        self.assertEqual(len(units), 2)
        self.assertEqual(units[0]['pause_after_ms'], 900)

    def test_tts_text_and_narrator(self):
        sc = p.script_to_scenario('[joy]\n今日（きょう）は良い日です。')
        seg = sc['segments'][0]
        seg['tts_text'] = 'きょうは良い日です。'
        sc['speakers']['assistant']['kind'] = 'narrator'
        units = p.plan_units(sc)
        self.assertEqual(units[0]['text'], 'きょうは良い日です。')
        req = p.build_requests(units, 'voice.wav', '', 314, 40, use_emotion=False)
        self.assertFalse(req[0]['text'].startswith('😆'))

    def test_multi_speaker_fails_fast(self):
        sc = p.script_to_scenario('こんにちは。')
        sc['speakers']['other'] = {'name': '別', 'kind': 'character'}
        with self.assertRaisesRegex(ValueError, '単一話者'):
            p.validate_scenario(sc)

    def test_ruby_without_tts_text_fails(self):
        sc = p.script_to_scenario('｜東京《とうきょう》に行きます。')
        with self.assertRaisesRegex(ValueError, 'tts_text'):
            p.validate_scenario(sc)

    def test_long_unpunctuated_tail_is_not_extremely_short(self):
        text = 'あ' * 81
        parts = p.split_text(text)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(p.MIN_CHARS <= len(part) <= p.MAX_CHARS for part in parts))

    def test_invalid_emotion_container_falls_back(self):
        sc = p.script_to_scenario('こんにちは。')
        sc['segments'][0]['emotion'] = ['joy']
        self.assertEqual(p.plan_units(sc)[0]['emotion'], 'neutral')

    def test_short_only_remains_short(self):
        sc = p.script_to_scenario('[neutral]\nはい。')
        units = p.plan_units(sc)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]['text'], 'はい。')

    def test_unknown_emotion_falls_back(self):
        sc = p.script_to_scenario('こんにちは。')
        sc['segments'][0]['emotion'] = 'mystery'
        units = p.plan_units(sc)
        self.assertEqual(units[0]['emotion'], 'neutral')

    def test_no_content_loss_in_mixed_length_segments(self):
        texts = ['小声。','そうですね、これは少し長い文章です。','長い文章です。' * 17,'はい。']
        sc = p.script_to_scenario('\n\n'.join(f'[neutral]\n{t}' for t in texts))
        units = p.plan_units(sc)
        self.assertEqual(''.join(u['text'] for u in units), ''.join(texts))
        self.assertTrue(all(len(u['text']) <= p.MAX_CHARS for u in units))


class FakeRuntimeTests(unittest.TestCase):
    def test_audio_concat_and_pause(self):
        try:
            import numpy as np
            import soundfile as sf
        except ImportError:
            self.skipTest('numpy / soundfile が利用できません')

        class FakeSpeaker:
            def __init__(self, *_):
                self.calls = 0
            def synthesize(self, request):
                self.calls += 1
                return np.ones(800, dtype=np.float32) * .1, 8000

        sc = p.script_to_scenario('[neutral]\nこれは一つ目の音声の文章です。\n\n[neutral]\nこちらが二つ目の音声の文章です。')
        sc['segments'][0]['pause_after_ms'] = 500
        with tempfile.TemporaryDirectory() as td:
            with patch.object(p, 'Speaker', FakeSpeaker):
                path = p.run(json.dumps(sc, ensure_ascii=False), 'dummy.wav', out_dir=td)
            with sf.SoundFile(str(path)) as full:
                # 2 * 0.1 sec + 0.5 sec, no trailing pause
                self.assertEqual(full.frames, 800 + 4000 + 800)
            self.assertTrue((Path(td)/'chunk_001.wav').exists())
            self.assertTrue((Path(td)/'chunk_002.wav').exists())
            self.assertFalse((Path(td)/'speech.partial.wav').exists())


if __name__ == '__main__':
    unittest.main()
