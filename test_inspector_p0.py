"""CPU-only compatibility tests for Scenario Inspector v0.1.6 P0.

Run: python -m unittest -v test_inspector_p0.py
The test intentionally does NOT execute notebook setup, Gradio, or synthesis.
"""
import ast
import json
from pathlib import Path
import re
import tempfile
import unittest
from types import SimpleNamespace

NOTEBOOK = Path(__file__).with_name("Koebuta_Colabv1.00.ipynb")
FUNCTIONS = ("checked_relative_wav", "notebook_settings", "check_tts_parts",
             "resolve_pauses", "resolve_project_wavs", "build_plan")


def load_function_namespace():
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    for cell in cells:
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), NOTEBOOK.name, "exec")
    ns = {
        "Path": Path, "PurePosixPath": __import__("pathlib").PurePosixPath,
        "RUBY_FORMATS": {"none", "aozora", "narou", "kakuyomu", "pixiv"},
        "_P0_BOOL_KEYS": ("use_emotion", "use_acting", "narrator_emotion"),
        "_P0_INT_RANGES": {"seed": (0, 2147483647), "steps": (1, 200),
                           "default_pause_ms": (0, 60000),
                           "default_blank_line_pause_ms": (0, 60000)},
        "SEPARATOR_PAUSE_MS": 1200, "EMOTIONS": {"neutral": "😐"},
        "STATE": {"plan_warnings": []}, "is_narrator": lambda r: r["kind"] == "narrator",
        "voice_key": lambda p, r: "shared" if p["reading"] == "shared" else r["id"],
        "require_ready": lambda p: None,
        "split_text": lambda t, limit=140: [t[i:i + limit] for i in range(0, len(t), limit)],
        "reading": lambda t, f: (t, []),
        "sf": SimpleNamespace(info=lambda p: SimpleNamespace(frames=10, channels=1))
    }
    found = set()
    for cell in cells:
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCTIONS:
                isolated = ast.Module(body=[node], type_ignores=[])
                exec(compile(isolated, NOTEBOOK.name, "exec"), ns)
                found.add(node.name)
    if found != set(FUNCTIONS):
        raise AssertionError("missing P0 helpers: " + str(set(FUNCTIONS) - found))
    return ns


class P0CompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = load_function_namespace()

    def sample(self):
        return {
            "reading": "cast",
            "roles": [{"id": "narrator", "kind": "narrator", "name": "地の文",
                       "acting": "", "_extras": {"reference_wav": "voices/narrator.wav"}}],
            "segments": [{"id": "t001", "role": "narrator", "text": "漢字です。次の文。",
                          "tts_text": "かんじです。次の文。", "emotion": "neutral",
                          "segment_type": "speech", "acting": "", "blank_lines_after": 1,
                          "_extras": {"koebuta_tts_parts": ["かんじです。", "次の文。"]}}],
            "_extras": {"koebuta_settings": {"reading_mode": "cast",
                         "default_pause_ms": 280,
                         "default_blank_line_pause_ms": 1200}},
            "baseCaption": "標準"
        }

    def test_parts_exact(self):
        p = self.sample()["segments"][0]
        self.assertEqual(self.api["check_tts_parts"](p), ["かんじです。", "次の文。"])
        p["tts_text"] += "!"
        with self.assertRaises(ValueError):
            self.api["check_tts_parts"](p)

    def test_preserves_two_explicit_units_and_final_pause(self):
        p = self.sample()
        plan = self.api["build_plan"](p, {"narrator": "/dummy/ref.wav"},
            use_acting=False, use_emotion=False, narrator_emotion=False,
            seed=314, steps=40, global_pause_ms=280)
        self.assertEqual([u["text"] for u in plan], ["かんじです。", "次の文。"])
        self.assertEqual([u["unit_id"] for u in plan], ["t001#1", "t001#2"])
        self.assertEqual([u["pause_after_ms"] for u in plan], [0, 1200])

    def test_explicit_zero_and_blank_override(self):
        p = self.sample()
        s = p["segments"][0]
        s["pause_after_ms"] = 0
        self.assertEqual(self.api["resolve_pauses"](p, 280)["t001"], 0)
        del s["pause_after_ms"]
        s["_extras"]["blank_line_pause_ms"] = 500
        self.assertEqual(self.api["resolve_pauses"](p, 280)["t001"], 500)

    def test_setting_validation_and_defaults(self):
        p = self.sample()
        self.assertEqual(self.api["notebook_settings"](p)["reading_mode"], "cast")
        p["_extras"]["koebuta_settings"]["seed"] = True
        with self.assertRaises(ValueError):
            self.api["notebook_settings"](p)
        self.assertEqual(self.api["notebook_settings"]({"_extras": {}}), {})

    def test_wav_rejects_escaping(self):
        for path in ("../secret.wav", "voices/../../secret.wav", "/etc/x.wav",
                     "C:/windows/x.wav", "voices\\x.wav", "voices//x.wav"):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.api["checked_relative_wav"](path)

    def test_project_wav_resolution(self):
        import wave
        p = self.sample()
        with tempfile.TemporaryDirectory() as d:
            voices_dir = Path(d, "voices")
            voices_dir.mkdir()
            with wave.open(str(voices_dir / "narrator.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(b"\0\0" * 10)
            voices, issues = self.api["resolve_project_wavs"](p, d)
            self.assertFalse(issues)
            self.assertTrue(Path(voices["narrator"]).is_file())

    def test_legacy_split_fallback(self):
        p = self.sample()
        del p["segments"][0]["_extras"]["koebuta_tts_parts"]
        plan = self.api["build_plan"](p, {"narrator": "/dummy/ref.wav"},
            use_acting=False, use_emotion=False, narrator_emotion=False,
            seed=314, steps=40, global_pause_ms=280)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["unit_id"], "t001")


if __name__ == "__main__":
    unittest.main()
