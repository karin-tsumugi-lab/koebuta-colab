# Notebook v2 generation-only prototype

Open `Koebuta_Colabv2.prototype.ipynb` in Colab and execute from the top on a GPU runtime.
The Notebook embeds its two v2 modules; no checkout of this feature branch is needed
after the Notebook is downloaded. Setup reuses the v1 pinned model/codec revisions
and records the resolved upstream commit. Review the original Colab usage and
licensing documents before using an external WebUI.

1. Optionally enable Drive mounting. Upload a ZIP OR specify a mounted project
   directory containing `scenario.json` and relative reference WAVs. ZIP takes
   priority if both are provided. One enclosing project directory is accepted.
   A standalone scenario `.json` upload is also accepted: it is copied into an
   isolated temporary project and uses the same validation/planning path. Relative
   reference WAVs are not bundled with JSON alone; use automatic voices, manually
   assign WAVs, or use ZIP/Drive for references. Original JSON is never overwritten.
2. Review validation messages and assign missing reference WAVs. Voice design
   generates a trial voice which can be assigned to a speaker without editing JSON.
   Missing WAVs no longer block the plan. Before actual generation, speakers
   with multiple utterances use a neutral 20–100-character line nearest 60
   characters as an automatic reference (excluding !/?/ellipsis and very low
   character variety). This is a heuristic, not semantic recognition of screams.
   Single-utterance speakers or groups without a suitable line use no-reference
   generation with the speaker caption. Automatic references are persisted with
   state and reused after restore. Supplied references take priority.
3. Update the read-only generation plan. Select a unit such as `t010#2`. Check
   the group option to regenerate/adopt/discard all units of that utterance.
   Regeneration creates fresh candidates even with a fixed seed; a deterministic
   model may produce identical samples. Candidates never change accepted audio.
4. Full generation automatically accepts missing or stale units. Existing current
   accepted units are retained. Recombine explicitly to create a new completed
   WAV and sequentially numbered individual WAV ZIP. The final trailing pause is
   omitted, matching v1. Changing only global pause does not invalidate speech.
5. Enter a separate Drive output directory to persist the accepted/candidate
   state and output files. Restore after loading the identical source JSON with
   the same model/codec/upstream identity. Local files remain if saving fails.

Source folders are read-only. Use a separate output folder; do not select the
original project directory as output. Editing stays in the HTML application.
Archive limits: 512 MiB expanded, 4096 entries, 16 MiB scenario JSON; encrypted,
symlink, device, traversal and suspicious high-expansion entries are rejected.

## Implementation and integration

Base: main `0440a2486b81f98b564828ddb31665dd918540f5`, including merged P0 PR #1.
Branch: `codex/notebook-v2`. v1 Notebook and CLI/HTML public formats are unchanged.
The builder copies P0 normalization, validation, pause planning and synthesis;
it replaces the entire editor/UI cell with the v2 UI. Rebuild after changing the
modules using `python tools/build_notebook_v2.py`. Do not edit generated cells.
The integration owner owns `AGENTS.md` and `docs/INTEGRATION_STATUS.md` updates.

## Prototype limitations / verification boundaries

Review follow-up: regeneration/adoption/discard now chain a detail/audio refresh.
Full generation refuses to overwrite pending candidates among missing/stale units;
adopt or discard those candidates first. A dedicated '作業状態を保存' action saves
partial work without requiring a completed WAV. Edited role captions and manual
reference WAV assignments are serialized with the audio state and restored.
Completed output uses the same state-save path. Restoration refreshes plan and
speaker controls. Partial regeneration prepares automatic references only for
the selected speaker group. Seed is emphasized and the randomizer uses a 44px
icon button in the generated Notebook launch CSS.

18 CPU tests pass with added observations for pending-candidate preservation and
partial save/restore including edited caption and copied manual reference WAV.
This test count includes extended existing cases. Browser audio refresh and
44px styling still require live Colab verification; no GPU run was performed.

Startup/UI follow-up: the launch cell calls `load_runtime()` before creating or
publishing the WebUI, with preparation messages in the Notebook output. GPU
memory is held while the UI is open; startup loading failure prevents publication.
Project loading builds the read-only plan automatically without synthesis.
Speaker selection displays ID/name, reference presence and the speaker's
voice_caption; user edits update the in-memory normalized role only, not source
JSON. Edited captions invalidate automatically created references for that voice
group, but explicitly assigned references keep precedence. Seed has an explicit
randomize button (0 through 2147483647); it does not randomize every generation.
CPU tests verify immediate plan rows, caption editing/source-byte preservation,
reference status and random seed bounds. Real GPU preload timing remains unverified.

User-reported Colab observation: generation completed with and without assigned
speaker WAVs. This is user evidence, not an agent GPU reproduction.

Cold-start/progress fix: load the runtime (which establishes the upstream import
path) before importing SamplingRequest, including voice trials and no-ref speech.
Normalize single callback results to one output rather than unpacking a path
string. CPU regression simulates the module being unavailable until runtime
initialization and verifies a playable trial file is returned. Gradio special_args
recognizes Progress on trial, regeneration, full generation and output callbacks.
18 CPU tests pass; generated Notebook cells compile. Progress reports preparation,
unit counts, assembly and saving via Gradio's queue progress overlay. It is not
per-step model progress and does not yet append a persistent streaming log.
Real Colab cold-start and browser progress rendering after this fix remain unverified.

Executed 2026-11-03: Python 3.14, Gradio 6.5.1, CPU only.
`python -X utf8 -m unittest -v test_notebook_v2.py test_notebook_v2_ui.py test_inspector_p0.py`
passed 17 tests. Gradio construction emitted unclosed event-loop ResourceWarnings;
no server was launched. Notebook cells also compile during rebuilding.
Follow-up automatic-reference selection regression: 18 total tests passed.
This extra test observes scream-first avoidance and single-utterance fallback;
automatic no-reference GPU synthesis itself has not been exercised.
The CPU end-to-end test now also executes the no-WAV flow using a mock runtime:
one speaker receives an automatically generated reference, a single-utterance
speaker stays reference-free, and the accepted speech is exported as WAV/ZIP.
Original scenario bytes remain unchanged. Total remains 18 tests (the existing
end-to-end case was extended). No real GPU/model inference was performed.

UI follow-up: compact five-column plan, selection-driven read-only details and
audio comparison, collapsed voice trial controls, purple Soft theme at launch.
The concept mock is not pixel-identical to the Gradio implementation. Speaker
reference assignment is still a textual listing; streaming logs and explicit
separate utterance/unit action buttons remain prototype follow-ups.

Observed specification evidence: the P0 adapter loads an actual scenario and
relative reference WAV; the UI callbacks expose `t010#1` and `t010#2`, generate
mock PCM candidates, leave acceptance empty until explicit adoption, adopt both
units together, and export real PCM WAV/ZIP while original JSON bytes stay equal.
Storage tests observe old candidates unchanged after second-piece failure,
accepted records unchanged after regeneration/discard, cache reuse despite pause
change, forced new file creation, corrupt-file regeneration, and local WAVs
surviving a persistence error. These are bounded CPU observations, not full v2
acceptance or a recommendation to merge as a stable release.

CPU storage tests cover candidate group rollback, adoption/discard/restoration,
cache hit/force regeneration, corrupt cache, Drive failure and ZIP layouts/traversal.
P0 regressions cover its generation boundaries, settings and reference lookup.
UI construction tests verify callback registration and shared serialization only.
Real Colab GPU synthesis, voice design, browser operations, actual Drive mount,
restart restoration and perceptual audio quality need manual validation.

Old accepted WAV blobs remain in the workspace. Old replaced candidate blobs
are currently retained as unreferenced files; only one candidate per unit is
visible/serialized. Garbage collection, streaming long-book concatenation,
resumable progress and independently browsing the ordinary cache are deferred.
Session temporary files live until runtime disposal. Do not treat them as backup.
Drive publication writes immutable blobs before an atomic state manifest; output
WAV and ZIP are each atomic but are not a multi-file transaction.
