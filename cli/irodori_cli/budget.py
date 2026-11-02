"""Pure Qwen context budgeting; no silent input truncation."""
def output_budget(prompt_tokens, context, requested=0, rows=0):
    if context < 512 or requested < 0:
        raise ValueError('Qwenのコンテキスト・出力上限の設定が不正です')
    available = context - prompt_tokens - 32
    # A conservative admission estimate, not a guarantee of successful generation.
    minimum = 768 + 24 * rows
    budget = requested or available
    if budget <= 0 or budget > available or budget < minimum:
        raise ValueError(f'Qwenの入出力枠が不足しています: 入力{prompt_tokens} / 全体{context}、'
                         f'出力枠{max(0, min(budget, available))}、必要目安{minimum}。'
                         '原稿を章ごとに分けるか、外部分析JSONをご利用ください。原稿は切り捨てません')
    return budget


def completion_text(response):
    choice = response['choices'][0]
    if choice.get('finish_reason') == 'length':
        raise ValueError('Qwenの出力枠不足で分析JSONが途中で切れました。結果は未適用です。'
                         '原稿を分割するか、外部分析JSONをご利用ください')
    return choice['text']


def speaker_profiles(speakers):
    import json
    profiles={};seen=set()
    for item in speakers:
        key=item['speaker_id']
        profile={k:v for k,v in item.items() if k!='speaker_id'}
        fingerprint=json.dumps(profile,ensure_ascii=False,sort_keys=True)
        if key in profiles:
            raise ValueError('Qwenの話者IDが重複しています')
        if fingerprint in seen:
            raise ValueError('Qwenが同一の人物設定を別話者として重複登録しました。分析結果は未適用です。話者整理を確認してください')
        seen.add(fingerprint);profiles[key]=profile
    return profiles
