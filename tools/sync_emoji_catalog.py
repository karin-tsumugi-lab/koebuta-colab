"""Refresh embedded catalogs in standalone distribution entry points."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cli'))
from irodori_cli.emoji_tags import EMOTIONS

source = ROOT / 'cli/irodori_cli/emoji_tags.py'
(ROOT / 'fast/emoji_tags.py').write_bytes(source.read_bytes())
html_path = ROOT / 'Koebuta_Scenario_Inspector_v0.1.6.html'
html = html_path.read_text(encoding='utf-8')
start = html.index('const EMOTIONS = {')
end = html.index('\n};', start) + 3
old = html[start:end]
labels = dict(re.findall(r"(\w+):\['([^']*)','[^']*'\]", old))
if not labels:
    labels = {key: value[0] for key, value in json.loads(old[len('const EMOTIONS = '):-1]).items()}
entries = {key: [labels.get(key, key), emoji or '―'] for key, emoji in EMOTIONS.items()}
html = html[:start] + 'const EMOTIONS = ' + json.dumps(entries, ensure_ascii=False, indent=2) + ';' + html[end:]
html = html.replace('id="shortLimit" type="number" min="1" step="1" value="12"', 'id="shortLimit" type="number" min="1" step="1" value="15"')
html = html.replace('low:12,high:140', 'low:15,high:140')
html_path.write_text(html, encoding='utf-8')
notebook_path = ROOT / 'notebook/Koebuta_Colabv1.00.ipynb'
notebook = json.loads(notebook_path.read_text(encoding='utf-8'))
for cell in notebook['cells']:
    text = ''.join(cell.get('source', []))
    if 'EMOTIONS = ' in text:
        text, count = re.subn(r'EMOTIONS = (?:dict\(zip\([\s\S]*?\)\)|\{[^\n]*\})', lambda match: 'EMOTIONS = ' + repr(EMOTIONS), text, count=1)
        assert count == 1
        cell['source'] = text.splitlines(keepends=True)
notebook_path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print('Synchronized CLI, Fast, Inspector and notebook emotion catalogs')
