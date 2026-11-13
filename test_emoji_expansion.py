import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'cli'))
sys.path.insert(0, str(ROOT / 'fast'))
from irodori_cli.emoji_tags import ALL_TAGS, EMOTIONS, align_readings, spoken_length
from irodori_cli.segmentation import split_segments
import speak_pipeline

class EmojiExpansionTests(unittest.TestCase):
    def test_catalog_and_distributions(self):
        self.assertEqual(len(ALL_TAGS), 45)
        self.assertEqual(EMOTIONS['tired'], '😮‍💨')
        self.assertEqual(EMOTIONS['worried'], '😟')
        self.assertEqual(EMOTIONS, speak_pipeline.EMOTIONS)
        notebook = json.loads((ROOT / 'notebook/Koebuta_Colabv1.00.ipynb').read_text(encoding='utf-8'))
        assignments = []
        for cell in notebook['cells']:
            if cell['cell_type'] != 'code':
                continue
            for node in ast.walk(ast.parse(''.join(cell['source']))):
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'EMOTIONS' for t in node.targets):
                    assignments.append(ast.literal_eval(node.value))
        self.assertEqual(assignments, [EMOTIONS])

    def test_event_alignment(self):
        self.assertEqual(align_readings([('最初の文。', []), ('次の文。', [])], '最初の文。😮‍💨🤭🤭次の文。'),
                         ['最初の文。', '😮‍💨🤭🤭次の文。'])
        self.assertIsNone(align_readings([('原文。', [])], '別の文。'))
        self.assertEqual(align_readings([('原文。', [])], '原文。💋'), ['原文。💋'])

    def test_long_reading_preserves_event(self):
        body = '最初の文章をゆっくり読みます。次の文章もそのまま読みます。'
        spoken = body.replace('次の', '😮‍💨次の')
        segments = split_segments([dict(id='s1', text=body, tts_text=spoken)], limit=18)
        self.assertEqual(''.join(s['text'] for s in segments), body)
        self.assertEqual(''.join(s['tts_text'] for s in segments), spoken)

    def test_short_utterance_length(self):
        self.assertEqual(spoken_length('あ' * 14 + '😮‍💨'), 14)
        self.assertEqual(speak_pipeline.MIN_CHARS, 15)

if __name__ == '__main__':
    unittest.main()
