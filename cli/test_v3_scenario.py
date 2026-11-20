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
from irodori_cli.faithful_worker import _resolve_ruby_plan, build_ruby_review
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

    def test_repeated_surface_is_resolved_by_context_after_working_text_edit(self):
        row = self.scenario['segments'][0]
        row.update(text='冷い朝に冷い川を見た。', tts_text='😐冷い朝に冷い川を見た。')
        start = row['text'].rindex('冷い')
        row['koebuta_added_ruby'] = [dict(start=start, end=start+2, surface='冷い',
                                         reading='つめたい', selection='kana')]
        self.save()
        _, _, requests = load_inputs(self.source, self.settings)
        self.assertEqual(requests[0]['request']['text'], '😐冷い朝につめたい川を見た。')

    def test_explicit_author_ruby_overlap_and_literal_plain_text(self):
        row = self.scenario['segments'][0]
        row.update(text='｜李徴《りせい》が来た。', koebuta_added_ruby=[
            dict(start=1, end=3, surface='李徴', reading='りちょう', selection='kana')])
        self.save()
        doc, _, requests = load_inputs(self.source, self.settings)
        self.assertEqual(requests[0]['request']['text'], 'りせいが来た。')
        self.assertEqual(doc['ruby_decisions'][0]['ignored_due_to_mandatory_ruby'],
                         row['koebuta_added_ruby'])
        row.update(text='｜という記号の隣に冷い川と記す。', text_format='none')
        start = row['text'].index('冷い')
        row['koebuta_added_ruby'] = [dict(start=start, end=start+2, surface='冷い',
                                         reading='つめたい', selection='auto')]
        self.save()
        doc, voices, requests = load_inputs(self.source, self.settings)
        plan, _ = _resolve_ruby_plan(doc, {'requests': requests}, voices, lambda *a: .1)
        self.assertEqual(plan['requests'][0]['request']['text'], '｜という記号の隣につめたい川と記す。')

    def test_dry_run_rejects_working_ruby_without_explicit_bar(self):
        row = self.scenario['segments'][0]
        row.update(text='明日に出発する予定です。', tts_text='明日《あす》に出発する予定です。')
        del row['koebuta_added_ruby']
        self.save()
        with self.assertRaisesRegex(PlanError, 't0001.*縦棒'):
            load_inputs(self.source, self.settings)

    def test_literal_bar_in_working_text_with_canonical_ruby(self):
        row = self.scenario['segments'][0]
        del row['koebuta_added_ruby']
        row.update(text='縦線｜を確かめて、明日を待つ。', text_format='none',
                   tts_text='縦線｜を確かめて、｜明日《あす》を待つ。')
        self.save()
        _, _, requests = load_inputs(self.source, self.settings)
        self.assertEqual(requests[0]['request']['text'], '縦線｜を確かめて、あすを待つ。')
        row['text_format'] = 'aozora'
        self.save()
        with self.assertRaisesRegex(PlanError, 'E_ORPHAN_BAR'):
            load_inputs(self.source, self.settings)

    def test_preflight_review_counts_only_automatic_candidates(self):
        self.save()
        doc, voices, requests = load_inputs(self.source, self.settings)
        plan, decisions = _resolve_ruby_plan(doc, {'requests': requests}, voices, lambda *a: .99)
        review = build_ruby_review(plan, decisions)
        self.assertEqual(review['total_ruby_spans'], 1)
        self.assertEqual(review['flagged_items'], [])

    def test_mandatory_ruby_without_added_ruby_field(self):
        row = self.scenario['segments'][0]
        del row['koebuta_added_ruby']
        for fmt, original in (
            ('aozora', '｜明日《あす》'), ('narou', '明日(あす)'),
            ('kakuyomu', '|明日《あす》'), ('pixiv', '[[rb:明日 > あす]]'),
        ):
            row.update(text=original + 'の朝に出発します。', text_format=fmt)
            for working in ('明日', 'あす', '｜明日《あす》', '｜あす《あす》'):
                with self.subTest(fmt=fmt, working=working):
                    row['tts_text'] = working + 'の朝に出発します。'
                    self.save()
                    _, _, requests = load_inputs(self.source, self.settings)
                    self.assertEqual(requests[0]['request']['text'], 'あすの朝に出発します。')
            for working in ('｜明日《あした》', '｜あす《あした》'):
                with self.subTest(fmt=fmt, conflict=working):
                    row['tts_text'] = working + 'の朝に出発します。'
                    self.save()
                    with self.assertRaisesRegex(PlanError, 't0001.*あす.*あした'):
                        load_inputs(self.source, self.settings)

    def test_remote_plan_and_dry_run_expand_ruby_without_added_ruby_field(self):
        self.scenario['segments'].append(dict(id='t0002', speaker_id='n', emotion='neutral',
            text='｜明日《あす》の朝に出発します。', tts_text='明日の朝に出発します。'))
        self.save()
        document, voices, requests = load_inputs(self.source, self.settings)
        resolved, _ = _resolve_ruby_plan(document, {'requests': requests}, voices, lambda *a: 0.99)
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--scenario', str(self.source), '--settings', str(self.settings),
                                   '--dry-run']), 0)
        for plan in (resolved, json.loads(output.getvalue())):
            self.assertEqual(plan['requests'][1]['request']['text'], 'あすの朝に出発します。')

    def test_author_reading_survives_legacy_conversion_or_flags_conflict(self):
        for fmt, original in (
            ('narou', '冷気(れいき)が窓から入ってきました。'),
            ('kakuyomu', '|冷気《れいき》が窓から入ってきました。'),
            ('pixiv', '[[rb:冷気 > れいき]]が窓から入ってきました。'),
            ('aozora', '｜冷気《れいき》が窓から入ってきました。'),
        ):
            with self.subTest(format=fmt):
                row = self.scenario['segments'][0]
                row.update(text=original, text_format=fmt, koebuta_added_ruby=[])
                for tts in ('冷気が窓から入ってきました。', 'れいきが窓から入ってきました。'):
                    row['tts_text'] = tts
                    self.save()
                    document, _, requests = load_inputs(self.source, self.settings)
                    self.assertEqual(document['scenario']['segments'][0]['text'], original)
                    self.assertEqual(requests[0]['request']['text'], 'れいきが窓から入ってきました。')
                row['tts_text'] = '｜冷気《ひやけ》が窓から入ってきました。'
                self.save()
                with self.assertRaisesRegex(PlanError, 'れいき.*ひやけ.*要確認'):
                    load_inputs(self.source, self.settings)
