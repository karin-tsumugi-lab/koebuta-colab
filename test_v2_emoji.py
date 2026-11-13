"""Check the shipped standalone runtime's emotion catalog without GPU setup."""
import ast
import json
from pathlib import Path
import unittest
import sys

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'cli'))
sys.path.insert(0, str(ROOT / 'fast'))
from irodori_cli.emoji_tags import EMOTIONS, ALL_TAGS, align_readings
from irodori_cli.segmentation import split_segments
import speak_pipeline


class V2EmojiTests(unittest.TestCase):
    def test_shipped_catalog_accepts_additional_emotions(self):
        path = Path(__file__).parent / 'notebook/Koebuta_Notebook_v2.ipynb'
        namespace = {}
        for cell in json.loads(path.read_text(encoding='utf-8'))['cells']:
            if cell['cell_type'] != 'code':
                continue
            for node in ast.parse(''.join(cell['source'])).body:
                assignment = isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == 'EMOTIONS'
                    for target in node.targets)
                update = (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                          and isinstance(node.value.func, ast.Attribute)
                          and isinstance(node.value.func.value, ast.Name)
                          and node.value.func.value.id == 'EMOTIONS')
                if assignment or update:
                    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
        catalog = namespace['EMOTIONS']
        self.assertEqual(catalog, EMOTIONS)
        self.assertEqual(catalog, speak_pipeline.EMOTIONS)
        self.assertEqual(len(ALL_TAGS), 45)
        self.assertEqual(len(catalog), 34)
        self.assertEqual(catalog['worried'] + 'どうしたのでしょう。', '😟どうしたのでしょう。')
        self.assertEqual(catalog['narration'], '📖')
        self.assertEqual(catalog['tired'], '😮‍💨')
        self.assertEqual(catalog['neutral'], '')

    def test_long_reading_preserves_inserted_events(self):
        body = '最初の文章をゆっくり読みます。次の文章もそのまま読みます。'
        spoken = body.replace('次の', '😮‍💨🤭🤭次の')
        segments = split_segments([dict(id='s1', text=body, tts_text=spoken)], limit=18)
        self.assertEqual(''.join(s['text'] for s in segments), body)
        self.assertEqual(''.join(s['tts_text'] for s in segments), spoken)
        self.assertIsNone(align_readings([('原文。', [])], '別の文。'))

    def test_fast_repetition_stays_together_at_chunk_boundary(self):
        text = 'あ' * 77 + '😮‍💨😮‍💨' + 'い' * 20
        chunks = speak_pipeline.split_text(text)
        self.assertEqual(''.join(chunks), text)
        self.assertTrue(any('😮‍💨😮‍💨' in chunk for chunk in chunks))
        self.assertEqual(speak_pipeline.parse_script('[sleep_talking]\n眠いので、そろそろお休みしましょう。')[0]['emotion'], 'sleep_talking')
