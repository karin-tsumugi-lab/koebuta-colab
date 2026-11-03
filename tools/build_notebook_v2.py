"""Build a standalone v2 Notebook while retaining P0 parsing and synthesis."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    original = json.loads((ROOT / 'notebook/Koebuta_Colabv1.00.ipynb').read_text(encoding='utf-8'))
    cells = original['cells'][:8]
    cells[0] = dict(cell_type='markdown', metadata={}, source=[
        '# Koebuta Notebook v2 — 生成専用試作\n',
        'GPUランタイムで上から実行してください。シナリオ編集はHTML版で行います。\n',
        'Driveは任意です。利用する場合は下のセルでマウントしてください。\n',
        'Colabの利用条件・モデルと音声素材の利用条件はv1と同様に確認してください。\n'])
    source = "print('Irodori-TTSモデルをGPUへ読み込み中です。完了後にWebUIを公開します。')\nload_runtime()\nprint('モデルの準備が完了しました。WebUIを構築します。')\nimport sys, types\n"
    for module in ('notebook_v2', 'notebook_v2_ui'):
        content = (ROOT / 'notebook' / (module + '.py')).read_text(encoding='utf-8')
        source += f"_module = types.ModuleType({module!r})\nsys.modules[{module!r}] = _module\nexec({content!r}, _module.__dict__)\n"
    source += "from notebook_v2_ui import create_v2_ui\nimport secrets, os, gradio as gr\ndemo = create_v2_ui(globals())\nui_user = 'koebuta'\nui_password = secrets.token_urlsafe(16)\nprint('ユーザー:', ui_user, 'パスワード:', ui_password)\ndemo.queue(default_concurrency_limit=1)\ndemo.launch(share=True, auth=(ui_user, ui_password), theme=gr.themes.Soft(primary_hue='purple'), show_error=True)\n"
    source = source.replace('show_error=True)', 'css="' + '#seed-random{flex:0 0 44px!important;width:44px!important;min-width:44px!important;max-width:44px!important}' + '", show_error=True)')
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
    (ROOT / 'notebook/Koebuta_Colabv2.prototype.ipynb').write_text(build(), encoding='utf-8')
