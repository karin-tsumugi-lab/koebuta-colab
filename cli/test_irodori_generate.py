import contextlib
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

from irodori_cli.core import atomic_json, file_hash, read_json
from irodori_generate import load_inputs, main


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)
        self.scenario = self.root / 'scenario.json'
        self.settings = self.root / 'settings.json'
        self.out = self.root / 'output'
        atomic_json(self.scenario, {'schema_version': 1,
            'speakers': {'assistant': {'name': '案内役', 'kind': 'character'}},
            'segments': [{'id': 't01', 'speaker_id': 'assistant',
                'text': '窓から明るい日差しが差し込んでいますね。',
                'tts_text': '窓から明るい日差しが差し込んでいますね。',
                'emotion': 'joy', 'acting_description': '柔らかく', 'pause_after_ms': 500}]})
        atomic_json(self.settings, {'voiceMode': 'design', 'reading': 'shared', 'acting': True})
        self.calls = []
        self.corrupt = False
        self.incomplete = False
        self.runtime = patch('irodori_generate.read_runtime', return_value={
            'hardware': 'T4', 'shape': 'Standard', 'identity': 'test-endpoint'})
        self.runtime.start(); self.addCleanup(self.runtime.stop)
        self.stopped = patch('irodori_generate.runtime_stopped', return_value=True)
        self.stopped.start(); self.addCleanup(self.stopped.stop)
        self.usage = patch('irodori_generate.read_usage', return_value={
            'balance': 20., 'rate': 2., 'active_assignments': 1, 'scope': 'account'})
        self.usage.start(); self.addCleanup(self.usage.stop)
    def tearDown(self):
        self.tmp.cleanup()
    def args(self, *extra):
        return ['--scenario', str(self.scenario), '--settings', str(self.settings),
                '--session', 'test-session', '--job', 'test-job', '--out', str(self.out), *extra]
    def fake_run(self, command, **kwargs):
        self.calls.append(command)
        if 'synthesize' in command:
            folder = Path(command[command.index('--out') + 1]); recovered = folder / 'run' / 'recovered'
            job = recovered / 'job'; job.mkdir(parents=True)
            with wave.open(str(job / 'take.wav'), 'wb') as stream:
                stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                stream.writeframes(b'\0\0' * 48)
            checksum = file_hash(job / 'take.wav')
            atomic_json(job / 'job.json', {'status': 'partial' if self.incomplete else 'complete',
                'takes': [{'file': 'take.wav', 'sha256': checksum, 'frames': 48}],
                'combined': {'file': 'take.wav', 'sha256': checksum, 'frames': 48,
                             'seconds': .001, 'take_files': ['take.wav']}})
            atomic_json(recovered / 'project.json', read_json(self.out / 'project.json'))
            atomic_json(folder / 'latest.json', {'recovered': str(recovered),
                'receipt': {'job_id': 'test-job', 'action': 'synthesize', 'exit_code': 0, 'ok': True}})
            if self.corrupt:
                with (job / 'take.wav').open('ab') as stream:stream.write(b'changed')
        if 'stop' in command:
            self.assertTrue((self.out / 'result.wav').is_file())
            self.assertEqual(read_json(self.out / 'pipeline.json')['status'], 'complete')
        return subprocess.CompletedProcess(command, 0)
    def invoke(self, *extra):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr), \
             patch('irodori_generate.run_logged', side_effect=lambda command, log, console: self.fake_run(command)), \
             patch('irodori_generate.subprocess.run', side_effect=self.fake_run):
            return main(self.args(*extra))
    def test_dry_run_has_no_colab_or_disk_writes_and_preserves_authored_fields(self):
        with patch('irodori_local.colab_command') as discover:
            self.assertEqual(self.invoke('--dry-run'), 0)
            discover.assert_not_called()
        self.assertFalse(self.out.exists()); self.assertEqual(self.calls, [])
        project, _, plan = load_inputs(self.scenario, self.settings)
        self.assertEqual(project['segments'][0]['emotion'], 'joy')
        self.assertEqual(project['segments'][0]['acting'], '柔らかく')
        self.assertEqual(plan[0]['pause_after_ms'], 500)
        self.assertFalse(project['segments'][0]['reviewed'])
    def test_complete_pipeline_exports_verified_audio_and_only_prepares_tts(self):
        before = self.scenario.read_bytes(), self.settings.read_bytes()
        self.assertEqual(self.invoke('--new'), 0)
        self.assertEqual([c[2] for c in self.calls], ['prepare', 'synthesize'])
        self.assertIn('--new', self.calls[0]); self.assertIn('tts', self.calls[0])
        self.assertIn('--allow-unreviewed', self.calls[1])
        self.assertTrue((self.out / 'result.wav').is_file())
        with zipfile.ZipFile(self.out / 'segments.zip') as archive:self.assertEqual(archive.namelist(), ['take.wav'])
        self.assertEqual(before, (self.scenario.read_bytes(), self.settings.read_bytes()))
        self.assertEqual(read_json(self.out / 'pipeline.json')['status'], 'complete')
    def test_existing_output_is_not_overwritten(self):
        self.out.mkdir()
        with self.assertRaises(FileExistsError):self.invoke()
        self.assertEqual(self.calls, [])
    def test_skip_prepare_and_stop_only_after_verified_export(self):
        with patch('irodori_local.colab_command', return_value=['colab']):
            self.assertEqual(self.invoke('--skip-prepare', '--stop-after-download'), 0)
        self.assertEqual([c[2] if len(c)>2 and c[1].endswith('.py') else c[1] for c in self.calls], ['synthesize', 'stop'])
        self.assertTrue(read_json(self.out / 'pipeline.json')['session_stopped'])
    def test_corrupt_audio_prevents_export_and_stop(self):
        self.corrupt = True
        with self.assertRaises(ValueError):self.invoke('--stop-after-download')
        self.assertFalse((self.out / 'result.wav').exists())
        self.assertEqual(read_json(self.out / 'pipeline.json')['status'], 'failed')
        self.assertFalse(any('stop' in c for c in self.calls))
    def test_partial_audio_is_not_reported_complete(self):
        self.incomplete = True
        with self.assertRaises(ValueError):self.invoke()
        self.assertFalse((self.out / 'result.wav').exists())
    def test_failure_halts_before_synthesis_and_keeps_logs(self):
        with patch('irodori_generate.run_logged', return_value=subprocess.CompletedProcess([], 1)) as run:
            with self.assertRaises(RuntimeError):main(self.args('--new'))
        self.assertEqual(run.call_count, 1)
        self.assertTrue((self.out / 'prepare.log').exists())
        self.assertEqual(read_json(self.out / 'pipeline.json')['status'], 'failed')
    def test_missing_clone_voice_fails_before_launch(self):
        atomic_json(self.settings, {'voiceMode': 'clone'})
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.calls, []); self.assertFalse(self.out.exists())
    def test_settings_relative_voices_and_multiple_speaker_mapping(self):
        (self.root / 'voice.wav').write_bytes(b'reference fixture')
        atomic_json(self.settings, {'voiceMode': 'clone', 'reading': 'cast',
            'speakerVoices': {'assistant': 'voice_b'}, 'voices': {'voice_b': 'voice.wav'}})
        _, voices, plan = load_inputs(self.scenario, self.settings)
        self.assertEqual(voices['voice_b'], str((self.root / 'voice.wav').resolve()))
        self.assertEqual(plan[0]['reference']['profile'], 'voice_b')
    def test_typo_in_settings_is_not_silently_ignored(self):
        atomic_json(self.settings, {'step': 20})
        with self.assertRaises(ValueError):self.invoke('--dry-run')
    def test_new_cannot_skip_prepare(self):
        with self.assertRaises(ValueError):self.invoke('--new', '--skip-prepare')
        self.assertEqual(self.calls, [])

    def test_usage_unavailable_does_not_block_generation_or_fake_zero(self):
        with patch('irodori_generate.read_usage', side_effect=RuntimeError('unavailable')):
            self.assertEqual(self.invoke(), 0)
        telemetry = read_json(self.out / 'telemetry.json')
        self.assertEqual(telemetry['usage_start'], {'available': False})
        self.assertNotIn('account_balance_decrease', telemetry)

    def test_usage_is_account_wide_and_no_usage_flag_skips_all_queries(self):
        with patch('irodori_generate.read_usage') as usage:
            self.assertEqual(self.invoke('--no-usage'), 0)
            usage.assert_not_called()
        self.assertFalse(read_json(self.out / 'telemetry.json')['usage_enabled'])

    def test_cu_difference_uses_measured_account_balances(self):
        samples = [{'balance': value, 'rate': 2., 'active_assignments': 1}
                   for value in (20., 19.8, 19.4)]
        with patch('irodori_generate.read_usage', side_effect=samples):
            self.assertEqual(self.invoke(), 0)
        telemetry = read_json(self.out / 'telemetry.json')
        self.assertEqual(telemetry['scope'], 'account')
        self.assertAlmostEqual(telemetry['account_balance_decrease'], .6)

    def test_recovery_hint_on_failure_never_dispatches_recovery(self):
        def fail(command, log, console):
            folder = Path(command[command.index('--out') + 1]) / 'attempt'
            atomic_json(folder / 'invocation.json', {'protocol': 2, 'job': 'test-job',
                'session': 'test-session', 'action': 'prepare', 'nonce': 'a' * 32})
            return subprocess.CompletedProcess(command, 1)
        with patch('irodori_generate.run_logged', side_effect=fail) as run:
            with self.assertRaises(RuntimeError):main(self.args())
        run.assert_called_once()
        command = read_json(self.out / 'recovery_command.json')
        self.assertEqual(command[2], 'recover')
        self.assertIn('--from-invocation', command)
        self.assertEqual(read_json(self.out / 'pipeline.json')['stage'], 'prepare')

    def test_keyboard_interrupt_records_state_and_returns_130(self):
        with patch('irodori_generate.run_logged', side_effect=KeyboardInterrupt):
            self.assertEqual(main(self.args('--no-usage')), 130)
        state = read_json(self.out / 'pipeline.json')
        self.assertEqual(state['status'], 'interrupted')
        self.assertFalse(state['session_stopped'])

    def test_stop_not_confirmed_preserves_success_with_warning(self):
        with patch('irodori_local.colab_command', return_value=['colab']), \
             patch('irodori_generate.runtime_stopped', return_value=False):
            self.assertEqual(self.invoke('--skip-prepare', '--stop-after-download'), 0)
        state = read_json(self.out / 'pipeline.json')
        self.assertEqual(state['status'], 'complete')
        self.assertFalse(state['session_stopped'])
        self.assertIn('shutdown_error', state)

    def test_replaced_runtime_is_not_stopped(self):
        with patch('irodori_generate.read_runtime', side_effect=[
                {'hardware': 'T4', 'shape': 'Standard', 'identity': 'first'}, {'identity': 'different'}]):
            self.assertEqual(self.invoke('--skip-prepare', '--stop-after-download'), 0)
        self.assertFalse(any('stop' in command for command in self.calls))
        self.assertIn('入れ替わった', read_json(self.out / 'pipeline.json')['shutdown_error'])

    def test_unknown_runtime_identity_preserves_audio_without_sending_stop(self):
        with patch('irodori_generate.read_runtime', side_effect=RuntimeError('status unavailable')), \
             patch('irodori_local.colab_command') as cli:
            self.assertEqual(self.invoke('--skip-prepare', '--stop-after-download'), 0)
        cli.assert_not_called()
        self.assertFalse(any('stop' in command for command in self.calls))
        state = read_json(self.out / 'pipeline.json')
        self.assertEqual(state['status'], 'complete')
        self.assertFalse(state['session_stopped'])
        self.assertIn('識別情報', state['shutdown_error'])
        self.assertIn('AUDIO_READY', self.stdout.getvalue())
        self.assertIn('停止未確認', self.stderr.getvalue())

    def test_stop_time_identity_query_failure_never_sends_stop(self):
        with patch('irodori_generate.read_runtime', side_effect=[
                {'hardware': 'T4', 'shape': 'Standard', 'identity': 'first'}, RuntimeError('status unavailable')]):
            self.assertEqual(self.invoke('--skip-prepare', '--stop-after-download'), 0)
        self.assertFalse(any('stop' in command for command in self.calls))
        state = read_json(self.out / 'pipeline.json')
        self.assertFalse(state['session_stopped'])
        self.assertIn('shutdown_error', state)

    def telemetry_locked(self, path, data):
        if Path(path).name == 'telemetry.json':
            raise PermissionError('telemetry file locked')
        return atomic_json(path, data)

    def test_telemetry_write_failure_throughout_run_does_not_abort_audio(self):
        with patch('irodori_generate.atomic_json', side_effect=self.telemetry_locked):
            self.assertEqual(self.invoke(), 0)
        state = read_json(self.out / 'pipeline.json')
        self.assertEqual(state['status'], 'complete')
        self.assertIn('PermissionError', state['telemetry']['save_error'])
        self.assertTrue((self.out / 'result.wav').is_file())
        self.assertIn('AUDIO_READY', self.stdout.getvalue())
        self.assertEqual(self.stderr.getvalue().count('WARNING: 補助情報'), 1)

    def test_telemetry_write_failure_after_success_keeps_audio_ready_and_stop_result(self):
        def save(path, data):
            state = self.out / 'pipeline.json'
            if Path(path).name == 'telemetry.json' and state.exists() and read_json(state).get('status') == 'complete':
                raise OSError('final telemetry write failed')
            return atomic_json(path, data)
        with patch('irodori_generate.atomic_json', side_effect=save), \
             patch('irodori_local.colab_command', return_value=['colab']):
            self.assertEqual(self.invoke('--stop-after-download'), 0)
        state = read_json(self.out / 'pipeline.json')
        self.assertEqual(state['status'], 'complete')
        self.assertTrue(state['session_stopped'])
        self.assertIn('AUDIO_READY', self.stdout.getvalue())
        self.assertIn('save_error', state['telemetry'])

    def test_telemetry_write_failure_does_not_replace_original_stage_error(self):
        with patch('irodori_generate.atomic_json', side_effect=self.telemetry_locked), \
             patch('irodori_generate.run_logged', return_value=subprocess.CompletedProcess([], 7)), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, '終了コード7'):
                main(self.args())
        state = read_json(self.out / 'pipeline.json')
        self.assertEqual(state['status'], 'failed')
        self.assertIn('終了コード7', state['error'])

    def test_telemetry_write_failure_does_not_replace_interrupt_exit_code(self):
        with patch('irodori_generate.atomic_json', side_effect=self.telemetry_locked), \
             patch('irodori_generate.run_logged', side_effect=KeyboardInterrupt), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(self.args('--no-usage')), 130)
        self.assertEqual(read_json(self.out / 'pipeline.json')['status'], 'interrupted')


if __name__ == '__main__':unittest.main()
