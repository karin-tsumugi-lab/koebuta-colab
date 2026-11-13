# Notebook v2 review actions — 2026-11-03

Input: user-supplied Koebuta_Notebook_v2_review_actions_2026-11-03.md.
Model preload before UI publication is retained. CLI/HTML formats are unchanged.

| Item | Implementation / evidence |
| --- | --- |
| NV2-01 | Accepted-take compatibility compares current content/reference/model with stored seed/steps. Full generation retains compatible accepted takes; explicit regeneration uses current controls. CPU case adopts one part at 999/50 and retains another at 314/40, exports and restores both. Candidate adoption still requires the displayed generation settings to match the candidate. |
| NV2-02 | Raw segment pause/blank-line pause values reject non-integers and values outside 0–60000ms. Output repeats bounds checks and streams PCM plus silence in 65536-frame blocks rather than concatenating a whole book in RAM. Extreme-pause load failure preserves prior project. |
| NV2-03 | Existing state identity must match before any persisted audio is written. Another-work test verifies manifest bytes unchanged. Same-work state manifest updates are intentional; audio blobs remain immutable. Outputs receive unique timestamped names. |
| NV2-04 | Only a mounted /content/drive ancestor earns a Drive-success message. Other paths remain allowed but explicitly report local/nonpersistent saving. CPU local-output case observes this message. Real mount behavior unverified. |
| NV2-05 | Ordinary cache is bounded to latest 32 keys. Current candidates, accepted audio, previous accepted history and references are protected. Unreferenced generated UUID WAVs are reclaimed after a committed manifest; no input files are targets. CPU repeated-seed case checks cache bound and accepted WAV protection. Historical accepted audio is intentionally retained without a bound. |
| NV2-06 | Reference reading follows valid tts_text, segment format, shared default_text_format/textOptions precedence and rejects reading warnings. CPU case observes global aozora format passed to the reading resolver. |
| NV2-08 | Load builds a separate session and commits only after plan success. CPU invalid-pause reload observes old project object retained. New work clears prior trial state. |

Output names: editable title (default upload stem/project directory), kind and
JST timestamp with microseconds; WAV/ZIP share the timestamp. ZIP entries contain
order, sanitized unit ID (part suffix) and speaker ID. Names are filename-safe.

Commands: `python tools/build_notebook_v2.py` compiles every generated code cell.
`python -X utf8 -m unittest -q test_notebook_v2.py test_notebook_v2_ui.py test_inspector_p0.py`
runs 21 CPU tests. Gradio emits existing event-loop ResourceWarnings.
GPU inference, actual Drive mount/permissions/capacity, and live browser behavior
remain unverified. These bounded observations do not constitute stable-release
acceptance; the integration owner and final reviewer retain merge authority.
