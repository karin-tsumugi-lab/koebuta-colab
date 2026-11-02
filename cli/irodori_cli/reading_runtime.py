"""Qwen adapter for shared reading prompts, using the pinned speaker environment."""
import json
import time
from pathlib import Path
from .core import atomic_json, digest, model_json
from .budget import completion_text, output_budget
from .speaker_prompts import chat

class QwenRuntime:
    def __init__(self,job,context):
        self.job=Path(job)
        from huggingface_hub import hf_hub_download
        from llama_cpp import Llama, llama_cpp
        from .environments import MODEL_REVISIONS
        if not 512<=context<=8192:raise ValueError('Qwenの読み補正は検証済みコンテキスト8192以下で指定してください')
        if 'cuda' not in llama_cpp.llama_print_system_info().decode(errors='replace').lower():raise RuntimeError('CUDA対応llama-cpp-pythonが必要です')
        from .gemma_runtime import idle_gpu
        idle_gpu()
        self.path=hf_hub_download('Qwen/Qwen3-8B-GGUF','Qwen3-8B-Q4_K_M.gguf',revision=MODEL_REVISIONS['Qwen/Qwen3-8B-GGUF'])
        self.context=context;self.llm=None
        self.provenance={'repo':'Qwen/Qwen3-8B-GGUF','revision':MODEL_REVISIONS['Qwen/Qwen3-8B-GGUF'],
                         'file':'Qwen3-8B-Q4_K_M.gguf','context':context,'contract':1}
        self.tokenizer=Llama(model_path=self.path,vocab_only=True,n_gpu_layers=0,verbose=False)
    def check(self,prompt,rows,label,requested=2048):
        formatted=chat(prompt);count=len(self.tokenizer.tokenize(formatted.encode()))
        if self.context-count-32<requested:raise ValueError('読み補正の入力がQwenのコンテキストサイズを超えています。原稿を章ごとに分けてください')
        return formatted,output_budget(count,self.context,requested,0)
    def infer(self,prompt,schema,rows,label,requested=2048):
        from llama_cpp import Llama,LlamaGrammar
        formatted,limit=self.check(prompt,rows,label,requested)
        if self.llm is None:
            from .gemma_runtime import idle_gpu
            idle_gpu(allow_current=True)
            self.llm=Llama(model_path=self.path,n_ctx=self.context,n_batch=256,n_gpu_layers=-1,seed=314,verbose=False)
        response=self.llm.create_completion(prompt=formatted,grammar=LlamaGrammar.from_json_schema(json.dumps(schema),verbose=False),temperature=0,top_p=1,max_tokens=limit,stop=['<|im_end|>'])
        choice=response['choices'][0]
        atomic_json(self.job/'qwen_completions'/f'{time.time_ns()}.json',{
            'stage':label,'prompt_sha256':digest(prompt),'output_limit':limit,
            'usage':response.get('usage',{}),'finish_reason':choice.get('finish_reason'),'text':choice['text']})
        return model_json(completion_text(response))
    def close(self):
        if self.llm:self.llm.close()
        self.tokenizer.close()
