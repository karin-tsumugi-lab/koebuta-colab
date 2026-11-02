"""Dependency-free project validation and request planning. No model imports."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import uuid
import time
from pathlib import Path

EMOTIONS = dict(zip(
    ['neutral','joy','anger','sad','kind','tease','anxiety','tension','surprise','tired','whisper','giggle','fear','sleepy','resolve'],
    ['','😆','😠','😭','🫶','😏','🥺','😰','😲','😮‍💨','👂','🤭','😱','😪','💥']))
ATTRS = {'age':['young_adult','adult','elderly'], 'gender':['feminine','masculine'],
         'pitch':['high','mid','low'], 'timbre':['clear','warm','soft','husky','bright','resonant'],
         'habitual_style':['gentle','measured','brisk','formal','casual','calm']}
STYLES = dict(zip(ATTRS['habitual_style'], ['穏やかな話し方。','落ち着いたテンポで話す。','きびきびした話し方。','端正で丁寧な話し方。','親しみやすい話し方。','静かで落ち着いた話し方。']))
from .text_conversion import metadata, options as text_options, convert_project

MODEL = 'Aratako/Irodori-TTS-v4.1-Small'
TTS_MODELS = (MODEL, 'Aratako/Irodori-TTS-v4-Large')


def is_narrator(role):
    return role.get('kind', 'narrator' if role.get('name') == '地の文' else 'character') == 'narrator'


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def text(value, label, limit, *, optional=False):
    if value is None and optional:
        return ''
    if not isinstance(value, str) or (not optional and not value.strip()) or len(value) > limit:
        raise ValueError(f'{label}: 空でない文字列、{limit}文字以内にしてください')
    return value


def identifier(value, label, length=40):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,' + str(length) + '}', value) or value in {'__proto__','constructor','prototype'}:
        raise ValueError(f'{label}: 不正なID')
    return value


def read_json(path):
    if Path(path).stat().st_size > 2*1024*1024:
        raise ValueError('JSONは2MB以内にしてください')
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'不正な数値: {value}')))


def model_json(value):
    """A structured model reply must not hide repeated keys or nonfinite numbers."""
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:raise ValueError('モデル応答のJSONキーが重複しています')
            result[key] = item
        return result
    return json.loads(value, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('モデル応答の数値が不正です')))


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                # Windows scanners/readers may briefly hold an existing JSON file.
                # Keep the old file intact and retry only sharing/access conflicts.
                if getattr(exc, 'winerror', None) not in (5, 32) or attempt == 5:
                    raise
                time.sleep(.02 * 2**attempt)
    finally:
        temporary.unlink(missing_ok=True)


def source_rows(source):
    text(source, 'source', 100000)
    rows = []
    for line in filter(None, (line.strip() for line in source.splitlines())):
        match = re.match(r'^([^「：:]{1,25}?)\s*(?:[：:]\s*)?「([\s\S]*)」\s*$', line) or re.match(r'^([^：:]{1,25})[：:]\s*(.+)$', line)
        # A pixiv ruby opener contains a colon, but is not a speaker label.
        if match and '[[rb' in match[1]:match=None
        rows.append({'id':f't{len(rows)+1:02d}', 'speaker_hint':match[1].strip() if match else '地の文', 'text':match[2] if match else line})
    if not 1 <= len(rows) <= 2000:
        raise ValueError('発話数は1〜2,000件にしてください')
    return rows


def import_analysis(raw, source=''):
    if not isinstance(raw, dict) or type(raw.get('schema_version')) is not int or raw.get('schema_version') != 1 or not isinstance(raw.get('speakers'), dict):
        raise ValueError('schema_version=1 / speakers の話者分析JSONが必要です')
    if 'textOptions' in raw:text_options(raw['textOptions'])
    profiles = raw['speakers']
    if not 1 <= len(profiles) <= 100:
        raise ValueError('話者数は1〜100人です')
    roles = []
    for key, profile in profiles.items():
        identifier(key, 'speaker_id')
        if not isinstance(profile, dict):
            raise ValueError('話者プロフィールはオブジェクトにしてください')
        attrs = {}
        for name, allowed in ATTRS.items():
            if name in profile:
                if profile[name] not in allowed:
                    raise ValueError(f'{key}.{name}: 不正な属性')
                attrs[name] = profile[name]
        kind=profile.get('kind', 'narrator' if profile.get('name')=='地の文' else 'character')
        if kind not in ('narrator','character'):raise ValueError('kindはnarratorまたはcharacterです')
        roles.append({'id':key, 'kind':kind, 'name':text(profile.get('name'), 'name', 50),
            'bio':text(profile.get('bio'), 'bio', 2000, optional=True),
            'caption':text(profile.get('voice_caption'), 'voice_caption', 1000, optional=True),
            'acting':text(profile.get('acting_description', STYLES.get(attrs.get('habitual_style'), '')), 'acting_description', 1000, optional=True),
            'voice':'voice_a', 'attributes':attrs})
    segments = raw.get('segments')
    if not isinstance(segments, list) or not 1 <= len(segments) <= 2000:
        raise ValueError('segmentsは1〜2,000発話の配列にしてください')
    seen, normalized = set(), []
    for row in segments:
        if not isinstance(row, dict):
            raise ValueError('発話はオブジェクトにしてください')
        key = identifier(row.get('id'), 'segment.id', 64)
        if key in seen or not isinstance(row.get('speaker_id'), str) or row['speaker_id'] not in profiles:
            raise ValueError(f'{key}: 重複IDまたは未登録話者')
        seen.add(key)
        if 'pause_after_ms' in row and (type(row['pause_after_ms']) is not int or not 0 <= row['pause_after_ms'] <= 10000):
            raise ValueError(f'{key}: pause_after_msは0〜10000の整数です')
        if 'tts_text' in row:
            text(row['tts_text'], 'tts_text', 5000)
        if 'emotion_locked' in row and type(row['emotion_locked']) is not bool:raise ValueError(f'{key}: emotion_lockedはbooleanです')
        emotion=row.get('emotion','neutral')
        if emotion not in EMOTIONS:raise ValueError(f'{key}: 未対応の感情IDです')
        normalized.append({'id':key, 'role':row['speaker_id'], 'text':text(row['text'], 'text', 5000) if 'text' in row else None,
                           'emotion':emotion, 'reviewed':False, 'acting':text(row.get('acting_description'), 'segment.acting_description',1000,optional=True),
                           **{k:row[k] for k in ('tts_text','pause_after_ms','emotion_locked') if k in row}, **metadata(row)})
    count = sum(row['text'] is not None for row in normalized)
    names = {r['id']:r['name'] for r in roles}
    if count not in (0, len(normalized)):
        raise ValueError('本文は全発話に含めるか、全発話で省略してください')
    if count:
        rows = [{'id':s['id'], 'speaker_hint':names[s['role']], 'text':s['text']} for s in normalized]
        source = '\n\n'.join(r['text'] if r['speaker_hint']=='地の文' else f"{r['speaker_hint']}「{r['text']}」" for r in rows)
    else:
        rows = source_rows(source)
        if len(rows) != len(normalized) or {r['id'] for r in rows} != seen or not raw.get('source_sha256'):
            raise ValueError('本文なし分析には原稿と一致する全発話ID・件数・source_sha256が必要です')
        assigned = {s['id']:s for s in normalized}
        normalized = [{**assigned[r['id']], 'text':r['text']} for r in rows]
    if 'source_sha256' in raw and (not isinstance(raw['source_sha256'], str) or digest(rows) != raw['source_sha256'].lower()):
        raise ValueError('原稿の照合ハッシュが一致しません')
    if 'source' in raw:
        if not count and raw['source']!=source:raise ValueError('本文なし分析のsourceが照合した原稿と一致しません')
        source=text(raw['source'],'source',100000)
    text(source, 'source', 100000)
    return roles, normalized, source


def normalize_project(raw):
    if not isinstance(raw, dict) or type(raw.get('version')) is not int or raw.get('version') != 1:
        raise ValueError('version=1のWeb UIプロジェクトJSONが必要です')
    source = text(raw.get('source'), 'source', 100000)
    roles = raw.get('roles')
    segments = raw.get('segments')
    if segments == [] and raw.get('analyzed') is False:
        provisional = new_project(source)
        roles, segments = provisional['roles'], provisional['segments']
    if not isinstance(roles, list) or not isinstance(segments, list):
        raise ValueError('roles / segments が必要です')
    profiles = {}
    for role in roles:
        if not isinstance(role, dict) or role.get('id') in profiles:
            raise ValueError('話者IDが重複しています')
        attrs = {k:v for k,v in role.get('attributes', {}).items() if k in ATTRS}
        profiles[role.get('id')] = {**attrs, 'kind':role.get('kind','narrator' if role.get('name')=='地の文' else 'character'), 'name':role.get('name'), 'bio':role.get('bio'), 'voice_caption':role.get('caption'), 'acting_description':role.get('acting')}
    clean_roles, clean_segments, _ = import_analysis({'schema_version':1, 'speakers':profiles,
        'segments':[{'id':s.get('id'), 'speaker_id':s.get('role'), 'text':s.get('text'), **{k:s[k] for k in ('tts_text','pause_after_ms') if k in s}, **metadata(s)} for s in segments]})
    for old, clean in zip(roles, clean_roles):
        clean['voice'] = identifier(old.get('voice', 'voice_a'), 'voice profile')
    for old, clean in zip(segments, clean_segments):
        if old.get('emotion', 'neutral') not in EMOTIONS:
            raise ValueError('未対応の感情IDです')
        clean.update(emotion=old.get('emotion', 'neutral'), reviewed=old.get('reviewed') is True,
                     acting=text(old.get('acting'), 'segment.acting', 1000, optional=True))
        if 'emotion_locked' in old:
            if type(old['emotion_locked']) is not bool:raise ValueError('emotion_lockedはbooleanです')
            clean['emotion_locked']=old['emotion_locked']
    clean = {'version':1, 'title':text(raw.get('title', '新しい朗読'), 'title', 100), 'source':source,
             'roles':clean_roles, 'segments':clean_segments, 'analyzed':raw.get('analyzed', True) is True,
             'reading':raw.get('reading', 'shared'), 'voiceMode':raw.get('voiceMode', 'design'),
             'baseCaption':text(raw.get('baseCaption', '自然で聞き取りやすい日本語の朗読。'), 'baseCaption', 2000, optional=True),
             'reference':text(raw.get('reference', ''), 'reference', 2000, optional=True), 'referenceKind':'custom' if raw.get('reference') else 'empty',
             'seed':raw.get('seed', 314), 'steps':raw.get('steps', 40), 'pause':raw.get('pause', .28),
             'ttsModel':raw.get('ttsModel', MODEL),
             'stage':min(3, max(0, raw.get('stage', 1))) if type(raw.get('stage', 1)) is int else 1,
             'acting':raw.get('acting', False), 'emotion':raw.get('emotion', True),
             'narratorEmotion':raw.get('narratorEmotion', False)}
    if clean['reading'] not in ('shared','cast') or clean['voiceMode'] not in ('clone','design'):
        raise ValueError('reading / voiceMode が不正です')
    if clean['ttsModel'] not in TTS_MODELS:
        raise ValueError('未対応のIrodoriモデルです')
    for name in ('acting','emotion','narratorEmotion'):
        if type(clean[name]) is not bool:
            raise ValueError(f'{name}はbooleanです')
    if 'voiceSample' in raw:
        if type(raw['voiceSample']) is not bool:raise ValueError('voiceSampleはbooleanです')
        if raw['voiceSample']:
            if (len(clean_segments)!=1 or len(clean_roles)!=1 or len(source)>200
                    or clean_segments[0]['text']!=source or not source.strip()
                    or clean['reading']!='shared' or clean['voiceMode']!='design'
                    or clean['acting'] or clean['emotion'] or 'tts_text' in clean_segments[0]
                    or clean_segments[0].get('segment_type','speech')!='speech'):
                raise ValueError('声のサンプルは200文字以内・参照なし・演技と感情なしの単一発話にしてください')
            clean['voiceSample']=True
    if type(clean['seed']) is not int or not 0 <= clean['seed'] <= 2147483647 or type(clean['steps']) is not int or clean['steps'] not in (20,40,60):
        raise ValueError('seed / steps が不正です')
    if type(clean['pause']) not in (float, int) or not math.isfinite(clean['pause']) or not 0 <= clean['pause'] <= 1:
        raise ValueError('pauseは0〜1秒です')
    from .execution_profiles import normalize_profile,normalize_ui
    if 'executionProfile' in raw:clean['executionProfile']=normalize_profile(raw['executionProfile'])
    if 'ui' in raw:clean['ui']=normalize_ui(raw['ui'])
    if 'textOptions' in raw:clean['textOptions']=text_options(raw['textOptions'])
    if 'voiceProfiles' in raw:
        profiles=raw['voiceProfiles']
        if not isinstance(profiles,list) or len(profiles)>100:raise ValueError('参照音声は100件までです')
        cleaned=[];seen=set()
        for profile in profiles:
            if not isinstance(profile,dict):raise ValueError('参照音声の形式が不正です')
            key=identifier(profile.get('id'),'voice profile')
            if key in seen or key in ('voice_a','design'):raise ValueError('参照音声IDの重複・予約名です')
            seen.add(key); item={'id':key,'name':text(profile.get('name'), '参照音声名',200)}
            if 'voiceId' in profile:
                if not isinstance(profile['voiceId'],str) or not re.fullmatch('[a-f0-9]{32}',profile['voiceId']):raise ValueError('参照音声の登録IDが不正です')
                item['voiceId']=profile['voiceId']
            cleaned.append(item)
        clean['voiceProfiles']=cleaned
    return clean


def new_project(source, analysis=None):
    if analysis is not None:
        roles, segments, source = import_analysis(analysis, source)
    else:
        rows = source_rows(source)
        hints = list(dict.fromkeys(r['speaker_hint'] for r in rows))
        profiles = {f'person_{i+1}':{'name':hint} for i,hint in enumerate(hints)}
        mapping = {p['name']:key for key,p in profiles.items()}
        roles, segments, _ = import_analysis({'schema_version':1, 'speakers':profiles,
            'segments':[{'id':r['id'], 'speaker_id':mapping[r['speaker_hint']], 'text':r['text']} for r in rows]})
    project = normalize_project({'version':1, 'source':source, 'roles':roles, 'segments':segments,
                                 **({'textOptions':analysis['textOptions']} if analysis and 'textOptions' in analysis else {}),
                                 'analyzed':analysis is not None})
    return project


def export_analysis(project):
    names = {r['id']:r['name'] for r in project['roles']}
    return {'schema_version':1, 'source':project['source'], 'source_sha256':digest([{'id':s['id'], 'speaker_hint':names[s['role']], 'text':s['text']} for s in project['segments']]),
            'speakers':{r['id']:{**r['attributes'], 'kind':r.get('kind','narrator' if is_narrator(r) else 'character'), 'name':r['name'], 'bio':r['bio'], 'voice_caption':r['caption'], 'acting_description':r['acting']} for r in project['roles']},
            **({'textOptions':project['textOptions']} if 'textOptions' in project else {}),
            'segments':[{'id':s['id'], 'speaker_id':s['role'], 'text':s['text'], 'emotion':s['emotion'], 'acting_description':s['acting'], **{k:s[k] for k in ('tts_text','pause_after_ms','emotion_locked') if k in s}, **metadata(s)} for s in project['segments']]}


def sampling_plan(project, voices=None, *, selected=None):
    project = normalize_project(project)
    if not project['analyzed']:
        raise ValueError('先にQwen分析か分析JSONの取り込みを行ってください')
    voices = voices or {}
    roles = {r['id']:r for r in project['roles']}
    plan = []
    reference_cache = {}
    converted={r['id']:r for r in convert_project(project)}
    pending_gap=None;pending_manual=False
    if selected is not None and not set(selected)<={r['id'] for r in project['segments']}:raise ValueError('生成する発話IDが存在しません')
    for segment in project['segments']:
        if selected is not None and segment['id'] not in selected:continue
        converted_row=converted[segment['id']]
        gap=converted_row['pause_after_ms']
        if converted_row['segment_type']=='separator':
            if plan and gap is not None:
                if 'pause_after_ms' in segment:
                    pending_gap=max(pending_gap or 0,gap) if pending_manual else gap;pending_manual=True
                elif not pending_manual:pending_gap=max(pending_gap or 0,gap)
            continue
        if converted_row['blocking']:raise ValueError(segment['id']+': '+' / '.join(converted_row['warnings']))
        if pending_gap is not None and plan and not plan[-1].get('_manual_pause'):
            plan[-1]['pause_after_ms']=pending_gap if pending_manual else max(plan[-1].get('pause_after_ms',round(project['pause']*1000)),pending_gap)
        pending_gap=None;pending_manual=False
        role = roles[segment['role']]
        shared = project['reading'] == 'shared'
        clone = (project['voiceMode']=='clone') if shared or role['voice']=='voice_a' else role['voice']!='design'
        caption = project['baseCaption'] if shared or clone else role['caption']
        if not caption.strip() and not clone:
            raise ValueError(f"{role['id']}: VoiceDesignの声質説明が空です")
        if project['acting']:
            caption = '\n'.join(p for p in [caption.rstrip(), role['acting'].strip(), segment['acting'].strip()] if p)
        request = {'text':(EMOTIONS[segment['emotion']] if project['emotion'] and (project['narratorEmotion'] or not is_narrator(role)) else '') + converted_row['tts_text'],
                   'caption':caption or None, 'no_ref':not clone, 'num_steps':project['steps'], 'seed':project['seed']}
        if project.get('voiceSample'):request['max_seconds']=30.0
        reference = None
        if clone:
            profile = 'voice_a' if shared else role['voice']
            if profile not in voices:
                raise ValueError(f'{profile}: --voice {profile}=音声ファイル の指定が必要です')
            if profile not in reference_cache:
                path = Path(voices[profile]).resolve(strict=True)
                if not path.is_file():
                    raise ValueError('参照音声はファイルを指定してください')
                reference_cache[profile] = (path, file_hash(path))
            path, checksum = reference_cache[profile]
            reference = {'profile':profile, 'sha256':checksum}
            request.update(ref_wav=str(path), max_ref_seconds=30)
        identity = {k:v for k,v in request.items() if k != 'ref_wav'}
        fingerprint = digest({'model':project['ttsModel'], 'request':identity, 'reference':reference, 'engine_contract':1})
        plan.append({'id':segment['id'], 'role':segment['role'], 'request':request,
                     'reference':reference, 'fingerprint':fingerprint, **({'pause_after_ms':gap} if gap is not None else {}), **({'_manual_pause':True} if 'pause_after_ms' in segment else {})})
    for row in plan:row.pop('_manual_pause',None)
    if not plan:raise ValueError('読み上げる本文がありません。区切りだけでは生成できません')
    return plan
