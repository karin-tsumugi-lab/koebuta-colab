"""Fixed Colab CLI entry: no shell interpolation, always emits a receipt and recovery ZIP."""
import json
import os
import subprocess
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

job_id = os.environ['IRODORI_JOB']
if not __import__('re').fullmatch(r'[A-Za-z0-9_-]{1,60}', job_id):
    raise ValueError('Invalid job ID')
root = Path('/content/irodori_cli_runs')/job_id
root.mkdir(parents=True, exist_ok=True)
background = os.environ.get('IRODORI_BACKGROUND') == '1'
code_root = Path(os.environ['IRODORI_CODE_ROOT']) if background else Path(tempfile.mkdtemp(prefix='irodori-cli-code-', dir='/content'))
if not background:
    with zipfile.ZipFile('/content/irodori_cli_code.zip') as archive:
        for member in archive.infolist():
            path = (code_root/member.filename).resolve()
            if not path.is_relative_to(code_root.resolve()) or not (member.filename.endswith('.py') or
                    member.filename in ('irodori_cli/requirements/llm.lock','irodori_cli/requirements/laya.lock')):
                raise ValueError('Invalid code archive')
        archive.extractall(code_root)
sys.path.insert(0, str(code_root))
from irodori_cli.core import atomic_json, normalize_project, read_json
action = os.environ['IRODORI_ACTION']
args = json.loads(os.environ.get('IRODORI_ARGS', '[]'))
nonce = os.environ['IRODORI_NONCE']
if not __import__('re').fullmatch(r'[a-f0-9]{32}', nonce):
    raise ValueError('Invalid invocation nonce')
receipt_path = root/'receipts'/f'{nonce}.json'
active_path = root/'.active.json'
receipt = {'action':action, 'job_id':job_id, 'nonce':nonce, 'ok':False, 'exit_code':1}
if background:
    receipt=read_json(receipt_path)


def recovery(value):
    archive_path = Path('/content')/f'irodori_cli_{job_id}_{nonce}_recovery.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('receipt.json', json.dumps(value, ensure_ascii=False))
        for path in root.rglob('*'):
            if path.name=='receipt.json' or (value.get('exit_code') is None and path.suffix=='.wav'):
                continue
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()):
                archive.write(path, path.relative_to(root).as_posix())


if action == 'inspect':
    workers=[]
    for marker in root.parent.glob('*/.active.json'):
        active=read_json(marker)
        try:
            os.kill(active['pid'],0)
        except ProcessLookupError:
            continue
        workers.append({'job':marker.parent.name,'pid':active['pid']})
    receipt.update(ok=True,exit_code=0,inspection={'active_workers':workers})
    atomic_json(receipt_path,receipt)
    recovery(receipt)
    print('REMOTE_INSPECTION',json.dumps(receipt),flush=True)
elif action == 'collect':
    receipt = read_json(receipt_path)
    log=root/f'execution_{nonce}.log'
    if log.exists():
        with log.open('rb') as stream:
            stream.seek(max(0,log.stat().st_size-12000))
            lines=stream.read().decode('utf-8',errors='replace').splitlines()
        progress=[line for line in lines if line.startswith('PROGRESS ')]
        if progress:print(progress[-1],flush=True)
    recovery(receipt)
    print('REMOTE_STATUS', json.dumps(receipt, ensure_ascii=False), flush=True)
elif not background and action in ('prepare','scenario','analyze','readings','emotions','synthesize','run'):
    # Return control to the Colab kernel, allowing pause/stop/status while the GPU worker runs.
    import fcntl
    # Also fence delayed requests from disconnected hosts and other UI workspaces.
    with (root.parent/'.launch.lock').open('a') as launch_lock:
        fcntl.flock(launch_lock,fcntl.LOCK_EX)
        for marker in root.parent.glob('*/.active.json'):
            active = read_json(marker)
            try:
                os.kill(active['pid'],0)
            except ProcessLookupError:
                continue
            raise RuntimeError('このColabランタイムには実行中の工程があります。重複起動しません')
        upload = Path('/content')/f'irodori_cli_{job_id}_project_upload.json'
        if os.environ.get('IRODORI_IMPORT_PROJECT') == '1':
            atomic_json(root/'project.json', normalize_project(read_json(upload)))
        receipt.update(exit_code=None, status='running')
        atomic_json(receipt_path, receipt)
        env = {**os.environ, 'IRODORI_BACKGROUND':'1', 'IRODORI_IMPORT_PROJECT':'0', 'IRODORI_CODE_ROOT':str(code_root)}
        with (root/f'launcher_{nonce}.log').open('a', encoding='utf-8') as stream:
            process = subprocess.Popen([sys.executable, str(code_root/'irodori_colab_entry.py')], env=env,
                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        atomic_json(active_path, {'nonce':nonce, 'pid':process.pid})
    print('REMOTE_STARTED', process.pid, flush=True)
else:
    def execute():
        global receipt
        try:
            command = [sys.executable,'-u','-m','irodori_cli.prepare',*args] if action=='prepare' else [sys.executable,'-u','-m','irodori_cli',action]
            if action in ('scenario','analyze','readings','emotions','synthesize','run','status'):
                command += ['--job',str(root/'job')]
                if action!='status':
                    command += ['--project',str(root/'project.json')]
            elif action not in ('prepare','control'):
                raise ValueError('Unsupported remote action')
            if action!='prepare':
                command += args
            environment = {**os.environ,'PYTHONPATH':str(code_root), 'PYTHONUNBUFFERED':'1',
                           'YOMIBUTA_RESIDENT_TTS':'1'}
            with (root/f'execution_{nonce}.log').open('a', encoding='utf-8') as log:
                process = subprocess.Popen(command, cwd=code_root, env=environment,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in process.stdout:
                    log.write(line); log.flush(); print(line, end='', flush=True)
                    if line.startswith('PROGRESS '):
                        receipt['progress_message']=line[9:].strip()[:240]
                        atomic_json(receipt_path,receipt)
                receipt['exit_code'] = process.wait()
                receipt['ok'] = receipt['exit_code'] == 0
                receipt['review_required'] = receipt['exit_code'] == 2
                if action=='prepare' and Path('/content/yomibuta_environment.json').is_file():
                    atomic_json(root/'job/runtime_environment.json',read_json(Path('/content/yomibuta_environment.json')))
        except Exception:
            receipt['error'] = traceback.format_exc()
            receipt.update(exit_code=1,ok=False)
        finally:
            receipt['status']='complete' if receipt['ok'] else 'review_required' if receipt.get('review_required') else 'failed'
            # Publish a terminal receipt only after its immutable recovery ZIP is ready.
            # Monitoring reads this small file over HTTP, without executing kernel code.
            recovery(receipt)
            atomic_json(receipt_path, receipt)
            if background:
                if active_path.exists() and read_json(active_path).get('nonce') == nonce:
                    active_path.unlink()
            print('REMOTE_RECEIPT', json.dumps(receipt, ensure_ascii=False), flush=True)
    execute()
