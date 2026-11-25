---
license: other
license_name: fish-audio-community-license-1.0
license_link: LICENSE
language:
  - ja
pipeline_tag: text-to-speech
library_name: speech.cpp
base_model:
  - Aratako/Drama-3-Japanese
base_model_relation: quantized
tags:
  - gguf
  - ggml
  - speech.cpp
  - audio.cpp
  - drama3
  - tts
  - speech
  - voice-cloning
  - japanese
  - emotional-speech-generation
  - imatrix
---

# Drama-3-Japanese GGUF for speech.cpp

Built with Fish Audio.

Stratified Japanese `imatrix`-calibrated GGUF quantizations of [Aratako/Drama-3-Japanese](https://huggingface.co/Aratako/Drama-3-Japanese) (based on `fishaudio/s2-pro`), ready for local zero-shot voice cloning and expressive Japanese TTS in [`speech.cpp`](https://github.com/nyosegawa/speech.cpp) and [`audio.cpp`](https://github.com/JarodMica/audio.cpp).

---

## Quick Model Comparison

| Model File | Size | Quantization | Recommended Runtime | Est. Free VRAM (+`~2.40 GiB` reserve) |
| --- | --- | --- | --- | --- |
| `Drama-35B-A3B-Japanese-v3-Q4_K.gguf` | `20.82 GiB` (`22.36 GB`) | Hybrid `Q4_K` experts + `Q8_0`/`F16`/`F32` | Official `speech.cpp` (`v0.11.2+`) Vulkan / CPU | `~23.21 GiB` (full GPU) |
| `Drama-35B-A3B-Japanese-v3-Q5_K.gguf` | `24.57 GiB` (`26.39 GB`) | Hybrid `Q5_K` experts + `Q8_0`/`F16`/`F32` | Official `speech.cpp` (`v0.11.2+`) Vulkan / CPU | `~26.96 GiB` (full GPU) |
| `Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf` | `9.09 GiB` (`9.76 GB`) | `IQ3_XXS` experts + `Q8_0`/`F16`/`F32` | `speech.cpp` (`v0.11.2` + `drama3-speechcpp-fast.patch`) CUDA / Vulkan | `~11.48 GiB` (16–24 GB GPUs) |
| `drama3-japanese-small-IQ3_XXS-audiocpp.gguf` | `9.28 GiB` (`9.96 GB`) | `IQ3_XXS` (`audio.cpp` layout) | `audio.cpp` CUDA | `~11–12 GiB` |

---

## Audio Samples

All samples are unmodified `44.1 kHz` PCM WAV outputs synthesized with `--voice none` (no real-speaker voice cloning).

| Model / Runtime | Prompt | Audio |
| --- | --- | --- |
| `small-IQ3_XXS` (RTX 4090 CUDA Fast Patch, `12.68 s`, `RTFx 4.18`) | 雨が降り出した夜道で、傘を広げた瞬間に遠くから踏切の音が聞こえた。少し迷ってから、私はゆっくりと駅の方へ歩き出した。 | <audio controls preload="none" src="https://huggingface.co/StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf/resolve/main/samples/01_small_iq3_xxs_narration_cuda_fast.wav"></audio> |
| `small-IQ3_XXS` (CUDA, `8.31 s`, Whisper) | [声帯をほとんど鳴らさず、すぐ耳元で息だけの小さな囁き声で話す若い女性。ASMRのように吐息が強く混じる親密な囁き。] [耳元で][囁き]ねえ、少しだけ声を落として。誰にも聞こえないように、今の話を続けよう。 | <audio controls preload="none" src="https://huggingface.co/StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf/resolve/main/samples/02_small_iq3_xxs_whisper_cuda.wav"></audio> |
| `Full Hybrid Q4_K` (Official `speech.cpp v0.11.2` Vulkan, `11.66 s`, `RTFx 1.91`) | [落ち着いた25歳の女性。親密な相手に耳元で優しく囁く。] [囁き]ねえ、そんなに急がないで。[吐息]ちゃんと、こっち見ててね。 | <audio controls preload="none" src="https://huggingface.co/StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf/resolve/main/samples/03_full_q4k_whisper_vulkan.wav"></audio> |
| `Full Hybrid Q5_K` (Official `speech.cpp v0.11.2` Vulkan, `6.08 s`, `RTFx 1.86`) | 深夜の図書館は静かで、ページをめくる音だけが規則正しく響いていた。 | <audio controls preload="none" src="https://huggingface.co/StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf/resolve/main/samples/04_full_q5k_narration_vulkan.wav"></audio> |

---

## Quick Start

### A. Full `Q4_K` / `Q5_K` on Official `speech.cpp` (`v0.11.2+`, Vulkan / CPU)

Keep the matching `.gguf.json` sidecar beside the `.gguf` file (`max_text_tokens: 8192`, `voice_codec: 2cf2ec268a087bd2ad91bfbb6796b0429fb03a73cdb8fd07f445d503e9a14d37`). On Vulkan, export the three `GGML_VK_DISABLE_*` flags:

```bash
export GGML_VK_DISABLE_F16=1
export GGML_VK_DISABLE_COOPMAT=1
export GGML_VK_DISABLE_COOPMAT2=1

# 1. Extract a reusable voice prompt
./build/speech voice Drama-35B-A3B-Japanese-v3-Q4_K.gguf ref.wav \
  --transcript "参照音声の正確な書き起こし" \
  speaker.voice.gguf

# 2. Synthesize Japanese speech on Vulkan
./build/speech tts Drama-35B-A3B-Japanese-v3-Q4_K.gguf \
  --device Vulkan0 \
  --voice speaker.voice.gguf \
  --seed 42 \
  -o out.wav \
  "深夜の図書館は静かで、ページをめくる音だけが規則正しく響いていた。"

# 3. Optional local server
./build/speech serve Drama-35B-A3B-Japanese-v3-Q4_K.gguf \
  --device Vulkan0 \
  --host 127.0.0.1 \
  --port 8080
```

### B. 12–24 GB CUDA GPUs (`Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf` + Fast CUDA Patch)

`drama3-speechcpp-fast.patch` targets `speech.cpp v0.11.2` and delivers ~`2.96×` aggregate CUDA speedup (`drama3-small-speechcpp.patch` provides the minimal `IQ3_XXS` compatibility patch without the CUDA speed optimizations):

```bash
git clone https://github.com/nyosegawa/speech.cpp
cd speech.cpp
git submodule update --init --recursive
git apply /path/to/drama3-speechcpp-fast.patch

cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_CUDA_GRAPHS=ON
cmake --build build --target speech speech-cli -j

SPEECH_DRAMA3_MAX_PAUSE_FRAMES=18 ./build/speech tts \
  Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf \
  --experts-on-cpu=false --voice none --seed 42 \
  -o small_out.wav \
  "深夜の図書館は静かで、ページをめくる音だけが規則正しく響いていた。"
```

### C. `audio.cpp` (`drama3-japanese-small-IQ3_XXS-audiocpp.gguf`)

```bash
AUDIOCPP_DRAMA3_MAX_PAUSE_FRAMES=18 \
AUDIOCPP_DRAMA3_SILENCE_CODES=silence_codes.json \
./audiocpp_cli \
  --task tts \
  --family fish_drama3 \
  --model drama3-japanese-small-IQ3_XXS-audiocpp.gguf \
  --backend cuda \
  --device 0 \
  --session-option fish_drama3.cpu_expert_layers=0 \
  --seed 42 --temperature 0.8 --top-k 30 --top-p 0.85 \
  --text "深夜の図書館は静かで、ページをめくる音だけが規則正しく響いていた。" \
  --out small_audiocpp.wav
```

---

## Important Backend & VRAM Notes

- **Use Vulkan or CPU for Full `Q4_K` / `Q5_K` (Do Not Use CUDA):** Upstream `ggml-cuda` stores `block_q8_1.ds` in FP16, which overflows on `ffn_down_exps` activations and triggers `not finite numbers` assertions on CUDA. Run Full `Q4_K` / `Q5_K` on Vulkan (with all three `GGML_VK_DISABLE_*=1` flags) or CPU (`block_q8_K`), and use `Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf` for CUDA GPUs.
- **VRAM Placement Overhead (`placement.cpp`):** `speech.cpp` adds `~2.40 GiB` of compute/KV reserve (`kComputeBytes = 1536 MiB` + runtime overhead) to weight bytes (`~23.21 GiB` for `Q4_K`, `~26.96 GiB` for `Q5_K`, `~11.48 GiB` for `small-IQ3_XXS`). On desktop 24 GB Windows GPUs with ~19–21 GiB free VRAM, `Q4_K` spills ~6–10 expert layers (`~0.42 GiB`/layer) to CPU rather than fitting all layers on GPU.
- **Voice Cloning & Stage/Emotion Tags:** Reference cloning (`--voice speaker.voice.gguf`) produces noticeably cleaner, more consistent prosody than text-only voice design, especially on whispered or multi-clause prompts. Inline emotion and stage tags follow [TAG_LIST.md](https://huggingface.co/Aratako/Drama-3-Japanese/blob/main/TAG_LIST.md).

---

## Speedup Highlight (`drama3-speechcpp-fast.patch`, RTX 4090 / CUDA 12.8)

Measured with `Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf`, `--experts-on-cpu=false`, and delta VRAM above pre-run idle (`14.697 GiB` desktop peak):

| Case | Base (`RTFx` / Audio / Wall / TTFA / ΔVRAM) | Fast (`RTFx` / Audio / Wall / TTFA / ΔVRAM) | Speedup / ΔVRAM Saved |
| --- | --- | --- | --- |
| `narration` | `1.19` (`5.712 s` / `4.817 s`, `0.403 s`, `+11.63 GiB`) | `3.17` (`2.601 s` / `0.820 s`, `0.280 s`, `+10.87 GiB`)* | `2.68×` / `-0.76 GiB` |
| `clone_jvnv` | `1.26` (`6.223 s` / `4.948 s`, `0.418 s`, `+11.69 GiB`) | `3.68` (`5.759 s` / `1.564 s`, `0.292 s`, `+10.89 GiB`) | `2.93×` / `-0.81 GiB` |
| `pause_clamp` | `1.40` (`13.235 s` / `9.434 s`, `0.321 s`, `+11.60 GiB`) | `4.18` (`12.678 s` / `3.036 s`, `0.283 s`, `+10.90 GiB`) | `2.98×` / `-0.70 GiB` |
| **Aggregate** | `1.31` (`25.170 s` audio total, max `+11.69 GiB`) | **`3.88`** (`21.038 s` audio total, max **`+10.90 GiB`**) | **`2.96×`** / **`-0.79 GiB`** |

*`seed=42` diverged (`2.601 s` vs `5.712 s`). Spot checks: greedy `--top-k 1` (`6.55 s` in `5.674 s`, `RTFx 1.2` -> `7.06 s` in `1.976 s`, `RTFx 3.6`), `seed=43` (`6.50 s` in `1.942 s`, `RTFx 3.3`, `TTFA 0.342 s`), post-hardening GPU pause-clamp (`2.60 s` in `0.923 s`, `RTFx 2.8`, `complete`), CPU fallback `"テストです。"` (`0.84 s` in `3.852 s`, `complete`). Table numbers were recorded on the pre-hardening build; after hardening, `drama3-speechcpp-fast.patch` was rebuilt and spot-checked, while `drama3-small-speechcpp.patch` was checked cleanly via `git apply --check` on `speech.cpp v0.11.2`.

---

<details>
<summary>All Repository Files & SHA-256 Checksums</summary>

Verify downloads locally against [`SHA256SUMS.txt`](SHA256SUMS.txt) and [`SMALL_SHA256SUMS.txt`](SMALL_SHA256SUMS.txt) (`sha256sum -c SHA256SUMS.txt SMALL_SHA256SUMS.txt`):

| File | Size | SHA-256 / Notes |
| --- | --- | --- |
| `Drama-35B-A3B-Japanese-v3-Q4_K.gguf` | `20.82 GiB` (`22,359,473,504` B) | `f624da9d84a5f133f2b0894aa8728ba8c560873d90c019a2bca2321daa8482dd` |
| `Drama-35B-A3B-Japanese-v3-Q5_K.gguf` | `24.57 GiB` (`26,386,005,344` B) | `fde34cca2062e364e1cc2eb89471faf3d3f76a02edcc13972e189d60e30aa28d` |
| `Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf` | `9.09 GiB` (`9,762,406,560` B) | `98edad9311a64ea07524f54f24d6d6db77055a3fe7233f24d3bd4351626d9338` |
| `drama3-japanese-small-IQ3_XXS-audiocpp.gguf` | `9.28 GiB` (`9,962,579,296` B) | `b63be0049b847393f8859d8c8ea860e4d72b276b5b42a9a15548ab11b0ab9e05` |
| `Drama-35B-A3B-Japanese-v3-Q4_K.gguf.json` | `1,629` B | `eb2fd5c62cf0bc32bcca1977c5a5685c50b8baeacc3cb95e093a19f973487db7` |
| `Drama-35B-A3B-Japanese-v3-Q5_K.gguf.json` | `1,629` B | `efc6346823e4ace0ac8cfe8d3d31600de733a85c18b4748fe77dbecc27abcdf1` |
| `Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf.json` | `1,347` B | Sidecar metadata (`speech.cpp` `small` preset) |
| `drama3-speechcpp-fast.patch` | `65,346` B | `1d9c7c25928f1cc9000dd7bb5ff258652911d3cf1537a5847605281ab761e65f` |
| `drama3-small-speechcpp.patch` | `27,184` B | `b25a15d62b76e064b6c2270fcfac76f4307ca35cb9e2b13f4feaee1a1a1b3059` |
| `silence_codes.json` | `1,247` B | `3b07eb0fc1c09c7b1cbbcb061fa5290b9a8b0a84b7f23d92a69d7b6b5f7803b3` |
| `LICENSE-SPEECH-CPP` | `1,067` B | `688f8aca0abe167966d277ed00bd594a5a51b028a4fbc1516ff9de7ef05c521a` |
| `LICENSE` | Upstream text | Fish Audio Community License 1.0 |
| `NOTICE` | `4,664` B | Required license notices & attribution boundaries |
| `TAG_LIST.md` | Tag reference | Expressive & stage tags from `Aratako/Drama-3-Japanese` |
| `SHA256SUMS.txt` | `418` B | Checksums for Full `Q4_K` / `Q5_K` GGUFs & `.gguf.json` |
| `SMALL_SHA256SUMS.txt` | Small sums | Checksums for `small` GGUFs, patches, `LICENSE-SPEECH-CPP`, `silence_codes.json` |
| `samples/01_small_iq3_xxs_narration_cuda_fast.wav` | `1,118,252` B | `f53e63ee51f73d82d52bc9bf81cfdf3a651e8e6be8daab04c7c2ebffaae5472c` |
| `samples/02_small_iq3_xxs_whisper_cuda.wav` | `733,228` B | `f8884031390c0143335258e59d7123b5a22b0491c3f5a1536bf8937f36195e10` |
| `samples/03_full_q4k_whisper_vulkan.wav` | `1,028,140` B | `6069101ad2eef61a329134ee371c37b1bdc93cc08df142b5c3ef34a567c6634a` |
| `samples/04_full_q5k_narration_vulkan.wav` | `536,620` B | `0ef0bbb66b04d6b42c18bd8ecb463e43e83120671cb7b19e0653e5d9c986831e` |

</details>

<details>
<summary>Conversion, Tensor Precision & 9-Run Verification Logs</summary>

### Stratified Japanese `imatrix` Calibration

- Calibrated in **BF16** across **300 stratified Japanese sequences** drawn from JSUT and JVNV (`10,240` expert layers/groups; `840` low-hit entries `<8` shrunk toward layer mean; `391` zero-hit entries smoothed).
- Captured extreme activation dynamic range in `ffn_down_exps` (channel-wise `mean(x²)` up to `6.77×10⁸`), protecting MoE routing and sensitive non-expert tensors during quantization.

### Hybrid Tensor Precision Breakdown (`1,531` tensors/file in Full GGUFs)

- **Routed Experts (`Q4_K` `18.12 GB` `file_type=14` / `Q5_K` `22.15 GB` `file_type=16`):** Routed MoE expert FFN projections.
- **`Q8_0` (`3.34 GB`):** Attention (`attn_*`), SSM linear/output projections (`ssm_in_qkv`, `ssm_in_z`, `ssm_out`), embeddings, `4,097`-row semantic `output` head, shared experts (`ffn_*_shexp`), and adapter layers (`ad.*`).
- **`F16` (`781.8 MB`):** Audio codec convolutions and matrices.
- **`F32` (`107.1 MB`):** Layer norms, MoE routers, `ffn_gate_inp_shexp`, SSM state/gate parameters (`ssm_in_a`, `ssm_in_b`, `ssm_conv1d`, `ssm_dt_bias`, `ssm_a_log`, `ssm_norm`), codec codebooks, and biases.

### Unpatched `speech.cpp v0.11.2` Verification (RTX PRO 6000 Blackwell `96 GB`, 9/9 `complete`)

All 9 runs produced finite `44100 Hz` PCM with `clip_pct == 0.0` (`--device Vulkan1` with all three `GGML_VK_DISABLE_*=1` flags, plus CPU fallback check):

| Model | Case | Audio | Wall | `RTFx` | `TTFA` | Peak VRAM (+Delta) | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `Q4_K` | `narration` (`Vulkan1`) | `6.22 s` | `3.288 s` | `1.89` | `0.608 s` | `23.125 GiB` (`+23.065 GiB`) | `RMS 0.05690`, clean delivery |
| `Q4_K` | `design_whisper` (`Vulkan1`) | `11.66 s` | `6.105 s` | `1.91` | `0.762 s` | `23.127 GiB` (`+23.067 GiB`) | `RMS 0.02491`, spoke both clauses cleanly |
| `Q4_K` | `clone_jvnv` (`Vulkan1`) | `6.50 s` | `3.950 s` | `1.65` | `1.137 s` | `23.163 GiB` (`+23.104 GiB`) | `RMS 0.02279` |
| `Q4_K` | `clone_jvnv_expressive` (`Vulkan1`) | `3.34 s` | `2.101 s` | `1.59` | `0.705 s` | `23.158 GiB` (`+23.099 GiB`) | `RMS 0.02501` |
| `Q4_K` | `cpu_check` (`CPU`) | `3.76 s` | `16.072 s` | `0.234` | `1.326 s` | — | `RMS 0.14631`, clean CPU fallback |
| `Q5_K` | `narration` (`Vulkan1`) | `6.08 s` | `3.261 s` | `1.86` | `0.609 s` | `26.875 GiB` (`+26.815 GiB`) | `RMS 0.06255`, clean delivery |
| `Q5_K` | `design_whisper` (`Vulkan1`) | `16.30 s` | `7.939 s` | `2.05` | `0.578 s` | `26.877 GiB` (`+26.817 GiB`) | `RMS 0.06538`, stopped early before last word (`~5.75 s` internal & `~2.35 s` trailing silence) |
| `Q5_K` | `clone_jvnv` (`Vulkan1`) | `5.94 s` | `3.402 s` | `1.75` | `0.716 s` | `27.375 GiB` (`+27.315 GiB`) | `RMS 0.02804` |
| `Q5_K` | `clone_jvnv_expressive` (`Vulkan1`) | `2.97 s` | `2.272 s` | `1.31` | `0.842 s` | See note* | `RMS 0.02987` |

*Between `Q5_K` runs 3 and 4, another process on the host raised idle `GPU1` memory from `61 MiB` to `538 MiB`+.

</details>

---

## License & Use Restrictions

- **Weights & Model Derivatives (`LICENSE`, `NOTICE`):** Governed by the **Fish Audio Community License 1.0** (`Built with Fish Audio.`). Permitted for **non-commercial research and personal use only** (commercial licensing is handled separately by 39 AI, INC.). Use must comply with all applicable laws and the license terms in [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
- **Runtime Patches (`LICENSE-SPEECH-CPP`, `NOTICE` §4):** Both `drama3-small-speechcpp.patch` and `drama3-speechcpp-fast.patch` are accompanied by [`LICENSE-SPEECH-CPP`](LICENSE-SPEECH-CPP) (MIT License, `Copyright (c) 2026 Sakasegawa`) **governing the base `speech.cpp` modifications in both patches**, **except** the pause-control `expected_frames()` implementation (`drama3-small-speechcpp.patch` lines 239–273 and `drama3-speechcpp-fast.patch` lines 778–812), which is ported from `pentacoxian-dev/drama3-small-GGUF` (`drama3-small-audiocpp.patch`, derived from Apache-2.0 `audio.cpp`, Copyright 2026 ShugoAI LLC) and is excluded from Sakasegawa's copyright statement (see [`NOTICE`](NOTICE) §4).
- **Calibration Provenance:** Stratified Japanese `imatrix` statistics were collected from **JSUT** and **JVNV** (`litagin/jvnv_corpus_v1_no_nv`, CC BY-SA 4.0). Only quantized tensor scaling statistics derived from calibration affect the published weights; no corpus audio is redistributed.

---

## Acknowledgments

This release builds directly on the open-source ecosystem and community contributions of:

- **39 AI, INC. / Fish Audio** — Base architecture and `fishaudio/s2-pro` foundation (`Built with Fish Audio.`)
- **Aratako** — [`Aratako/Drama-3-Japanese`](https://huggingface.co/Aratako/Drama-3-Japanese) Japanese adaptation and [`TAG_LIST.md`](TAG_LIST.md)
- **nyosegawa / Sakasegawa** — [`speech.cpp`](https://github.com/nyosegawa/speech.cpp) native GGUF inference engine (MIT)
- **pentacoxian-dev** — [`drama3-small-GGUF`](https://huggingface.co/pentacoxian-dev) inspiration, `silence_codes.json`, and pause-control `expected_frames()` design
- **JarodMica & ShugoAI LLC** — [`audio.cpp`](https://github.com/JarodMica/audio.cpp) (Apache-2.0)
- **ggml-org** — [`ggml`](https://github.com/ggml-org/ggml) tensor and quantization runtime
- **JSUT Corpus Authors** & **JVNV Corpus Authors / litagin** (`litagin/jvnv_corpus_v1_no_nv`, CC BY-SA 4.0) — Japanese speech corpora used for stratified `imatrix` calibration
