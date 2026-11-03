"""CPU-only construction and callback wiring, no server or model downloads."""
from contextvars import ContextVar
import sys
from pathlib import Path
import unittest
import tempfile
import json
import numpy as np

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
            settings = [314, 40, False, False, False, 280]
            inspected = callbacks['inspect'](state, *settings)
            self.assertEqual([r[0] for r in inspected[0]], ['t010#1', 't010#2'])
            callbacks['regenerate'](state, 't010#1', True, *settings)
            self.assertFalse(state['store'].accepted)
            callbacks['adopt'](state, 't010#1', True)
            exported = callbacks['output'](state, '', *settings)
            self.assertTrue(Path(exported[0]).is_file())
            self.assertTrue(Path(exported[2]).is_file())
            self.assertEqual((project / 'scenario.json').read_bytes(), raw)

    def test_constructs_without_editor_or_server(self):
        demo = create_v2_ui({'_CTX': ContextVar('test'), 'new_session': dict})
        callbacks = {fn.fn.__name__: fn for fn in demo.fns.values()}
        self.assertEqual(set(callbacks), {'load', 'inspect', 'assign', 'sample', 'adopt_sample',
                                         'select', 'regenerate', 'adopt', 'discard', 'generate', 'output', 'restore'})
        for callback in callbacks.values():
            self.assertEqual(callback.concurrency_id, 'koebuta-v2')
            self.assertEqual(callback.concurrency_limit, 1)
        self.assertFalse(any(getattr(block, 'interactive', False) for block in demo.blocks.values()
                             if block.__class__.__name__ == 'Dataframe'))


if __name__ == '__main__':
    unittest.main()
