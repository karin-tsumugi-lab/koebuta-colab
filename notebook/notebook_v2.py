"""Koebuta v2 prototype: CPU-testable storage and candidate transactions.

Scenario parsing and generation plans are supplied by the existing P0 adapter.
All writes belong to a separate workspace, never the source project.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import threading
import uuid
import wave
import zipfile


def reference_choices(project, reading):
    """Choose normal 20–100-character speech; no suitable line means no-ref."""
    groups = {}
    for segment in project['segments']:
        if segment.get('segment_type') == 'separator':
            continue
        key = 'shared' if project.get('reading') == 'shared' else segment['role']
        groups.setdefault(key, []).append(segment)
    result = {}
    for key, segments in groups.items():
        suitable = []
        for segment in segments:
            text = segment.get('tts_text') or reading(segment['text'], segment.get('text_format', 'none'))[0]
            if (20 <= len(text.strip()) <= 100 and segment.get('emotion', 'neutral') == 'neutral'
                    and not any(c in text for c in '!！?？…') and len(set(text.strip())) >= 8):
                suitable.append((abs(len(text) - 60), segment['id'], text))
        result[key] = min(suitable)[1:] if len(segments) >= 2 and suitable else None
    return result


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def unpack_project(archive, destination, max_bytes=512 * 1024 * 1024,
                   max_entries=4096):
    """Validate the complete central directory before extracting any member."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('展開先には新しいフォルダを指定してください')
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > max_entries or sum(x.file_size for x in entries) > max_bytes:
            raise ValueError('ZIPの容量または項目数が上限を超えています')
        seen = set()
        for entry in entries:
            name = entry.filename.rstrip('/')
            parts = PurePosixPath(name).parts
            mode = entry.external_attr >> 16
            if (not name or '\\' in name or ':' in name or '\x00' in name
                    or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))
                    or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                    or entry.flag_bits & 1 or name.casefold() in seen
                    or (entry.file_size > 1024 * 1024 and entry.file_size > max(1, entry.compress_size) * 200)):
                raise ValueError('安全でないZIP項目です: ' + name)
            seen.add(name.casefold())
        destination.mkdir(parents=True)
        for entry in entries:
            target = destination.joinpath(*PurePosixPath(entry.filename).parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                atomic_bytes(target, source.read(entry))
    return find_project(destination)


def find_project(folder):
    root = Path(folder).resolve(strict=True)
    candidates = [root / 'scenario.json']
    candidates += [p / 'scenario.json' for p in root.iterdir() if p.is_dir() and not p.is_symlink()]
    found = [p for p in candidates if p.is_file() and not p.is_symlink()]
    if len(found) != 1:
        raise ValueError('scenario.jsonを作品直下に一つ配置してください')
    return found[0].parent


def load_project(folder, normalize, validate, settings, resolve_wavs):
    root = find_project(folder)
    path = root / 'scenario.json'
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('シナリオJSONが16MiBを超えています')
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('JSONのルートはオブジェクトが必要です')
    project = normalize(data)
    validate(project)
    config = settings(project)
    voices, warnings = resolve_wavs(project, root)
    return project, config, voices, warnings, hashlib.sha256(raw).hexdigest()


def valid_wav(path):
    try:
        with wave.open(str(path), 'rb') as audio:
            return audio.getnframes() > 0 and len(audio.readframes(audio.getnframes())) == audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
    except (OSError, EOFError, wave.Error):
        return False


class CandidateStore:
    """Latest candidate per unit; accepted immutable blobs survive replacement.

    The synthesizer writes a WAV to its supplied path. A group is published only
    after every synthesis succeeds and every WAV is validated.
    """
    def __init__(self, workspace, identity):
        self.root = Path(workspace)
        self.root.mkdir(parents=True, exist_ok=True)
        self.identity = dict(identity)
        self.accepted, self.candidates, self.cache, self.references = {}, {}, {}, {}
        self.lock = threading.RLock()

    def key(self, unit):
        payload = {k: v for k, v in unit.items()
                   if k not in ('unit_id', 'segment_id', 'pause_after_ms', 'ref_wav')}
        payload['reference_sha256'] = hashlib.sha256(Path(unit['ref_wav']).read_bytes()).hexdigest() if unit.get('ref_wav') else None
        payload['identity'] = self.identity
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

    def regenerate(self, units, synthesize, force=True, progress=None):
        with self.lock:
            units = list(units)
            staged = {}
            for index, unit in enumerate(units):
                if progress:
                    progress(index / max(1, len(units)), desc=f"音声準備 {index + 1}/{len(units)}: {unit['unit_id']}")
                key = self.key(unit)
                record = self.cache.get(key)
                if force or not record or not self._valid(record):
                    path = self.root / (uuid.uuid4().hex + '.wav')
                    try:
                        synthesize(unit, path)
                        if not valid_wav(path):
                            raise ValueError('生成WAVが破損しています')
                        record = {'file': path.name, 'key': key,
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'unit': {k: v for k, v in unit.items() if k != 'ref_wav'},
                                  'identity': self.identity}
                    except Exception:
                        path.unlink(missing_ok=True)
                        raise
                staged[unit['unit_id']] = record
                if progress:
                    progress((index + 1) / len(units), desc=f"完了 {index + 1}/{len(units)}: {unit['unit_id']}")
            updated = {**self.candidates, **staged}
            self._save(self.accepted, updated)
            self.candidates = updated
            self.cache.update({r['key']: r for r in staged.values()})
            return staged

    def _valid(self, record):
        name = record.get('file', '')
        if not name or Path(name).name != name:
            return False
        path = self.root / name
        return valid_wav(path) and hashlib.sha256(path.read_bytes()).hexdigest() == record.get('sha256')

    def adopt(self, unit_ids):
        with self.lock:
            ids = list(unit_ids)
            if not ids or any(i not in self.candidates or not self._valid(self.candidates[i]) for i in ids):
                raise ValueError('全片の有効な候補が必要です')
            accepted = {**self.accepted, **{i: self.candidates[i] for i in ids}}
            candidates = {i: r for i, r in self.candidates.items() if i not in ids}
            self._save(accepted, candidates)
            self.accepted, self.candidates = accepted, candidates

    def discard(self, unit_ids):
        with self.lock:
            candidates = {i: r for i, r in self.candidates.items() if i not in unit_ids}
            self._save(self.accepted, candidates)
            self.candidates = candidates

    def _save(self, accepted, candidates):
        cache = {**self.cache, **{r['key']: r for group in (accepted, candidates) for r in group.values()}}
        atomic_bytes(self.root / 'state.json', json.dumps({
            'version': 2, 'identity': self.identity, 'accepted': accepted,
            'candidates': candidates, 'cache': cache, 'references': self.references}, ensure_ascii=False, allow_nan=False).encode())

    def restore(self):
        with self.lock:
            state = json.loads((self.root / 'state.json').read_bytes())
            if state.get('version') != 2 or state.get('identity') != self.identity:
                raise ValueError('保存状態のモデル識別情報が一致しません')
            groups = [state['accepted'], state['candidates']]
            if any(not self._valid(r) for group in groups for r in group.values()):
                raise ValueError('保存状態の音声が欠落または破損しています')
            self.accepted, self.candidates = groups
            self.references = {k: r for k, r in state.get('references', {}).items() if self._valid(r)}
            self.cache = {k: r for k, r in state.get('cache', {}).items() if self._valid(r)}
            self.cache.update({r['key']: r for group in groups for r in group.values()})

    def persist(self, destination):
        """Copy audio first, publish the manifest last; local results stay intact."""
        try:
            destination = Path(destination)
            if destination.resolve() == self.root.resolve():
                return None
            for group in (self.accepted, self.candidates, self.cache, self.references):
                for record in group.values():
                    if not self._valid(record):
                        raise ValueError('保存対象WAVが破損しています')
                    atomic_bytes(destination / record['file'], (self.root / record['file']).read_bytes())
            atomic_bytes(destination / 'state.json', (self.root / 'state.json').read_bytes())
            return None
        except Exception as exc:
            return 'Drive保存に失敗しました。一時領域の結果は保持しています: ' + str(exc)
