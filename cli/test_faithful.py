"""Acceptance tests for authored scenarios, host/remote identity and PCM assembly."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from irodori_cli.faithful import build_plan, PlanError, CONTRACT, plan_signature, project_document
from irodori_cli.faithful_worker import execute, main as remote_main
from irodori_cli.core import atomic_json, read_json
from irodori_generate import load_inputs, main, verify_authored_recovery


def wav(path, frames=100, rate=1000):
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\x01\0' * frames)


class FaithfulTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = dict(schema_version=1, speakers={'n': {'name': '朗読者', 'kind': 'narrator'}},
                        segments=[dict(id='a', speaker_id='n', text='春の灯\n架空花子\n第一章', emotion='joy'),
                                  dict(id='b', speaker_id='n', text='続きを読みます。', emotion='neutral')])

    def plan(self, raw=None, cfg=None, **kw):
        return build_plan(self.raw if raw is None else raw, {} if cfg is None else cfg,
                          base=self.root, **kw)

    def parts(self):
        raw = copy.deepcopy(self.raw)
        raw['segments'][0].update(tts_text='前半です。😮‍💨後半です。',
                                  koebuta_tts_parts=['前半です。', '😮‍💨後半です。'], pause_after_ms=900)
        return raw

    def document(self, raw=None, cfg=None, ids=None):
        scenario = self.root / 'scenario.json'
        settings = self.root / 'settings.json'
        atomic_json(scenario, self.raw if raw is None else raw)
        atomic_json(settings, {} if cfg is None else cfg)
        return load_inputs(scenario, settings, selected=ids)

    def test_no_split_or_merge_and_input_never_mutates(self):
        raw = copy.deepcopy(self.raw)
        raw['segments'][1]['text'] = '長い文章です。' * 80
        before = copy.deepcopy(raw)
        plan = self.plan(raw)
        self.assertEqual([q['id'] for q in plan['requests']], ['a', 'b'])
        self.assertEqual(plan['requests'][0]['request']['text'], '😆' + raw['segments'][0]['text'])
        self.assertEqual(plan['requests'][1]['request']['text'], raw['segments'][1]['text'])
        self.assertEqual(raw, before)
        self.assertNotIn('source', raw)
        self.assertIn('I_SOURCE_UNCHECKED', [d['code'] for d in plan['diagnostics']])

    def test_parts_inherit_directives_and_only_last_piece_has_pause(self):
        raw = self.parts()
        raw['speakers']['n']['acting_description'] = '落ち着いて'
        raw['segments'][0]['acting_description'] = '明るく'
        plan = self.plan(raw)
        self.assertEqual([q['id'] for q in plan['requests']], ['a#1', 'a#2', 'b'])
        self.assertEqual([q['request']['text'] for q in plan['requests'][:2]], ['😆前半です。', '😆😮‍💨後半です。'])
        self.assertEqual([q['pause_after_ms'] for q in plan['requests']], [0, 900, 0])
        self.assertTrue(all('明るく' in q['request']['caption'] for q in plan['requests'][:2]))

    def test_invalid_parts_and_unicode_cuts_fail_without_repair(self):
        pairs = [('😮\u200d', '💨声'), ('声', '\ufe0fです'), ('あ', '\u3099いう'),
                 ('🇯', '🇵です'), ('\u1100', '\u1161です'), ('a\r', '\nb')]
        for pair in pairs:
            raw = self.parts()
            raw['segments'][0].update(tts_text=''.join(pair), koebuta_tts_parts=list(pair))
            with self.subTest(pair=pair), self.assertRaises(PlanError): self.plan(raw)
        for parts in [[], ['一片'], ['正しい', '別の文字'], ['正しい', ' '], [None, '別']]:
            raw = self.parts(); raw['segments'][0]['koebuta_tts_parts'] = parts
            with self.subTest(parts=parts), self.assertRaises(PlanError): self.plan(raw)

    def test_selection_order_dedup_parent_and_piece(self):
        plan = self.plan(self.parts(), selected='b,a#2,b,a#2')
        self.assertEqual([r['id'] for r in plan['requests']], ['a#2', 'b'])
        self.assertEqual(plan['execution']['complete_segment_ids'], ['b'])
        self.assertEqual(plan['execution']['scope'], 'selection')
        self.assertEqual([r['id'] for r in self.plan(self.parts(), selected='a,a#2')['requests']], ['a#1', 'a#2'])
        for selector in ['', ',', 'missing', 'a#0', 'a#3', 'a,', ' a']:
            with self.subTest(selector=selector), self.assertRaises(PlanError):
                self.plan(self.parts(), selected=selector)

    def test_separator_empty_missing_speaker_and_pause_precedence(self):
        raw = copy.deepcopy(self.raw)
        raw['segments'].insert(1, dict(id='sep', segment_type='separator', emotion='neutral', pause_after_ms=900))
        raw['segments'].insert(2, dict(id='sep2', segment_type='separator', text='', emotion='neutral', pause_after_ms=1200))
        self.assertEqual(self.plan(raw)['requests'][0]['pause_after_ms'], 1200)
        raw['segments'][0]['pause_after_ms'] = 0
        self.assertEqual(self.plan(raw)['requests'][0]['pause_after_ms'], 0)
        self.assertIn('W_PAUSE_CONFLICT', [d['code'] for d in self.plan(raw)['diagnostics']])
        with self.assertRaises(PlanError): self.plan(raw, selected='sep')

    def test_explicit_edges_and_no_default_edge_silence(self):
        raw = copy.deepcopy(self.raw)
        self.assertEqual(self.plan(raw)['execution']['trailing_pause_ms'], 0)
        raw['segments'].insert(0, dict(id='begin', segment_type='separator', emotion='neutral', pause_after_ms=200))
        raw['segments'].append(dict(id='end', segment_type='separator', emotion='neutral', pause_after_ms=300))
        plan = self.plan(raw)
        self.assertEqual(plan['execution']['leading_pause_ms'], 200)
        self.assertEqual(plan['execution']['trailing_pause_ms'], 300)
        selected = self.plan(raw, selected='a')
        self.assertEqual(selected['execution']['leading_pause_ms'], 200)
        self.assertEqual(selected['execution']['trailing_pause_ms'], 0)

    def test_source_mismatch_warns_absent_source_not_fabricated(self):
        raw = copy.deepcopy(self.raw); raw['source'] = '元の表題'
        p = self.plan(raw)
        self.assertIn('W_SOURCE_MISMATCH', [d['code'] for d in p['diagnostics']])
        self.assertEqual(raw['source'], '元の表題')
        doc, _, _ = self.document()
        self.assertNotIn('source', doc['scenario'])

    def test_disabled_directives_warn_and_preserve_caption_when_enabled(self):
        raw = copy.deepcopy(self.raw)
        raw['segments'][0]['acting_description'] = '演技指示'
        p = self.plan(raw, dict(emotion=True, narratorEmotion=False))
        self.assertEqual(p['requests'][0]['request']['text'], raw['segments'][0]['text'])
        self.assertIn('演技指示', p['requests'][0]['request']['caption'])
        p = self.plan(raw, dict(acting=False))
        self.assertNotIn('演技指示', p['requests'][0]['request']['caption'])
        self.assertIn('W_DIRECTIVE_DISABLED', [d['code'] for d in p['diagnostics']])

    def test_only_selected_voices_need_files_and_host_remote_paths_may_differ(self):
        raw = copy.deepcopy(self.raw)
        raw['speakers']['other'] = dict(name='別人', kind='character')
        raw['segments'][1]['speaker_id'] = 'other'
        wav(self.root / 'local.wav')
        (self.root / 'remote.wav').write_bytes((self.root / 'local.wav').read_bytes())
        cfg = dict(voiceMode='clone', reading='cast', speakerVoices={'n': 'v1', 'other': 'v2'},
                   voices={'v1': 'local.wav', 'v2': 'absent.wav'})
        local = self.plan(raw, cfg, selected='a')
        remote = self.plan(raw, cfg, selected='a', voices={'v1': str(self.root / 'remote.wav')})
        self.assertEqual(plan_signature(local), plan_signature(remote))
        self.assertEqual(set(local['voices']), {'v1'})
        with self.assertRaises(PlanError): self.plan(raw, cfg)
        (self.root / 'remote.wav').write_bytes(b'changed')
        altered = self.plan(raw, cfg, selected='a', voices={'v1': str(self.root / 'remote.wav')})
        self.assertNotEqual(plan_signature(local), plan_signature(altered))

    def test_errors_are_aggregated_and_layout_is_never_inferred(self):
        raw = copy.deepcopy(self.raw)
        raw['segments'][0].update(speaker_id='unknown', emotion=[], pause_after_ms=True)
        raw['segments'][1]['text'] = ''
        with self.assertRaises(PlanError) as cm: self.plan(raw)
        self.assertGreaterEqual(len(cm.exception.diagnostics), 4)
        raw = copy.deepcopy(self.raw); raw['segments'][0]['blank_lines_after'] = 4
        self.assertEqual(self.plan(raw)['requests'][0]['pause_after_ms'], 280)
        for opt in [dict(blankMode='group'), dict(symbolSeparators=True), dict(readingMode='all')]:
            with self.assertRaises(PlanError): self.plan(cfg=dict(textOptions=opt))

    def test_dry_run_is_offline_and_does_not_write(self):
        doc, _, _ = self.document(self.parts())
        before = (self.root / 'scenario.json').read_bytes()
        args = ['--scenario', str(self.root / 'scenario.json'), '--settings', str(self.root / 'settings.json'),
                '--ids', 'a#2', '--session', 'test', '--job', 'test', '--out', str(self.root / 'out'), '--dry-run']
        output = io.StringIO()
        with patch('irodori_generate.run_logged') as network, contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 0)
            network.assert_not_called()
        self.assertFalse((self.root / 'out').exists())
        self.assertEqual([r['id'] for r in json.loads(output.getvalue())['requests']], ['a#2'])
        self.assertEqual(before, (self.root / 'scenario.json').read_bytes())

    def test_remote_executes_same_plan_without_legacy_split_and_parent_wav_is_complete(self):
        raw = self.parts()
        raw['segments'].insert(0, dict(id='start', segment_type='separator', emotion='neutral', pause_after_ms=200))
        raw['segments'].append(dict(id='end', segment_type='separator', emotion='neutral', pause_after_ms=300))
        doc, voices, requests = self.document(raw)
        job = self.root / 'run/job'
        calls = []
        with contextlib.redirect_stdout(io.StringIO()), patch('irodori_cli.segmentation.prepare_with_mapping', side_effect=AssertionError('legacy split')):
            manifest = execute(doc, voices, job, lambda req, dest: (calls.append(req['text']), wav(dest)))
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(calls, [r['request']['text'] for r in requests])
        self.assertEqual(manifest['combined']['frames'], 1700)  # 3*100 + 200 + 900 + 300
        self.assertEqual(manifest['parent_audio']['a']['frames'], 200)
        self.assertEqual(doc['scenario'], raw)
        atomic_json(self.root / 'run/project.json', doc)
        verify_authored_recovery(self.root / 'run', doc, requests)
        with self.assertRaises(ValueError): execute(doc, voices, job, lambda *_: self.fail('reused job'))

    def test_remote_rejects_different_plan_before_inference(self):
        doc, voices, _ = self.document()
        doc['scenario']['segments'][0]['text'] = '変更された発話'
        with self.assertRaises(ValueError):
            execute(doc, voices, self.root / 'job', lambda *_: self.fail('unexpected synthesis'))
        self.assertFalse((self.root / 'job').exists())

    def test_piece_only_is_selection_and_not_parent_completion(self):
        doc, voices, req = self.document(self.parts(), ids='a#2')
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = execute(doc, voices, self.root / 'job', lambda _, dest: wav(dest))
        self.assertEqual(manifest['combined']['frames'], 100)
        self.assertEqual(manifest['execution']['scope'], 'selection')
        self.assertEqual(manifest['execution']['complete_segment_ids'], [])
        self.assertFalse(manifest['parent_audio'])

    def test_runtime_dispatch_uses_tts_venv_and_existing_resident(self):
        doc, _, _ = self.document()
        atomic_json(self.root / 'project.json', doc)
        args = ['--project', str(self.root / 'project.json'), '--job', str(self.root / 'job')]
        with patch('irodori_cli.environments.executable', return_value='/tts/python'), \
             patch('irodori_cli.resident.enabled', return_value=True), \
             patch('irodori_cli.resident.run') as run, \
             patch('irodori_cli.faithful_worker.runtime_infer', side_effect=AssertionError('base Python cannot load models')):
            self.assertEqual(remote_main(args), 0)
        self.assertEqual(run.call_args.args[0], '/tts/python')
        self.assertEqual(run.call_args.args[1][0], 'faithful')

    def test_unknown_contract_never_falls_back_to_legacy(self):
        with self.assertRaises(ValueError): project_document(dict(contract='unknown'))

    def test_source_tamper_rejected_before_model_loading(self):
        doc, voices, _ = self.document()
        doc['scenario']['source'] = '元の原稿を後から差し替えた'
        atomic_json(self.root / 'project.json', doc)
        with patch('irodori_cli.faithful_worker.runtime_infer') as runtime:
            with self.assertRaises(ValueError):
                remote_main(['--project', str(self.root / 'project.json'),
                             '--job', str(self.root / 'job'), '--runtime'])
            runtime.assert_not_called()
        self.assertFalse((self.root / 'job').exists())

    def test_parent_assembly_error_is_not_success(self):
        doc, voices, _ = self.document(self.parts())
        with patch('irodori_cli.faithful_worker.assembly', side_effect=OSError('disk full')), \
             contextlib.redirect_stdout(io.StringIO()):
            manifest = execute(doc, voices, self.root / 'job', lambda _, dest: wav(dest))
        self.assertEqual(manifest['status'], 'failed')
        self.assertEqual(read_json(self.root / 'job/job.json')['status'], 'failed')
        self.assertEqual(manifest['errors'][-1]['id'], 'parent_assembly')

    def test_diagnostic_length_levels_and_strict_boolean(self):
        for size, level, message in [(9, 'warning', '強い警告'), (14, 'warning', '短文警告'),
                                     (19, 'info', '推奨範囲外'), (81, 'info', '推奨範囲外')]:
            raw = copy.deepcopy(self.raw)
            raw['segments'][0]['text'] = 'あ' * size
            diag = next(d for d in self.plan(raw)['diagnostics']
                        if d['code'] == 'W_LENGTH' and d['segment_id'] == 'a')
            self.assertEqual(diag['level'], level)
            self.assertIn(message, diag['message'])
        with self.assertRaises(PlanError):
            self.plan(cfg={'textOptions': {'symbolSeparators': 0}})


if __name__ == '__main__': unittest.main()
