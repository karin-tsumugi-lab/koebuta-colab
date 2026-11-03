import contextlib
import copy
import io
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import wave

from irodori_cli.auto_reference import prepare_references, reference_plan, verify_references, final_speech_plan
from irodori_cli.core import atomic_json, digest, file_hash, new_project, normalize_project, read_json, sampling_plan
from irodori_cli.jobs import generate
from irodori_generate import load_inputs, main


NORMAL = '今日は窓のそばに座って、庭に咲いている花をゆっくり眺めていました。'


def wav(path, value=0):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        stream.writeframes(value.to_bytes(2, 'little') * 240)


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scenario = self.root / 'scenario.json'
        self.settings = self.root / 'settings.json'
        self.job = self.root / 'job'
        atomic_json(self.scenario, {'schema_version': 1,
            'speakers': {'a': {'name': 'A', 'voice_caption': '落ち着いた低い声。'},
                         'b': {'name': 'B', 'voice_caption': '明るい高い声。'}},
            'segments': [{'id': 'a1', 'speaker_id': 'a', 'text': '助けて！', 'emotion': 'fear'},
                         {'id': 'a2', 'speaker_id': 'a', 'text': NORMAL},
                         {'id': 'b1', 'speaker_id': 'b', 'text': 'そうですね。'}]})
        atomic_json(self.settings, {'reading': 'cast'})
        self.calls = []
        self.engine = {'model_revision': 'pinned-model', 'codec_revision': 'pinned-codec', 'upstream': 'pinned-code'}

    def infer(self, request, destination):
        self.calls.append(copy.deepcopy(request))
        wav(destination, len(self.calls))

    def load(self):
        return load_inputs(self.scenario, self.settings)

    def test_scream_first_selects_later_neutral_without_emotion_or_acting(self):
        project, voices, plan = self.load()
        effective, groups = reference_plan(project, voices)
        a, b = groups
        self.assertEqual(a['segment'], 'a2')
        self.assertEqual(a['request']['text'], NORMAL)
        self.assertTrue(a['request']['no_ref'])
        self.assertEqual(a['request']['caption'], '落ち着いた低い声。')
        self.assertEqual(b['mode'], 'fallback')
        self.assertEqual(plan[0]['fingerprint'], None)
        self.assertFalse(self.job.exists())
        with self.assertRaises(ValueError): sampling_plan(project, voices)

    def test_prepare_then_clone_every_original_utterance_in_order(self):
        project, voices, _ = self.load()
        before = copy.deepcopy(project)
        effective, resolved, contexts = prepare_references(project, voices, self.job, self.infer, self.engine)
        plan = sampling_plan(effective, resolved)
        self.assertEqual([r['id'] for r in plan], ['a1', 'a2', 'b1'])
        self.assertEqual([r['request']['no_ref'] for r in plan], [False, False, True])
        self.assertTrue(plan[0]['request']['text'].startswith('😱'))
        self.assertEqual(plan[1]['request']['text'], NORMAL)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(project, before)
        self.assertEqual(verify_references(self.job), 1)

    def test_explicit_wav_wins_and_missing_or_corrupt_file_is_rejected(self):
        reference = self.root / 'reference.wav'
        wav(reference)
        atomic_json(self.settings, {'reading': 'cast', 'voiceMode': 'clone',
            'speakerVoices': {'a': 'provided'}, 'voices': {'provided': 'reference.wav'}})
        project, voices, plan = self.load()
        self.assertEqual(reference_plan(project, voices)[1][0]['mode'], 'supplied')
        self.assertEqual(plan[0]['reference']['sha256'], file_hash(reference))
        reference.write_bytes(b'not a wav')
        with self.assertRaises(ValueError): self.load()
        reference.unlink()
        with self.assertRaises(FileNotFoundError): self.load()

    def test_explicit_design_and_role_design_opt_out(self):
        atomic_json(self.settings, {'reading': 'cast', 'voiceMode': 'design'})
        project, voices, plan = self.load()
        self.assertTrue(all(r['request']['no_ref'] for r in plan))
        self.assertFalse(any(g['mode'] == 'automatic' for g in reference_plan(project, voices)[1]))
        atomic_json(self.settings, {'reading': 'cast', 'speakerVoices': {'a': 'design'}})
        self.assertTrue(all(r['request']['no_ref'] for r in self.load()[2]))

    def test_all_short_fallback_and_single_long_utterance(self):
        raw = read_json(self.scenario)
        raw['segments'][1]['text'] = 'こんにちは。'
        raw['segments'][2]['text'] = NORMAL
        atomic_json(self.scenario, raw)
        project, voices, plan = self.load()
        self.assertTrue(all(r['request']['no_ref'] for r in plan))
        self.assertEqual([g['mode'] for g in reference_plan(project, voices)[1]], ['fallback', 'fallback'])

    def test_shared_one_group_and_explicit_shared_overrides_per_speaker(self):
        atomic_json(self.settings, {'reading': 'shared'})
        project, voices, plan = self.load()
        groups = reference_plan(project, voices)[1]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['group'], 'shared')
        self.assertTrue(all(r['reference']['pending'] for r in plan))
        wav(self.root / 'reference.wav')
        atomic_json(self.settings, {'reading': 'shared', 'speakerVoices': {'a': 'other'},
                                   'voices': {'voice_a': 'reference.wav', 'other': 'reference.wav'}})
        project, voices, plan = self.load()
        self.assertEqual(set(voices), {'voice_a'})
        self.assertTrue(all(r['reference']['profile'] == 'voice_a' for r in plan))

    def test_shared_partial_assignments_are_conflicts_even_with_yes(self):
        atomic_json(self.settings, {'reading': 'shared', 'speakerVoices': {'a': 'a'}})
        with patch('irodori_generate.run_logged') as remote:
            with self.assertRaises(ValueError): main(self.args('--yes'))
            remote.assert_not_called()
        self.assertFalse((self.root / 'out').exists())

    def test_repeatable_selection_and_explicit_replacement(self):
        raw = read_json(self.scenario)
        raw['segments'].append({'id': 'a3', 'speaker_id': 'a', 'text': NORMAL + 'そう思います。'})
        atomic_json(self.scenario, raw)
        project, voices, _ = self.load()
        a = reference_plan(project, voices)[1][0]
        self.assertEqual(a, reference_plan(normalize_project(project), voices)[1][0])
        atomic_json(self.settings, {'reading': 'cast', 'autoReferenceSegments': {'a': 'a3'}})
        project, voices, _ = self.load()
        self.assertEqual(reference_plan(project, voices)[1][0]['segment'], 'a3')
        atomic_json(self.settings, {'reading': 'cast', 'autoReferenceSegments': {'a': 'a1'}})
        with self.assertRaises(ValueError): self.load()

    def test_resume_reuses_and_pause_only_edits_reuse(self):
        project, voices, _ = self.load()
        one, resolved, _ = prepare_references(project, voices, self.job, self.infer, self.engine)
        original = read_json(self.job / 'references.json')
        project['pause'] = .8
        project['segments'][1]['pause_after_ms'] = 900
        two, again, _ = prepare_references(project, voices, self.job, self.infer, self.engine)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(original, read_json(self.job / 'references.json'))
        self.assertEqual([r['fingerprint'] for r in sampling_plan(one, resolved)],
                         [r['fingerprint'] for r in sampling_plan(two, again)])

    def test_changes_rebuild_references_preserve_old_wav_and_invalidate_dependents(self):
        for change in ('caption', 'text', 'seed', 'engine'):
            with self.subTest(change=change):
                project, voices, _ = self.load()
                job = self.root / change
                effective, resolved, contexts = prepare_references(project, voices, job, self.infer, self.engine)
                old_plan = sampling_plan(effective, resolved)
                old_file = Path(next(iter(resolved.values())))
                engine = dict(self.engine)
                if change == 'caption': project['roles'][0]['caption'] += '少し柔らかい声。'
                if change == 'text': project['segments'][1]['text'] += 'そう感じました。'
                if change == 'seed': project['seed'] += 1
                if change == 'engine': engine['model_revision'] = 'other-pinned-model'
                effective, resolved, next_contexts = prepare_references(project, voices, job, self.infer, engine)
                new_plan = sampling_plan(effective, resolved)
                self.assertNotEqual(contexts, next_contexts)
                self.assertNotEqual(old_plan[0]['fingerprint'], new_plan[0]['fingerprint'])
                self.assertTrue(old_file.exists())

    def test_corrupt_saved_reference_fails_without_regeneration(self):
        project, voices, _ = self.load()
        _, resolved, _ = prepare_references(project, voices, self.job, self.infer, self.engine)
        Path(next(iter(resolved.values()))).write_bytes(b'corrupt')
        with self.assertRaises(ValueError): prepare_references(project, voices, self.job, self.infer, self.engine)
        with self.assertRaises(ValueError): verify_references(self.job)
        self.assertEqual(len(self.calls), 1)

    def test_interrupted_preparation_reuses_committed_group_and_never_runs_speech(self):
        raw = read_json(self.scenario)
        raw['segments'] += [{'id': 'b2', 'speaker_id': 'b', 'text': NORMAL}]
        atomic_json(self.scenario, raw)
        project, voices, _ = self.load()
        calls = []
        def interrupted(request, destination):
            calls.append(request)
            if len(calls) == 2:
                destination.write_bytes(b'incomplete')
                raise KeyboardInterrupt()
            wav(destination)
        with self.assertRaises(KeyboardInterrupt):
            prepare_references(project, voices, self.job, interrupted, self.engine)
        self.assertEqual(len(read_json(self.job / 'references.json')['entries']), 1)
        self.assertFalse(list(self.job.rglob('*.partial.wav')))
        self.assertFalse((self.job / 'job.json').exists())
        prepare_references(project, voices, self.job, self.infer, self.engine)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(verify_references(self.job), 2)

    def test_cpu_full_generation_reuses_takes_and_reassembles_pause(self):
        project, voices, _ = self.load()
        effective, resolved, _ = prepare_references(project, voices, self.job, self.infer, self.engine)
        plan = sampling_plan(effective, resolved)
        manifest = generate(self.job, plan, .28, self.infer)
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(len(self.calls), 4)  # one reference, three original utterances
        first_frames = manifest['combined']['frames']
        manifest = generate(self.job, plan, .5, self.infer)
        self.assertEqual(len(self.calls), 4)
        self.assertGreater(manifest['combined']['frames'], first_frames)

    def test_same_wav_bytes_but_changed_preparation_invalidates_only_dependent_takes(self):
        project, voices, _ = self.load()
        def constant_audio(request, destination):
            self.calls.append(request)
            wav(destination)
        effective, resolved, contexts = prepare_references(project, voices, self.job, constant_audio, self.engine)
        first = final_speech_plan(effective, resolved, contexts, self.engine)
        generate(self.job, first, .28, constant_audio)
        self.assertEqual(len(self.calls), 4)
        project['roles'][0]['caption'] += '優しい声。'
        effective, resolved, contexts = prepare_references(project, voices, self.job, constant_audio, self.engine)
        second = final_speech_plan(effective, resolved, contexts, self.engine)
        self.assertNotEqual(first[0]['fingerprint'], second[0]['fingerprint'])
        self.assertEqual(first[2]['fingerprint'], second[2]['fingerprint'])
        result = generate(self.job, second, .28, constant_audio)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(self.calls), 7)  # new reference and A's two utterances; B reused

    def test_truncated_explicit_wav_fails_before_gpu(self):
        reference = self.root / 'reference.wav'
        wav(reference)
        reference.write_bytes(reference.read_bytes()[:-4])
        atomic_json(self.settings, {'reading': 'cast', 'voices': {'voice_a': 'reference.wav'}})
        with self.assertRaises(ValueError): self.load()

    def test_valid_float_wav_is_not_misclassified_as_corrupt(self):
        import struct
        fmt = struct.pack('<HHIIHH', 3, 1, 24000, 96000, 4, 32)
        body = b'fmt ' + struct.pack('<I', len(fmt)) + fmt + b'data' + struct.pack('<I', 8) + struct.pack('<ff', .1, .2)
        (self.root / 'float.wav').write_bytes(b'RIFF' + struct.pack('<I', len(body) + 4) + b'WAVE' + body)
        atomic_json(self.settings, {'reading': 'cast', 'voices': {'voice_a': 'float.wav'}})
        self.assertEqual(self.load()[2][0]['reference']['sha256'], file_hash(self.root / 'float.wav'))

    def test_reference_metadata_survives_bundle_recovery_and_detects_traversal(self):
        import shutil
        project, voices, _ = self.load()
        prepare_references(project, voices, self.job, self.infer, self.engine)
        recovered = self.root / 'recovered'
        shutil.copytree(self.job, recovered)
        self.assertEqual(verify_references(recovered), 1)
        data = read_json(recovered / 'references.json')
        data['entries']['a']['file'] = '../outside.wav'
        atomic_json(recovered / 'references.json', data)
        with self.assertRaises(ValueError): verify_references(recovered)

    def test_real_worker_flow_prepares_before_speech_and_reuses_resident_runtime(self):
        """Exercise worker orchestration with a CPU backend replacing ML imports."""
        from irodori_cli import worker
        from irodori_cli.environments import IRODORI_COMMIT
        checkpoint = self.root / 'model.bin'
        checkpoint.write_bytes(b'cpu-test-model')
        project, _, _ = self.load()
        project_path = self.root / 'project.json'
        atomic_json(project_path, project)
        requests = []
        instances = []
        class Tensor:
            size = 240
            def detach(self): return self
            def cpu(self): return self
            def float(self): return self
            def view(self, *args): return self
            def numpy(self): return self
        class Request:
            def __init__(self, text, caption, no_ref, num_steps, seed, max_seconds=None,
                         ref_wav=None, max_ref_seconds=None):
                self.__dict__.update(locals())
                self.__dict__.pop('self')
        class Runtime:
            @classmethod
            def from_key(cls, key):
                instances.append(cls())
                return instances[-1]
            def synthesize(self, request):
                requests.append(request)
                return types.SimpleNamespace(audios=[Tensor()], sample_rate=24000)
        backend = types.SimpleNamespace(InferenceRuntime=Runtime,
                                        RuntimeKey=lambda **kw: kw, SamplingRequest=Request)
        fake_modules = {
            'huggingface_hub': types.SimpleNamespace(hf_hub_download=lambda *a, **kw: str(checkpoint)),
            'numpy': types.SimpleNamespace(isfinite=lambda x: types.SimpleNamespace(all=lambda: True)),
            'soundfile': types.SimpleNamespace(write=lambda path, *a, **kw: wav(path)),
            'irodori_tts': types.ModuleType('irodori_tts'),
            'irodori_tts.inference_runtime': backend}
        args = types.SimpleNamespace(project=str(project_path), job=str(self.job), voice=[], ids=None, regenerate=False)
        runtimes = {}
        with patch.dict('sys.modules', fake_modules), \
                patch('importlib.metadata.version', return_value='cpu-test'), \
                patch('irodori_cli.worker.subprocess.check_output', return_value=IRODORI_COMMIT), \
                patch('irodori_cli.worker.memory', return_value={}), \
                patch('irodori_cli.tts_dependencies.pinned_watermark_backend', side_effect=contextlib.nullcontext), \
                patch('irodori_cli.tts_dependencies.pinned_text_tokenizers', side_effect=contextlib.nullcontext), \
                patch('irodori_cli.tts_dependencies.require_watermark'), \
                patch.dict('os.environ', {}, clear=False):
            worker.synthesize(args, runtimes)
            worker.synthesize(args, runtimes)
        self.assertEqual(len(instances), 1)
        self.assertEqual(len(requests), 4)
        self.assertEqual([r.no_ref for r in requests], [True, False, False, True])
        self.assertEqual(requests[0].text, NORMAL)
        self.assertTrue(Path(requests[1].ref_wav).is_file())
        self.assertEqual(requests[1].ref_wav, requests[2].ref_wav)
        self.assertEqual(read_json(self.job / 'job.json')['status'], 'complete')
        self.assertEqual(verify_references(self.job), 1)

    def args(self, *extra):
        return ['--scenario', str(self.scenario), '--settings', str(self.settings),
                '--session', 'test', '--job', 'test', '--out', str(self.root / 'out'), *extra]

    def test_dry_run_never_prompts_connects_or_writes_and_originals_unchanged(self):
        before = self.scenario.read_bytes(), self.settings.read_bytes()
        with patch('builtins.input') as prompt, patch('irodori_generate.run_logged') as remote, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(self.args('--dry-run')), 0)
            prompt.assert_not_called()
            remote.assert_not_called()
        self.assertFalse((self.root / 'out').exists())
        self.assertEqual(before, (self.scenario.read_bytes(), self.settings.read_bytes()))

    def test_decline_and_eof_leave_no_side_effects(self):
        for answer in ('n', '', 'yes', EOFError()):
            with self.subTest(answer=answer), patch('irodori_generate.sys.stdin.isatty', return_value=True), \
                    patch('builtins.input', side_effect=answer if isinstance(answer, Exception) else None,
                          return_value=answer), patch('irodori_generate.run_logged') as remote, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(self.args()), 0)
                remote.assert_not_called()
                self.assertFalse((self.root / 'out').exists())

    def test_one_yes_prompt_before_remote_work(self):
        with patch('irodori_generate.sys.stdin.isatty', return_value=True), \
                patch('builtins.input', return_value='y') as prompt, \
                patch('irodori_generate.run_logged', side_effect=RuntimeError('test stops before remote')) as remote, \
                patch('irodori_generate.read_usage', side_effect=AssertionError('must not query usage')), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError): main(self.args('--no-usage'))
            prompt.assert_called_once()
            remote.assert_called_once()

    def test_noninteractive_requires_yes_or_config(self):
        from irodori_generate import confirm_generation
        summary = {'utterances': 1, 'automatic_references': [], 'potential_rebuild_utterances': 0, 'resume_policy': ''}
        with patch('irodori_generate.sys.stdin.isatty', return_value=False), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError): main(self.args())
            self.assertTrue(confirm_generation(summary, assume_yes=True))
            self.assertTrue(confirm_generation(summary, enabled=False))
        self.assertFalse((self.root / 'out').exists())

    def test_invalid_settings_cannot_be_bypassed(self):
        for config in ({'confirm': 'false'}, {'autoReference': 1},
                       {'autoReference': False, 'autoReferenceSegments': {'a': 'a2'}},
                       {'autoReferenceSegments': {'unknown': 'a2'}}):
            with self.subTest(config=config):
                atomic_json(self.settings, config)
                with self.assertRaises(ValueError): self.load()

    def test_confirm_false_bypasses_prompt_but_not_validation(self):
        atomic_json(self.settings, {'reading': 'cast', 'confirm': False})
        with patch('irodori_generate.sys.stdin.isatty', return_value=False), \
                patch('builtins.input') as prompt, \
                patch('irodori_generate.run_logged', side_effect=RuntimeError('CPU test stops before remote')) as remote, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError): main(self.args('--no-usage'))
            prompt.assert_not_called()
            remote.assert_called_once()

    def test_disabling_automatic_reference_keeps_strict_clone(self):
        atomic_json(self.settings, {'reading': 'cast', 'voiceMode': 'clone', 'autoReference': False})
        with self.assertRaises(ValueError): self.load()


if __name__ == '__main__':
    unittest.main()
