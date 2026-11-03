# CLI automatic reference: implementation handoff

Date: 2026-11-03 JST. Branch: `codex/cli-auto-reference`.
Base: `c7ae251` on `codex/notebook-v2`. This is a dependency on the notebook-v2
stream, not a merge of that stream into main. No main or integration-ledger edits.
The integration owner must review the base dependency before integration.

Update: the subsequent [real T4 matrix](CLI_AUTO_REFERENCE_GPU.md) passed all
three short reference conditions. GPU mechanical generation/recovery is now
verified for that scope; listening quality remains unverified.

Subsequent review found and fixed two edge cases: recovery after replacing a
corrupt unused automatic WAV, and original single-utterance detection after TTS
splitting. See [the fix evidence](CLI_AUTO_REFERENCE_REVIEW_FIXES.md).

## Changed interfaces and paths

- `cli/irodori_generate.py`: CLI v1.1.0; `--yes`/`-y`; settings `confirm`,
  `autoReference`, `autoReferenceSegments`; `voiceMode` omission enables automatic
  preparation. Explicit existing clone/design assignments retain their meaning.
- Project JSON: optional `autoReference: {version: 1, selections: {...}}` survives
  normalization/transfer. Existing projects without it retain strict planning.
- `sampling_plan(..., allow_pending=True)` is a planning-only contract. Pending
  references have no final fingerprint. Default planning still rejects pending
  references. Worker prepares actual WAVs before final fingerprints.
- `cli/irodori_cli/auto_reference.py`, `core.py`, `worker.py`, `__main__.py`:
  selection, preparation, immutable metadata, verification, final fingerprints.
- Job/recovered output: `references.json`, `references/*.wav`. Recovery ZIP
  already carries job files; `irodori_colab_cli.py` now verifies references and
  the generation entry exports them alongside finished speech.
- Tests: `test_auto_reference.py`, `test_irodori_generate.py`.
- Docs: `cli/README.md`, `cli/AGENTS.md`, `docs/CLI_AUTO_REFERENCE.md`, and
  `docs/CLI_AUTO_REFERENCE_PLAN.md`. `cli/BUILD.json` is refreshed to current
  repository bytes; historical `DISTRIBUTED_BUILD.json` is unchanged.

## Commands/tests and observed results

- Windows Python 3.14: from `cli/`,
  `python -X utf8 -m unittest test_auto_reference test_irodori_generate test_cli_terminal`:
  **57 passed**. Local `cli-cpu-tests.log`.
- WSL Ubuntu-26.04 Python 3.14: same three modules via `python3 -m unittest`:
  **57 passed**. Local `wsl-cli-cpu-tests.log`.
- Existing root standard-library regression suite:
  `python -X utf8 -c "import sys,tempfile,unittest; from pathlib import Path; tempfile.tempdir=str(Path.cwd()); sys.path.insert(0,str(Path('cli').resolve())); suite=unittest.TestLoader().loadTestsFromNames(['test_inspector_p0','test_notebook_v2']); result=unittest.TextTestRunner(verbosity=1).run(suite); sys.exit(not result.wasSuccessful())"`:
  **16 passed**. Local `root-stdlib-cpu-tests.log`.
- Full root discovery in standard Python: 16 passed; UI module could not import
  because Gradio was absent. An attempt using the existing notebook venv did not
  complete import and was interrupted. UI smoke: **not verified**. No dependency
  installation or notebook modifications were made.
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`:
  passed. CRLF is intentional for original bundled files (`cli/** -text`).
- `cli/BUILD.json`: all listed file hashes checked against current bytes; final
  verification covers 57 files with zero mismatches. No release ZIP has been published.
- Shipped sample `irodori_generate.py --dry-run`: valid JSON with two requests;
  no generation output directory created. Local `outputs/sample-dry-run.json`.
- At initial CPU handoff, Colab/GPU generation and listening were **not run**. CPU worker test substitutes
  model imports with a local fake backend. No Colab connection or CU use.
- After the GPU matrix, the output-only summary flush fix was checked with
  `python -X utf8 -m unittest test_irodori_generate test_auto_reference`:
  **51 passed**. Local `post-gpu-cpu-tests.log`. GPU inference was not repeated
  for the flush-only change.

## Requirement-to-observation evidence

| Requirement | Observation |
| --- | --- |
| Omitted versus explicitly invalid WAV | Missing assignments plan automatic/fallback; missing, corrupt, truncated declared files fail before remote launch. Valid IEEE-float WAV is accepted by container validation. Spoken content is not inspected. |
| Supplied reference/design precedence | Supplied hash survives planning; explicit design and per-role design create no automatic reference. |
| Neutral reference selection | Scream-first fixture selects the later neutral line; deterministic selection and valid manual replacement checked; invalid replacement rejected. |
| Single/all-short fallback | Single long utterance and repeated short utterances remain no-ref, with a consistency warning. |
| Shared reading | One common group covers all actual speech; explicit shared WAV wins; partial per-speaker settings without common WAV fail even with `--yes`. |
| Preparation before final speech | Real worker orchestration with fake backend makes one neutral no-ref call, two clone calls for the multi-line speaker, then the single speaker's no-ref call; second invocation uses the resident runtime and makes no new inference calls. |
| Resume | Committed metadata/WAV verified and reused; interrupt during second speaker's reference leaves first reference reusable and creates no main speech. Temporary WAV is not reusable. |
| Changed conditions | Caption, text, seed, engine changes create a new reference. Even identical fake WAV bytes with changed preparation invalidate dependent speech; unaffected speaker's take remains reusable. Old files remain present. |
| Pause-only changes | Reference reused; speech fingerprints unchanged; existing takes reused and new pause applied during assembly. |
| Recovery | Export contains references and metadata; corrupt recovered reference blocks AUDIO_READY/export/runtime stop. Recovered metadata path traversal is rejected. |
| One confirmation | One `y` prompt precedes remote work; decline, blank, EOF do not create output or launch work. Noninteractive default fails; `--yes`/`confirm: false` skip the prompt, not input errors. |
| Read-only inputs and host dry-run | Original bytes unchanged; no prompt, remote work, output directory, or invented final hash during dry-run. |

## Limits and review status

- The pre-generation host display reports the **maximum** utterances affected by
  automatic reference preparation. Actual remote cache reuse/rebuild counts are
  determined on the worker, not asserted from unavailable host state.
- Resume applies to the same surviving remote job. Restoring an entire job onto
  another Colab runtime is not implemented. First collect state after connection
  loss; do not blindly resubmit a possibly running invocation.
- Neutrality/content and voice consistency need human listening. The selection
  heuristic and CPU test success are not evidence of synthesis quality.
- Acceptance/merge recommendation remains with Sol and the integration owner;
  GPU mechanical evidence is recorded separately. Listening and notebook UI
  smoke remain unverified.
