"""Human-readable CLI progress. No ML imports and no inference retries."""
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
import time

from .colab_usage import parse_usage
from .connection import capture


def read_usage():
    from irodori_local import colab_command
    return {**parse_usage(capture(colab_command(), ['usage'], 15)),
            'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': 'account'}


def read_runtime(session):
    from irodori_local import colab_command
    raw = capture(colab_command(), ['status', '-s', session], 15)
    pattern = (r'^\[' + re.escape(session) + r'\]\s+(\S+)\s*\|\s*Hardware:\s*([^|]+)'
               r'\|\s*Shape:\s*([^|]+)\|\s*Variant:\s*([^|]+)\|\s*Status:\s*(\S+)')
    for line in raw.splitlines():
        match = re.match(pattern, line.strip())
        if match:
            return dict(zip(('identity', 'hardware', 'shape', 'variant', 'status'),
                            (s.strip() for s in match.groups())))
    raise RuntimeError('指定セッションのGPU情報を確認できませんでした')


def runtime_stopped(session):
    from irodori_local import colab_command
    raw = capture(colab_command(), ['status', '-s', session], 15)
    return f"Session '{session}' not found." in raw


def command_text(command):
    import os
    import shlex
    if os.name == 'nt':
        return '& ' + ' '.join("'" + item.replace("'", "''") + "'" for item in command)
    return shlex.join(command)


def duration(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'


class Console:
    def __init__(self, events=None, clock=time.monotonic, stream=None):
        self.clock = clock
        self.started = clock()
        self.stream = stream if stream is not None else sys.stderr
        self.events = events
        self.previous = None
        self.baseline = None
        self.last_display = self.started

    def say(self, message, **data):
        elapsed = self.clock() - self.started
        self.last_display = self.clock()
        print(f'[{duration(elapsed)}] {message}', file=self.stream, flush=True)
        if self.events:
            with self.events.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'elapsed_seconds': round(elapsed, 3),
                    'message': message, **data}, ensure_ascii=False) + '\n')

    def progress(self, line):
        line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
        if line.startswith('COLAB_STATE_UNCONFIRMED'):
            self.say('遠隔の結果は未確認です。自動で生成を再送しません')
            return
        if not line.startswith('PROGRESS '):
            return
        message = line[9:]
        # File polling is a transport detail; retain it only in the raw log.
        if message.startswith('Colab:'):
            operation = message.partition(':')[2].strip()
            message = {'new': 'ランタイムを作成中', 'upload': '入力・コードを転送中',
                       'exec': '遠隔工程を起動中'}.get(operation)
            if message is None:
                if self.previous and self.clock() - self.last_display >= 30:
                    self.say(self.previous + '（待機継続中）')
                return
        if message == self.previous:
            if self.clock() - self.last_display >= 30:
                self.say(message + '（待機継続中）')
            return
        self.previous = message
        match = re.search(r'音声生成: (\d+)/(\d+)件目', message)
        extra = {}
        if match:
            current, total = map(int, match.groups())
            completed = max(0, current - 1)
            extra = {'current': current, 'total': total, 'completed': completed}
            if completed and self.baseline is None:
                # The first completed item includes model loading; exclude it
                # from steady-state ETA rather than guessing its cost.
                self.baseline = self.clock(), completed
            if self.baseline and completed > self.baseline[1]:
                elapsed = self.clock() - self.baseline[0]
                eta = elapsed / (completed - self.baseline[1]) * (total - completed)
                extra['generation_eta_seconds'] = round(eta, 1)
                message += f' / 残り生成 約{duration(eta)}（実測目安・回収時間を除く）'
            else:
                message += ' / 残り生成: 初回計測中'
        if '結合・整合性' in message:
            self.baseline = None
        self.say(message, **extra)


def run_logged(command, log, console):
    """Stream useful progress, keeping complete UTF-8 diagnostics on disk."""
    import os
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONUNBUFFERED': '1'}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace', env=env)
    try:
        for line in process.stdout:
            log.write(line)
            log.flush()
            console.progress(line)
        code = process.wait()
    except BaseException:
        # Stop local observation only. A launched remote worker may continue.
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    finally:
        process.stdout.close()
    return subprocess.CompletedProcess(command, code)
