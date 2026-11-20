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

from irodori_cli.core import atomic_json, identifier, read_json
from irodori_cli.jobs import inside
from irodori_cli.faithful import PlanError
from irodori_colab_cli import verify_recovery
from irodori_cli.terminal import (Console, command_text, duration, read_runtime,
                                 read_usage, run_logged, runtime_stopped)

ROOT = Path(__file__).resolve().parent



def load_inputs(
    scenario_path,
    settings_path,
    voice_items=(),
    selected=None,
    *,
    ruby_mode=None,
    ruby_threshold=0.8327,
    ruby_single_threshold=0.65,
    ruby_device='auto',
    ruby_preflight=False,
    ruby_scorer=None,
):
    from irodori_cli.faithful import build_plan, load_json, plan_signature, CONTRACT, PlanError
    from irodori_cli.ruby_bridge import apply_ruby_to_scenario, prepare_remote_ruby_scenario, uses_added_ruby, has_automatic_ruby
    try:
        scenario, settings = load_json(scenario_path), load_json(settings_path)
    except (ValueError, OSError) as exc:
        raise PlanError([dict(level='error', code='E_STRUCTURE', segment_id=None,
                              field='input', message=str(exc))]) from exc
    if ruby_mode is None:
        ruby_mode = 'auto_select' if has_automatic_ruby(scenario) else 'none'
    ruby_report = []
    ruby_filter = None
    if ruby_preflight and ruby_device == 'local':
        raise ValueError('--ruby-preflight は遠隔判定モードです。--ruby-device local とは併用できません')
    if ruby_preflight and ruby_mode == 'none':
        ruby_mode = 'auto_select'
    if ruby_mode != 'none' or uses_added_ruby(scenario):
        resolved_device = 'remote' if ruby_preflight else (
            ('remote' if ruby_mode == 'auto_select' else 'local') if ruby_device == 'auto' else ruby_device
        )
        try:
            if resolved_device == 'remote' and ruby_mode != 'none':
                scenario = prepare_remote_ruby_scenario(scenario, strict=True)
                ruby_filter = {
                    'mode': ruby_mode,
                    'threshold': float(ruby_threshold),
                    'single_token_threshold': ruby_single_threshold,
                }
            else:
                scenario, ruby_report = apply_ruby_to_scenario(
                    scenario,
                    mode=ruby_mode,
                    threshold=ruby_threshold,
                    single_token_threshold=ruby_single_threshold,
                    strict=True,
                    scorer=ruby_scorer,
                )
        except ValueError as exc:
            raise PlanError([dict(level='error', code='E_RUBY_SYNTAX', segment_id=None,
                                  field='tts_text', message=str(exc))]) from exc
    overrides = {}
    for item in voice_items:
        key, separator, value = item.partition('=')
        identifier(key, 'voice profile')
        if not separator or not value or key in overrides:
            raise ValueError('--voiceは重複のないprofile=ファイル形式です')
        overrides[key] = str(Path(value).expanduser().resolve())
    plan = build_plan(scenario, settings, base=Path(settings_path).resolve().parent,
                      voices=overrides, selected=selected, ruby_deferred=bool(ruby_filter))
    if set(overrides) - set(plan['voices']):
        raise ValueError('--voiceに選択範囲で使用しない参照音声があります')
    document = dict(contract=CONTRACT, scenario=scenario, settings=settings, selection=selected,
                    expected_plan=plan_signature(plan), execution=plan['execution'],
                    diagnostics=plan['diagnostics'], effective_settings=plan['settings'])
    if ruby_report:
        document['ruby_decisions'] = ruby_report
    if ruby_filter:
        document['ruby_filter'] = ruby_filter
    if ruby_preflight:
        document['ruby_preflight'] = True
    # The existing transport reads a 2MiB project, including its execution envelope.
    # Check the actual serialized size before allocating a remote runtime.
    serialized = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if sys.platform == 'win32':
        serialized = serialized.replace('\n', '\r\n')
    if len(serialized.encode('utf-8')) > 2 * 1024 * 1024:
        raise PlanError([dict(level='error', code='E_STRUCTURE', segment_id=None,
                              field='input', message='実行記録を含む転送JSONが2MiBを超えます。章単位に分けてください')])
    return document, plan['voices'], plan['requests']


def write_segment_archive(destination, job, manifest):
    """Keep take names and avoid collisions when extracting on Windows."""
    devices = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{port}{i}' for port in ('COM', 'LPT') for i in range(1, 10)}
    parents = manifest.get('parent_audio', {})
    reserved = {f'{sid}.wav'.casefold() for sid in parents}
    used = set()
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for relative in dict.fromkeys(manifest['combined']['take_files']):
            archive.write(inside(job, relative), relative)
        for sid, record in parents.items():
            name = f'{sid}.wav'
            if name.casefold() in used or sid.upper() in devices:
                serial = 1
                name = f'{sid}__{serial}.wav'
                while name.casefold() in reserved or name.casefold() in used:
                    serial += 1
                    name = f'{sid}__{serial}.wav'
            used.add(name.casefold())
            archive.write(inside(job, record['file']), f'utterances/{name}')


def verify_authored_recovery(recovered, document, requests):
    manifest = read_json(Path(recovered) / 'job/job.json')
    if (manifest.get('authored_plan_signature') != document['expected_plan']
            or manifest.get('execution') != document['execution']
            or read_json(Path(recovered) / 'project.json') != document):
        raise ValueError('回収した実行契約・生成計画・入力がホストと一致しません')
    combined = manifest.get('combined') or {}
    used = [next((t for t in reversed(manifest.get('takes', [])) if t['file'] == name), {})
            for name in combined.get('take_files', [])]
    if [t.get('id') for t in used] != [r['id'] for r in requests]:
        raise ValueError('回収した音声の対象ID・順序・個数が生成計画と一致しません')
    expected_parents = {r['segment_id'] for r in requests if r['part_count'] > 1
                        and r['segment_id'] in document['execution']['complete_segment_ids']}
    if set(manifest.get('parent_audio', {})) != expected_parents:
        raise ValueError('親発話WAVの完成範囲が生成計画と一致しません')
    for record in manifest.get('parent_audio', {}).values():
        from irodori_cli.jobs import wav_info
        from irodori_cli.core import file_hash
        path = inside(Path(recovered) / 'job', record['file'])
        if file_hash(path) != record['sha256'] or wav_info(path)['frames'] != record['frames']:
            raise ValueError('親発話WAVの回収検証に失敗しました')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description='本文付きシナリオJSONからColabで音声生成・回収（再分析なし）')
    parser.add_argument('--scenario', required=True, type=Path, help='本文付きschema_version=1のシナリオJSON')
    parser.add_argument('--settings', required=True, type=Path, help='独立した生成設定JSON')
    parser.add_argument('--ids', help='対象発話IDまたは明示片（例 t001,t003#2）。新しい出力先へ選択生成')
    parser.add_argument('--voice', action='append', default=[], help='profile=WAV。設定内の同名プロファイルを上書き')
    parser.add_argument('--session', help='Colabセッション名。新規作成は--newを指定（--dry-run時は省略可）')
    parser.add_argument('--job', help='遠隔ジョブの識別名（英数字・_・-、60文字以内。--dry-run時は省略可）')
    parser.add_argument('--out', type=Path, help='新しい出力フォルダー（--dry-run時は省略可）')
    parser.add_argument('--new', action='store_true', help='新しいGPUランタイムを作成')
    parser.add_argument('--gpu', default='T4', choices=['T4', 'L4', 'G4', 'A100', 'H100'])
    parser.add_argument('--skip-prepare', action='store_true', help='同じ版のTTS準備済みランタイムを使用')
    parser.add_argument('--stop-after-download', action='store_true', help='回収と検証の成功後に指定ランタイムを停止')
    parser.add_argument('--timeout', type=int, default=7200, help='工程ごとの待機上限秒（既定7200）。切断時は遠隔状態を確認')
    parser.add_argument('--dry-run', action='store_true', help='ローカル検査と生成計画のみ。Colabに接続しない')
    parser.add_argument('--no-usage', action='store_true', help='CU残量の照会を省略する')
    parser.add_argument('--ruby-mode',
                        choices=['none', 'original', 'partial_kana', 'auto_select'],
                        help='tts_text（未指定時はtext）のルビ変換モード（既定: 自動採用の追加ルビがあれば auto_select、それ以外は none）')
    parser.add_argument('--ruby-threshold', type=float, default=0.8327,
                        help='auto_select時の複数トークン語閾値（既定: 0.8327）')
    parser.add_argument('--ruby-single-threshold', type=float, default=0.65,
                        help='auto_select時の1トークン語閾値（既定: 0.65）')
    parser.add_argument('--ruby-device', default='auto',
                        choices=['auto', 'remote', 'local'],
                        help='ルビ選択の実行先（既定: auto = auto_selectはColab GPU、他はローカル）')
    parser.add_argument('--ruby-preflight', action='store_true',
                        help='音声生成を行わず、Colab GPUでauto_selectの事前判定と要確認語リスト(ruby_review.json)のみ回収する')
    parser.add_argument('--export-compatible', type=Path, metavar='JSON',
                        help='確定した読みを旧版向けJSONへ書き出す（音声生成なし）')
    parser.add_argument('--version', action='version', version='Koebuta CLI 2.0.0-dev (faithful-v1)')
    args = parser.parse_args(argv)
    if args.export_compatible and (args.ids or args.ruby_preflight or args.new):
        parser.error('--export-compatible は作品全体の書き出し専用です')
    if args.dry_run or args.export_compatible:
        args.session = args.session or 'dry-run'
        args.job = args.job or 'dry-run'
    elif not args.session or not args.job or args.out is None:
        parser.error('--session / --job / --out は必須です（--dry-run 時のみ省略可）')
    identifier(args.session, 'session', 60)
    identifier(args.job, 'job', 60)
    if args.timeout <= 0 or (args.new and args.skip_prepare):
        raise ValueError('timeoutは正の秒数です。--newと--skip-prepareは併用できません')
    project, voices, requests = load_inputs(
        args.scenario,
        args.settings,
        args.voice,
        args.ids,
        ruby_mode='none' if args.export_compatible else args.ruby_mode,
        ruby_threshold=args.ruby_threshold,
        ruby_single_threshold=args.ruby_single_threshold,
        ruby_device=args.ruby_device,
        ruby_preflight=args.ruby_preflight,
    )
    if args.export_compatible:
        exported = project['scenario']
        for row in exported['segments']:
            row.pop('koebuta_added_ruby', None)
        with args.export_compatible.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(exported, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        return 0
    cfg = project['effective_settings']
    for item in project['diagnostics']:
        if item['level'] == 'warning':
            print(f"WARNING {item['code']} {item.get('segment_id') or '全体'}: {item['message']}", file=sys.stderr)
    if args.dry_run:
        from irodori_cli.faithful import build_plan
        from irodori_cli.ruby_bridge import apply_ruby_to_scenario, uses_added_ruby

        ruby_decisions = project.get('ruby_decisions')
        diagnostics = project['diagnostics']
        pending = []
        ruby_filter = project.get('ruby_filter', {})
        if ruby_filter and uses_added_ruby(project['scenario']):
            preview, ruby_decisions = apply_ruby_to_scenario(
                project['scenario'], mode='none',
                selected_segment_ids={row['segment_id'] for row in requests})
            preview_plan = build_plan(preview, project['settings'], voices=voices,
                                      selected=project['selection'],
                                      base=args.settings.resolve().parent)
            requests = preview_plan['requests']
            diagnostics = preview_plan['diagnostics']
            if ruby_filter['mode'] == 'auto_select':
                for result in ruby_decisions:
                    for item in result['decisions']:
                        if item['selection'] == 'auto':
                            item['selected'] = None
                            pending.append(dict(segment_id=result['segment_id'], **item))
        payload = {'session': args.session, 'new_runtime': args.new,
                   'prepare': not args.skip_prepare, 'engine': 'tts',
                   'model': cfg['ttsModel'], 'requests': requests,
                   'execution': project['execution'], 'settings': cfg,
                   'diagnostics': diagnostics}
        if ruby_decisions is not None:
            payload['ruby_decisions'] = ruby_decisions
        if pending:
            payload['ruby_pending'] = pending
        if 'ruby_filter' in project:
            payload['ruby_filter'] = project['ruby_filter']
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    # Claim a fresh directory before invoking Colab; never overwrite previous results.
    out = args.out.resolve()
    if out.exists():
        raise FileExistsError(f'出力先が既にあります。新しいフォルダーを指定してください: {out}')
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
    atomic_json(out / 'plan.json', {'requests': requests, 'execution': project['execution'],
                                    'diagnostics': project['diagnostics'], 'settings': cfg})
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
        console.say(f'開始: {cfg["title"]} / セッション {args.session} / ジョブ {args.job}')
        console.say(f'モデル: {cfg["ttsModel"]} / {cfg["steps"]}ステップ / seed {cfg["seed"]}')
        console.say(f'朗読: {"一人朗読" if cfg["reading"] == "shared" else "人物別"} / '
                    f'{len(requests)}生成単位 / クローン {len(requests)-counts}・参照なし {counts}')
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
        if args.ruby_preflight:
            if verified.get('job_status') != 'preflight_complete':
                raise ValueError('事前判定が完了していません。回収結果を確認してください')
            manifest = read_json(recovered / 'job/job.json')
            if manifest.get('authored_plan_signature') != project['expected_plan']:
                raise ValueError('回収した事前判定の計画署名がホストと一致しません')
            shutil.copyfile(recovered / 'job/ruby_decisions.json', out / 'ruby_decisions.json')
            shutil.copyfile(recovered / 'job/ruby_review.json', out / 'ruby_review.json')
            shutil.copyfile(recovered / 'project.json', out / 'generated_project.json')
            summary = {'status': 'preflight_complete', 'session': args.session, 'job': args.job,
                       'ruby_decisions': str(out / 'ruby_decisions.json'),
                       'ruby_review': str(out / 'ruby_review.json'),
                       'flagged_count': manifest.get('ruby_review', {}).get('flagged_count', 0),
                       'recovered': str(recovered), 'verification': verified, 'session_stopped': False,
                       'execution': project['execution']}
            atomic_json(out / 'pipeline.json', summary)
        else:
            if not verified.get('audio_checked') or verified.get('job_status') != 'complete':
                raise ValueError('対象範囲の音声生成が完了していません。回収結果を確認してください')
            manifest = verify_authored_recovery(recovered, project, requests)
            combined = manifest['combined']
            shutil.copyfile(inside(recovered / 'job', combined['file']), out / 'result.wav')
            write_segment_archive(out / 'segments.zip', recovered / 'job', manifest)
            shutil.copyfile(recovered / 'project.json', out / 'generated_project.json')
            summary = {'status': 'complete', 'session': args.session, 'job': args.job,
                       'audio': str(out / 'result.wav'), 'segments': str(out / 'segments.zip'),
                       'recovered': str(recovered), 'verification': verified, 'session_stopped': False,
                       'execution': project['execution']}
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
    if args.ruby_preflight:
        console.say(f'事前判定完了: {len(requests)}生成単位 / 要確認語 {summary["flagged_count"]}件 / 経過 {duration(time.monotonic()-started)}')
        console.say('要確認語リスト: ' + str(out / 'ruby_review.json'))
        console.say('全判定結果: ' + str(out / 'ruby_decisions.json'))
        console.say('ランタイム: ' + ('停止確認済み' if summary['session_stopped'] else
                    '停止未確認（状態を確認してください）' if summary.get('shutdown_error') else '保持中（明示停止が必要）'))
        print('PREFLIGHT_READY', out / 'ruby_review.json', flush=True)
        return 0
    console.say(f'{"選択範囲の生成完了" if project["execution"]["scope"] == "selection" else "全体の生成完了"}: {len(requests)}生成単位 / 音声 {verified["combined_seconds"]:.2f}秒 / 経過 {duration(time.monotonic()-started)}')
    console.say('検証: WAVのハッシュ・フレーム数が一致')
    console.say(('選択範囲WAV: ' if project['execution']['scope'] == 'selection' else '完成WAV: ') + str(out / 'result.wav'))
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
    except PlanError as exc:
        print(json.dumps({'status': 'invalid', 'diagnostics': exc.diagnostics}, ensure_ascii=False))
        print('ERROR:', exc, file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        raise SystemExit(1)
