"""Local layout preview only; no GPU or external sharing."""
import sys
from pathlib import Path
from contextvars import ContextVar
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'notebook'))
from notebook_v2_ui import create_v2_ui

if __name__ == '__main__':
    demo = create_v2_ui({'_CTX': ContextVar('preview'), 'new_session': dict})
    demo.launch(server_name='127.0.0.1', server_port=7862, share=False)
