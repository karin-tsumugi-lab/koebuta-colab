"""Explicit, deterministic reading conversion. Never rewrite the source manuscript.

This is a basic ruby reader, not a complete Aozora typesetting implementation.
Unknown annotations and malformed notation require review rather than deletion.
"""
import copy
import re

FORMATS = ('none', 'aozora', 'narou', 'kakuyomu', 'pixiv')
SEGMENT_FIELDS = ('text_format', 'segment_type', 'blank_lines_after')
KANJI = r'\u3400-\u9fff\U00020000-\U0002ffff々〆〇ヶ'


def options(raw):
    if not isinstance(raw, dict):raise ValueError('textOptionsはオブジェクトです')
    result={'format':raw.get('format','none'), 'blankMode':raw.get('blankMode','off'),
            'blankPauseMs':raw.get('blankPauseMs',1200), 'symbolSeparators':raw.get('symbolSeparators',False), **({'readingMode':raw['readingMode']} if 'readingMode' in raw else {})}
    if result['format'] not in FORMATS:raise ValueError('未対応のルビ形式です')
    if result['blankMode'] not in ('off','group','count'):raise ValueError('空行の処理方法が不正です')
    if type(result['blankPauseMs']) is not int or not 0<=result['blankPauseMs']<=10000:raise ValueError('空行の間は0〜10000ミリ秒です')
    if type(result['symbolSeparators']) is not bool:raise ValueError('symbolSeparatorsはbooleanです')
    if result.get('readingMode','off') not in ('off','selective','all'):raise ValueError('読み補正の設定が不正です')
    return result


def metadata(row):
    result={k:row[k] for k in SEGMENT_FIELDS if k in row}
    if 'text_format' in result and result['text_format'] not in FORMATS:raise ValueError('未対応のtext_formatです')
    if 'segment_type' in result and result['segment_type'] not in ('speech','separator'):raise ValueError('segment_typeはspeechまたはseparatorです')
    if 'blank_lines_after' in result and (type(result['blank_lines_after']) is not int or not 0<=result['blank_lines_after']<=100000):raise ValueError('blank_lines_afterは0〜100000の整数です')
    if 'tts_text_origin' in row:
        if row['tts_text_origin']!='analysis':raise ValueError('読みの作成元が不正です')
        result['tts_text_origin']='analysis'
    if 'reading_correction' in row:
        c=row['reading_correction']
        if not isinstance(c,dict) or set(c)!={'before','after','mode','note'} or c['mode'] not in ('selective','all') or any(not isinstance(c[k],str) or len(c[k])>5000 for k in ('before','after')) or not isinstance(c['note'],str) or len(c['note'])>1000:raise ValueError('読み補正記録が不正です')
        result['reading_correction']=copy.deepcopy(c)
    return result


def reading(body, fmt):
    """Return a reading plus review warnings; explicit tts_text bypasses this."""
    value, warnings, _ = convert_with_map(body, fmt)
    return value, warnings


def convert_with_map(body, fmt):
    """Same conversion as reading(), recording positions during each operation."""
    from .text_map import TextMap
    if fmt not in FORMATS:raise ValueError('未対応のルビ形式です')
    mapped=TextMap(body)
    if fmt=='none':return body,[],mapped.export()
    warnings=[]
    marker='\ue000'
    while marker in body:marker+='\ue000'
    if fmt=='pixiv':
        mapped.sub(r'\[\[rb:([^\[\]\n>]+?)\s*>\s*([^\[\]\n]+?)\]\]',lambda m:m[2].strip(),'ruby')
        if '[[' in mapped.rendered or ']]' in mapped.rendered:warnings.append('未対応または不正なpixiv記法があります')
    else:
        if fmt=='aozora':
            # A known kana reading is usable even when the small glyph is not.
            # Keep the original gaiji notation in text; never guess unknown gaiji.
            mapped.sub(r'※［＃小書き平仮名([ぁ-ゖ])、[0-9０-９]+[-－][0-9０-９]+］',lambda m:m[1],'ruby')
            def layout(match):
                note=match[1]
                known=(r'(?:改ページ|改丁|改見開き|ここから[０-９0-9]+字下げ|ここで字下げ終わり|[０-９0-9]+字下げ|'
                       r'「[^「」［］\n]+」に傍点|「[^「」［］\n]+」は[大中小]見出し|[大中小]見出し(?:終わり)?)')
                return '' if re.fullmatch(known,note) else match[0]
            mapped.sub(r'［＃([^［］\n]*)］',layout,'layout')
        # Protect escaped opening marks before ruby processing.
        if fmt=='kakuyomu':mapped.sub('｜《',lambda m:marker+'a','escape')
        if fmt=='narou':mapped.sub(r'[｜|]([（(])',lambda m:marker+('b' if m[1]=='(' else 'c'),'escape')
        if fmt=='kakuyomu':mapped.sub(r'《《([^《》\n]+)》》',r'\1','emphasis')
        bars='｜' if fmt=='aozora' else '｜|'
        mapped.sub('['+bars+r']([^｜|《》\n]+)《([^《》\n]+)》',lambda m:m[2],'ruby')
        mapped.sub('['+KANJI+r']+《([^《》\n]+)》',lambda m:m[1],'ruby')
        if fmt=='narou':
            mapped.sub('['+KANJI+r']+\(([ぁ-ゖァ-ヺー]+)\)',lambda m:m[1],'ruby')
            mapped.sub('['+KANJI+r']+（([ぁ-ゖァ-ヺー]+)）',lambda m:m[1],'ruby')
        if any(mark in mapped.rendered for mark in ('《','》','［＃','｜','］')):warnings.append('未対応または不正なルビ・注記があります')
        for suffix,value in (('a','《'),('b','('),('c','（')):
            mapped.sub(re.escape(marker+suffix),lambda m,v=value:v,'escape')
    result=mapped.rendered
    if not result.strip():warnings.append('変換後に読み上げる本文がありません。区切りを指定してください')
    return result,warnings,mapped.export()


def separator(body):
    # Deliberately exclude ellipsis, long vowel marks, dialogue and arbitrary punctuation.
    compact=re.sub(r'[ \t\u3000]','',body.strip())
    return bool(re.fullmatch(r'([―—─━*＊◇◆☆★])\1{2,}',compact))


def validate_split(row, pieces, default_format='none'):
    if not isinstance(pieces,list) or len(pieces)<2 or any(not isinstance(p,str) or not p.strip() for p in pieces) or ''.join(pieces)!=row['text']:
        raise ValueError('分割前後の本文が一致しません')
    fmt=row.get('text_format',default_format)
    if fmt=='none':return
    original,issues=reading(row['text'],fmt)
    readings=[reading(piece,fmt) for piece in pieces]
    # Cutting inside an implicit parent word can produce two individually valid
    # pieces but a different reading (東 + 京《とうきょう》). Check the whole reading.
    if issues or any(w for _,w in readings) or ''.join(p for p,_ in readings)!=original:
        raise ValueError(row['id']+': ルビをまたぐ分割です。ルビの前後で分割してください')


def protected_ranges(body, fmt):
    """Spans that must stay atomic while choosing source-preserving TTS cuts."""
    if fmt=='none':return []
    patterns=[r'※?［＃[^［］\n]*］'] if fmt=='aozora' else []
    if fmt=='pixiv':patterns.append(r'\[\[rb:[^\[\]\n]+\]\]')
    else:
        bars='｜' if fmt=='aozora' else '｜|'
        patterns.extend(['['+bars+r'][^｜|《》\n]+《[^《》\n]+》',
                         '['+KANJI+r']+《[^《》\n]+》'])
        if fmt=='narou':patterns.extend(['['+KANJI+r']+\([ぁ-ゖァ-ヺー]+\)', '['+KANJI+r']+（[ぁ-ゖァ-ヺー]+）'])
        if fmt=='kakuyomu':patterns.append(r'《《[^《》\n]+》》')
    spans=sorted((m.start(),m.end()) for pattern in patterns for m in re.finditer(pattern,body))
    merged=[]
    for a,b in spans:
        if merged and a<merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else:merged.append((a,b))
    return merged


def convert_project(project):
    """Annotate only. Automatic decisions remain reversible and are not saved as edits."""
    result=copy.deepcopy(project); cfg=options(project.get('textOptions',{})); rows=[]; cursor=0
    for original in result['segments']:
        row=copy.deepcopy(original); warnings=[]
        body=row['text']; needle=body.strip(); found=result['source'].find(needle,cursor)
        count=row.get('blank_lines_after',0)
        if found>=0:
            end=found+len(needle); cursor=end
            tail=result['source'][end:]
            # Scenario dialogue may omit its outer closing quote. Only bridge
            # that delimiter at a line boundary; never skip subsequent prose.
            gap=re.match(r'[」』”"]?[ \t\u3000]*(?:\r?\n[ \t\u3000]*)+',tail)
            if 'blank_lines_after' not in row and gap and tail[gap.end():].strip():count=max(0,gap[0].count('\n')-1)
        elif cfg['blankMode']!='off' and 'blank_lines_after' not in row:
            warnings.append('原稿との位置を照合できないため、空行の間は自動設定しません')
        fmt=row.get('text_format',cfg['format'])
        spoken,issues=(row['tts_text'],[]) if 'tts_text' in row else reading(body,fmt)
        warnings+=issues
        kind=row.get('segment_type','separator' if cfg['symbolSeparators'] and separator(body) else 'speech')
        automatic=None
        if count and cfg['blankMode']!='off':automatic=min(10000,cfg['blankPauseMs']*(count if cfg['blankMode']=='count' else 1))
        if kind=='separator' and automatic is None:automatic=cfg['blankPauseMs']
        rows.append({'id':row['id'],'text':body,'tts_text':spoken,'segment_type':kind,
                     'text_format':fmt,'reading_origin':'ai' if row.get('tts_text_origin')=='analysis' else 'manual' if 'tts_text' in row else 'converted' if fmt!='none' else 'source',
                     'blank_lines_after':count,'pause_after_ms':row.get('pause_after_ms',automatic),
                     'pause_origin':'manual' if 'pause_after_ms' in row else 'automatic' if automatic is not None else 'global',
                     'blocking':bool(issues) and kind=='speech',
                     'warnings':warnings if kind=='speech' else []})
    return rows


def carry_reading_settings(project, roles, segments):
    """Re-analysis must not silently erase human reading/voice assignments."""
    if not project.get('analyzed'):return
    fields=(*SEGMENT_FIELDS,'reading_correction','tts_text_origin','tts_text','pause_after_ms','emotion_locked')
    previous=project['segments'];used=set()
    for row in segments:
        candidates=[s for s in previous if s['text']==row['text'] and s['id'] not in used]
        exact=next((s for s in candidates if s['id']==row['id']),None)
        old=exact or (candidates[0] if len(candidates)==1 else None)
        if old:
            used.add(old['id']);row.update({k:old[k] for k in fields if k in old})
            if old.get('emotion_locked'):row['emotion']=old.get('emotion','neutral')
    if any(s['id'] not in used and any(k in s for k in fields) for s in previous):
        raise ValueError('再分析で発話の区切りが変わり、個別の読み・間を引き継げません。結果は未適用です。現在のプロジェクトを保存してから別プロジェクトで分析してください')
    for role in roles:
        old=next((r for r in project['roles'] if r['name']==role['name'] and r.get('kind')==role.get('kind')),None)
        if old:
            role['voice']=old.get('voice','voice_a')
            if role['voice']=='design':role['caption']=old['caption']
