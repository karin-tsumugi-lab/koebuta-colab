"""Generation-only Gradio prototype, executed in the P0 Notebook namespace."""
import functools
import tempfile
import uuid
import zipfile
import gradio as gr


def create_v2_ui(api):
    from notebook_v2 import CandidateStore, load_project, unpack_project, atomic_bytes, valid_wav
    import numpy as np
    import soundfile as sf
    from pathlib import Path

    def session():
        root = Path(tempfile.mkdtemp(prefix='koebuta-v2-'))
        return {'root': root, 'project': None, 'voices': {}, 'store': None, 'plan': [], 'sample': None}

    def guarded(fn):
        @functools.wraps(fn)
        def call(state, *args):
            state = state or session()
            token = api['_CTX'].set(api['new_session']())
            try:
                result = fn(state, *args)
                return (*result, state)
            except Exception as exc:
                raise gr.Error(str(exc)) from exc
            finally:
                api['_CTX'].reset(token)
        return call

    def plan(state, seed, steps, acting, emotion, narrator, pause):
        if state['project'] is None:
            raise ValueError('作品を読み込んでください')
        units = api['build_plan'](state['project'], state['voices'], use_acting=acting,
            use_emotion=emotion, narrator_emotion=narrator, seed=int(seed),
            steps=int(steps), global_pause_ms=int(pause))
        state['plan'] = units
        return units

    def summary(state):
        segments = {s['id']: s for s in state['project']['segments']}
        return [[u['unit_id'], u['segment_id'], segments[u['segment_id']].get('role'),
                 segments[u['segment_id']].get('emotion'), segments[u['segment_id']]['text'], u['text'], u['caption'],
                 u['pause_after_ms'], '採用済み' if u['unit_id'] in state['store'].accepted else '未生成',
                 '候補あり' if u['unit_id'] in state['store'].candidates else ''] for u in state['plan']]

    @guarded
    def load(state, archive, folder):
        source = unpack_project(archive, state['root'] / uuid.uuid4().hex) if archive else folder
        project, config, voices, warnings, digest = load_project(source,
            api['normalize_scenario'], api['require_ready'], api['notebook_settings'], api['resolve_project_wavs'])
        from notebook_v2 import find_project
        state.update(project=project, voices=voices, plan=[], source=find_project(source))
        identity = {k: api.get(k, 'unknown') for k in
                    ('MODEL_ID', 'MODEL_REVISION', 'CODEC_ID', 'CODEC_REVISION', 'IRODORI_RESOLVED_COMMIT')}
        identity['scenario_sha256'] = digest
        state['store'] = CandidateStore(state['root'] / uuid.uuid4().hex, identity)
        roles = ['shared'] if project.get('reading') == 'shared' else [r['id'] for r in project['roles']]
        return (f"発話数: {sum(s.get('segment_type') != 'separator' for s in project['segments'])} / 参照音声数: {len(voices)}\n" + '\n'.join(warnings),
                gr.update(choices=roles, value=roles[0] if roles else None),
                config.get('seed', 314), config.get('steps', 40), config.get('use_acting', False),
                config.get('use_emotion', True), config.get('narrator_emotion', False), config.get('default_pause_ms', 280),
                str(voices), [], gr.update(choices=[], value=None))

    def synthesis(unit, path):
        audio, sr = api['synthesize'](unit, api['load_runtime']())
        sf.write(str(path), audio, sr, subtype='PCM_16')

    @guarded
    def inspect(state, *settings):
        units = plan(state, *settings)
        return summary(state), gr.update(choices=[u['unit_id'] for u in units], value=units[0]['unit_id']), f'生成単位数: {len(units)}\n' + '\n'.join(api['STATE']['plan_warnings'])

    def targets(state, selected, group):
        unit = next((u for u in state['plan'] if u['unit_id'] == selected), None)
        if unit is None:
            raise ValueError('生成計画を更新して対象を選んでください')
        return [u for u in state['plan'] if u['segment_id'] == unit['segment_id']] if group else [unit]

    @guarded
    def regenerate(state, selected, group, *settings):
        plan(state, *settings)
        state['store'].regenerate(targets(state, selected, group), synthesis)
        return summary(state), '候補を更新しました。試聴後に採用してください'

    @guarded
    def select(state, selected):
        store = state['store']
        def audio(group):
            record = group.get(selected)
            return str(store.root / record['file']) if record and store._valid(record) else None
        return audio(store.accepted), audio(store.candidates)

    @guarded
    def adopt(state, selected, group):
        state['store'].adopt([u['unit_id'] for u in targets(state, selected, group)])
        return summary(state), '採用しました。完成WAVは再結合で更新できます'

    @guarded
    def discard(state, selected, group):
        state['store'].discard([u['unit_id'] for u in targets(state, selected, group)])
        return summary(state), '候補を破棄しました'

    @guarded
    def assign(state, role, upload):
        if not upload or not valid_wav(upload):
            raise ValueError('有効なPCM WAVを選んでください')
        target = state['root'] / (uuid.uuid4().hex + '.wav')
        atomic_bytes(target, Path(upload).read_bytes())
        state['voices'][role] = str(target)
        return str(state['voices']), str(target)

    @guarded
    def sample(state, text, caption, seed, steps):
        unit = dict(text=text, caption=caption or None, ref_wav=None, seed=int(seed), num_steps=int(steps))
        # Voice design is reference-free, matching the v1 runtime request.
        from irodori_tts.inference_runtime import SamplingRequest
        result = api['load_runtime']().synthesize(SamplingRequest(text=text, caption=caption or None,
                    no_ref=True, num_steps=int(steps), seed=int(seed)))
        target = state['root'] / (uuid.uuid4().hex + '.wav')
        sf.write(str(target), result.audios[0].detach().cpu().float().view(-1).numpy(), int(result.sample_rate), subtype='PCM_16')
        if not valid_wav(target):
            raise ValueError('試作音声が不正です')
        state['sample'] = str(target)
        return str(target)

    @guarded
    def adopt_sample(state, role):
        if not state['sample']:
            raise ValueError('声を試作してください')
        state['voices'][role] = state['sample']
        return str(state['voices'])

    @guarded
    def generate(state, *settings):
        units = plan(state, *settings)
        missing = [u for u in units if u['unit_id'] not in state['store'].accepted
                   or not state['store']._valid(state['store'].accepted[u['unit_id']])
                   or state['store'].accepted[u['unit_id']]['key'] != state['store'].key(u)]
        if missing:
            state['store'].regenerate(missing, synthesis, force=False)
            state['store'].adopt([u['unit_id'] for u in missing])
        return summary(state), '全編の採用済み音声を準備しました。再結合してください'

    @guarded
    def output(state, destination, *settings):
        units = plan(state, *settings)
        store = state['store']
        chunks, rate = [], None
        zip_path = state['root'] / (uuid.uuid4().hex + '.zip')
        # Validate all accepted inputs before publishing any output.
        for unit in units:
            record = store.accepted.get(unit['unit_id'])
            if not record or not store._valid(record) or record['key'] != store.key(unit):
                raise ValueError(unit['unit_id'] + ': 現在の条件に一致する採用音声が必要です')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for index, unit in enumerate(units):
                path = store.root / store.accepted[unit['unit_id']]['file']
                audio, sr = sf.read(str(path), dtype='float32')
                if audio.ndim != 1 or (rate is not None and sr != rate):
                    raise ValueError('音声の形式が一致しません')
                rate = sr
                chunks.append(audio)
                if index < len(units) - 1:
                    chunks.append(np.zeros(int(sr * unit['pause_after_ms'] / 1000), dtype='float32'))
                archive.write(path, f'{index + 1:06d}.wav')
        target = state['root'] / (uuid.uuid4().hex + '.wav')
        sf.write(str(target), np.concatenate(chunks), rate, subtype='PCM_16')
        message = '完成WAVと個別音声ZIPを作成しました'
        if destination.strip():
            resolved = Path(destination).resolve()
            if resolved == state['source'] or resolved.is_relative_to(state['source']):
                raise ValueError('元作品の保護のため、作品フォルダ外の保存先を指定してください。完成結果は一時領域に保持しています')
            warning = store.persist(destination)
            try:
                atomic_bytes(Path(destination) / 'narration.wav', target.read_bytes())
                atomic_bytes(Path(destination) / 'individual.zip', zip_path.read_bytes())
            except Exception as exc:
                warning = 'Drive出力保存失敗。一時領域の結果は保持しています: ' + str(exc)
            message += '\n' + (warning or 'Driveへ保存しました')
        return str(target), str(target), str(zip_path), message

    @guarded
    def restore(state, folder):
        source = CandidateStore(folder, state['store'].identity)
        source.restore()
        warning = source.persist(state['store'].root)
        if warning:
            raise ValueError(warning)
        state['store'].restore()
        return '保存状態を復元しました。生成計画を更新してください'

    with gr.Blocks() as demo:
        state = gr.State(None)
        gr.Markdown('# Koebuta Notebook v2 試作\nシナリオJSONは読み取り専用です。編集はHTML版で行ってください。')
        with gr.Group():
            gr.Markdown('## 1. 作品の読み込み')
            archive = gr.File(label='作品ZIP（ZIPがある場合はこちらを優先）', type='filepath')
            folder = gr.Textbox(label='マウント済みDrive作品フォルダ')
            load_button = gr.Button('作品を読み込む')
            status = gr.Textbox(label='構造検証・進捗', interactive=False)
        with gr.Group():
            gr.Markdown('## 2. 声の設定')
            role = gr.Dropdown(label='話者ID')
            voices = gr.Textbox(label='参照WAV割り当て', interactive=False)
            upload = gr.File(label='参照WAV', type='filepath')
            assign_button = gr.Button('参照WAVを割り当て')
            reference_audio = gr.Audio(label='参照音声')
            sample_text = gr.Textbox(label='試作の読み上げ文', value='こんにちは。今日はどのようなお話をいたしましょうか。')
            caption = gr.Textbox(label='試作する声の説明')
            sample_button = gr.Button('声を試作')
            sample_audio = gr.Audio(label='試作音声')
            adopt_sample_button = gr.Button('試作を話者の参照音声に採用')
        with gr.Group():
            gr.Markdown('## 3. 生成・試聴・採用')
            seed = gr.Number(label='seed', value=314, precision=0)
            steps = gr.Slider(1, 200, value=40, step=1, label='steps')
            acting = gr.Checkbox(label='演技を反映')
            emotion = gr.Checkbox(label='感情を反映', value=True)
            narrator = gr.Checkbox(label='地の文にも感情を反映')
            pause = gr.Slider(0, 60000, value=280, step=1, label='共通休止時間 ms')
            settings = [seed, steps, acting, emotion, narrator, pause]
            inspect_button = gr.Button('生成計画を更新')
            table = gr.Dataframe(headers=['生成単位', '発話', '話者', '感情', '原文', '読み上げ文', '演技', '休止ms', '採用', '候補'], interactive=False)
            selected = gr.Dropdown(label='対象TTS生成単位')
            group = gr.Checkbox(label='同じ発話の全片をまとめて操作', value=False)
            accepted_audio = gr.Audio(label='採用済み音声')
            candidate_audio = gr.Audio(label='最新候補')
            listen = gr.Button('対象の音声を表示')
            regenerate_button = gr.Button('新しい候補を生成')
            adopt_button = gr.Button('採用')
            discard_button = gr.Button('候補を破棄')
        with gr.Group():
            gr.Markdown('## 4. 出力')
            generate_button = gr.Button('全編生成（未採用の単位を生成・採用）')
            destination = gr.Textbox(label='Drive保存先（空欄なら一時領域のみ）')
            restore_button = gr.Button('この保存先から採用・候補状態を復元')
            output_button = gr.Button('完成WAV再結合・出力')
            master = gr.Audio(label='完成WAV')
            download = gr.File(label='完成WAV保存')
            individual = gr.File(label='個別WAV ZIP')
        queue = dict(concurrency_id='koebuta-v2', concurrency_limit=1)
        load_button.click(load, [state, archive, folder], [status, role, *settings, voices, table, selected, state], **queue)
        inspect_button.click(inspect, [state, *settings], [table, selected, status, state], **queue)
        assign_button.click(assign, [state, role, upload], [voices, reference_audio, state], **queue)
        sample_button.click(sample, [state, sample_text, caption, seed, steps], [sample_audio, state], **queue)
        adopt_sample_button.click(adopt_sample, [state, role], [voices, state], **queue)
        listen.click(select, [state, selected], [accepted_audio, candidate_audio, state], **queue)
        regenerate_button.click(regenerate, [state, selected, group, *settings], [table, status, state], **queue)
        adopt_button.click(adopt, [state, selected, group], [table, status, state], **queue)
        discard_button.click(discard, [state, selected, group], [table, status, state], **queue)
        generate_button.click(generate, [state, *settings], [table, status, state], **queue)
        output_button.click(output, [state, destination, *settings], [master, download, individual, status, state], **queue)
        restore_button.click(restore, [state, destination], [status, state], **queue)
    return demo
