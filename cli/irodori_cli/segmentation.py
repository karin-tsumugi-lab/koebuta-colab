"""Lossless, deterministic TTS chunks. Length is a heuristic, not a duration guarantee."""
import copy
import hashlib
import re

MAX_CHARS = 80


def split_text(text, limit=MAX_CHARS):
    if not isinstance(text,str) or not text.strip():raise ValueError('分割する本文が空です')
    if type(limit) is not int or limit<8:raise ValueError('分割上限は8文字以上です')
    # Preserve every character, including newlines and punctuation, in order.
    units=re.findall(r'[^\n。！？!?]*[。！？!?][」』”"）)]*|[^\n。！？!?]*\n+|[^\n。！？!?]+',text)
    if ''.join(units)!=text:raise ValueError('発話分割で本文を保持できませんでした')
    parts=[];current=''
    for unit in units:
        if current and (len(current)+len(unit)>limit or current.endswith('\n')):
            parts.append(current);current=''
        while len(unit)>limit:
            if current:parts.append(current);current=''
            positions=[m.end() for m in re.finditer(r'[、，,；;：:\s]+',unit[:limit]) if m.end()>=limit//3 and unit[:m.end()].strip()]
            cut=positions[-1] if positions else limit
            # Do not separate combining marks, variation selectors, or a ZWJ sequence.
            import unicodedata
            while cut>1 and (unicodedata.combining(unit[cut]) or unit[cut] in ('\ufe0f','\u200d') or unit[cut-1]=='\u200d'):cut-=1
            parts.append(unit[:cut]);unit=unit[cut:]
        current+=unit
    if current:parts.append(current)
    # Whitespace-only pieces carry no speech; attach them without discarding them.
    clean=[];pending=''
    for part in parts:
        if not part.strip() and clean:clean[-1]+=part
        elif not part.strip():pending+=part
        else:
            clean.append(pending+part);pending=''
    if ''.join(clean)!=text or any(not p.strip() for p in clean):
        raise ValueError('空の分割発話があります')
    return clean


def split_segments(segments,limit=MAX_CHARS,*,with_mapping=False,default_format='none',symbol_separators=False,prefer_reading=False):
    from .text_conversion import separator
    result=[];used={s['id'] for s in segments};mapping={}
    for row in segments:
        if row.get('segment_type', 'separator' if symbol_separators and separator(row['text']) else 'speech')=='separator':
            result.append(copy.deepcopy(row));mapping[row['id']]=[row['id']];continue
        # A complete short explicit reading is the actual TTS input. Its long
        # source notation need not be split (nor aligned by text similarity).
        pieces=([row['text']] if prefer_reading and 'tts_text' in row and len(row['tts_text'])<=limit
                else split_text(row['text'],limit))
        fmt=row.get('text_format',default_format)
        if len(pieces)>1 and fmt!='none':
            from .text_conversion import protected_ranges,reading
            spans=protected_ranges(row['text'],fmt);cuts=[];offset=0
            for piece in pieces[:-1]:
                offset+=len(piece);cut=offset
                for a,b in spans:
                    if a<cut<b:
                        cut=a if a>(cuts[-1] if cuts else 0) else b
                        if len(reading(row['text'][a:b],fmt)[0])>limit:
                            raise ValueError(row['id']+': ルビの読みが分割目安を超えます。読みと本文を手動で分けてください')
                        break
                if cut>(cuts[-1] if cuts else 0) and cut<len(row['text']):cuts.append(cut)
            positions=[0,*cuts,len(row['text'])]
            pieces=[row['text'][a:b] for a,b in zip(positions,positions[1:])]
            # Layout-only fragments belong to adjacent speech, not an empty TTS call.
            clean=[];pending=''
            for piece in pieces:
                spoken,_=reading(piece,fmt)
                if not spoken.strip() and clean:clean[-1]+=piece
                elif not spoken.strip():pending+=piece
                else:clean.append(pending+piece);pending=''
            pieces=clean if clean else [row['text']]
        if len(pieces)>1:
            from .text_conversion import validate_split
            validate_split(row,pieces,default_format)
        spoken_pieces=None
        if len(pieces)>1 and 'tts_text' in row and row['tts_text'] != row['text']:
            from .text_conversion import reading
            readings=[reading(piece,fmt) for piece in pieces]
            from .emoji_tags import align_readings
            spoken_pieces = align_readings(readings, row['tts_text'])
            if spoken_pieces is None:
                raise ValueError(f"{row['id']}: 読み補正と原文の分割位置を安全に対応付けられません。演技・感情の該当行の「分割」で原文と読み上げ用テキストを分けてください。内容は保持しています")
        mapping[row['id']]=[]
        for index,body in enumerate(pieces):
            item=copy.deepcopy(row);item['text']=body
            if len(pieces)>1:item.pop('reading_correction',None)
            if 'tts_text' in item and len(pieces)>1:item['tts_text']=spoken_pieces[index] if spoken_pieces else body
            if index < len(pieces)-1:
                item.pop('pause_after_ms',None);item.pop('blank_lines_after',None)
            if index:
                salt=0
                while True:
                    suffix=hashlib.sha256(f"{row['id']}:{index}:{salt}".encode()).hexdigest()[:12]
                    key=row['id'][:49]+'_s'+suffix
                    if key not in used:break
                    salt+=1
                used.add(key);item['id']=key
            result.append(item)
            mapping[row['id']].append(item['id'])
    if len(result)>2000:raise ValueError('TTS用の分割後に2000発話を超えます。章ごとにプロジェクトを分けてください')
    return (result,mapping) if with_mapping else result


def prepare_project(project):
    result,_=prepare_with_mapping(project)
    return result


def prepare_with_mapping(project):
    result=copy.deepcopy(project)
    if project.get('voiceSample'):
        from .core import normalize_project
        result=normalize_project(project)
        return result,{s['id']:[s['id']] for s in result['segments']}
    cfg=project.get('textOptions',{})
    result['segments'],mapping=split_segments(project['segments'],with_mapping=True,default_format=cfg.get('format','none'),symbol_separators=cfg.get('symbolSeparators',False),prefer_reading=True)
    return result,mapping


def expand_ids(ids,mapping):
    if ids is None:return None
    if not set(ids)<=set(mapping):raise ValueError('分割対象の発話IDが存在しません')
    return [part for key in ids for part in mapping[key]]
