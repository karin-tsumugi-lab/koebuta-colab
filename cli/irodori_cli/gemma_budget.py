"""Conservative, measured Gemma admission for the experimental local analyzer.

Memory observations must come from an otherwise idle, single-GPU runtime.
This is a bounded operating policy, not a claim about a model's maximum context.
"""
import copy
import math

from .core import EMOTIONS


class ContextOverflow(ValueError):
    def __init__(self,prompt_tokens,context,budget):
        self.details={'input_tokens':prompt_tokens,'output_tokens':budget,'margin':128,'context':context,
                      'required_tokens':prompt_tokens+budget+128}
        super().__init__(f'入力がコンテキストサイズを超えます: 入力{prompt_tokens}、出力予約{budget}、'
                         f'安全余白128、全体{context}。原稿を章ごとに分けてください。原稿は切り捨てません')


def context_plan(total_mib, free_mib, observations, cap=16384):
    """observations: (context tokens, incremental GPU MiB), batch held constant."""
    if (len(observations) < 2 or cap < 512 or not 0 < free_mib <= total_mib
            or not all(math.isfinite(v) for v in (total_mib, free_mib, cap))):
        raise ValueError('コンテキストサイズの計測値が不足・不正です')
    points = sorted(observations)
    (a, ma), (b, mb) = points[-2:]
    if a <= 0 or b <= a or min(ma, mb) <= 0 or not all(math.isfinite(v) for v in (a,b,ma,mb)):
        raise ValueError('コンテキストサイズの計測値が不正です')
    # Round-up/allocation noise must not produce a zero or negative KV estimate.
    slope = max((mb-ma)/(b-a), 0.125) * 1.25
    reserve = max(2048, total_mib * .20)
    base = max(ma-slope*a, mb-slope*b, 0)
    available = free_mib-reserve-base
    context = min(cap, math.floor(available/slope/512)*512)
    if context < 512:
        raise ValueError('GPUの空きメモリが不足しています。他の処理を終了してください')
    return {'context':context, 'reserve_mib':math.ceil(reserve),
            'estimated_increment_mib':math.ceil(base+slope*context),
            'mib_per_token':slope, 'free_mib_at_plan':free_mib, 'cap':cap}


def admit(prompt_tokens, context, rows, requested=0):
    """Call after exact official-template tokenization, before inference."""
    if min(prompt_tokens, rows, requested) < 0 or context < 512:
        raise ValueError('入力枠の設定が不正です')
    required = 256 + 64 * rows
    available = context-prompt_tokens-128
    budget = requested or required
    if budget < required or budget > available:
        raise ContextOverflow(prompt_tokens,context,budget)
    return budget


def apply_emotions(rows, assignments, finish_reason='stop'):
    """Apply only complete ID-aligned results; model never owns source text."""
    if not isinstance(assignments,list) or any(not isinstance(r,dict) for r in assignments):
        raise ValueError('感情分析JSONの形式が不正です。結果は未適用です')
    ids = [r['id'] for r in rows]
    if finish_reason == 'length' or len(set(ids)) != len(ids):
        raise ValueError('分析が途中で終了したか、原稿IDが重複しています。結果は未適用です')
    if [r.get('id') for r in assignments] != ids:
        raise ValueError('分析行の欠落・重複・順序変更があります。結果は未適用です')
    if any(set(r) != {'id', 'emotion'} or r['emotion'] not in EMOTIONS for r in assignments):
        raise ValueError('不正な感情タグです。結果は未適用です')
    result = copy.deepcopy(rows)
    for row, assignment in zip(result, assignments):
        row['emotion'] = assignment['emotion']
    return result
