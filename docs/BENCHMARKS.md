# Yomibuta (Drama-3-Japanese) 実測ベンチマーク記録

本書は、リポジトリ内に保存されている Google Colab（T4 / L4）での実測ログ（`spike/` および `examples/`）に基づき、ビルド所要時間・モデルロード時間・常駐推論時の発話合成速度（RTFx）・VRAM 使用量の内訳を正確に記録するものです。

---

## 1. 指標の定義（コールド実行と常駐合成の区別）

`RTFx`（音声秒数 ÷ 処理秒数、`1.0` 超で実時間より高速）は、**モデルロードを含むか否か**で数値が大きく異なります。

| 区分 | 含まれる時間 | 該当経路・記録箇所 |
|---|---|---|
| **① 常駐合成 RTFx（Warm `speech serve`）** | HTTP POST 送信 → 推論・デコード → WAV 受信（モデルは VRAM 常駐済み） | `examples/out_mvp*/manifest.json` の `takes[].rtfx`、および `speech` stderr の `RTFx` |
| **② 単発コールド CLI RTFx（Cold `speech tts`）** | プロセス起動 + 9.76 GB GGUF の CUDA ロード（約 4.7 秒）+ 1 発話合成 | `spike/out_phase0_l4_run2/spike_report.json` の `tts_test_1.wav.rtfx` |
| **③ ジョブ全体所要時間（End-to-End）** | 新規セッション時の Hugging Face からの GGUF 取得（9.76 GB）+ バイナリ転送 + 参照音声プロンプト抽出（`speech voice`）+ 全発話合成 + WAV 正規化・結合 | `examples/out_mvp*/manifest.json` の `elapsed_total_sec` |

---

## 2. Colab T4 (16 GB VRAM / 2 vCPU) 実測値

* **対象バイナリ**: `bin/speech_cuda13_sm75_89.gz`（CUDA 13, `sm_75;89`, SHA-256: `a2fe66e3de41eba835d48e2be650eb1f46f62ffd99a6000b8b03ea7871508b24`）
* **モデル**: `Drama-35B-A3B-Japanese-v3-small-IQ3_XXS.gguf`（9,762,406,560 bytes）
* **注意（ソースビルド不可）**: T4 セッション（2 vCPU）での `speech.cpp` CUDA ソースビルドは 1,200〜1,500 秒でタイムアウトするため（`spike/out_phase0/spike_report.json`, `spike/out_phase0_run2/spike_report.json`）、事前ビルド済み単体バイナリの使用を必須としています。

### 2.1 常駐 `speech serve` 発話別実測（`examples/`）

| 実行ログ | モード | 発話 ID | 音声長 (秒) | 合成時間 (秒) | 常駐合成 RTFx | ジョブ全体時間 (`elapsed_total_sec`) |
|---|---|---|---:|---:|---:|---:|
| `examples/out_mvp01_t4/manifest.json` | VoiceDesign (`serve`) | `t0010` | 5.898 | 4.665 | **1.264** | 284.55 秒（初回 GGUF 取得・起動込み、計 18.20 秒音声） |
| 同上 | VoiceDesign (`serve`) | `t0020` | 6.455 | 4.566 | **1.414** | 〃 |
| 同上 | VoiceDesign (`serve`) | `t0030` | 3.715 | 2.812 | **1.321** | 〃 |
| 同上 | VoiceDesign (`serve`) | `t0040` | 0.836 | 0.760 | **1.100** | 〃 |
| `examples/out_mvp02_t4_clone/manifest.json` | VoiceClone (`serve`) | `t0010` | 8.313 | 6.548 | **1.270** | 290.70 秒（初回 GGUF 取得・`speech voice` 抽出・RMS 正規化込み、計 23.27 秒音声） |
| 同上 | VoiceClone (`serve`) | `t0020` | 5.294 | 3.916 | **1.352** | 〃 |
| 同上 | VoiceClone (`serve`) | `t0030` | 4.180 | 3.141 | **1.331** | 〃 |
| 同上 | VoiceClone (`serve`) | `t0040` | 4.180 | 3.132 | **1.335** | 〃 |
| `examples/out_mvp03_t4_clean_clone/manifest.json` | VoiceClone (`serve`, `cloneCaption: false`) | `t0010` | 2.786 | 2.613 | **1.066** | 322.66 秒（`t0020` でリトライ発生、計 21.41 秒音声） |
| 同上 | （旧リトライ時の単発 `cli` フォールバック※） | `t0020` | 10.356 | 45.516 | 0.228 | ※現行 `remote_worker.py` ではリトライ時も `speech serve` 常駐を維持するよう改修済み |
| 同上 | VoiceClone (`serve`, `cloneCaption: false`) | `t0030` | 4.180 | 3.711 | **1.126** | 〃 |
| 同上 | VoiceClone (`serve`, `cloneCaption: false`) | `t0040` | 2.786 | 1.993 | **1.398** | 〃 |

* **T4 常駐 `speech serve` 合成速度まとめ**: **RTFx `1.07〜1.41`**（11 発話全件で実時間超え）。

---

## 3. Colab L4 (24 GB VRAM / 12 vCPU) 実測値

* **記録元**: `spike/out_phase0_l4_run2/spike_report.json` および `spike/remote_phase0_finish.py`
* **CUDA ソースビルド（`--target speech speech-cli -j 12`）**: `893.19 秒`（約 14.9 分）
* **GGUF ダウンロード（9.76 GB）**: `34.49 秒`
* **ピーク VRAM（`--experts-on-cpu=false`）**: `10,964 MiB`（約 10.7 GiB）
* **VoiceDesign 単発 CLI（`spike_sample_01_design.wav`, 8.824 秒音声）**:
  * プロセス全体時間: `9.925 秒`（CUDA モデルロード `4.68 秒` を含む）→ **コールド単発 RTFx `0.889`**
  * `speech` 内部計測（モデルロード後の純粋合成）: `8.82 s of audio in 4.652 s` → **合成部 RTFx `1.9`**（TTFA `0.456 秒`）
* **VoiceClone 抽出・合成来歴**:
  * `speech voice` による `.voice.gguf` 抽出: `12.033 秒`
  * 初回 `spike_report.json` の `tts_test_2_clone` は `--voice <path>` 直接指定により `rc=1` で失敗。同一セッション上で `spike/remote_phase0_finish.py` により `--add-voice spk=... --voice spk` 形式で再実行し、`spike_sample_02_clone.wav` の生成を確認（`remote_phase0_spike.py` 本体も同形式および `clone_failed` ステータス判定へ修正済み）。
