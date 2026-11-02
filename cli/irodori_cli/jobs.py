"""Immutable takes, verified caches, inter-utterance control and streaming assembly."""
from __future__ import annotations

import contextlib
import json
import os
import socket
import time
import uuid
import wave
from pathlib import Path

from .core import atomic_json, digest, file_hash, read_json


def wav_info(path):
    with wave.open(str(path), 'rb') as wav:
        if wav.getcomptype() != 'NONE' or wav.getsampwidth() != 2 or wav.getnchannels() != 1 or wav.getnframes() <= 0:
            raise ValueError('空でないモノラルPCM16 WAVが必要です')
        frames, rate = wav.getnframes(), wav.getframerate()
        actual = 0
        while chunk := wav.readframes(65536):
            actual += len(chunk)
        if rate <= 0 or actual != frames*2:
            raise ValueError('WAVのフレームが不正です')
        return {'frames':frames, 'sample_rate':rate, 'seconds':frames/rate}


def inside(job, relative):
    path = (Path(job)/relative).resolve()
    if not path.is_relative_to(Path(job).resolve()):
        raise ValueError('ジョブ外の音声パスは使えません')
    return path


@contextlib.contextmanager
def execution_guard(job):
    """OS-owned lock: process death releases it. Never unlink its stable inode."""
    with (job/'.execution.lock').open('a+b') as guard:
        try:
            if os.name=='nt':
                import msvcrt
                if guard.seek(0,2)==0:
                    guard.write(b'\0');guard.flush()
                guard.seek(0)
                msvcrt.locking(guard.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('この処理は実行中です。完了または停止後に再試行してください') from None
        yield


def legacy_owner_dead(record):
    """Old workers have no OS lock. Only reclaim a known dead local owner."""
    pid=record.get('pid')
    if record.get('host')!=socket.gethostname() or type(pid) is not int or pid<=0:
        return False
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x100000,False,pid)  # SYNCHRONIZE; never send signals.
        if not handle:return ctypes.get_last_error()==87  # Invalid/nonexistent PID.
        try:return kernel.WaitForSingleObject(handle,0)==0
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0)
    except ProcessLookupError:return True
    except PermissionError:return False
    return False


@contextlib.contextmanager
def job_lock(job):
    job = Path(job)
    job.mkdir(parents=True, exist_ok=True)
    lock = job/'.lock'
    token = uuid.uuid4().hex
    with execution_guard(job):
        if lock.exists():
            previous=read_json(lock)
            if previous.get('lock_version')!=2 and not legacy_owner_dead(previous):
                raise RuntimeError('以前の処理の終了を確認できません。実行状態を確認してから再試行してください')
            # Version 2 always holds execution_guard, so this is a crash remnant.
            lock.unlink()
        with lock.open('x', encoding='utf-8') as stream:
            json.dump({'pid':os.getpid(), 'host':socket.gethostname(), 'token':token,'lock_version':2}, stream)
        try:
            yield
        finally:
            if lock.exists() and read_json(lock).get('token') == token:
                lock.unlink()


def load_manifest(job):
    path = Path(job)/'job.json'
    return read_json(path) if path.exists() else {'version':1, 'status':'new', 'takes':[], 'combined':None,
        'human_listening_review':'required; code does not validate voice identity, acting or emotional quality'}


def find_take(job, manifest, request):
    for take in reversed(manifest['takes']):
        if take['id'] != request['id'] or take['fingerprint'] != request['fingerprint']:
            continue
        path = inside(job, take['file'])
        try:
            if path.is_file() and file_hash(path) == take['sha256']:
                wav_info(path)
                return take
        except (ValueError, wave.Error, EOFError):
            pass
    return None


def control(job, action):
    job = Path(job)
    if not (job/'job.json').is_file():
        raise ValueError('既存ジョブを指定してください')
    if action == 'resume':
        for name in ('.pause','.stop'):
            (job/name).unlink(missing_ok=True)
    elif action in ('pause','stop'):
        atomic_json(job/f'.{action}', {'requested_at':time.time()})
    else:
        raise ValueError('pause / stop / resume を指定してください')


def assembly(job, plan, pause, manifest):
    takes = [find_take(job, manifest, row) for row in plan]
    if any(take is None for take in takes):
        manifest['combined'] = None
        return None
    rates = {take['sample_rate'] for take in takes}
    if len(rates) != 1:
        raise ValueError('結合対象のサンプルレートが一致しません')
    rate = rates.pop()
    relative = f'combined/conversation_{uuid.uuid4().hex[:12]}.wav'
    destination = inside(job, relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stream individual files; do not hold a novel's combined waveform in memory.
    with wave.open(str(destination), 'wb') as output:
        output.setparams((1,2,rate,0,'NONE','not compressed'))
        for index, take in enumerate(takes):
            if index:
                gap = plan[index-1].get('pause_after_ms')
                output.writeframesraw(b'\x00\x00'*int(rate*(pause if gap is None else gap/1000)))
            with wave.open(str(inside(job, take['file'])), 'rb') as stream:
                while chunk := stream.readframes(65536):
                    output.writeframesraw(chunk)
    info = wav_info(destination)
    manifest['combined'] = {'file':relative, **info, 'sha256':file_hash(destination),
                            'take_files':[take['file'] for take in takes], 'pause':pause}
    return manifest['combined']


def generate(job, plan, pause, synthesize, *, selected=None, regenerate=False, provenance=None):
    """synthesize(request, destination) must create real PCM16 audio or raise."""
    job = Path(job)
    selected = set(selected or [r['id'] for r in plan])
    if not selected <= {r['id'] for r in plan}:
        raise ValueError('選択した発話IDが存在しません')
    with job_lock(job):
        manifest = load_manifest(job)
        manifest.update(status='running', combined=None, errors=[], plan_sha256=digest(plan),
                        provenance=provenance or {})
        atomic_json(job/'plan.json', plan)
        atomic_json(job/'job.json', manifest)
        pending=[r for r in plan if r['id'] in selected and (regenerate or not find_take(job,manifest,r))]
        processed=0
        for row in plan:
            if (job/'.stop').exists() or (job/'.pause').exists():
                manifest['status'] = 'stopped' if (job/'.stop').exists() else 'paused'
                atomic_json(job/'job.json', manifest)
                return manifest
            if row['id'] not in selected or (not regenerate and find_take(job, manifest, row)):
                continue
            processed+=1
            print(f'PROGRESS 音声生成: {processed}/{len(pending)}件目を処理中',flush=True)
            relative = f"audio/{row['id']}_{row['fingerprint'][:12]}_{uuid.uuid4().hex[:8]}.wav"
            destination = inside(job, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix('.partial.wav')
            try:
                started = time.perf_counter()
                synthesize(row['request'], temporary)
                info = wav_info(temporary)
                os.replace(temporary, destination)
                take = {'id':row['id'], 'fingerprint':row['fingerprint'], 'file':relative,
                        **info, 'sha256':file_hash(destination), 'seed':row['request']['seed'],
                        'generation_seconds':time.perf_counter()-started}
                manifest['takes'].append(take)
                print('WAV_READY', relative, flush=True)
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                manifest['errors'].append({'id':row['id'], 'error':str(exc)})
                print('WAV_FAILED', row['id'], str(exc), flush=True)
            atomic_json(job/'job.json', manifest)
        try:
            print('PROGRESS 音声生成: 結合・整合性確認中',flush=True)
            manifest['duration_warnings']=[{'id':row['id'],'seconds':take['seconds'],'reason':'30秒上限付近のため、末尾の欠落を試聴してください。必要ならさらに分割して再生成してください。'}
                for row in plan if (take:=find_take(job,manifest,row)) and take['seconds']>=29]
            combined = assembly(job, plan, pause, manifest)
            manifest['status'] = 'failed' if manifest['errors'] else ('complete' if combined else 'partial')
        except Exception as exc:
            manifest['errors'].append({'id':'assembly', 'error':str(exc)})
            manifest['status'] = 'failed'
        atomic_json(job/'job.json', manifest)
        return manifest
