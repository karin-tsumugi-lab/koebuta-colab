"""Bounded, read-only Colab discovery. Failure is never treated as an empty list."""
import json
import re
import subprocess
from pathlib import Path


def capture(cli,args,timeout=45):
    from irodori_colab_cli import timed_colab_command
    result=subprocess.run(timed_colab_command(cli,args,timeout),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if result.returncode:
        details=(result.stderr+'\n'+result.stdout).lower()
        if 'connection was lost' in details:raise RuntimeError('Colabとの通信が途中で切れました。「再接続して状態を確認」で再試行できます')
        if any(word in details for word in ('invalid_grant','unauthenticated','authentication failed')):raise RuntimeError('Colab CLIの認証を確認してください。認証の確認後、接続先一覧を更新できます')
        raise RuntimeError('Colab CLIから正常な応答を受け取れませんでした。通信・認証を確認し、接続確認を再試行してください')
    return re.sub(r'\x1b\[[0-9;]*m','',result.stdout+'\n'+result.stderr)


def inventory(cli):
    raw=capture(cli,['sessions'])
    entries=[]
    for line in raw.splitlines():
        match=re.fullmatch(r'\[([A-Za-z0-9_-]{1,60})\]\s+([^|\s]+)\s*\|\s*Hardware:\s*([^|]+)(?:\|.*)?',line.strip())
        if match:entries.append({'name':match[1],'identity':match[2],'hardware':match[3].strip()})
    if not entries and 'No active sessions found on server.' not in raw:
        raise RuntimeError('ランタイム一覧の応答形式を確認できません。ランタイムが無いとは判断しません')
    if len({e['name'] for e in entries})!=len(entries):raise RuntimeError('ランタイム名が重複しています')
    return entries


def probe(cli,session,job,nonce=''):
    from . import environments as runtime_env
    expected={engine:{'signature':runtime_env.signature(engine),'python':runtime_env.python_path(engine).as_posix()}
              for engine in runtime_env.ENGINES}
    path=Path(__file__).resolve().parent.parent/'irodori_session_probe.py'
    from irodori_colab_cli import remote_path
    raw=capture(cli,['exec','-s',session,'--timeout','30','--env','YOMIBUTA_PROBE_JOB='+job,
        '--env','YOMIBUTA_PROBE_NONCE='+nonce,'--env','YOMIBUTA_EXPECT_RUNTIME='+json.dumps(expected),'-f',remote_path(path)],45)
    lines=[line.partition('YOMIBUTA_CONNECTION ')[2] for line in raw.splitlines() if line.startswith('YOMIBUTA_CONNECTION ')]
    if len(lines)!=1:raise RuntimeError('Colabから接続確認の応答を受け取れませんでした')
    value=json.loads(lines[0])
    if not isinstance(value,dict) or not isinstance(value.get('workers'),list) or type(value.get('prepared')) is not bool:raise ValueError('接続確認の応答が不正です')
    return value
