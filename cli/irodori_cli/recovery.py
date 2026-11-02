"""Fail-closed host driver discovery before clearing uncertain runs."""
import json
import os
import subprocess


def active_host_drivers():
    if os.name == 'nt':
        script = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                  "Where-Object { $_.CommandLine -match 'irodori_colab_cli[.]py' } | "
                  "Select-Object -ExpandProperty CommandLine | ConvertTo-Json -Compress")
        result = subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],
                                capture_output=True,text=True,timeout=15,check=True)
        data=json.loads(result.stdout) if result.stdout.strip() else []
        commands=[data] if isinstance(data,str) else data
        # Include orphaned Linux CLI calls, not just their former Windows parent.
        linux=subprocess.run(['wsl','-e','pgrep','-af','/bin/colab (exec|upload|download|log)'],
                             capture_output=True,text=True,timeout=15)
        if linux.returncode not in (0,1):raise ValueError('WSL側の接続状態を確認できません')
        commands+=linux.stdout.splitlines()
    else:
        result=subprocess.run(['ps','-eo','args='],capture_output=True,text=True,timeout=15,check=True)
        commands=[line for line in result.stdout.splitlines() if 'irodori_colab_cli.py' in line]
    if not isinstance(commands,list) or any(not isinstance(c,str) for c in commands):
        raise ValueError('ホスト側の実行状況を確認できません')
    return commands
