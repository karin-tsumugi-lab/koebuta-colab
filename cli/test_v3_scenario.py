"""Regression coverage for managed rubies, production notes and legacy export."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from irodori_cli.faithful import PlanError
from irodori_cli.faithful_worker import _resolve_ruby_plan
from irodori_generate import load_inputs, main, write_segment_archive


class V3ScenarioTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.settings = Path(__file__).parent / 'irodori_cli_examples/generate_settings.json'
        self.source = self.root / 'scenario.json'
        text = '｜扉《とびら》の前で冷い水を飲み、冷い水を置きました。'
        start = text.index('冷い')
        self.scenario = dict(schema_version=1, speakers={'n': dict(name='朗読者', kind='narrator')},
            segments=[dict(id='t0001', speaker_id='n', text=text, emotion='neutral',
                notes=['[効果音] 直後に扉の音', '追加メモ\n二行目'],
                koebuta_added_ruby=[
                    dict(start=start, end=start+2, surface='冷い', reading='つめたい', selection='kana'),
                    dict(start=text.rindex('冷い'), end=text.rindex('冷い')+2, surface='冷い',
                         reading='つめたい', selection='auto'),
                ])])

    def save(self, scenario=None):
        self.source.write_text(json.dumps(scenario or self.scenario, ensure_ascii=False), encoding='utf8')

    def test_remote_only_scores_auto_and_notes_do_not_affect_requests(self):
        self.save()
        document, voices, requests = load_inputs(self.source, self.settings)
        self.assertEqual(document['ruby_filter']['mode'], 'auto_select')
        called = []

        def scorer(plain, replacement, start, end, reading):
            called.append((plain[start:end], start, reading))
            return 0.99

        plan, _ = _resolve_ruby_plan(document, {'requests': requests}, voices, scorer)
        self.assertEqual(len(called), 1)
        self.assertEqual(plan['requests'][0]['request']['text'],
                         'とびらの前でつめたい水を飲み、冷い水を置きました。')
        plain = copy.deepcopy(self.scenario)
        plain['segments'][0]['notes'] = ['別の素材を使う']
        self.save(plain)
        _, _, changed = load_inputs(self.source, self.settings)
        self.assertEqual(changed, requests)

    def test_legacy_export_is_synthesis_ready_and_retains_notes(self):
        self.save()
        destination = self.root / 'legacy.json'
        self.assertEqual(main(['--scenario', str(self.source), '--settings', str(self.settings),
                              '--export-compatible', str(destination)]), 0)
        exported = json.loads(destination.read_text(encoding='utf8'))['segments'][0]
        self.assertNotIn('koebuta_added_ruby', exported)
        self.assertEqual(exported['notes'], self.scenario['segments'][0]['notes'])
        self.assertEqual(exported['tts_text'], 'とびらの前でつめたい水を飲み、冷い水を置きました。')

    def test_shifted_range_stops_generation(self):
        self.scenario['segments'][0]['text'] = '昨日、' + self.scenario['segments'][0]['text']
        self.save()
        with self.assertRaisesRegex(PlanError, 't0001'):
            load_inputs(self.source, self.settings)

    def test_unrelated_legacy_rows_keep_their_declared_formats(self):
        self.scenario['segments'] += [
            dict(id='n1', speaker_id='n', emotion='neutral', text_format='narou',
                 text='先ほど冷気(れいき)が窓から入ってきました。'),
            dict(id='k1', speaker_id='n', emotion='neutral', text_format='kakuyomu',
                 text='先ほど《《冷気》》が窓から入ってきました。'),
        ]
        self.save()
        document, voices, requests = load_inputs(self.source, self.settings)
        plan, _ = _resolve_ruby_plan(document, {'requests': requests}, voices, lambda *a: 0.99)
        self.assertEqual([r['request']['text'] for r in plan['requests'][1:]], [
            '先ほどれいきが窓から入ってきました。',
            '先ほど冷気が窓から入ってきました。',
        ])

    def test_v3_uses_canonical_tts_annotations_with_legacy_source_offsets(self):
        for fmt, source in (
            ('narou', '冷気(れいき)と冷い風が窓から入ってきました。'),
            ('kakuyomu', '｜冷気《れいき》と《《冷い風》》が窓から入ってきました。'),
            ('pixiv', '[[rb:冷気 > れいき]]と冷い風が窓から入ってきました。'),
        ):
            with self.subTest(fmt=fmt):
                row = self.scenario['segments'][0]
                row.update(text=source, text_format=fmt,
                           tts_text='｜冷気《れいき》と冷い風が窓から入ってきました。')
                start = row['text'].index('冷い')
                row['koebuta_added_ruby'] = [dict(start=start,end=start+2,surface='冷い',
                                                   reading='つめたい',selection='kana')]
                self.save()
                document, _, requests = load_inputs(self.source, self.settings)
                self.assertEqual(requests[0]['request']['text'], 'れいきとつめたい風が窓から入ってきました。')
                self.assertEqual(document['scenario']['segments'][0]['text'], row['text'])
                del row['tts_text']
                self.save()
                with self.assertRaisesRegex(PlanError,'青空文庫形式'):
                    load_inputs(self.source, self.settings)

    def test_v3_rows_use_utterances_instead_of_tts_parts(self):
        row = self.scenario['segments'][0]
        row['tts_text'] = row['text']
        row['koebuta_tts_parts'] = [row['text'][:9],row['text'][9:]]
        self.save()
        with self.assertRaisesRegex(PlanError,'発話ID'):
            load_inputs(self.source,self.settings)

    def test_legacy_parent_wavs_have_distinct_windows_paths(self):
        source = self.root / 'audio.wav'
        source.write_bytes(b'fixture')
        path = self.root / 'segments.zip'
        parents = {sid:{'file':source.name} for sid in ('T1','t1','t1__1','CON')}
        write_segment_archive(path,self.root,{'combined':{'take_files':[]},'parent_audio':parents})
        with zipfile.ZipFile(path) as archive:
            self.assertEqual(archive.namelist(), [
                'utterances/T1.wav','utterances/t1__2.wav','utterances/t1__1.wav','utterances/CON__1.wav'])

    def test_aozora_layout_does_not_enter_tts_or_shift_ruby(self):
        row = self.scenario['segments'][0]
        original = '［＃改ページ］井戸から［＃ここから２字下げ］冷い水をくみました。'
        offset = original.index('冷い')
        row.update(text=original, text_format='aozora',
                   tts_text='井戸から冷い水をくみました。［＃ここで字下げ終わり］',
                   koebuta_added_ruby=[dict(start=offset, end=offset+2, surface='冷い',
                                           reading='つめたい', selection='kana')])
        self.save()
        document, _, requests = load_inputs(self.source, self.settings)
        self.assertEqual(document['scenario']['segments'][0]['text'], original)
        self.assertEqual(requests[0]['request']['text'], '井戸からつめたい水をくみました。')

    def test_remote_dry_run_displays_confirmed_readings_and_marks_pending(self):
        self.save()
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.assertEqual(main(['--scenario', str(self.source), '--settings', str(self.settings),
                                  '--dry-run']), 0)
        preview = json.loads(captured.getvalue())
        self.assertEqual(preview['requests'][0]['request']['text'],
                         'とびらの前でつめたい水を飲み、冷い水を置きました。')
        self.assertEqual(preview['ruby_filter']['mode'], 'auto_select')
        pending, = preview['ruby_pending']
        self.assertEqual((pending['segment_id'], pending['surface'], pending['reading']),
                         ('t0001', '冷い', 'つめたい'))
        self.assertIsNone(pending['selected'])
        resolved, unresolved = preview['ruby_decisions'][0]['decisions']
        self.assertEqual(resolved['selected'], 'kana')
        self.assertIsNone(unresolved['selected'])
