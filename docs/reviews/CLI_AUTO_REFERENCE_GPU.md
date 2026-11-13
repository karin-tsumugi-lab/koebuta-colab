# Short CLI reference matrix: real T4 observations

Date: 2026-11-03 JST. Tested implementation: `db3c58d6434c83ba194afec96f7e6d1d451e7c23`.
User requested real generation for configured, unconfigured and mixed speakers.
Original reference files were already authorized for this Colab test workflow.

## Commands/results

Host: Windows Python 3.14, existing authenticated Colab CLI in WSL Ubuntu-26.04.
Model: `Aratako/Irodori-TTS-v4.1-Small`; 40 steps; seed 314; cast reading;
emotion/acting enabled. Actual GPU: T4 / Standard. One dedicated runtime,
`cli-auto-ref-20261103`, reused for all cases; no unrelated runtime stopped.

Common command (paths are local test artifacts):

```text
python -X utf8 cli/irodori_generate.py --scenario <scenario.json> --settings <case_settings.json> --session cli-auto-ref-20261103 --job <case_job> --out <fresh_case_output> --yes --timeout 1800
```

First case: `--new --gpu T4`. Later cases: `--skip-prepare`.
Last case: additionally `--stop-after-download`.
Exact argument arrays are recorded per case, not reconstructed from shell text.

| Case | Exit | Main utterances | Generated references | Output seconds | Entry elapsed seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Both speakers assigned a WAV | 0 | 4 | 0 | 14.64 | 267.916 |
| Neither speaker assigned a WAV | 0 | 4 | 2 | 25.24 | 60.960 |
| A assigned, B omitted | 0 | 4 | 1 | 14.76 | 72.104 |

Entry elapsed times include transfer, observations, recovery and, for the first
case, fresh environment/model preparation; the last includes shutdown. These are
not isolated model-inference comparisons. Summed main-take inference times were
52.426 / 16.748 / 12.251 seconds; automatic-reference inference is additional.

## Requirement-to-observation evidence

- Same self-authored four-utterance scenario used for all cases: A1, B1, A2, B2.
  Two neutral sentences establish references; A2 includes joy and acting.
- Supplied WAV hashes remain the actual references for all configured speakers.
  Original source reference files remain byte-for-byte unchanged.
- Unconfigured case saves two verified reference WAVs and metadata (A and B).
  Mixed case saves only B's reference. Reference requests use plain selected text,
  no reference, and voice captions. Main plan contains four clone requests in the
  original order, including the selected lines, with actual reference hashes and
  final fingerprints.
- Final WAVs, take files, hashes and frames pass `verify_recovery`. References
  pass `verify_references` and are also exported alongside final audio.
- Both later jobs' recovered execution logs explicitly report reuse of the
  loaded Irodori runtime. They do not reload a model per speaker or utterance.
- Independently generated B reference WAVs in unconfigured/mixed cases have the
  same hash for this identical seed/text/caption. This single observation is not
  a general cross-hardware determinism guarantee.
- All output signals are nonempty and nonzero PCM16 mono. RMS levels are about
  -17.77 / -16.21 / -16.88 dBFS. Full-scale sample fractions are about
  0.00028% / 0.00091% / 0.00028%; signal statistics do not validate listening quality.
- Last pipeline reports `session_stopped: true`, with identity checked before
  stopping. Only the dedicated test runtime is targeted.

## CU and limitations

Start account balance: 22.76 CU. End observed balance: 22.70 CU. The 0.06-CU
difference is account-wide and sampled, not a measurement of this test alone.
Another assignment appeared during the test. Account usage rate was 2.30 CU/hr
with two assignments and 1.15 CU/hr with one after this runtime stopped.
The first entry's initial CU query timed out; later observations succeeded.

Human listening, pronunciation, speaker similarity and voice consistency are
**not verified**. Real-GPU interrupted-job resume was not exercised here; its
CPU evidence is recorded separately in `CLI_AUTO_REFERENCE_ACCEPTANCE.md`.

Local artifacts in the project workspace: `outputs/cli_auto_reference_gpu_20261103/`:
`scenario.json`, three settings/plan/command files, `execution.json`,
`validation.json`, `audio_observations.json`, per-case logs, recovered jobs,
and `<case>_run/result.wav`. Audio and user reference files are not committed.

## Follow-up from the test

With stdout redirected to a log, the plan was buffered until the end while
stderr progress appeared immediately. The confirmation summary now flushes stdout
before remote work. This is an output-only fix; GPU inference above was performed
on the stated commit, and was not repeated solely for this flush change.
