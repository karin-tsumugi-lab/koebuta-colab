"""Validated split attribution and one-profile-per-call Qwen stage."""
import json
from pathlib import Path
from .core import atomic_json, digest, import_analysis, normalize_project, read_json, source_rows, text
from .budget import completion_text, output_budget
from .speaker_prompts import chat, known_speakers, dialogue_prompt, profiles_prompt


def run(args):
    from huggingface_hub import hf_hub_download
    from llama_cpp import Llama, LlamaGrammar, llama_cpp
    from .worker import memory
    project=normalize_project(read_json(args.project))
    if project['analyzed'] and not args.replace_analysis:
        raise ValueError('分析済みの設定です。置換するには --replace-analysis が必要です')
    rows=source_rows(project['source']);known=known_speakers(rows);job=Path(args.job)
    if 'cuda' not in llama_cpp.llama_print_system_info().decode(errors='replace').lower():
        raise RuntimeError('CUDA対応の事前ビルド済みllama-cpp-pythonが必要です')
    print('PROGRESS Qwen: モデルファイルの取得・キャッシュ確認中',flush=True)
    from .environments import MODEL_REVISIONS
    path=hf_hub_download('Qwen/Qwen3-8B-GGUF','Qwen3-8B-Q4_K_M.gguf',revision=MODEL_REVISIONS['Qwen/Qwen3-8B-GGUF'])
    # Check the full context before GPU allocation, including the later profile task.
    tokenizer=Llama(model_path=path,vocab_only=True,n_gpu_layers=0,verbose=False)
    budgets=[]
    def admit(model,prompt,cap):
        formatted=chat(prompt);count=len(model.tokenize(formatted.encode()))
        limit=output_budget(count,args.context,args.max_tokens,0)
        return formatted,count,min(limit,cap)
    try:
        preflight=[profiles_prompt(rows,{'speaker_1':'人物名'})[0]]
        if len(known)!=len(rows):preflight.append(dialogue_prompt(rows,known)[0])
        for prompt in preflight:admit(tokenizer,prompt,max(512,64*len(rows)))
    finally:tokenizer.close()
    print('PROGRESS Qwen: モデルを読み込み中。名前付き台詞・地の文はコードで確定します',flush=True)
    llm=Llama(model_path=path,n_ctx=args.context,n_batch=256,n_gpu_layers=-1,seed=314,verbose=False)
    atomic_json(job/'qwen_memory_while_loaded.json',memory())
    def infer(prompt,schema,cap,label):
        formatted,count,limit=admit(llm,prompt,cap)
        budgets.append({'stage':label,'input_tokens':count,'output_limit':limit,'context':args.context,'margin':32})
        atomic_json(job/'qwen_budget.json',{'contract':2,'requests':budgets,'input_tokens':count,'output_limit':limit,'context':args.context,'margin':32,'output_estimate_is_guarantee':False})
        response=llm.create_completion(prompt=formatted,grammar=LlamaGrammar.from_json_schema(json.dumps(schema),verbose=False),temperature=0,top_p=1,max_tokens=limit,stop=['<|im_end|>'])
        atomic_json(job/f'qwen_response_{len(budgets):03d}.json',{'stage':label,'prompt':formatted,'response':response})
        return json.loads(completion_text(response))
    try:
        if len(known)!=len(rows):
            print('PROGRESS Qwen: 名前のない台詞の話者を判定中',flush=True)
            prompt,schema=dialogue_prompt(rows,known)
            inferred=infer(prompt,schema,max(512,64*(len(rows)-len(known))),'assignment')
            if set(inferred)!={r['id'] for r in rows if r['id'] not in known}:raise ValueError('Qwenの発話IDが一致しません')
            known.update(inferred)
        assignment={}
        for row in rows:
            name=text(known[row['id']],'話者名',50).strip()
            if name in ('ナレーター','ナレーション','語り手','narrator'):name='地の文'
            assignment[row['id']]=name
        names={f'speaker_{i+1}':name for i,name in enumerate(dict.fromkeys(assignment.values()))}
        if len(names)>100:raise ValueError('話者は100人以内にしてください')
        profiles={}
        atomic_json(job/'qwen_assignments.json',assignment)
        for index,(key,name) in enumerate(names.items(),1):
            if (job/'.stop').exists() or (job/'.pause').exists():raise RuntimeError('人物設定の生成を中断しました。分析結果は未適用です')
            print(f'PROGRESS Qwen: 人物設定 {index}/{len(names)}人目（{name}）',flush=True)
            prompt,schema=profiles_prompt(rows,{key:name})
            data=infer(prompt,schema,512,key)
            if set(data)!={key} or data[key].get('name')!=name or set(data[key])!=set(schema['properties'][key]['required']):raise ValueError('人物設定のID・名前・項目が一致しません')
            profiles[key]=data[key]
        mapping={name:key for key,name in names.items()}
        analysis={'schema_version':1,'source_sha256':digest(rows),'speakers':profiles,
            'segments':[{'id':r['id'],'speaker_id':mapping[assignment[r['id']]]} for r in rows]}
        roles,segments,_=import_analysis(analysis,project['source'])
        from .text_conversion import carry_reading_settings
        carry_reading_settings(project,roles,segments)
        project.update(roles=roles,segments=segments,analyzed=True,stage=1)
        atomic_json(job/'qwen_speaker_analysis.json',analysis)
        atomic_json(args.project,normalize_project(project))
        print('QWEN_ANALYSIS_READY',len(roles),len(segments),flush=True)
    finally:llm.close()
