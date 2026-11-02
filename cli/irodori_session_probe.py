"""Read runtime identity, environment readiness and worker receipts without mutation."""
import json
import os
import re
import subprocess
from pathlib import Path

job=os.environ['YOMIBUTA_PROBE_JOB'];nonce=os.environ.get('YOMIBUTA_PROBE_NONCE','')
if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}',job) or (nonce and not re.fullmatch('[a-f0-9]{32}',nonce)):raise ValueError('Invalid probe identity')
def read(path):return json.loads(path.read_text()) if path.is_file() else None
marker=read(Path('/content/yomibuta_environment.json'))
expected=json.loads(os.environ.get('YOMIBUTA_EXPECT_RUNTIME','{}'))
def ready(engine):
    spec=expected.get(engine,{})
    record=(marker or {}).get('capabilities',{}).get('llm' if engine in ('gemma','qwen') else engine,{})
    return bool(spec and record.get('signature')==spec.get('signature') and Path(spec['python']).is_file())
workers=[]
for path in Path('/content/irodori_cli_runs').glob('*/.active.json'):
    data=read(path)
    if type(data.get('pid')) is not int or data['pid']<=0:raise ValueError('Invalid worker PID')
    try:os.kill(data['pid'],0)
    except ProcessLookupError:continue
    workers.append({'job':path.parent.name,'nonce':data.get('nonce')})
receipt=read(Path('/content/irodori_cli_runs')/job/'receipts'/f'{nonce}.json') if nonce else None
terminal=[]
for receipt_file in Path('/content/irodori_cli_runs').glob('*/receipts/*.json'):
    saved=read(receipt_file)
    if saved.get('action') in ('prepare','analyze','emotions','synthesize','run') and type(saved.get('exit_code')) is int:
        terminal.append({'job':saved.get('job_id'),'nonce':saved.get('nonce')})
gpu=subprocess.run(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10)
gpu_processes=[line.strip() for line in gpu.stdout.splitlines() if line.strip()] if gpu.returncode==0 else None

def idle_tts_pid():
    """Recognize only our authenticated, idle service; foreign GPU owners still block shutdown."""
    import fcntl
    import socket
    directory=Path(os.environ.get('YOMIBUTA_RESIDENT_ROOT','/content/yomibuta_tts_service'))
    try:
        with (directory/'lifecycle.lock').open('r') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            service=read(directory/'service.json')
            pid=service['pid']
            stat=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            command=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            if (stat[0]=='Z' or stat[19]!=service['start'] or b'irodori_cli.resident' not in command
                    or service['token'].encode() not in command):return None
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.settimeout(2);client.connect(str(directory/'service.sock'))
                client.sendall((json.dumps({'op':'ping','token':service['token']})+'\n').encode())
                with client.makefile('r') as stream:reply=json.loads(stream.readline(4096))
                return pid if reply=={'ok':True,'pid':pid} else None
    except (OSError,ValueError,KeyError,TypeError,IndexError):return None

resident_pid=idle_tts_pid()
details=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10)
gpu_details=None
if details.returncode==0 and len(details.stdout.strip().splitlines())==1:
    gpu_name,gpu_total=details.stdout.strip().rsplit(',',1)
    gpu_details={'name':gpu_name.strip(),'total_mib':int(gpu_total.strip())}
print('YOMIBUTA_CONNECTION '+json.dumps({'environment_id':marker.get('id') if marker else None,
    'gpu_details':gpu_details,'prepared':any(ready(e) for e in ('gemma','qwen','laya','tts')),
    **{e+'_ready':ready(e) for e in ('gemma','qwen','laya','tts')},'workers':workers,'receipt':receipt,
    'terminal_receipts':terminal,'gpu_processes':gpu_processes,'idle_tts_pid':resident_pid,
    'control_flags':[flag for flag in ('.pause','.stop') if (Path('/content/irodori_cli_runs')/job/'job'/flag).exists()]}),flush=True)
