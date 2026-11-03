# Second review and real generation after the fixes

2026-11-03 JST. Reviewed and GPU-tested implementation: `08d301c` on
`codex/cli-auto-reference`. This subsequent record changes documentation only.

## Review and CPU execution

Rechecked active/inactive reference handling, backward metadata compatibility,
public export paths, fragment-to-original ID propagation, repeated normalization
and splitting, worker preparation, and final reference-dependent fingerprints.
No additional actionable findings in this review. This is not a general claim
that every failure mode or long-form workload has been verified.

`python -X utf8 -m unittest test_auto_reference test_irodori_generate test_cli_terminal`
from `cli/`: **63 passed**. Local `second-review-cpu-tests.log`. The two original
review reproductions remain covered by regression tests; their before/after
evidence is in `CLI_AUTO_REFERENCE_REVIEW_FIXES.md`.

## GPU commands/results

Repeated the same short scenario and settings as `CLI_AUTO_REFERENCE_GPU.md`:
two speakers, four original utterances, Small model, 40 steps, seed 314, acting
and emotion enabled. Source scenario checksum matches the prior fixture.
Exact command arrays are in the local `*_command.json` and `execution.json`.

One dedicated new T4 runtime, `cli-auto-ref-recheck-1103`, served all cases.
First command: `--new --gpu T4`; subsequent commands: `--skip-prepare`;
last command: `--stop-after-download`. All use `--yes --timeout 1800`.

| Case | Exit | Active automatic references | Main utterances | WAV seconds | Entry elapsed seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| All WAVs supplied | 0 | 0 | 4 | 14.64 | 238.532 |
| No WAVs supplied | 0 | 2 | 4 | 25.24 | 58.871 |
| Mixed | 0 | 1 | 4 | 14.76 | 64.229 |

First entry includes fresh environment/model preparation; last includes shutdown.
Timings are not an isolated model-inference benchmark.

## Requirement-to-observation evidence

- All three final WAV hashes are identical to the corresponding earlier outputs
  that the user said were fine. This is an observation for these fixed inputs,
  not a cross-hardware determinism guarantee or a new independent listening test.
- Main order, supplied-reference hashes, final speech fingerprints, take WAVs,
  combined WAVs and current reference hashes/frames pass the matrix verifier.
- Recovered projects preserve the expected original-ID mapping. Saved metadata
  records active groups A/B for no-WAV, B for mixed, and no generated reference
  for all-supplied. The export matches those active groups.
- Both later jobs' execution logs explicitly report resident model reuse.
- Nonempty/nonzero PCM16 mono signals confirmed. Audio observations match the
  earlier samples. Human evaluation is limited to the user's earlier feedback.
- Last pipeline reports `session_stopped: true`. Additional status lookup reports
  this dedicated runtime not found. No unrelated session was stopped.
- Account balance samples: 21.84 to 21.76 CU (0.08 difference); rates 0 → 1.15 →
  0 CU/hour; assignments 0 → 1 → 0. These are account-wide sampled observations,
  not exact per-job billing.

Local project artifacts: `outputs/cli_auto_reference_gpu_recheck_20261103/`:
`validation.json`, `audio_observations.json`, `comparison.json`,
`postfix_metadata.json`, command arrays, logs, recovered jobs, final WAVs and
`runtime_after.txt`. Original reference files were not modified. Audio and user
reference files are not committed.

The corrupt-unused-reference and split-single-utterance edge cases are verified
on CPU; this GPU rerun covers the normal three-condition matrix. Full notebook
UI smoke and broad long-form workload testing remain outside this verification.
Final integration/merge remains with Sol and the integration owner.
