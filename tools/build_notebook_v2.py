"""Build a standalone v2 Notebook while retaining P0 parsing and synthesis."""
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def v2_validation_source(source):
    """Keep source alignment advisory in v2 without editing the v1 artifact."""
    replacements = (
        ("add('要確認',f'項目 {s.get(\"id\")}', '原稿全文中に同じ原文を順序どおり見つけられません（部分照合）')",
         "add('警告',f'項目 {s.get(\"id\")}', '原稿全文中に同じ原文を順序どおり見つけられません（部分照合）。許可済みの見出し改変か、意図しない本文の差分かを確認してください。生成は継続できます')"),
        ("lines = [f'要確認・エラー: {len(issues)}件 / 読込時の注意: {len(warns)}件']",
         "blocking = [issue for issue in issues if issue[0] != '警告']\n"
         "    lines = [f'要確認・エラー: {len(blocking)}件 / 警告: {len(issues) - len(blocking)}件 / 読込時の注意: {len(warns)}件']"),
        ("def require_ready(project):\n    issues = validate_project(project)",
         "def require_ready(project):\n    issues = [issue for issue in validate_project(project) if issue[0] != '警告']"),
    )
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError('v2 validation adapter no longer matches the v1 source: ' + before)
        source = source.replace(before, after, 1)
    return source


def build():
    original = json.loads((ROOT / 'notebook/Koebuta_Colabv1.00.ipynb').read_text(encoding='utf-8'))
    cells = original['cells'][:8]
    # Extend the runtime before validation or request planning can use it.
    additions = runpy.run_path(str(ROOT / 'cli/irodori_cli/emoji_tags.py'))['ADDITIONAL']
    for cell in cells:
        if cell['cell_type'] == 'code' and 'def validate_project(' in ''.join(cell['source']):
            cell['source'] = v2_validation_source(''.join(cell['source'])).splitlines(True)
        if cell['cell_type'] == 'code' and 'def build_plan(' in ''.join(cell['source']):
            source = ''.join(cell['source'])
            before = "STATE['plan_warnings'] = []"
            if source.count(before) != 1:
                raise ValueError('v2 plan warning adapter no longer matches the v1 source')
            cell['source'] = source.replace(before,
                "STATE['plan_warnings'] = [f'{level} | {item}: {message}'\n"
                "        for level, item, message in validate_project(project) if level == '警告']", 1).splitlines(True)
        if cell['cell_type'] == 'code' and 'EMOTIONS = dict(zip(' in ''.join(cell['source']):
            cell['source'] = (''.join(cell['source']) + f'\nEMOTIONS.update({additions!r})\n').splitlines(True)
    cells[0] = dict(cell_type='markdown', metadata={}, source=(ROOT / 'notebook/NOTEBOOK_V2_GUIDE.md').read_text(encoding='utf-8').splitlines(True))
    cells[7]['source'] = ['## 4. 画面（WebUI）\n', '\n', 'モデルをGPUへ読み込んでから、認証付きのGradio共有リンクを表示します。準備中はセルの出力をご確認ください。\n']
    source = "print('Irodori-TTSモデルをGPUへ読み込み中です。完了後にWebUIを公開します。')\nload_runtime()\nprint('モデルの準備が完了しました。WebUIを構築します。')\nimport sys, types\n"
    source += "_koebuta_package = types.ModuleType('irodori_cli')\n_koebuta_package.__path__ = []\nsys.modules['irodori_cli'] = _koebuta_package\n"
    for name in ('ruby_core', 'ruby_bridge'):
        content = (ROOT / 'cli' / 'irodori_cli' / (name + '.py')).read_text(encoding='utf-8')
        module = 'irodori_cli.' + name
        source += f"_module = types.ModuleType({module!r})\nsys.modules[{module!r}] = _module\nexec({content!r}, _module.__dict__)\n"
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
    # The prototype is a historical artifact, not a second current release.
    (ROOT / 'notebook/Koebuta_Notebook_v2.ipynb').write_text(content, encoding='utf-8', newline='\n')
