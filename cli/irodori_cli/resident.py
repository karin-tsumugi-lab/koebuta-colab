"""Single-runtime Colab TTS service. No network listener, no implicit inference retry.

The client owns the lifecycle lock for an entire request. Analysis may only start
after the old service process has exited, releasing its complete CUDA context.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

from .core import atomic_json, digest, file_hash, read_json


def root():
    return Path(os.environ.get('YOMIBUTA_RESIDENT_ROOT', '/content/yomibuta_tts_service'))


def enabled():
    return os.environ.get('YOMIBUTA_RESIDENT_TTS') == '1'


@contextlib.contextmanager
def locked():
    import fcntl
    directory = root()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory/'lifecycle.lock').open('a') as stream:
        # A disconnected host must not queue a second inference behind a live one.
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Irodoriは処理中です。停止・成果物回収後に再試行してください')
        yield


def alive(record):
    """Check process identity, including Linux start time (protect against PID reuse)."""
    try:
        stat = Path(f'/proc/{record["pid"]}/stat').read_text().rsplit(')', 1)[1].split()
        command = Path(f'/proc/{record["pid"]}/cmdline').read_bytes().split(b'\0')
        return (stat[0] != 'Z' and stat[19] == record['start'] and
                b'irodori_cli.resident' in command and record['token'].encode() in command)
    except (OSError, KeyError, IndexError):
        return False


def state():
    path = root()/'service.json'
    return read_json(path) if path.exists() else None


def connect():
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(2)
    try:
        client.connect(str(root()/'service.sock'))
        return client
    except BaseException:
        client.close()
        raise


def send(client, value):
    client.sendall((json.dumps(value, ensure_ascii=False)+'\n').encode())


def receive(client):
    with client.makefile('r', encoding='utf-8') as stream:
        line = stream.readline(1024 * 1024)
    if not line.endswith('\n'):
        raise RuntimeError('Irodori待機プロセスとの通信が切れました。成功分を回収して再開してください')
    return json.loads(line)


def stop_locked():
    record = state()
    if record and alive(record):
        print('PROGRESS Irodoriを終了し、GPUメモリを解放しています', flush=True)
        with connect() as client:
            send(client, {'op':'stop', 'token':record['token']})
            if not receive(client).get('ok'):
                raise RuntimeError('Irodoriの終了を確認できません')
        deadline = time.monotonic()+30
        while alive(record):
            if time.monotonic() >= deadline:
                raise RuntimeError('Irodoriの終了待ちが時間切れです。別モデルをロードせず停止しました')
            time.sleep(.1)
    # Never kill an unknown/PID-reused process.
    (root()/'service.json').unlink(missing_ok=True)
    (root()/'service.sock').unlink(missing_ok=True)


def unload():
    if enabled():
        with locked():
            stop_locked()


def identity(python, project):
    from .environments import signature
    package = Path(__file__).parent
    return digest({'python':python, 'environment':signature('tts'),
                   'model':read_json(project)['ttsModel'],
                   'code':{p.name:file_hash(p) for p in sorted(package.glob('*.py'))}})


def start(python, key):
    token = uuid.uuid4().hex
    with (root()/'startup.log').open('a', encoding='utf-8') as log:
        process = subprocess.Popen([python, '-u', '-m', 'irodori_cli.resident', '--detach', token],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        record = state()
        if record and record.get('token') == token and alive(record):
            process.wait(timeout=10)  # Reap the short-lived launcher, not the resident child.
            record['key'] = key
            atomic_json(root()/'service.json', record)
            return record
        if process.poll() not in (None, 0):
            raise RuntimeError('Irodori待機プロセスを起動できません。startup.logを確認してください')
        time.sleep(.1)
    # We own this Popen, so terminating it cannot target a reused/foreign PID.
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
    record = state()
    if record and record.get('token') == token:
        stop_locked()
    raise RuntimeError('Irodori待機プロセスの準備が時間切れです')


def run(python, argv, job, project):
    """Stream the current request log. A lost response never triggers generation again."""
    with locked():
        key = identity(python, project)
        record = state()
        if record and alive(record) and record.get('busy'):
            raise RuntimeError('Irodoriの前回処理が終了していません。成果物と実行状態を確認してください')
        if not record or not alive(record) or record.get('key') != key:
            stop_locked()
            record = start(python, key)
        log_path = Path(job).resolve()/f'resident_{uuid.uuid4().hex}.log'
        log_path.touch()
        with connect() as client, log_path.open(encoding='utf-8') as log:
            atomic_json(root()/'service.json', {**record, 'busy':True})
            send(client, {'op':'generate', 'token':record['token'], 'argv':argv, 'log':str(log_path)})
            import select
            while not select.select([client], [], [], .15)[0]:
                print(log.read(), end='', flush=True)
                if not alive(record):
                    raise RuntimeError('Irodoriが異常終了しました。成功分は保持されています。状態を確認して再開してください')
            # The service publishes the response only after flushing/closing the log.
            response = receive(client)
            print(log.read(), end='', flush=True)
        if not response.get('ok'):
            raise RuntimeError('Irodoriの生成に失敗しました。成功分と工程ログを確認してください')


def serve(token):
    """Keep exactly one model in one process; any inference error retires the service."""
    path = root()/'service.sock'
    path.unlink(missing_ok=True)
    runtimes = {}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path)); os.chmod(path, 0o600); server.listen(1)
        stat = Path(f'/proc/{os.getpid()}/stat').read_text().rsplit(')', 1)[1].split()
        atomic_json(root()/'service.json', {'pid':os.getpid(), 'start':stat[19], 'token':token})
        while True:
            client, _ = server.accept()
            with client:
                client.settimeout(5)
                request = receive(client)
                if request.get('token') != token:
                    send(client, {'ok':False}); continue
                if request.get('op') == 'stop':
                    send(client, {'ok':True}); return
                if request.get('op') == 'ping':
                    send(client, {'ok':True, 'pid':os.getpid()}); continue
                if request.get('op') != 'generate':
                    send(client, {'ok':False}); continue
                failed = False
                with open(request['log'], 'a', encoding='utf-8', buffering=1) as log:
                    # Python redirect plus fd redirect captures native-library messages too.
                    old_out, old_err = os.dup(1), os.dup(2)
                    try:
                        sys.stdout.flush(); sys.stderr.flush()
                        os.dup2(log.fileno(), 1); os.dup2(log.fileno(), 2)
                        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                            from .worker import main
                            if request['argv'][0] != 'synthesize':
                                raise ValueError('Only synthesis is allowed in the resident process')
                            main(request['argv'], runtimes)
                    except BaseException:
                        import traceback
                        traceback.print_exc(file=log); failed = True
                    finally:
                        sys.stdout.flush(); sys.stderr.flush()
                        os.dup2(old_out, 1); os.dup2(old_err, 2)
                        os.close(old_out); os.close(old_err)
                try:
                    record = state()
                    if record and record.get('token') == token:
                        atomic_json(root()/'service.json', {**record, 'busy':False})
                    send(client, {'ok':not failed})
                except OSError:
                    return  # Host lost: release CUDA after finishing/preserving this request.
                if failed:
                    return


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] not in ('--serve', '--detach'):
        raise SystemExit('Internal resident service entry only')
    if sys.argv[1] == '--detach':
        if os.fork():
            raise SystemExit(0)
        os.setsid()
    serve(sys.argv[2])
