"""Source alignment is advisory in the shipped v2, with no GPU/UI dependencies."""
import ast
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from tools.build_notebook_v2 import build

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'notebook'))
from notebook_v2 import CandidateStore, atomic_bytes, load_project, unpack_project


def load_api(work):
    cells = json.loads((ROOT / 'notebook/Koebuta_Notebook_v2.ipynb').read_text(encoding='utf-8'))['cells']
    api = {}
    with contextlib.redirect_stdout(io.StringIO()):
        exec(''.join(cells[5]['source']).replace('/content/koebuta_work', work.as_posix()), api)
    # Use real planning functions, excluding only optional audio-library imports.
    tree = ast.parse(''.join(cells[7]['source']))
    names = {'voice_key', 'resolve_pauses', 'build_plan', 'resolve_project_wavs'}
    nodes = [n for n in tree.body if
             (isinstance(n, ast.FunctionDef) and n.name in names) or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
              t.id in {'DEFAULT_PAUSE_MS', 'SEPARATOR_PAUSE_MS'} for t in n.targets))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<v2-planning>', 'exec'), api)
    return api


class SourceValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.api = load_api(self.root / 'runtime')
        self.raw = {'schema_version': 1, 'source': '太宰治\n女生徒\n雨が降っていた。',
                    'speakers': {'narrator': {'name': '朗読者', 'kind': 'narrator'}},
                    'segments': [
                        {'id': 'title', 'speaker_id': 'narrator', 'text': 'これから、太宰治の『女生徒』を朗読いたします。', 'emotion': 'neutral'},
                        {'id': 'body', 'speaker_id': 'narrator', 'text': '雨が降っていた。', 'emotion': 'neutral'}]}

    def project(self):
        return self.api['normalize_scenario'](copy.deepcopy(self.raw))

    def plan(self, project):
        return self.api['build_plan'](project, {'narrator': None}, use_acting=True,
            use_emotion=True, narrator_emotion=True, seed=314, steps=40, global_pause_ms=280)

    def test_heading_mismatch_warns_but_loads_plans_and_preserves_source(self):
        folder = self.root / 'source'
        folder.mkdir()
        original = json.dumps(self.raw, ensure_ascii=False).encode()
        (folder / 'scenario.json').write_bytes(original)
        project, _, _, _, _ = load_project(folder, self.api['normalize_scenario'],
            self.api['require_ready'], self.api['notebook_settings'], self.api['resolve_project_wavs'])
        self.assertEqual([level for level, _, _ in self.api['validate_project'](project)], ['警告'])
        self.assertIsNone(self.api['require_ready'](project))
        self.assertEqual([u['text'] for u in self.plan(project)], [s['text'] for s in self.raw['segments']])
        self.assertIn('原稿全文', '\n'.join(self.api['STATE']['plan_warnings']))
        self.assertIn('要確認・エラー: 0件 / 警告: 1件', self.api['issues_message'](project))
        exported = self.api['export_scenario'](project)
        self.assertEqual(exported['source'], self.raw['source'])
        self.assertEqual([s['text'] for s in exported['segments']], [s['text'] for s in self.raw['segments']])
        self.assertEqual((folder / 'scenario.json').read_bytes(), original)

    def test_matching_and_absent_source_have_no_alignment_warning(self):
        self.plan(self.project())
        self.assertTrue(any('原稿全文' in w for w in self.api['STATE']['plan_warnings']))
        for absent in (False, True):
            raw = copy.deepcopy(self.raw)
            raw['segments'] = [raw['segments'][1]]
            if absent:
                raw.pop('source')
            project = self.api['normalize_scenario'](raw)
            self.assertFalse(self.api['validate_project'](project))
            self.plan(project)
            self.assertFalse(any('原稿全文' in w for w in self.api['STATE']['plan_warnings']))

    def test_body_mismatch_is_still_visible_and_not_treated_as_permission(self):
        raw = copy.deepcopy(self.raw)
        raw['segments'] = [raw['segments'][1]]
        raw['segments'][0]['text'] = '雪が降っていた。'
        project = self.api['normalize_scenario'](raw)
        self.plan(project)
        warning = '\n'.join(self.api['STATE']['plan_warnings'])
        self.assertIn('項目 body', warning)
        self.assertIn('意図しない本文の差分', warning)
        self.assertEqual(project['source'], raw['source'])

    def test_other_invalid_data_still_blocks_despite_source_warning(self):
        def bad_reference(p): p['segments'][1]['role'] = 'missing'
        def empty_text(p): p['segments'][1]['text'] = ''
        def duplicate_id(p): p['segments'][1]['id'] = p['segments'][0]['id']
        def pending_id(p): p['segments'][1]['_pending_id'] = True
        def bad_parts(p): p['segments'][1]['_extras']['koebuta_tts_parts'] = ['不一致', 'です']
        def bad_settings(p): p['_extras']['koebuta_settings'] = {'seed': True}
        def bad_wav_path(p): p['roles'][0]['_extras']['reference_wav'] = '../outside.wav'
        def bad_type(p): p['segments'][1]['segment_type'] = 'unknown'
        for mutate in (bad_reference, empty_text, duplicate_id, pending_id, bad_parts, bad_settings, bad_wav_path, bad_type):
            with self.subTest(case=mutate.__name__):
                project = self.project()
                mutate(project)
                with self.assertRaises(ValueError): self.api['require_ready'](project)
                with self.assertRaises(ValueError): self.plan(project)

    def test_real_load_and_inspect_callbacks_display_warning(self):
        # Execute the real callbacks and plan; mock only Gradio widget updates.
        tree = ast.parse((ROOT / 'notebook/notebook_v2_ui.py').read_text(encoding='utf-8'))
        create = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'create_v2_ui')
        names = {'plan', 'summary', 'speaker_choices', 'load', 'inspect'}
        nodes = [n for n in create.body if isinstance(n, ast.FunctionDef) and n.name in names]
        for node in nodes: node.decorator_list = []
        ns = dict(api=self.api, Path=Path, uuid=uuid, CandidateStore=CandidateStore,
                  atomic_bytes=atomic_bytes, load_project=load_project, unpack_project=unpack_project,
                  gr=SimpleNamespace(update=lambda **kwargs: kwargs))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<v2-callbacks>', 'exec'), ns)
        folder = self.root / 'source'
        folder.mkdir()
        (folder / 'scenario.json').write_text(json.dumps(self.raw), encoding='utf-8')
        state = {'root': self.root / 'workspace'}
        loaded = ns['load'](state, None, str(folder))
        self.assertIn('警告 | 項目 title', loaded[0])
        self.assertIn('生成は継続できます', loaded[0])
        inspected = ns['inspect'](state, 314, 40, True, True, True, 280)
        self.assertIn('警告 | 項目 title', inspected[2])
        self.assertEqual(len(state['plan']), 2)

    def test_shipped_notebook_matches_reproducible_build(self):
        self.assertEqual(build(), (ROOT / 'notebook/Koebuta_Notebook_v2.ipynb').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
