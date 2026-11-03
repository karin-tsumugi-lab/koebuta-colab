"""Generate a prepared scenario through the existing Colab CLI transport."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

from irodori_cli.core import (atomic_json, identifier, new_project, normalize_project,
                              read_json, sampling_plan)
from irodori_cli.jobs import inside
from irodori_cli.auto_reference import reference_plan, validate_supplied
from irodori_cli.segmentation import prepare_project
from irodori_colab_cli import verify_recovery
from irodori_cli.terminal import (Console, command_text, duration, read_runtime,
                                 read_usage, run_logged, runtime_stopped)

ROOT = Path(__file__).resolve().parent
SETTINGS = {'title', 'reading', 'voiceMode', 'baseCaption', 'seed', 'steps', 'pause',
            'ttsModel', 'acting', 'emotion', 'narratorEmotion', 'textOptions',
            'speakerVoices', 'voices', 'autoReference', 'autoReferenceSegments', 'confirm'}


def load_inputs(scenario_path, settings_path, voice_items=()):
    scenario = read_json(scenario_path)
    if not isinstance(scenario, dict) or not isinstance(scenario.get('segments'), list):
        raise ValueError('本文付きschema_version=1のシナリオJSONが必要です')
    if any(not isinstance(row, dict) or 'text' not in row for row in scenario['segments']):
        raise ValueError('すべての発話にtextが必要です。本文なし分析には対応しません')
    settings = read_json(settings_path)
    if not isinstance(settings, dict) or set(settings) - SETTINGS:
        unknown = ', '.join(sorted(set(settings) - SETTINGS)) if isinstance(settings, dict) else 'オブジェクト以外'
        raise ValueError('生成設定に未対応の項目があります: ' + unknown)
    project = new_project('', scenario)
    for key in ('autoReference', 'confirm'):
        if key in settings and type(settings[key]) is not bool:
            raise ValueError(key + 'はbooleanです')
    project.update({k: v for k, v in settings.items() if k not in
                    ('speakerVoices', 'voices', 'autoReference', 'autoReferenceSegments', 'confirm')})
    # Omission requests automatic preparation; an explicit design mode opts out.
    if 'voiceMode' not in settings:
        project['voiceMode'] = 'clone'
    if settings.get('autoReference', True):
        project['autoReference'] = {'version': 1, 'selections': settings.get('autoReferenceSegments', {})}
    elif settings.get('autoReferenceSegments'):
        raise ValueError('autoReference=falseでは参照文の選択を指定できません')
    assignments = settings.get('speakerVoices', {})
    if not isinstance(assignments, dict) or set(assignments) - {r['id'] for r in project['roles']}:
        raise ValueError('speakerVoicesに未登録の話者があります')
    for role in project['roles']:
        if role['id'] in assignments:
            role['voice'] = identifier(assignments[role['id']], 'voice profile')
    project = prepare_project(normalize_project(project))
    declared = settings.get('voices', {})
    if not isinstance(declared, dict):
        raise ValueError('voicesはプロファイルIDと音声パスのオブジェクトです')
    voices = {}
    for key, value in declared.items():
        identifier(key, 'voice profile')
        if not isinstance(value, str) or not value.strip():
            raise ValueError('参照音声は空でないパスを指定してください')
        path = Path(value).expanduser()
        voices[key] = str((Path(settings_path).resolve().parent / path).resolve())
    overrides = set()
    for item in voice_items:
        key, separator, value = item.partition('=')
        identifier(key, 'voice profile')
        if not separator or not value or key in overrides:
            raise ValueError('--voiceは重複のないprofile=ファイル形式です')
        overrides.add(key)
        voices[key] = str(Path(value).expanduser().resolve())
    for path in voices.values():
        validate_supplied(path)
    if project['reading'] == 'shared':
        if 'voice_a' in voices:
            # The explicitly shared WAV takes precedence over per-speaker WAVs.
            voices = {'voice_a': voices['voice_a']}
        elif assignments or voices:
            raise ValueError('一人朗読の声が競合しています。共通WAVをvoices.voice_aで指定するか、人物別朗読を選んでください')
    requests = sampling_plan(project, voices, allow_pending=True)
    used = {row['reference']['profile'] for row in requests if row['reference']}
    if set(voices) - used:
        raise ValueError('未使用の参照音声があります。voicesと声の割当を確認してください')
    return project, voices, requests


def generation_summary(project, voices, requests):
    _, groups = reference_plan(project, voices)
    if not groups:
        grouped = {}
        for row in requests:
            group = 'shared' if project['reading'] == 'shared' else row['role']
            item = grouped.setdefault(group, {'group': group,
                'mode': 'supplied' if row['reference'] else 'design',
                'profile': row['reference']['profile'] if row['reference'] else None, 'utterances': []})
            item['utterances'].append(row['id'])
        groups = list(grouped.values())
    for group in groups:
        if group['mode'] == 'supplied':
            group['wav'] = voices[group['profile']]
    return {'automatic_references': groups,
            'utterances': len(requests),
            'potential_rebuild_utterances': sum(len(g['utterances']) for g in groups if g['mode'] == 'automatic'),
            'resume_policy': '設定とWAV検証が一致する参照のみ再利用。変更時は依存音声を作り直します。遠隔キャッシュの有無は実行時に確定します'}


def confirm_generation(summary, *, assume_yes=False, enabled=True):
    print('生成計画: ' + str(summary['utterances']) + '発話')
    modes = {'automatic': '自動参照', 'supplied': '指定WAV', 'design': '参照なし', 'fallback': '参照なし（候補文なし・単一発話）'}
    for group in summary['automatic_references']:
        print(f'  {group["group"]}: {modes[group["mode"]]}' +
              (f' / 参照文 {group["segment"]}: {group["text"]}' if group['mode'] == 'automatic' else ''))
        if group.get('wav'):
            print('  WAV: ' + group['wav'])
        if group.get('caption'):
            print('  声質: ' + group['caption'])
        if group.get('warning'):
            print('  注意: ' + group['warning'])
    print(f'自動参照の新規作成・変更時に生成する音声: 最大{summary["potential_rebuild_utterances"]}発話')
    print(summary['resume_policy'], flush=True)
    if assume_yes or not enabled:
        return True
    if not sys.stdin.isatty():
        raise ValueError('対話できません。--dry-runで計画を確認し、承認済みなら--yesを指定してください')
    try:
        return input('この内容で生成しますか？ [y/N] ').strip().lower() == 'y'
    except EOFError:
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description='本文付きシナリオJSONからColabで音声生成・回収（再分析なし）')
    parser.add_argument('--scenario', required=True, type=Path, help='本文付きschema_version=1のシナリオJSON')
    parser.add_argument('--settings', required=True, type=Path, help='独立した生成設定JSON')
    parser.add_argument('--voice', action='append', default=[], help='profile=WAV。設定内の同名プロファイルを上書き')
    parser.add_argument('--session', required=True, help='Colabセッション名。新規作成は--newを指定')
    parser.add_argument('--job', required=True, help='遠隔ジョブの識別名（英数字・_・-、60文字以内）')
    parser.add_argument('--out', required=True, type=Path, help='新しい出力フォルダー')
    parser.add_argument('--new', action='store_true', help='新しいGPUランタイムを作成')
    parser.add_argument('--gpu', default='T4', choices=['T4', 'L4', 'G4', 'A100', 'H100'])
    parser.add_argument('--skip-prepare', action='store_true', help='同じ版のTTS準備済みランタイムを使用')
    parser.add_argument('--stop-after-download', action='store_true', help='回収と検証の成功後に指定ランタイムを停止')
    parser.add_argument('--timeout', type=int, default=7200, help='工程ごとの待機上限秒（既定7200）。切断時は遠隔状態を確認')
    parser.add_argument('--dry-run', action='store_true', help='ローカル検査と生成計画のみ。Colabに接続しない')
    parser.add_argument('--yes', '-y', action='store_true', help='生成前の確認を省略。入力の競合・不正は省略しない')
    parser.add_argument('--no-usage', action='store_true', help='CU残量の照会を省略する')
    parser.add_argument('--version', action='version', version='Irodori Colab CLI 1.1.0')
    args = parser.parse_args(argv)
    identifier(args.session, 'session', 60)
    identifier(args.job, 'job', 60)
    if args.timeout <= 0 or (args.new and args.skip_prepare):
        raise ValueError('timeoutは正の秒数です。--newと--skip-prepareは併用できません')
    project, voices, requests = load_inputs(args.scenario, args.settings, args.voice)
    summary_plan = generation_summary(project, voices, requests)
    if args.dry_run:
        print(json.dumps({'session': args.session, 'new_runtime': args.new,
                          'prepare': not args.skip_prepare, 'engine': 'tts',
                          'model': project['ttsModel'], 'plan': summary_plan,
                          'requests': requests}, ensure_ascii=False, indent=2))
        return 0
    # Claim a fresh directory before invoking Colab; never overwrite previous results.
    out = args.out.resolve()
    if out.exists():
        raise FileExistsError(f'出力先が既にあります。新しいフォルダーを指定してください: {out}')
    if not confirm_generation(summary_plan, assume_yes=args.yes,
                              enabled=read_json(args.settings).get('confirm', True)):
        print('生成を取りやめました。')
        return 0
    out.mkdir(parents=True, exist_ok=False)
    console = Console(out / 'events.jsonl')
    telemetry = {'scope': 'account', 'usage_enabled': not args.no_usage}
    started = time.monotonic()
    active_stage = None
    runtime = None
    telemetry_warning_shown = False

    def save_telemetry():
        nonlocal telemetry_warning_shown
        try:
            atomic_json(out / 'telemetry.json', telemetry)
        except OSError as exc:
            # CU/runtime observations are supplementary. Keep the warning in
            # memory so pipeline.json can still record it after audio succeeds.
            telemetry['save_error'] = f'{type(exc).__name__}: {exc}'
            if not telemetry_warning_shown:
                print('WARNING: 補助情報 telemetry.json を保存できません。生成結果の判定は維持します。',
                      file=sys.stderr, flush=True)
                telemetry_warning_shown = True

    def usage(label):
        if args.no_usage:
            return
        try:
            sample = read_usage()
            telemetry['usage_' + label] = sample
            title = {'start': '開始時', 'allocated': '準備後', 'end': '終了時'}[label]
            console.say(f'CU（アカウント全体・{title}）: 残量 {sample["balance"]:.2f} / '
                        f'消費率 {sample["rate"]:.2f} CU/時間 / 稼働枠 {sample["active_assignments"]}')
        except Exception:
            telemetry['usage_' + label] = {'available': False}
            console.say('CU情報: 取得不可。生成は継続します')
        save_telemetry()

    def finish_telemetry(fetch_end=True):
        if fetch_end:
            usage('end')
        telemetry['elapsed_seconds'] = round(time.monotonic() - started, 3)
        first, last = telemetry.get('usage_start', {}), telemetry.get('usage_end', {})
        if 'balance' in first and 'balance' in last:
            telemetry['account_balance_decrease'] = round(first['balance'] - last['balance'], 6)
            console.say(f'CU残量の差分（アカウント全体）: {telemetry["account_balance_decrease"]:.2f} '
                        'CU。ほかの処理や残量の補充も含み得ます')
        save_telemetry()

    atomic_json(out / 'project.json', project)
    atomic_json(out / 'plan.json', {'requests': requests, **summary_plan})
    atomic_json(out / 'pipeline.json', {'status': 'running', 'session': args.session, 'job': args.job})
    driver = [sys.executable, str(ROOT / 'irodori_colab_cli.py')]
    common = ['--session', args.session, '--job', args.job, '--timeout', str(args.timeout)]

    def stage(name, extra):
        nonlocal active_stage
        active_stage = name
        command = driver + [name] + common + ['--out', str(out / name)] + extra
        atomic_json(out / (name + '_command.json'), command)
        console.previous = None
        console.baseline = None
        console.say({'prepare': '環境準備を開始', 'synthesize': '生成・回収を開始'}[name] + f' / ログ: {out / (name + ".log")}')
        with (out / (name + '.log')).open('w', encoding='utf-8') as log:
            result = run_logged(command, log, console)
        if result.returncode:
            raise RuntimeError(f'{name}に失敗しました。終了コード{result.returncode}。ログ: {out / (name + ".log")}')

    try:
        counts = sum(row['request']['no_ref'] for row in requests)
        console.say(f'開始: {project["title"]} / セッション {args.session} / ジョブ {args.job}')
        console.say(f'モデル: {project["ttsModel"]} / {project["steps"]}ステップ / seed {project["seed"]}')
        console.say(f'朗読: {"一人朗読" if project["reading"] == "shared" else "人物別"} / '
                    f'{len(requests)}発話 / クローン {len(requests)-counts}・参照なし {counts}')
        console.say('GPU: ' + (args.gpu + '（新規作成の指定）' if args.new else '既存セッションを照会します'))
        console.say('終了後のランタイム: ' + ('回収成功後に停止' if args.stop_after_download else '保持（明示停止が必要）'))
        usage('start')
        if not args.skip_prepare:
            extra = ['--engine', 'tts']
            if args.new:
                extra += ['--new', '--gpu', args.gpu]
            stage('prepare', extra)
        try:
            runtime = read_runtime(args.session)
            telemetry['runtime'] = runtime
            console.say(f'実行GPU: {runtime["hardware"]} / {runtime["shape"]} / {runtime["identity"]}')
        except Exception:
            console.say('実行GPUの詳細: 取得不可。生成は継続します')
        usage('allocated')
        # Inputs are already authored scenarios. This explicit unattended entry
        # bypasses the interactive review gate without fabricating reviewed flags.
        extra = ['--project', str(out / 'project.json'), '--allow-unreviewed']
        for key, value in voices.items():
            extra += ['--voice', key + '=' + value]
        stage('synthesize', extra)
        console.say('回収結果を検証中')
        latest = read_json(out / 'synthesize' / 'latest.json')
        receipt = latest['receipt']
        if (receipt.get('job_id') != args.job or receipt.get('action') != 'synthesize'
                or receipt.get('exit_code') != 0 or receipt.get('ok') is not True):
            raise ValueError('生成完了の受付情報が一致しません')
        recovered = Path(latest['recovered']).resolve()
        if not recovered.is_relative_to(out / 'synthesize'):
            raise ValueError('回収先が今回の出力フォルダーに含まれていません')
        verified = verify_recovery(recovered)
        if not verified.get('audio_checked') or verified.get('job_status') != 'complete':
            raise ValueError('全体の音声生成が完了していません。回収結果を確認してください')
        manifest = read_json(recovered / 'job' / 'job.json')
        if (recovered / 'job' / 'references.json').exists():
            shutil.copytree(recovered / 'job' / 'references', out / 'references')
            shutil.copyfile(recovered / 'job' / 'references.json', out / 'references.json')
        combined = manifest['combined']
        shutil.copyfile(inside(recovered / 'job', combined['file']), out / 'result.wav')
        with zipfile.ZipFile(out / 'segments.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for relative in dict.fromkeys(combined['take_files']):
                archive.write(inside(recovered / 'job', relative), relative)
        shutil.copyfile(recovered / 'project.json', out / 'generated_project.json')
        summary = {'status': 'complete', 'session': args.session, 'job': args.job,
                   'audio': str(out / 'result.wav'), 'segments': str(out / 'segments.zip'),
                   'recovered': str(recovered), 'verification': verified, 'session_stopped': False}
        atomic_json(out / 'pipeline.json', summary)
    except (Exception, KeyboardInterrupt) as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        failed = {'status': 'interrupted' if interrupted else 'failed', 'session': args.session,
                  'job': args.job, 'stage': active_stage, 'error': str(exc), 'session_stopped': False}
        if active_stage:
            invocations = sorted((out / active_stage).glob('*/invocation.json'))
            if invocations:
                recovery = driver + ['recover', '--session', args.session, '--job', args.job,
                    '--from-invocation', str(invocations[-1].parent), '--out', str(out / 'recovery'),
                    '--timeout', str(args.timeout)]
                failed['recovery_command'] = recovery
                atomic_json(out / 'recovery_command.json', recovery)
                console.say('再生成せず状態・成果物を回収するコマンド: ' + command_text(recovery))
        atomic_json(out / 'pipeline.json', failed)
        console.say(f'{"中断" if interrupted else "失敗"}: ランタイムは停止していません。ログ: {out}')
        finish_telemetry(fetch_end=not interrupted)
        if interrupted:
            return 130
        raise
    if args.stop_after_download:
        from irodori_local import colab_command
        try:
            console.say('ランタイムを停止中')
            if not runtime or not runtime.get('identity'):
                raise RuntimeError('実行したランタイムの識別情報を取得できていないため、自動停止せず保持します')
            if read_runtime(args.session)['identity'] != runtime['identity']:
                raise RuntimeError('同名のランタイムが入れ替わったため停止しません')
            with (out / 'stop.log').open('w', encoding='utf-8') as log:
                result = subprocess.run(colab_command() + ['stop', '-s', args.session], timeout=90,
                                        stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(f'終了コード{result.returncode}')
            if not runtime_stopped(args.session):
                raise RuntimeError('停止後の状態を確認できませんでした')
            summary['session_stopped'] = True
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            summary['shutdown_error'] = str(exc)
            print('SESSION_STOP_FAILED: 音声は回収済みです。セッションの状態を確認してください', file=sys.stderr)
        atomic_json(out / 'pipeline.json', summary)
    finish_telemetry()
    summary['telemetry'] = telemetry
    atomic_json(out / 'pipeline.json', summary)
    console.say(f'完了: {len(requests)}発話 / 音声 {verified["combined_seconds"]:.2f}秒 / 経過 {duration(time.monotonic()-started)}')
    console.say('検証: WAVのハッシュ・フレーム数が一致')
    console.say('完成WAV: ' + str(out / 'result.wav'))
    console.say('発話別ZIP: ' + str(out / 'segments.zip'))
    console.say('ランタイム: ' + ('停止確認済み' if summary['session_stopped'] else
                '停止未確認（状態を確認してください）' if summary.get('shutdown_error') else '保持中（明示停止が必要）'))
    print('AUDIO_READY', out / 'result.wav', flush=True)
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('中断しました。回収済みファイルは保持しています。ランタイムの状態を確認してください。', file=sys.stderr)
        raise SystemExit(130)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        raise SystemExit(1)
