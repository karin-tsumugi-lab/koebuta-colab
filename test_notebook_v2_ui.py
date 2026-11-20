"""CPU-only construction and callback wiring, no server or model downloads."""
from contextvars import ContextVar
import sys
from pathlib import Path
import unittest
import tempfile
import json
import numpy as np
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent / 'notebook'))
from notebook_v2_ui import create_v2_ui


class UiSmoke(unittest.TestCase):
    def test_cpu_end_to_end_p0_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notebook = json.loads((Path(__file__).parent / 'notebook/Koebuta_Colabv1.00.ipynb').read_text(encoding='utf-8'))
            api = {k: 'mock' for k in ('MODEL_ID', 'MODEL_REVISION', 'CODEC_ID', 'CODEC_REVISION', 'IRODORI_RESOLVED_COMMIT')}
            exec(''.join(notebook['cells'][4]['source']).replace('/content/koebuta_work', (root / 'runtime').as_posix()), api)
            exec(''.join(notebook['cells'][6]['source']), api)
            api['load_runtime'] = lambda: None
            api['synthesize'] = lambda unit, runtime: (np.ones(160, dtype=np.float32) * .1, 16000)
            project = root / 'source'
            project.mkdir()
            from test_notebook_v2 import wav
            wav(project / 'ref.wav')
            raw = json.dumps({'schema_version': 1, 'speakers': {'a': {'name': 'A', 'kind': 'character', 'reference_wav': 'ref.wav'}},
                'segments': [{'id': 't010', 'speaker_id': 'a', 'text': 'こんにちは。お元気ですか。', 'tts_text': 'こんにちは。お元気ですか。',
                              'koebuta_tts_parts': ['こんにちは。', 'お元気ですか。']}],
                'koebuta_settings': {'reading_mode': 'cast'}}).encode()
            (project / 'scenario.json').write_bytes(raw)
            demo = create_v2_ui(api)
            callbacks = {fn.fn.__name__: fn.fn for fn in demo.fns.values()}
            loaded = callbacks['load'](None, None, str(project))
            state = loaded[-1]
            self.assertEqual([row[0] for row in loaded[-3]], ['t010#1', 't010#2'])
            self.assertIn('声設定 有', callbacks['role_info'](state, 'a')[1]['choices'][0][0])
            callbacks['edit_caption'](state, 'a', '穏やかで低い声')
            self.assertEqual(callbacks['role_info'](state, 'a')[0], '穏やかで低い声')
            self.assertEqual((project / 'scenario.json').read_bytes(), raw)
            self.assertTrue(0 <= callbacks['random_seed']() <= 2147483647)
            settings = [314, 40, False, False, False, 280]
            inspected = callbacks['inspect'](state, *settings)
            self.assertEqual([r[0] for r in inspected[0]], ['t010#1', 't010#2'])
            callbacks['regenerate'](state, 't010#1', True, *settings)
            self.assertFalse(state['store'].accepted)
            before = dict(state['store'].candidates)
            with self.assertRaises(Exception):
                callbacks['generate'](state, *settings)
            self.assertEqual(before, state['store'].candidates)
            with self.assertRaises(Exception):
                callbacks['adopt'](state, 't010#1', True, 999, 40, False, False, False, 280)
            self.assertFalse(state['store'].accepted)
            callbacks['inspect'](state, *settings)
            saved_folder = root / 'saved'
            callbacks['save_state'](state, str(saved_folder), 999, 50, True, False, True, 900)
            restored = callbacks['load'](None, None, str(project))[-1]
            restored_result = callbacks['restore'](restored, str(saved_folder))
            self.assertEqual(list(restored_result[1:7]), [999, 50, True, False, True, 900])
            self.assertEqual(before, restored['store'].candidates)
            self.assertEqual(callbacks['role_info'](restored, 'a')[0], '穏やかで低い声')
            self.assertTrue(Path(restored['voices']['a']).is_file())
            callbacks['inspect'](state, *settings)
            callbacks['adopt'](state, 't010#1', True)
            second = dict(state['store'].accepted['t010#2'])
            callbacks['regenerate'](state, 't010#1', False, 999, 50, False, False, False, 280)
            callbacks['adopt'](state, 't010#1', False, 999, 50, False, False, False, 280)
            self.assertEqual(second, state['store'].accepted['t010#2'])
            exported = callbacks['output'](state, '', *settings)
            self.assertTrue(Path(exported[0]).is_file())
            self.assertTrue(Path(exported[2]).is_file())
            self.assertIn('_完成_', Path(exported[0]).name)
            callbacks['save_state'](state, str(saved_folder), *settings)
            mixed = callbacks['load'](None, None, str(project))[-1]
            callbacks['restore'](mixed, str(saved_folder))
            self.assertEqual(mixed['store'].accepted['t010#1']['unit']['seed'], 999)
            self.assertEqual(mixed['store'].accepted['t010#2']['unit']['seed'], 314)
            mixed_export = callbacks['output'](mixed, str(root / 'local-output'), *settings)
            self.assertIn('Drive永続保存ではありません', mixed_export[3])
            self.assertTrue(Path(mixed_export[0]).is_file())
            self.assertEqual((project / 'scenario.json').read_bytes(), raw)
            # Missing references: one multi-line speaker plus a single-line speaker.
            data = json.loads(raw)
            del data['speakers']['a']['reference_wav']
            data['speakers']['b'] = {'name': 'B', 'kind': 'character', 'voice_caption': '明瞭な声'}
            data['segments'].extend([
                {'id': 't011', 'speaker_id': 'a', 'text': '今日はとてもよい天気ですから、少し遠くの公園まで歩いてみましょう。'},
                {'id': 't012', 'speaker_id': 'b', 'text': 'わかりました。'}])
            updated = json.dumps(data).encode()
            (project / 'scenario.json').write_bytes(updated)
            state = callbacks['load'](None, None, str(project))[-1]
            callbacks['inspect'](state, *settings)  # Must never load a model.
            tensor = MagicMock()
            tensor.detach.return_value.cpu.return_value.float.return_value.view.return_value.numpy.return_value = np.ones(160, dtype=np.float32) * .1
            runtime = SimpleNamespace(synthesize=lambda request: SimpleNamespace(audios=[tensor], sample_rate=16000))
            api['load_runtime'] = lambda: runtime
            fake = SimpleNamespace(SamplingRequest=lambda **kwargs: SimpleNamespace(**kwargs))
            with patch.dict(sys.modules, {'irodori_tts.inference_runtime': fake}):
                updates = []
                callbacks['generate'](state, *settings,
                    progress=lambda value, **kw: updates.append((value, kw['desc'])))
                result = callbacks['output'](state, '', *settings)
            self.assertTrue(any('自動参照音声を生成中 1/1' in message for _, message in updates))
            self.assertTrue(any('本文音声を生成中' in message for _, message in updates))
            self.assertEqual(updates[-1][0], 1)
            self.assertEqual([value for value, _ in updates], sorted(value for value, _ in updates))
            self.assertIn('a', state['store'].references)
            self.assertNotIn('b', state['store'].references)
            labels = dict((key, label) for label, key in callbacks['role_info'](state, 'a')[1]['choices'])
            self.assertIn('声設定 有', labels['a'])
            self.assertIn('声設定 無', labels['b'])
            self.assertTrue(Path(result[0]).is_file())
            self.assertEqual((project / 'scenario.json').read_bytes(), updated)
            json_only = callbacks['load'](None, str(project / 'scenario.json'), '')
            self.assertTrue(json_only[-3])
            self.assertFalse(json_only[-1]['voices'])
            self.assertEqual((project / 'scenario.json').read_bytes(), updated)
            invalid = root / 'invalid.json'
            invalid.write_text('{broken')
            with self.assertRaises(Exception):
                callbacks['load'](None, str(invalid), '')
            old_project = state['project']
            invalid.write_text(json.dumps({'schema_version': 1, 'speakers': data['speakers'],
                'segments': [{'id': 'bad', 'speaker_id': 'a', 'text': 'bad', 'pause_after_ms': 10**20}]}))
            with self.assertRaises(Exception):
                callbacks['load'](state, str(invalid), '')
            self.assertIs(state['project'], old_project)
            # Cold start: the module becomes importable only during runtime loading.
            events = []
            def cold_load():
                events.append('runtime')
                sys.modules['irodori_tts.inference_runtime'] = fake
                return runtime
            api['load_runtime'] = cold_load
            with patch.dict(sys.modules):
                sys.modules.pop('irodori_tts.inference_runtime', None)
                trial = callbacks['sample'](None, '起動直後の試作です。', '明瞭な声', 314, 40,
                    progress=lambda value, **kw: events.append(kw['desc']))
            self.assertTrue(Path(trial[0]).is_file())
            self.assertEqual(events[1], 'runtime')
            self.assertIn('完了', events[-1])
            trial_state = trial[-1]
            trial_state['sample_role'] = 'a'
            with self.assertRaises(Exception):
                callbacks['adopt_sample'](trial_state, 'b')

    def test_constructs_without_editor_or_server(self):
        demo = create_v2_ui({'_CTX': ContextVar('test'), 'new_session': dict})
        callbacks = {fn.fn.__name__: fn for fn in demo.fns.values()}
        self.assertEqual(set(callbacks), {'save_state', 'role_info', 'edit_caption', 'random_seed', 'load', 'inspect', 'assign', 'sample', 'adopt_sample',
                                         'details', 'regenerate', 'adopt', 'discard', 'generate', 'output', 'restore'})
        for callback in callbacks.values():
            self.assertEqual(callback.concurrency_id, 'koebuta-v2')
            self.assertEqual(callback.concurrency_limit, 1)
        from gradio.helpers import special_args
        for name in ('sample', 'regenerate', 'generate', 'output'):
            self.assertIsNotNone(special_args(callbacks[name].fn)[1], name)
        self.assertFalse(any(getattr(block, 'interactive', False) for block in demo.blocks.values()
                             if block.__class__.__name__ == 'Dataframe'))


if __name__ == '__main__':
    unittest.main()
