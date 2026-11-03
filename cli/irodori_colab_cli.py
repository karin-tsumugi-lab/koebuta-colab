"""Host-side Colab driver. Always recover outputs; stop only after verified download."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from irodori_cli.core import atomic_json, identifier, normalize_project, read_json
from irodori_cli.core import file_hash
from irodori_cli.jobs import inside, wav_info
from irodori_cli.gemini_models import DEFAULT_MODEL, MODELS

ROOT = Path(__file__).resolve().parent


def timed_colab_command(cli, arguments, seconds):
    # Killing wsl.exe alone can leave the Linux CLI alive. Bound it inside WSL too.
    if os.name=='nt' and cli[:2]==['wsl','-e']:
        return cli[:2]+['timeout','--signal=TERM','--kill-after=2',f'{max(.1,seconds-4):.2f}s',*cli[2:],*arguments]
    return cli+arguments


def bounded_colab_call(cli, arguments, deadline, check=True):
    remaining=deadline-time.monotonic()
    if remaining<=0:
        print('COLAB_STATE_UNCONFIRMED 待機期限を超えました。自動再実行しません',flush=True)
        raise TimeoutError('Colabの確認期限を超えました')
    print('PROGRESS Colab: '+arguments[0],flush=True)
    try:
        limit=300 if arguments[0] in ('upload','download') else 180 if arguments[0]=='new' else 90
        seconds=min(limit,remaining)
        started=time.monotonic()
        result=subprocess.run(timed_colab_command(cli,arguments,seconds),check=check,timeout=seconds)
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
        code=exc.returncode if isinstance(exc,subprocess.CalledProcessError) else 'host_timeout'
        print(f'COLAB_CALL_FAILED operation={arguments[0]} elapsed={time.monotonic()-started:.2f}s limit={seconds:.2f}s code={code}',flush=True)
        print('COLAB_STATE_UNCONFIRMED 接続または回収に失敗。遠隔状態の照合が必要です',flush=True)
        raise
    if result.returncode:
        print('COLAB_STATE_UNCONFIRMED CLIが異常終了。完了受付を照合します',flush=True)
    print(f'COLAB_CALL_END operation={arguments[0]} elapsed={time.monotonic()-started:.2f}s code={result.returncode}',flush=True)
    return result


def validate_receipt(receipt,job,action,nonce):
    if not isinstance(receipt,dict) or receipt.get('job_id')!=job or receipt.get('action')!=action or receipt.get('nonce')!=nonce:
        raise ValueError('実行受付情報が一致しません。ランタイムを停止しません')
    if receipt.get('exit_code') is not None and type(receipt.get('exit_code')) is not int:
        raise ValueError('実行受付の終了コードが不正です')
    return receipt


def wait_receipt(call,session,job,action,nonce,destination,deadline,interval=10):
    """Read-only HTTP polling; never rerun a model on a transport failure."""
    remote=f'/content/irodori_cli_runs/{job}/receipts/{nonce}.json'
    failures=0
    while True:
        try:
            call(['download','-s',session,remote,remote_path(destination)])
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
            failures+=1
            if failures>=3 or time.monotonic()>=deadline:raise
            print(f'PROGRESS 状態ファイルの取得を再試行します（{failures}/2）。モデルは再実行しません',flush=True)
            time.sleep(min(interval,max(0,deadline-time.monotonic())))
            continue
        failures=0
        receipt=validate_receipt(read_json(destination),job,action,nonce)
        if receipt.get('progress_message'):print('PROGRESS '+receipt['progress_message'],flush=True)
        if receipt['exit_code'] is not None:return receipt
        if time.monotonic()>=deadline:raise TimeoutError('確認時間を超えました。遠隔処理と成果物は保持しています')
        time.sleep(min(interval,max(0,deadline-time.monotonic())))


def verify_recovery(recovered):
    root = Path(recovered)/'job'
    manifest_path = root/'job.json'
    if not manifest_path.exists():
        return {'audio_checked':False, 'reason':'no synthesis job yet'}
    manifest = read_json(manifest_path)
    combined = manifest.get('combined')
    if manifest['status']=='complete' and not combined:
        raise ValueError('完了ジョブの結合音声がありません。ランタイムを停止しません')
    if not combined:
        return {'audio_checked':False, 'job_status':manifest['status']}
    from irodori_cli.auto_reference import verify_references
    references_checked = verify_references(root)
    for relative in combined['take_files']:
        take = next(t for t in reversed(manifest['takes']) if t['file']==relative)
        path = inside(root, relative)
        if file_hash(path)!=take['sha256'] or wav_info(path)['frames']!=take['frames']:
            raise ValueError('回収した発話WAVの検証に失敗しました。ランタイムを停止しません')
    path = inside(root, combined['file'])
    if file_hash(path)!=combined['sha256'] or wav_info(path)['frames']!=combined['frames']:
        raise ValueError('回収した結合WAVの検証に失敗しました。ランタイムを停止しません')
    return {'audio_checked':True,'job_status':manifest['status'],'combined_seconds':combined['seconds'],
            'references_checked': references_checked, 'speech_quality_validated':False}


def remote_path(path):
    path = Path(path).resolve()
    if os.name == 'nt':
        return '/mnt/'+path.drive[0].lower()+'/'+path.as_posix()[3:]
    return str(path)


def main():
    parser = argparse.ArgumentParser(description='Colab CLIを使う実推論の工程別ドライバー。既定ではランタイムを保持します。')
    parser.add_argument('action', choices=['prepare','scenario','analyze','readings','emotions','synthesize','run','status','pause','stop','resume','inspect','recover'])
    parser.add_argument('--from-invocation',type=Path,help='recover: 保存済みinvocation.jsonのあるフォルダー。モデルを再実行せず回収を再開')
    parser.add_argument('--session'); parser.add_argument('--job', required=True)
    parser.add_argument('--expect-session-id',help='接続確認済みランタイムの識別子。同名環境の入れ替わりを拒否')
    parser.add_argument('--new', action='store_true'); parser.add_argument('--gpu', default='T4')
    parser.add_argument('--project'); parser.add_argument('--out', required=True)
    parser.add_argument('--voice', action='append', default=[])
    parser.add_argument('--ids'); parser.add_argument('--regenerate', action='store_true')
    parser.add_argument('--allow-unreviewed', action='store_true')
    parser.add_argument('--replace-analysis', action='store_true')
    parser.add_argument('--qwen', action='store_true'); parser.add_argument('--stop-after-download', action='store_true')
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--analyzer', choices=['qwen','gemini','gemma'], default='qwen')
    parser.add_argument('--context',type=int,default=0)
    parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--engine',choices=['gemma','qwen','laya','tts','all'])
    parser.add_argument('--api-timeout', type=int, default=180)
    parser.add_argument('--gemini-model', choices=MODELS, default=DEFAULT_MODEL)
    parser.add_argument('--scenario-emotion', choices=['on','off'], default='on')
    parser.add_argument('--structure', choices=['auto','prose','script'], default='auto')
    parser.add_argument('--release-tts-session', help='既存の確認済みColabのIrodoriだけを解放（新規接続しない）')
    args = parser.parse_args()
    nonce = uuid.uuid4().hex
    if args.action=='recover':
        if not args.from_invocation:parser.error('recoverには --from-invocation が必要です')
        saved=read_json(args.from_invocation/'invocation.json')
        if saved.get('protocol') not in (None,2) or saved.get('job')!=args.job or (args.session and saved.get('session')!=args.session):
            raise ValueError('回収対象のジョブ・接続先・保存形式が一致しません')
        identifier(saved.get('nonce'),'nonce',32)
        if len(saved['nonce'])!=32 or any(c not in '0123456789abcdef' for c in saved['nonce']):raise ValueError('不正な実行受付IDです')
        if saved.get('action') not in ('prepare','scenario','analyze','readings','emotions','synthesize','run','status','pause','stop','resume','inspect'):raise ValueError('回収対象の工程が不正です')
        if args.new or args.project or args.voice:raise ValueError('recoverでは新規ランタイム・原稿・音声を指定しないでください')
        nonce=saved['nonce'];args.action=saved['action'];args.session=saved['session']
    elif args.from_invocation:
        parser.error('--from-invocation は recover 専用です')
    identifier(args.job, 'job', 60)
    args.out = Path(args.out).resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    invocation = args.out/f'{time.time_ns()}_{args.action}'
    invocation.mkdir()
    atomic_json(invocation/'invocation.json',{'protocol':2,'nonce':nonce,'action':args.action,'job':args.job,'session':args.session})
    readings_done=False
    if args.analyzer=='gemini' and args.action in ('analyze','readings','emotions','run'):
        if not args.project:
            raise ValueError('Geminiのローカル分析には --project が必要です')
        if args.release_tts_session:
            from irodori_cli.connection import inventory,capture
            from irodori_local import colab_command
            cli=colab_command()
            entries=inventory(cli)
            bound=next((e for e in entries if e['name']==args.release_tts_session),None)
            if bound:
                if not args.expect_session_id or bound['identity']!=args.expect_session_id:
                    raise RuntimeError('Colabの識別情報が変わったためIrodoriを解放しません')
                print(capture(cli,['exec','-s',args.release_tts_session,'--timeout','30',
                    '-f',remote_path(ROOT/'irodori_tts_release.py')],45),flush=True)
        from irodori_local import local_command, wsl_path
        recovered=invocation/'recovered'
        recovered.mkdir()
        project_file=recovered/'project.json'
        atomic_json(project_file,normalize_project(read_json(args.project)))
        local_action=args.action if args.action in ('emotions','readings') else 'analyze'
        command,environment=local_command(['-m','irodori_cli',local_action,'--analyzer','gemini',
            '--project',wsl_path(project_file),'--job',wsl_path(recovered/'job'),'--api-timeout',str(args.api_timeout),'--gemini-model',args.gemini_model])
        if args.replace_analysis:command+=['--replace-analysis']
        result=subprocess.run(command,env=environment,timeout=args.api_timeout+30)
        if result.returncode==0 and args.action=='run':
            from irodori_cli.reading_stage import enabled
            if enabled(read_json(project_file)):
                reading_command,reading_environment=local_command(['-m','irodori_cli','readings','--analyzer','gemini',
                    '--project',wsl_path(project_file),'--job',wsl_path(recovered/'job'),'--api-timeout',str(args.api_timeout),'--gemini-model',args.gemini_model])
                result=subprocess.run(reading_command,env=reading_environment,timeout=args.api_timeout+30)
                readings_done=result.returncode==0
        receipt={'action':local_action,'analyzer':'gemini','job_id':args.job,'nonce':nonce,'ok':result.returncode==0,'exit_code':result.returncode}
        atomic_json(recovered/'receipt.json',receipt)
        atomic_json(args.out/'latest.json',{'recovered':str(recovered),'receipt':receipt})
        if result.returncode or args.action in ('analyze','readings','emotions'):
            print('LOCAL_ARTIFACTS',recovered)
            return result.returncode
        args.project=str(project_file)
        # Remaining GPU stages receive only analyzed JSON, never the API key.
    if not args.session:
        raise ValueError('Colabを使う工程には --session が必要です')
    from irodori_local import colab_command
    cli = colab_command()
    if args.expect_session_id:
        from irodori_cli.connection import inventory
        entries=inventory(cli)
        found=next((e for e in entries if e['name']==args.session),None)
        if not found or found['identity']!=args.expect_session_id:
            raise ValueError('接続先が終了したか別のランタイムに変わりました。再接続して確認してください。工程は起動していません')
    deadline = time.monotonic()+args.timeout
    def call(arguments, check=True):
        return bounded_colab_call(cli,arguments,deadline,check)
    action = 'control' if args.action in ('pause','stop','resume') else args.action
    if not args.from_invocation:
        code_zip = invocation/'code.zip'
        with zipfile.ZipFile(code_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in (ROOT/'irodori_cli').glob('*.py'):
                archive.write(path, 'irodori_cli/'+path.name)
            for name in ('llm.lock','laya.lock'):
                path=ROOT/'irodori_cli/requirements'/name
                archive.write(path,'irodori_cli/requirements/'+name)
            archive.write(ROOT/'irodori_colab_entry.py', 'irodori_colab_entry.py')
        if args.new:
            call(['new','-s',args.session,'--gpu',args.gpu])
        call(['upload','-s',args.session,remote_path(code_zip),'/content/irodori_cli_code.zip'])
        extra = []
        if args.project:
            local_project = invocation/'project_upload.json'
            atomic_json(local_project, normalize_project(read_json(args.project)))
            call(['upload','-s',args.session,remote_path(local_project),f'/content/irodori_cli_{args.job}_project_upload.json'])
        for item in args.voice:
            key, separator, path = item.partition('=')
            identifier(key, 'voice profile')
            if not separator or not Path(path).is_file():
                raise ValueError('参照音声は profile=既存ファイル の形式です')
            target = f'/content/irodori_cli_voice_{args.job}_{key}.wav'
            call(['upload','-s',args.session,remote_path(path),target])
            extra += ['--voice',key+'='+target]
        action = args.action
        if action == 'prepare':
            extra = ['--engine',args.engine] if args.engine else ['--engine','gemma'] if args.analyzer=='gemma' else ['--qwen'] if args.qwen else []
        elif action in ('pause','stop','resume'):
            extra = ['--job',f'/content/irodori_cli_runs/{args.job}/job',action]
            action = 'control'
        else:
            if action=='scenario':
                if args.analyzer not in ('gemma','qwen'):raise ValueError('統合シナリオ化のモデルを確認してください')
                extra += ['--scenario-emotion',args.scenario_emotion,'--structure',args.structure]
            if args.analyzer=='gemma' and action in ('scenario','analyze','readings','emotions','synthesize','run'):
                extra += ['--analyzer','gemma','--context',str(args.context)]
                if args.check_only:extra += ['--check-only']
            if args.ids:
                extra += ['--ids',args.ids]
            if args.regenerate:
                extra += ['--regenerate']
            if args.replace_analysis:
                extra += ['--replace-analysis']
            if args.allow_unreviewed:
                extra += ['--allow-unreviewed']
        environment = ['--env','IRODORI_READINGS_DONE='+('1' if readings_done else '0'),'--env','IRODORI_NONCE='+nonce, '--env','IRODORI_JOB='+args.job, '--env','IRODORI_ACTION='+action,
                       '--env','IRODORI_IMPORT_PROJECT='+('1' if args.project else '0'),
                       '--env','IRODORI_ARGS='+json.dumps(extra, ensure_ascii=False)]
        call(['exec','-s',args.session,'--timeout',str(args.timeout),*environment,'-f',remote_path(ROOT/'irodori_colab_entry.py')], check=False)
    # A successful CLI exit alone does not prove the Python stage succeeded.
    downloaded = invocation/'recovery.zip'
    recovered = invocation/'recovered'
    receipt=wait_receipt(call,args.session,args.job,action,nonce,invocation/'remote_receipt.json',deadline)
    for attempt in range(3):
        try:
            call(['download','-s',args.session,f'/content/irodori_cli_{args.job}_{nonce}_recovery.zip',remote_path(downloaded)])
            break
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
            if attempt==2:raise
            print('PROGRESS 成果物の取得だけを再試行します。モデルは再実行しません',flush=True)
    with zipfile.ZipFile(downloaded) as archive:
        for entry in archive.infolist():
            if not (recovered/entry.filename).resolve().is_relative_to(recovered.resolve()):
                raise ValueError('回収ZIPに不正なパスがあります。ランタイムを停止しません')
        archive.extractall(recovered)
    recovered_receipt=validate_receipt(read_json(recovered/'receipt.json'),args.job,action,nonce)
    if recovered_receipt['exit_code']!=receipt['exit_code']:raise ValueError('回収結果と実行受付が一致しません')
    print('PROGRESS 回収した成果物の整合性を確認中',flush=True)
    verification = verify_recovery(recovered)
    atomic_json(args.out/'latest.json', {'recovered':str(recovered), 'receipt':receipt, 'verification':verification})
    # Optional log export must never delay a verified result or hide its receipt.
    try:
        subprocess.run(timed_colab_command(cli,['log','-s',args.session,'-o',remote_path(invocation/'colab_execution.md')],10), timeout=10, check=False)
    except (subprocess.TimeoutExpired,OSError):
        print('PROGRESS 診断ログの取得は時間切れ。回収済みの結果は保存済みです',flush=True)
    if args.stop_after_download and receipt['ok']:
        call(['stop','-s',args.session])
    print('LOCAL_ARTIFACTS', recovered)
    print('SESSION', args.session, '停止済み' if args.stop_after_download and receipt['ok'] else '保持中。終了時は colab stop を明示実行してください')
    return receipt['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
