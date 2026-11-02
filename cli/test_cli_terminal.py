import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from irodori_cli.terminal import Console, read_runtime, read_usage, run_logged, runtime_stopped


class TerminalTests(unittest.TestCase):
    def test_long_wait_reports_liveness_without_repeating_every_poll(self):
        now = [0.]
        stream = io.StringIO()
        console = Console(clock=lambda: now[0], stream=stream)
        console.progress('PROGRESS IrodoriをGPUへロードしています')
        now[0] = 20
        console.progress('PROGRESS Colab: download')
        self.assertNotIn('待機継続中', stream.getvalue())
        now[0] = 31
        console.progress('PROGRESS Colab: download')
        console.progress('PROGRESS Colab: download')
        self.assertEqual(stream.getvalue().count('待機継続中'), 1)

    def test_eta_excludes_initial_model_load_and_polling_noise(self):
        now = [0.]
        stream = io.StringIO()
        console = Console(clock=lambda: now[0], stream=stream)
        console.progress('PROGRESS 音声生成: 1/10件目を処理中')
        now[0] = 100
        console.progress('PROGRESS IrodoriをGPUへロードしています')
        now[0] = 120
        console.progress('PROGRESS 音声生成: 2/10件目を処理中')
        now[0] = 130
        console.progress('PROGRESS 音声生成: 4/10件目を処理中')
        console.progress('PROGRESS Colab: download')
        console.progress('PROGRESS 音声生成: 4/10件目を処理中')
        text = stream.getvalue()
        self.assertIn('初回計測中', text)
        self.assertEqual(text.count('残り生成 約00:00:35'), 1)
        self.assertNotIn('Colab: download', text)

    def test_real_child_progress_is_visible_and_raw_errors_are_logged(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path = Path(folder) / 'stage.log'
            visible = io.StringIO()
            with path.open('w', encoding='utf-8') as log:
                result = run_logged([sys.executable, '-c',
                    "print('PROGRESS 音声生成: 1/2件目を処理中'); print('RAW_DIAGNOSTIC'); raise SystemExit(7)"],
                    log, Console(stream=visible))
            self.assertEqual(result.returncode, 7)
            self.assertIn('1/2件目', visible.getvalue())
            self.assertNotIn('RAW_DIAGNOSTIC', visible.getvalue())
            self.assertIn('RAW_DIAGNOSTIC', path.read_text(encoding='utf-8'))

    def test_runtime_parser_binds_only_requested_name(self):
        raw = '[test] endpoint-a | Hardware: T4 | Shape: Standard | Variant: GPU | Status: IDLE'
        with patch('irodori_local.colab_command', return_value=['colab']), \
             patch('irodori_cli.terminal.capture', return_value=raw):
            self.assertEqual(read_runtime('test')['identity'], 'endpoint-a')
            with self.assertRaises(RuntimeError):read_runtime('other')

    def test_stop_requires_missing_exact_session_not_just_zero_exit(self):
        with patch('irodori_local.colab_command', return_value=['colab']), \
             patch('irodori_cli.terminal.capture', return_value="[colab] Session 'other' not found."):
            self.assertFalse(runtime_stopped('test'))
        with patch('irodori_local.colab_command', return_value=['colab']), \
             patch('irodori_cli.terminal.capture', return_value="[colab] Session 'test' not found."):
            self.assertTrue(runtime_stopped('test'))

    def test_cu_snapshot_uses_existing_parser_and_marks_account_scope(self):
        with patch('irodori_local.colab_command', return_value=['colab']), \
             patch('irodori_cli.terminal.capture', return_value=
                'Current balance: 20.5 compute units\nUsage rate: 2.0/hr\nActive assignments: 1'):
            sample = read_usage()
        self.assertEqual(sample['balance'], 20.5)
        self.assertEqual(sample['scope'], 'account')
        self.assertIn('checked_at', sample)


if __name__ == '__main__':unittest.main()
