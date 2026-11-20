"""Regression coverage for managed rubies, production notes and legacy export."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from irodori_cli.faithful import PlanError
from irodori_cli.faithful_worker import _resolve_ruby_plan
from irodori_generate import load_inputs, main


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
