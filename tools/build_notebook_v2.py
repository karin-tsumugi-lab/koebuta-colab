"""Build a standalone v2 Notebook while retaining P0 parsing and synthesis."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    original = json.loads((ROOT / 'notebook/Koebuta_Colabv1.00.ipynb').read_text(encoding='utf-8'))
    cells = original['cells'][:8]
    cells[0] = dict(cell_type='markdown', metadata={}, source=(ROOT / 'notebook/NOTEBOOK_V2_GUIDE.md').read_text(encoding='utf-8').splitlines(True))
    cells[7]['source'] = ['## 4. 画面（WebUI）\n', '\n', 'モデルをGPUへ読み込んでから、認証付きのGradio共有リンクを表示します。準備中はセルの出力をご確認ください。\n']
    source = "print('Irodori-TTSモデルをGPUへ読み込み中です。完了後にWebUIを公開します。')\nload_runtime()\nprint('モデルの準備が完了しました。WebUIを構築します。')\nimport sys, types\n"
    for module in ('notebook_v2', 'notebook_v2_ui'):
        content = (ROOT / 'notebook' / (module + '.py')).read_text(encoding='utf-8')
        source += f"_module = types.ModuleType({module!r})\nsys.modules[{module!r}] = _module\nexec({content!r}, _module.__dict__)\n"
    source += "from notebook_v2_ui import create_v2_ui\nimport secrets, os, gradio as gr\ndemo = create_v2_ui(globals())\nui_user = 'koebuta'\nui_password = secrets.token_urlsafe(16)\nprint('ユーザー:', ui_user, 'パスワード:', ui_password)\ndemo.queue(default_concurrency_limit=1)\ndemo.launch(share=True, auth=(ui_user, ui_password), theme=gr.themes.Soft(primary_hue='purple'), show_error=True)\n"
    source = source.replace('show_error=True)', 'css="' + '#seed-field{position:relative}#seed-random{position:absolute!important;top:4px;right:8px;left:auto!important;z-index:5;min-height:22px!important;height:22px!important;padding:0!important;width:32px!important;min-width:32px!important;max-width:32px!important}' + '", show_error=True)')
    cells.append(dict(cell_type='code', metadata={}, execution_count=None, outputs=[], source=source.splitlines(True)))
    cells.insert(2, dict(cell_type='code', metadata={}, execution_count=None, outputs=[], source=[
        '# Driveを利用する場合だけTrueにして実行\n',
        'USE_DRIVE = False\n',
        'if USE_DRIVE:\n',
        '    from google.colab import drive\n',
        "    drive.mount('/content/drive')\n"]))
    for cell in cells:
        if cell['cell_type'] == 'code':
            cell['outputs'] = []
            cell['execution_count'] = None
            compile(''.join(cell['source']), '<v2-cell>', 'exec')
    original['cells'] = cells
    return json.dumps(original, ensure_ascii=False, indent=1) + '\n'


if __name__ == '__main__':
    content = build()
    for name in ('Koebuta_Notebook_v2.ipynb', 'Koebuta_Colabv2.prototype.ipynb'):
        (ROOT / 'notebook' / name).write_text(content, encoding='utf-8')
