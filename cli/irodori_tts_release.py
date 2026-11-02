"""Release an existing idle Colab TTS service before local Gemini API work.

Standalone because this control operation must not install/upload model code or
start a new Colab runtime. Uses the same locks as the launcher and service client.
"""
import fcntl
import json
import os
from pathlib import Path
import socket
import time


def release():
    directory=Path(os.environ.get('YOMIBUTA_RESIDENT_ROOT','/content/yomibuta_tts_service'))
    jobs=Path(os.environ.get('YOMIBUTA_RUNTIME_ROOT','/content'))/'irodori_cli_runs'
    marker=directory/'service.json'
    if not marker.exists():return
    def read(path):return json.loads(path.read_text())
    def alive(record):
        try:
            stat=Path(f'/proc/{record["pid"]}/stat').read_text().rsplit(')',1)[1].split()
            command=Path(f'/proc/{record["pid"]}/cmdline').read_bytes().split(b'\0')
            return (stat[0]!='Z' and stat[19]==record['start'] and
                    b'irodori_cli.resident' in command and record['token'].encode() in command)
        except (OSError,KeyError,IndexError):return False
    with (jobs/'.launch.lock').open('a') as launch:
        fcntl.flock(launch,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for path in jobs.glob('*/.active.json'):
            record=read(path)
            try:os.kill(record['pid'],0)
            except ProcessLookupError:continue
            raise RuntimeError('Colabで実行中の工程があるためIrodoriを解放できません')
        with (directory/'lifecycle.lock').open('r') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            record=read(marker)
            if not alive(record):return
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.settimeout(2);client.connect(str(directory/'service.sock'))
                client.sendall((json.dumps({'op':'stop','token':record['token']})+'\n').encode())
                with client.makefile('r') as stream:reply=json.loads(stream.readline(4096))
                if reply!={'ok':True}:raise RuntimeError('Irodoriの終了応答を確認できません')
            deadline=time.monotonic()+20
            while alive(record):
                if time.monotonic()>deadline:raise RuntimeError('Irodoriの終了を確認できません')
                time.sleep(.1)
    print('PROGRESS Irodoriを解放しました',flush=True)


if __name__=='__main__':release()
