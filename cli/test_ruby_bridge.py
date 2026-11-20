import contextlib
import io
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parent
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

from irodori_cli.faithful import PlanError
from irodori_cli.faithful_worker import execute, execute_preflight
from irodori_cli.ruby_bridge import apply_ruby_to_scenario
from irodori_generate import load_inputs, main


def _write_dummy_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b'\x00\x00' * 2400)


class TestRubyBridgeIntegration(unittest.TestCase):
    def test_partial_kana_preserves_text_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario = {
                'schema_version': 1,
                'source': 'もっとも、昨夜も夜更かしをされていたようです。',
                'speakers': {'alice': {'name': 'アリス', 'kind': 'narrator'}},
                'segments': [
                    {
                        'id': 's01',
                        'speaker_id': 'alice',
                        'text': 'もっとも、昨夜も夜更かしをされていたようです。',
                        'tts_text': 'もっとも、昨夜《さくや》も夜更《よふ》かしをされていたようです。',
                        'emotion': 'exasperated',
                    }
                ],
            }
            settings = {
                'title': 'ruby test',
                'voiceMode': 'design',
                'reading': 'shared',
                'baseCaption': '落ち着いた日本語の語り。',
            }
            sc_path = root / 'scenario.json'
            st_path = root / 'settings.json'
            sc_path.write_text(json.dumps(scenario, ensure_ascii=False), encoding='utf-8')
            st_path.write_text(json.dumps(settings, ensure_ascii=False), encoding='utf-8')

            doc, _, requests = load_inputs(sc_path, st_path, ruby_mode='partial_kana')
            self.assertEqual(doc['diagnostics'], [])
            self.assertEqual(
                requests[0]['request']['text'],
                '🙄もっとも、さくやもよふかしをされていたようです。',
            )
            self.assertEqual(
                doc['scenario']['segments'][0]['text'],
                'もっとも、昨夜も夜更かしをされていたようです。',
            )

    def test_auto_select_with_mock_scorer_and_invalid_syntax(self):
        scenario = {
            'schema_version': 1,
            'speakers': {'alice': {'name': 'アリス', 'kind': 'narrator'}},
            'segments': [
                {
                    'id': 's01',
                    'speaker_id': 'alice',
                    'text': '本日も昨夜も。',
                    'tts_text': '本日《ほんじつ》も昨夜《さくや》も。',
                    'emotion': 'neutral',
                }
            ],
        }

        class MockScorer:
            def score_span(self, plain, repl, s, e, r):
                return {'本日': (0.7215, 1), '昨夜': (0.5658, 1)}[plain[s:e]]

            def __call__(self, plain, repl, s, e, r):
                return self.score_span(plain, repl, s, e, r)[0]

        updated, report = apply_ruby_to_scenario(
            scenario,
            mode='auto_select',
            threshold=0.8327,
            single_token_threshold=0.65,
            scorer=MockScorer(),
        )
        self.assertEqual(updated['segments'][0]['tts_text'], '本日もさくやも。')
        self.assertEqual([d['selected'] for d in report[0]['decisions']], ['kanji', 'kana'])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = dict(scenario)
            bad['segments'] = [{
                'id': 's01',
                'speaker_id': 'alice',
                'text': 'あいう',
                'tts_text': 'あ《い》う',
                'emotion': 'neutral',
            }]
            sc_path = root / 'scenario.json'
            st_path = root / 'settings.json'
            sc_path.write_text(json.dumps(bad, ensure_ascii=False), encoding='utf-8')
            st_path.write_text(json.dumps({
                'title': 'bad', 'voiceMode': 'design', 'reading': 'shared', 'baseCaption': 'test'
            }, ensure_ascii=False), encoding='utf-8')
            with self.assertRaises(PlanError) as ctx:
                load_inputs(sc_path, st_path, ruby_mode='partial_kana')
            self.assertEqual(ctx.exception.diagnostics[0]['code'], 'E_RUBY_SYNTAX')

    def test_cli_dry_run_with_and_without_session_job_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sc_path = root / 'scenario.json'
            st_path = root / 'settings.json'
            sc_path.write_text(json.dumps({
                'schema_version': 1,
                'speakers': {'a': {'name': 'A', 'kind': 'narrator'}},
                'segments': [{
                    'id': 's01', 'speaker_id': 'a', 'text': '昨夜のこと。',
                    'tts_text': '昨夜《さくや》のこと。', 'emotion': 'neutral',
                }],
            }, ensure_ascii=False), encoding='utf-8')
            st_path.write_text(json.dumps({
                'title': 'cli', 'voiceMode': 'design', 'reading': 'shared', 'baseCaption': 'test'
            }, ensure_ascii=False), encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc1 = main([
                    '--scenario', str(sc_path),
                    '--settings', str(st_path),
                    '--ruby-mode', 'partial_kana',
                    '--dry-run',
                ])
            self.assertEqual(rc1, 0)

    def test_hybrid_absorbs_kakuyomu_and_pixiv_but_not_narou(self):
        scenario = {
            'schema_version': 1,
            'speakers': {'a': {'name': 'A', 'kind': 'narrator'}},
            'segments': [
                {
                    'id': 's01',
                    'speaker_id': 'a',
                    'text': '東京（とうきょう）と李徴と夜更かし。',
                    'tts_text': '東京（注釈）と|李徴《りちょう》と[[rb:夜更かし > よふかし]]。',
                    'emotion': 'neutral',
                }
            ],
        }
        updated, _ = apply_ruby_to_scenario(scenario, mode='partial_kana')
        self.assertEqual(updated['segments'][0]['tts_text'], '東京（注釈）とりちょうとよふかし。')

    def test_remote_auto_select_no_false_length_warning_and_no_torch_on_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sc_path = root / 'scenario.json'
            st_path = root / 'settings.json'
            # Plain text is 54 chars (within 20-80 range), but ruby string is > 90 chars.
            text = 'もっとも、昨夜も夜更かしをされていたようですから、お顔が少しばかりお疲れのようで本当に心配いたしております。'
            tts_ruby = 'もっとも、昨夜《さくや》も[[rb:夜更 > よふ]]かしをされていたようですから、お顔《かお》が少《すこ》しばかりお疲《つか》れのようで本当《ほんとう》に心配《しんぱい》いたしております。'
            self.assertGreater(len(tts_ruby), 80)
            sc_path.write_text(json.dumps({
                'schema_version': 1,
                'source': text,
                'speakers': {'a': {'name': 'A', 'kind': 'narrator'}},
                'segments': [{
                    'id': 's01',
                    'speaker_id': 'a',
                    'text': text,
                    'tts_text': tts_ruby,
                    'emotion': 'exasperated',
                }],
            }, ensure_ascii=False), encoding='utf-8')
            st_path.write_text(json.dumps({
                'title': 'v3-remote', 'voiceMode': 'design', 'reading': 'shared', 'baseCaption': 'test'
            }, ensure_ascii=False), encoding='utf-8')

            doc, _, requests = load_inputs(sc_path, st_path, ruby_mode='auto_select', ruby_device='auto')
            self.assertEqual(doc['diagnostics'], [])
            self.assertEqual(doc['ruby_filter']['mode'], 'auto_select')
            self.assertTrue(requests[0]['request']['text'].startswith('🙄もっとも、昨夜《さくや》も｜夜更《よふ》かし'))

    def test_preflight_and_remote_execute_strip_emotion_prefix_during_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sc_path = root / 'scenario.json'
            st_path = root / 'settings.json'
            sc_path.write_text(json.dumps({
                'schema_version': 1,
                'source': '温かい蒲団で昨夜はゆっくりと眠りましたね。',
                'speakers': {'a': {'name': 'A', 'kind': 'narrator'}},
                'segments': [{
                    'id': 's01',
                    'speaker_id': 'a',
                    'text': '温かい蒲団で昨夜はゆっくりと眠りましたね。',
                    'tts_text': '温《あたた》かい蒲団《ふとん》で昨夜《さくや》はゆっくりと眠《ねむ》りましたね。',
                    'emotion': 'kind',
                }],
            }, ensure_ascii=False), encoding='utf-8')
            st_path.write_text(json.dumps({
                'title': 'preflight', 'voiceMode': 'design', 'reading': 'shared', 'baseCaption': 'test'
            }, ensure_ascii=False), encoding='utf-8')

            seen_plains = []

            class MockScorer:
                def score_span(self, plain, repl, s, e, r):
                    seen_plains.append(plain)
                    return {'温': (0.95, 1), '蒲団': (0.70, 2), '昨夜': (0.56, 1), '眠': (0.92, 1)}[plain[s:e]]

                def __call__(self, plain, repl, s, e, r):
                    return self.score_span(plain, repl, s, e, r)[0]

            doc, voices, _ = load_inputs(sc_path, st_path, ruby_preflight=True)
            job_dir = root / 'job_pre'
            manifest = execute_preflight(doc, voices, job_dir, scorer=MockScorer())
            self.assertEqual(manifest['status'], 'preflight_complete')
            # Scorer must see pure plain text without the prepended '🫶' emotion tag!
            self.assertTrue(all(not p.startswith('🫶') for p in seen_plains))
            review = json.loads((job_dir / 'ruby_review.json').read_text(encoding='utf-8'))
            self.assertEqual(review['flagged_count'], 2)
            self.assertEqual([item['surface'] for item in review['flagged_items']], ['蒲団', '昨夜'])
            self.assertTrue(all('🫶' not in item['context'] for item in review['flagged_items']))

            # Now test remote execute with the same scorer: emotion tag '🫶' must be prepended AFTER ruby conversion.
            doc_syn, voices_syn, _ = load_inputs(sc_path, st_path, ruby_mode='auto_select', ruby_device='remote')
            synthesized_texts = []
            with contextlib.redirect_stdout(io.StringIO()):
                syn_manifest = execute(
                    doc_syn,
                    voices_syn,
                    root / 'job_syn',
                    lambda req, dest: (synthesized_texts.append(req['text']), _write_dummy_wav(Path(dest))),
                    ruby_scorer=MockScorer(),
                )
            self.assertEqual(syn_manifest['status'], 'complete')
            self.assertEqual(synthesized_texts, ['🫶温かいふとんでさくやはゆっくりと眠りましたね。'])

    def test_koebuta_tts_parts_supported_and_split_kanji_base_rejected(self):
        scenario = {
            'schema_version': 1,
            'speakers': {'a': {'name': 'A', 'kind': 'narrator'}},
            'segments': [
                {
                    'id': 's01',
                    'speaker_id': 'a',
                    'text': '前半の昨夜と後半の本日です。',
                    'tts_text': '前半の昨夜《さくや》と後半の本日《ほんじつ》です。',
                    'koebuta_tts_parts': ['前半の昨夜《さくや》と', '後半の本日《ほんじつ》です。'],
                    'emotion': 'neutral',
                }
            ],
        }

        class MockScorer:
            def score_span(self, plain, repl, s, e, r):
                return {'昨夜': (0.56, 1), '本日': (0.72, 1)}[plain[s:e]]

            def __call__(self, plain, repl, s, e, r):
                return self.score_span(plain, repl, s, e, r)[0]

        updated, _ = apply_ruby_to_scenario(scenario, mode='auto_select', scorer=MockScorer())
        self.assertEqual(updated['segments'][0]['tts_text'], '前半のさくやと後半の本日です。')
        self.assertEqual(updated['segments'][0]['koebuta_tts_parts'], ['前半のさくやと', '後半の本日です。'])

        # Splitting a kanji run across parts without bar must raise RubySyntaxError.
        bad_parts = dict(scenario)
        bad_parts['segments'] = [{
            'id': 's01',
            'speaker_id': 'a',
            'text': '前半の昨夜です。',
            'tts_text': '前半の昨夜《さくや》です。',
            'koebuta_tts_parts': ['前半の昨', '夜《さくや》です。'],
            'emotion': 'neutral',
        }]
        with self.assertRaises(ValueError):
            apply_ruby_to_scenario(bad_parts, mode='partial_kana')


if __name__ == '__main__':
    unittest.main()
