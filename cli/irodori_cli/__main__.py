"""python -m irodori_cli --help"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

from .core import atomic_json, export_analysis, new_project, normalize_project, read_json, sampling_plan
from .jobs import control, load_manifest
from .gemini_models import DEFAULT_MODEL, MODELS


def setup_parser():
    parser = argparse.ArgumentParser(description='Irodori朗読CLI: 分析→人間の確認→音声生成。実行前にprepareが必要です。')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('init', help='原稿・外部分析・Web UIのJSONからプロジェクトを作成')
    p.add_argument('--source'); p.add_argument('--analysis'); p.add_argument('--ui-project')
    p.add_argument('--out', required=True)
    p.add_argument('--voice-mode', choices=['clone','design'])
    p.add_argument('--reading', choices=['shared','cast'])
    for name in ['analyze','readings','emotions','synthesize','run','scenario']:
        p = commands.add_parser(name)
        p.add_argument('--project', required=True); p.add_argument('--job', required=True)
        p.add_argument('--voice', action='append', default=[])
        p.add_argument('--ids'); p.add_argument('--regenerate', action='store_true')
        p.add_argument('--allow-unreviewed', action='store_true')
        p.add_argument('--replace-analysis', action='store_true')
        p.add_argument('--include-reviewed', action='store_true')
        p.add_argument('--context', type=int, default=0, help='Gemma: 0で自動。Qwen: 0で従来の8192')
        p.add_argument('--max-tokens', type=int, default=0, help='0: 入力・安全余裕を除いた残りを出力枠に使用')
        p.add_argument('--analyzer', choices=['qwen','gemini','gemma'], default='qwen')
        p.add_argument('--check-only', action='store_true')
        p.add_argument('--api-timeout', type=int, default=180)
        p.add_argument('--gemini-model', choices=MODELS, default=DEFAULT_MODEL)
        if name=='scenario':
            p.add_argument('--scenario-emotion', choices=['on','off'], default='on')
            p.add_argument('--structure', choices=['auto','prose','script'], default='auto')
    p = commands.add_parser('plan', help='モデルを読み込まずSamplingRequestを確認')
    p.add_argument('--project', required=True); p.add_argument('--voice', action='append', default=[])
    p = commands.add_parser('review', help='利用者による確認済み指定（品質の自動検証ではありません）')
    p.add_argument('--project', required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true'); group.add_argument('--ids')
    p = commands.add_parser('export-analysis'); p.add_argument('--project', required=True); p.add_argument('--out', required=True)
    p = commands.add_parser('status'); p.add_argument('--job', required=True)
    p = commands.add_parser('control'); p.add_argument('--job', required=True); p.add_argument('action', choices=['pause','stop','resume'])
    p = commands.add_parser('bundle'); p.add_argument('--project', required=True); p.add_argument('--job', required=True); p.add_argument('--out', required=True)
    return parser


def voices(items):
    result = {}
    for item in items:
        key, separator, value = item.partition('=')
        if not separator or not key or not value or key in result:
            raise ValueError('--voiceは重複のない profile=ファイル 形式です')
        result[key] = value
    return result


def create(path, data):
    if Path(path).exists():
        raise FileExistsError(f'{path}: 既存ファイルを上書きしません。別の出力先を指定してください')
    atomic_json(path, data)


def worker(stage, args):
    job = Path(args.job)
    job.mkdir(parents=True, exist_ok=True)
    if not (job/'job.json').exists():
        atomic_json(job/'job.json', load_manifest(job))
    before = normalize_project(read_json(args.project))
    atomic_json(job/'snapshots'/f'{time.time_ns()}_{stage}.json', before)
    from .environments import executable
    from . import resident
    if stage != 'synthesize':
        resident.unload()
    engine='gemma' if stage.startswith('gemma') else {'qwen':'qwen','qwen-readings':'qwen','qwen-scenario':'qwen','emotions':'laya','synthesize':'tts'}[stage]
    command = [executable(engine),'-u','-m','irodori_cli.worker',stage,'--project',str(Path(args.project).resolve()),'--job',str(job.resolve()),
               '--context',str(args.context if stage.startswith('gemma') else (args.context or 8192)),'--max-tokens',str(args.max_tokens)]
    if args.check_only:command.append('--check-only')
    if stage.endswith('-scenario'):
        command += ['--analyzer',args.analyzer,'--scenario-emotion',args.scenario_emotion,'--structure',args.structure]
    for flag in ('replace_analysis','include_reviewed','regenerate'):
        if getattr(args, flag):
            command.append('--'+flag.replace('_','-'))
    for key, value in voices(args.voice).items():
        command.extend(['--voice',key+'='+value])
    if args.ids:
        command.extend(['--ids',args.ids])
    started = time.time()
    atomic_json(job/'stage_status.json', {'stage':stage,'status':'running','started':started})
    persistent = stage == 'synthesize' and resident.enabled()
    try:
        if persistent:
            resident.run(command[0], command[4:], job, args.project)
            result = subprocess.CompletedProcess(command, 0)
        else:
            result = subprocess.run(command)
    except BaseException:
        atomic_json(job/'stage_status.json', {'stage':stage,'status':'failed',
            'error':'Worker interrupted or resident response lost; collect before retry'})
        raise
    atomic_json(job/'stage_status.json', {'stage':stage,'status':'complete' if not result.returncode else 'failed','returncode':result.returncode})
    # The parent imports no ML libraries. Analysis exits; TTS may stay in its service.
    memory = subprocess.run(['nvidia-smi','--query-gpu=memory.used,memory.total','--format=csv,noheader,nounits'], capture_output=True, text=True)
    atomic_json(job/f'{stage}_{"model_lifecycle" if persistent else "process_exit"}.json', {'stage':stage,'returncode':result.returncode,
        'seconds':time.time()-started,
        'gpu_while_resident' if persistent else 'gpu_after_process_exit':memory.stdout.strip(),
        'isolation':'resident TTS retained for next generation' if persistent else 'subprocess exited before next model load'})
    if result.returncode and not (stage.endswith('-scenario') and result.returncode==2):
        raise RuntimeError(f'{stage}工程に失敗しました。成功分と診断情報は{job}に保持しています')
    return result.returncode


def main(argv=None):
    args = setup_parser().parse_args(argv)
    if getattr(args,'check_only',False) and (args.analyzer!='gemma' or args.command not in ('analyze','readings','emotions')):
        raise ValueError('原稿検査はanalyze/emotions --analyzer gemmaで実行してください')
    if args.command == 'init':
        if args.ui_project and (args.source or args.analysis):
            raise ValueError('--ui-projectと原稿・分析JSONの同時指定はできません')
        source = Path(args.source).read_text(encoding='utf-8-sig') if args.source else ''
        project = normalize_project(read_json(args.ui_project)) if args.ui_project else new_project(source, read_json(args.analysis) if args.analysis else None)
        if args.voice_mode:
            project['voiceMode'] = args.voice_mode
        if args.reading:
            project['reading'] = args.reading
        create(args.out, project)
        print('PROJECT_READY', args.out, 'analyzed=', project['analyzed'])
        return 0
    if args.command == 'status':
        manifest = load_manifest(args.job)
        stage_path = Path(args.job)/'stage_status.json'
        if stage_path.exists():
            manifest['stage'] = read_json(stage_path)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'control':
        control(args.job, args.action)
        print('CONTROL_REQUESTED', args.action, '発話の境界で停止。resume後は同じsynthesizeコマンドで再開します')
        return 0
    project = normalize_project(read_json(args.project))
    if args.command=='scenario':
        if project['analyzed'] or args.analyzer not in ('gemma','qwen'):
            raise ValueError('統合シナリオ化は新規原稿とGemma/Qwenで使用してください。既存シナリオは保持しています')
        return worker(args.analyzer+'-scenario',args)
    if args.command == 'review':
        selected = set(s['id'] for s in project['segments']) if args.all else set(args.ids.split(','))
        if not selected <= {s['id'] for s in project['segments']}:
            raise ValueError('未登録の発話IDがあります')
        for row in project['segments']:
            if row['id'] in selected:
                row['reviewed'] = True
        atomic_json(args.project, project)
        print('REVIEW_MARKED', len(selected), '品質を自動検証したものではありません')
        return 0
    if args.command == 'export-analysis':
        create(args.out, export_analysis(project))
        return 0
    if args.command == 'plan':
        from .segmentation import prepare_project
        project=prepare_project(project)
        print(json.dumps(sampling_plan(project, voices(args.voice)), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'bundle':
        output = Path(args.out)
        if output.exists():
            raise FileExistsError('ZIPの既存ファイルは上書きしません')
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('project.json', json.dumps(project, ensure_ascii=False, indent=2))
            root = Path(args.job).resolve()
            for path in root.rglob('*'):
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root) and path.suffix in ('.json','.wav','.log') and path.resolve()!=output.resolve():
                    archive.write(path, 'job/'+path.relative_to(root).as_posix())
            archive.writestr('LISTENING_REVIEW.txt', 'Human listening required: speaker assignment; voice consistency; pronunciation and omissions; emotion/acting; joins and gaps; clipping/noise. Code success does not validate emotional quality.\nReference voice files are NOT included.\n')
        print('BUNDLE_READY', output)
        return 0
    if args.command in ('analyze','run') and (args.command=='analyze' or not project['analyzed']):
        if args.analyzer=='gemini':
            from .gemini import analyze_project
            if project['analyzed'] and not args.replace_analysis:
                raise ValueError('分析済み設定の置換には --replace-analysis が必要です')
            print(json.dumps(analyze_project(args.project,args.job,model=args.gemini_model,timeout=args.api_timeout),ensure_ascii=False))
        else:
            worker('gemma' if args.analyzer=='gemma' else 'qwen', args)
        if args.check_only:return 0
    if args.command in ('analyze','readings','emotions','synthesize','run') and any((Path(args.job)/name).exists() for name in ('.pause','.stop')):
        print('CONTROLLED_STOP: resumeで停止要求を解除してから同じ工程を再実行してください')
        return 3
    from .reading_stage import enabled as reading_enabled
    if args.command=='readings' or (args.command=='run' and os.environ.get('IRODORI_READINGS_DONE')!='1' and reading_enabled(normalize_project(read_json(args.project)))):
        if args.analyzer=='gemini':
            from .reading_stage import run
            run(args,analyzer='gemini')
        else:worker('gemma-readings' if args.analyzer=='gemma' else 'qwen-readings',args)
        if args.command=='readings':return 0
    if args.command == 'emotions' or (args.command=='run' and normalize_project(read_json(args.project))['emotion']):
        if args.analyzer=='gemini':
            from .gemini import emotions_project
            print(json.dumps(emotions_project(args.project,args.job,model=args.gemini_model,timeout=args.api_timeout),ensure_ascii=False))
        else:
            worker('gemma-emotions' if args.analyzer=='gemma' else 'emotions', args)
        if args.command=='run' and args.analyzer=='gemma':
            print('REVIEW_REQUIRED: 感情候補を確認して反映し、synthesizeで音声を生成してください。')
            return 2
        if any((Path(args.job)/name).exists() for name in ('.pause','.stop')):
            return 3
    if args.command in ('synthesize','run'):
        project = normalize_project(read_json(args.project))
        from .segmentation import prepare_with_mapping,expand_ids
        original=project
        project,mapping=prepare_with_mapping(project)
        if any(len(parts)>1 for parts in mapping.values()):atomic_json(Path(args.job)/'snapshots'/f'{time.time_ns()}_before_tts_split.json',{'project':original,'mapping':mapping})
        if args.ids:args.ids=','.join(expand_ids(args.ids.split(','),mapping))
        atomic_json(args.project,project)
        selected = set(args.ids.split(',')) if args.ids else {s['id'] for s in project['segments']}
        if not selected <= {s['id'] for s in project['segments']}:
            raise ValueError('生成対象の発話IDが存在しません')
        from .text_conversion import convert_project
        speaking={r['id'] for r in convert_project(project) if r['segment_type']=='speech'}
        if not selected&speaking:raise ValueError('指定範囲に読み上げる本文がありません')
        if not args.allow_unreviewed and any(not s['reviewed'] for s in project['segments'] if s['id'] in selected&speaking):
            print('REVIEW_REQUIRED: プロジェクトJSONの話者・感情を確認し、reviewで確認済みにしてください。推論結果は保存済みです。')
            return 2
        sampling_plan(project, voices(args.voice))  # Validate paths/settings before GPU load.
        worker('synthesize', args)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        raise SystemExit(1)
