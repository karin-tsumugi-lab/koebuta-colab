"""Run local analysis in WSL, forwarding Windows credentials in environment only."""
import os
import subprocess
import sys
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parent


def wsl_path(path):
    path=Path(path).resolve()
    return '/mnt/'+path.drive[0].lower()+'/'+path.as_posix()[3:] if os.name=='nt' else str(path)


def local_command(arguments):
    env=os.environ.copy()
    if os.name!='nt':
        return [sys.executable,*arguments],env
    forwarding=env.get('WSLENV','').split(':') if env.get('WSLENV') else []
    for name in ('GEMINI_API_KEY','GOOGLE_API_KEY'):
        if env.get(name) and not any(p.split('/')[0]==name for p in forwarding):
            forwarding.append(name+'/u')
    env['WSLENV']=':'.join(forwarding)
    return ['wsl','--cd',wsl_path(ROOT),'-e','python3',*arguments],env


def colab_command():
    """Resolve an executable, never a shell string or an HTTP-supplied command."""
    override=os.environ.get('YOMIBUTA_COLAB_BIN')
    if os.name!='nt':
        binary=override or shutil.which('colab')
        if not binary:
            candidate=Path.home()/'.local/bin/colab'
            if candidate.is_file():binary=str(candidate)
        if not binary:raise RuntimeError('Colab CLIがありません。YOMIBUTA_COLAB_BINで実行ファイルを指定してください')
        return [binary]
    if not override:
        # Discovery needs neither the mounted project directory nor Gemini credentials.
        command=['wsl','-e','python3','-c',
            "from pathlib import Path; import shutil; p=shutil.which('colab'); q=Path.home()/'.local/bin/colab'; print(p or (str(q) if q.is_file() else ''))"]
        try:result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=30)
        except subprocess.TimeoutExpired:
            raise RuntimeError('WSLの起動・Colab CLIの確認が時間切れです。接続確認をやり直すか、YOMIBUTA_COLAB_BINで実行ファイルを指定してください') from None
        override=result.stdout.strip() if result.returncode==0 else ''
    if not override or '\n' in override or '\r' in override:
        raise RuntimeError('WSLのColab CLIが見つかりません。YOMIBUTA_COLAB_BINでWSL内の実行ファイルを指定してください')
    os.environ['YOMIBUTA_COLAB_BIN']=override  # Reuse successful discovery in this server and its children.
    return ['wsl','-e',override]


if __name__=='__main__':
    command,environment=local_command(sys.argv[1:])
    raise SystemExit(subprocess.run(command,env=environment).returncode)
