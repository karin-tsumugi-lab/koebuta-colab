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
        def call(state, *args, **kwargs):
            state = state or session()
            token = api['_CTX'].set(api['new_session']())
            try:
                result = fn(state, *args, **kwargs)
                if not isinstance(result, tuple):
                    result = (result,)
                return (*result, state)
            except Exception as exc:
                raise gr.Error(str(exc)) from exc
            finally:
                api['_CTX'].reset(token)
        return call

    def plan(state, seed, steps, acting, emotion, narrator, pause, prepare=False, selected_role=None):
        if state['project'] is None:
            raise ValueError('作品を読み込んでください')
        from notebook_v2 import reference_choices
        import hashlib
        choices = reference_choices(state['project'], api['reading'])
        voices = dict(state['voices'])
        for key, choice in choices.items():
            if key in voices:
                continue
            record = state['store'].references.get(key)
            if record and state['store']._valid(record):
                voices[key] = str(state['store'].root / record['file'])
            elif prepare and choice and (selected_role is None or key == selected_role):
                role = next(r for r in state['project']['roles'] if r['id'] == next(s['role'] for s in state['project']['segments'] if s['id'] == choice[0]))
                unit = dict(text=choice[1], caption=role.get('caption') or state['project'].get('baseCaption') or None,
                            ref_wav=None, no_ref=True, seed=int(seed), num_steps=int(steps))
                path = state['store'].root / (uuid.uuid4().hex + '.wav')
                synthesis(unit, path)
                if not valid_wav(path):
                    raise ValueError('自動参照音声が不正です')
                record = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                              source_segment=choice[0], text=choice[1], seed=int(seed), steps=int(steps))
                state['store'].references[key] = record
                state['store']._save(state['store'].accepted, state['store'].candidates)
                voices[key] = str(path)
            else:
                voices[key] = None
        units = api['build_plan'](state['project'], voices, use_acting=acting,
            use_emotion=emotion, narrator_emotion=narrator, seed=int(seed),
            steps=int(steps), global_pause_ms=int(pause))
        roles = {r['id']: r for r in state['project']['roles']}
        segments = {s['id']: s for s in state['project']['segments']}
        for unit in units:
            key = 'shared' if state['project'].get('reading') == 'shared' else segments[unit['segment_id']]['role']
            unit['ref_wav'] = voices[key]
            unit['no_ref'] = voices[key] is None
            if unit['no_ref']:
                role_caption = roles[segments[unit['segment_id']]['role']].get('caption', '')
                unit['caption'] = '\n'.join(x for x in [role_caption, unit['caption']] if x) or None
        state['plan'] = units
        return units

    def summary(state):
        segments = {s['id']: s for s in state['project']['segments']}
        return [[u['unit_id'], segments[u['segment_id']].get('role'),
                 segments[u['segment_id']]['text'][:45], u['segment_id'],
                 '候補あり' if u['unit_id'] in state['store'].candidates else
                 ('採用済み' if u['unit_id'] in state['store'].accepted else '未生成')] for u in state['plan']]

    def speaker_choices(state):
        project = state['project']
        people = [('shared', '共通の声')] if project.get('reading') == 'shared' else [(r['id'], r['name']) for r in project['roles']]
        result = []
        for key, name in people:
            record = state['store'].references.get(key)
            configured = bool(state['voices'].get(key)) or bool(record and state['store']._valid(record))
            result.append((f"{key} · {name} · 声設定 {'有' if configured else '無'}", key))
        return result

    @guarded
    def role_info(state, role):
        if not state.get('project') or not role:
            return '', gr.update(choices=[], value=None), None
        person = next((r for r in state['project']['roles'] if r['id'] == role), None)
        record = state['store'].references.get(role)
        path = state['voices'].get(role)
        if not path and record and state['store']._valid(record):
            path = str(state['store'].root / record['file'])
        return (person.get('caption', '') if person else state['project'].get('baseCaption', ''),
                gr.update(choices=speaker_choices(state), value=role), path)

    @guarded
    def edit_caption(state, role, value):
        if state.get('project'):
            if role == 'shared':
                state['project']['baseCaption'] = value
            else:
                person = next(r for r in state['project']['roles'] if r['id'] == role)
                person['caption'] = value
            state['store'].references.pop(role, None)
        return ()

    def random_seed():
        import secrets
        return secrets.randbelow(2147483648)

    @guarded
    def details(state, selected):
        unit = next((u for u in state['plan'] if u['unit_id'] == selected), None)
        if unit is None:
            return '', None, None
        segment = next(s for s in state['project']['segments'] if s['id'] == unit['segment_id'])
        store = state['store']
        def audio(records):
            record = records.get(selected)
            return str(store.root / record['file']) if record and store._valid(record) else None
        return (f"{selected}\n話者: {segment['role']} / 感情: {segment['emotion']} / 休止: {unit['pause_after_ms']}ms\n"
                f"読み上げ文: {unit['text']}\n演技・声質: {unit['caption'] or '指定なし'}",
                audio(store.accepted), audio(store.candidates))

    @guarded
    def load(state, archive, folder):
        if archive and Path(archive).suffix.lower() == '.json':
            source = state['root'] / uuid.uuid4().hex
            path = Path(archive)
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError('シナリオJSONが16MiBを超えています')
            atomic_bytes(source / 'scenario.json', path.read_bytes())
        else:
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
        role_choices = speaker_choices(state)
        units = plan(state, config.get('seed', 314), config.get('steps', 40), config.get('use_acting', False),
                     config.get('use_emotion', True), config.get('narrator_emotion', False), config.get('default_pause_ms', 280))
        return (f"発話数: {sum(s.get('segment_type') != 'separator' for s in project['segments'])} / 参照音声数: {len(voices)}\n" + '\n'.join(warnings),
                gr.update(choices=role_choices, value=roles[0] if roles else None),
                config.get('seed', 314), config.get('steps', 40), config.get('use_acting', False),
                config.get('use_emotion', True), config.get('narrator_emotion', False), config.get('default_pause_ms', 280),
                str(voices), summary(state), gr.update(choices=[u['unit_id'] for u in units], value=units[0]['unit_id']))

    def synthesis(unit, path):
        runtime = api['load_runtime']()
        if unit.get('no_ref'):
            from irodori_tts.inference_runtime import SamplingRequest
            result = runtime.synthesize(SamplingRequest(text=unit['text'], caption=unit['caption'],
                    no_ref=True, num_steps=unit['num_steps'], seed=unit['seed']))
            audio, sr = result.audios[0].detach().cpu().float().view(-1).numpy(), int(result.sample_rate)
        else:
            audio, sr = api['synthesize'](unit, runtime)
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
    def regenerate(state, selected, group, seed, steps, acting, emotion, narrator, pause, progress=gr.Progress()):
        settings = (seed, steps, acting, emotion, narrator, pause)
        progress(0, desc='モデル準備・自動参照音声を確認中（初回は時間がかかります）')
        target = targets(state, selected, group)[0]
        segment = next(s for s in state['project']['segments'] if s['id'] == target['segment_id'])
        selected_role = 'shared' if state['project'].get('reading') == 'shared' else segment['role']
        plan(state, *settings, prepare=True, selected_role=selected_role)
        state['store'].regenerate(targets(state, selected, group), synthesis, progress=progress)
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
    def sample(state, text, caption, seed, steps, progress=gr.Progress()):
        unit = dict(text=text, caption=caption or None, ref_wav=None, seed=int(seed), num_steps=int(steps))
        # Voice design is reference-free, matching the v1 runtime request.
        progress(0, desc='モデル準備中（初回は取得・GPU読み込みに時間がかかります）')
        runtime = api['load_runtime']()
        from irodori_tts.inference_runtime import SamplingRequest
        progress(0.5, desc='声の試作を生成中')
        result = runtime.synthesize(SamplingRequest(text=text, caption=caption or None,
                    no_ref=True, num_steps=int(steps), seed=int(seed)))
        target = state['root'] / (uuid.uuid4().hex + '.wav')
        sf.write(str(target), result.audios[0].detach().cpu().float().view(-1).numpy(), int(result.sample_rate), subtype='PCM_16')
        if not valid_wav(target):
            raise ValueError('試作音声が不正です')
        state['sample'] = str(target)
        progress(1, desc='声の試作が完了しました')
        return str(target)

    @guarded
    def adopt_sample(state, role):
        if not state['sample']:
            raise ValueError('声を試作してください')
        state['voices'][role] = state['sample']
        return str(state['voices'])

    @guarded
    def generate(state, seed, steps, acting, emotion, narrator, pause, progress=gr.Progress()):
        settings = (seed, steps, acting, emotion, narrator, pause)
        progress(0, desc='モデル準備・自動参照音声を確認中（初回は時間がかかります）')
        units = plan(state, *settings, prepare=True)
        missing = [u for u in units if u['unit_id'] not in state['store'].accepted
                   or not state['store']._valid(state['store'].accepted[u['unit_id']])
                   or state['store'].accepted[u['unit_id']]['key'] != state['store'].key(u)]
        if missing:
            pending = [u['unit_id'] for u in missing if u['unit_id'] in state['store'].candidates]
            if pending:
                raise ValueError('試聴待ち候補を先に採用または破棄してください: ' + '、'.join(pending))
            state['store'].regenerate(missing, synthesis, force=False, progress=progress)
            state['store'].adopt([u['unit_id'] for u in missing])
        progress(1, desc='全編の音声準備が完了しました')
        return summary(state), '全編の採用済み音声を準備しました。再結合してください'

    @guarded
    def output(state, destination, seed, steps, acting, emotion, narrator, pause, progress=gr.Progress()):
        settings = (seed, steps, acting, emotion, narrator, pause)
        progress(0, desc='採用音声の整合性を確認中')
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
                progress(index / len(units) * 0.8, desc=f"結合・ZIP作成 {index + 1}/{len(units)}")
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
            progress(0.9, desc='Driveへ保存中（一時領域にも保持します）')
            resolved = Path(destination).resolve()
            if resolved == state['source'] or resolved.is_relative_to(state['source']):
                raise ValueError('元作品の保護のため、作品フォルダ外の保存先を指定してください。完成結果は一時領域に保持しています')
            saved_message = save_state(state, destination)[0]
            warning = saved_message if '失敗' in saved_message else None
            try:
                atomic_bytes(Path(destination) / 'narration.wav', target.read_bytes())
                atomic_bytes(Path(destination) / 'individual.zip', zip_path.read_bytes())
            except Exception as exc:
                warning = 'Drive出力保存失敗。一時領域の結果は保持しています: ' + str(exc)
            message += '\n' + (warning or 'Driveへ保存しました')
        progress(1, desc='完成WAV・ZIPの出力が完了しました')
        return str(target), str(target), str(zip_path), message

    @guarded
    def save_state(state, destination):
        import hashlib
        if not state.get('store') or not destination.strip():
            raise ValueError('作品と保存先を指定してください')
        resolved = Path(destination).resolve()
        if resolved == state['source'] or resolved.is_relative_to(state['source']):
            raise ValueError('元作品フォルダ外の保存先を指定してください')
        store = state['store']
        manual = {}
        for role_id, source in state['voices'].items():
            data = Path(source).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            name = 'reference_' + digest + '.wav'
            atomic_bytes(store.root / name, data)
            store.references['manual:' + role_id] = dict(file=name, sha256=digest)
            manual[role_id] = name
        store.session_settings = {'captions': {r['id']: r.get('caption', '') for r in state['project']['roles']},
                                  'baseCaption': state['project'].get('baseCaption', ''), 'manual': manual}
        store._save(store.accepted, store.candidates)
        return store.persist(destination) or '作業途中の候補・採用状態と声の設定を保存しました'

    @guarded
    def restore(state, folder):
        source = CandidateStore(folder, state['store'].identity)
        source.restore()
        warning = source.persist(state['store'].root)
        if warning:
            raise ValueError(warning)
        state['store'].restore()
        saved = state['store'].session_settings
        for person in state['project']['roles']:
            person['caption'] = saved.get('captions', {}).get(person['id'], person.get('caption', ''))
        state['project']['baseCaption'] = saved.get('baseCaption', state['project'].get('baseCaption', ''))
        state['voices'] = {key: str(state['store'].root / name) for key, name in saved.get('manual', {}).items()
                           if Path(name).name == name and valid_wav(state['store'].root / name)}
        return '保存状態を復元しました。生成計画を更新してください'

    with gr.Blocks() as demo:
        state = gr.State(None)
        gr.Markdown('# Koebuta Notebook v2 試作\nシナリオJSONは読み取り専用です。編集はHTML版で行ってください。')
        with gr.Row():
          with gr.Column(scale=1, min_width=400):
            gr.Markdown('## 1. 作品の読み込み')
            archive = gr.File(label='作品ZIP / シナリオJSON（アップロードを優先）', type='filepath', file_types=['.zip', '.json'])
            gr.Markdown('JSON単体では参照WAVは付属しません。声は自動生成または手動で割り当てられます。')
            folder = gr.Textbox(label='マウント済みDrive作品フォルダ')
            load_button = gr.Button('作品を読み込む')
            validation = gr.Textbox(label='構造検証', interactive=False, lines=2)
          with gr.Column(scale=1, min_width=400):
            gr.Markdown('## 2. 声の設定')
            role = gr.Dropdown(label='人物一覧（話者ID・名前・声設定）')
            voices = gr.Textbox(label='参照WAV割り当て', interactive=False)
            with gr.Accordion('参照WAVの割り当て・試聴', open=False):
                upload = gr.File(label='参照WAV', type='filepath')
                assign_button = gr.Button('参照WAVを割り当て')
                reference_audio = gr.Audio(label='参照音声')
            gr.Markdown('WAV未設定でも生成できます。適切な台詞から声を自動作成し、候補がなければ参照なしで生成します。')
            with gr.Accordion('声の試作', open=False):
                sample_text = gr.Textbox(label='試作の読み上げ文', value='こんにちは。今日はどのようなお話をいたしましょうか。')
                caption = gr.Textbox(label='試作する声の説明')
                sample_button = gr.Button('声を試作')
                sample_audio = gr.Audio(label='試作音声')
                adopt_sample_button = gr.Button('試作を話者の参照音声に採用')
        with gr.Group():
            gr.Markdown('## 3. 生成・試聴・採用')
            with gr.Row():
                with gr.Column(scale=1, min_width=250):
                    with gr.Row(equal_height=True):
                        with gr.Column(scale=0, min_width=40):
                            gr.Markdown('**Seed**')
                        random_button = gr.Button('🎲', size='sm', scale=0, min_width=40, elem_id='seed-random')
                    seed = gr.Number(label='Seed', show_label=False, value=314, precision=0)
                steps = gr.Slider(1, 200, value=40, step=1, label='Steps')
                pause = gr.Slider(0, 60000, value=280, step=1, label='共通休止時間 ms')
            with gr.Row():
                acting = gr.Checkbox(label='演技を反映')
                emotion = gr.Checkbox(label='感情を反映', value=True)
                narrator = gr.Checkbox(label='地の文にも感情を反映')
            settings = [seed, steps, acting, emotion, narrator, pause]
            inspect_button = gr.Button('生成計画を更新')
            with gr.Row():
              with gr.Column(scale=1, min_width=400):
                table = gr.Dataframe(headers=['生成単位', '話者', '原文（抜粋）', '発話', '状態'], interactive=False)
              with gr.Column(scale=1, min_width=400):
                selected = gr.Dropdown(label='選択中のTTS生成単位')
                detail = gr.Textbox(label='選択対象の詳細（読み取り専用）', interactive=False, lines=4)
                group = gr.Checkbox(label='同じ発話の全片をまとめて操作', value=False)
                with gr.Row():
                    accepted_audio = gr.Audio(label='採用済み音声')
                    candidate_audio = gr.Audio(label='最新候補')
                with gr.Row():
                    regenerate_button = gr.Button('新しい候補を生成', variant='primary')
                with gr.Row():
                    adopt_button = gr.Button('候補を採用', variant='primary')
                    discard_button = gr.Button('候補を破棄')
                gr.Markdown('未採用候補は、各生成単位につき最新1件です。')
        with gr.Group():
            gr.Markdown('## 4. 出力')
            with gr.Row():
              with gr.Column(scale=3):
                destination = gr.Textbox(label='Drive保存先（空欄なら一時領域のみ）')
                with gr.Row():
                    generate_button = gr.Button('全編生成', variant='primary')
                    output_button = gr.Button('完成WAV再結合・出力')
                    restore_button = gr.Button('保存状態を復元')
                    save_button = gr.Button('作業状態を保存')
                master = gr.Audio(label='完成WAV')
                with gr.Row():
                    download = gr.File(label='完成WAV保存')
                    individual = gr.File(label='個別WAV ZIP')
              with gr.Column(scale=2):
                status = gr.Textbox(label='処理ログ・進捗', interactive=False, lines=8)
        queue = dict(concurrency_id='koebuta-v2', concurrency_limit=1)
        random_button.click(random_seed, [], [seed], **queue)
        save_button.click(save_state, [state, destination], [status, state], **queue)
        role.input(role_info, [state, role], [caption, role, reference_audio, state], **queue)
        caption.input(edit_caption, [state, role, caption], [state], **queue)
        load_button.click(load, [state, archive, folder], [validation, role, *settings, voices, table, selected, state], **queue).then(
            role_info, [state, role], [caption, role, reference_audio, state], **queue)
        inspect_button.click(inspect, [state, *settings], [table, selected, status, state], **queue)
        assign_button.click(assign, [state, role, upload], [voices, reference_audio, state], **queue).then(
            role_info, [state, role], [caption, role, reference_audio, state], **queue)
        sample_button.click(sample, [state, sample_text, caption, seed, steps], [sample_audio, state], **queue)
        adopt_sample_button.click(adopt_sample, [state, role], [voices, state], **queue).then(
            role_info, [state, role], [caption, role, reference_audio, state], **queue)
        selected.change(details, [state, selected], [detail, accepted_audio, candidate_audio, state], **queue)
        for button, fn, inputs in ((regenerate_button, regenerate, [state, selected, group, *settings]),
                                   (adopt_button, adopt, [state, selected, group]),
                                   (discard_button, discard, [state, selected, group])):
            button.click(fn, inputs, [table, status, state], **queue).then(
                details, [state, selected], [detail, accepted_audio, candidate_audio, state], **queue)
        generate_button.click(generate, [state, *settings], [table, status, state], **queue).then(
            role_info, [state, role], [caption, role, reference_audio, state], **queue)
        output_button.click(output, [state, destination, *settings], [master, download, individual, status, state], **queue)
        restore_button.click(restore, [state, destination], [status, state], **queue).then(
            inspect, [state, *settings], [table, selected, status, state], **queue).then(
            role_info, [state, role], [caption, role, reference_audio, state], **queue)
    return demo
