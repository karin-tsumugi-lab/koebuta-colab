# 第三者のコード・バイナリ・モデルと利用条件

Yomibuta 独自部分の用途制限付きライセンス（[LICENSE](LICENSE)）は、第三者が別ライセンスで提供しているコード・バイナリ・モデルの許諾条件を変更しません。

Built with Fish Audio.

---

## 1. 同梱バイナリおよびパッチ（`bin/speech_cuda13_sm75_89.gz` / `spike/out_phase0/patches/`）

本リポジトリに同梱している事前ビルド済み推論バイナリ `bin/speech_cuda13_sm75_89.gz` およびスパイク検証記録内のパッチは、以下のオープンソースソフトウェアからビルド・構成されています。再配布時はそれぞれの著作権表示とライセンス全文を保持してください。

1. **`speech.cpp`（`v0.11.2`）および `ggml`**
   - 提供元: `nyosegawa/speech.cpp` (https://github.com/nyosegawa/speech.cpp), `ggml-org/ggml`
   - ライセンス: MIT License（全文: [LICENSES/speech.cpp-MIT.md](LICENSES/speech.cpp-MIT.md)）
2. **`drama3-speechcpp-fast.patch` / `drama3-small-speechcpp.patch`**
   - 提供元: `StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf`
   - ベース `speech.cpp` 改変部: MIT License (`Copyright (c) 2026 Sakasegawa`、[LICENSES/speech.cpp-MIT.md](LICENSES/speech.cpp-MIT.md))
   - 無音フレーム制御 `expected_frames()` 移植部: `pentacoxian-dev/drama3-small-GGUF` (`drama3-small-audiocpp.patch`) を経由した `JarodMica/audio.cpp` (`Copyright 2026 ShugoAI LLC`) 由来であり、**Apache License 2.0**（全文: [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt)）が適用されます。

---

## 2. モデル重み（非同梱）および公式タグ定義

モデルの重みファイル（GGUF および Safetensors）は本リポジトリには含まれず、Colab 実行時に Hugging Face Hub から直接取得されます。`prompts/TAG_LIST.md` は `Aratako/Drama-3-Japanese` 公開の公式タグ一覧を参照用に同梱したものです。

- ベースモデル・日本語特化モデル:
  - `fishaudio/s2-pro` (39 AI, INC. / Fish Audio)
  - `Aratako/Drama-3-Japanese` (https://huggingface.co/Aratako/Drama-3-Japanese) — `prompts/TAG_LIST.md` を含む
- GGUF 量子化モデル:
  - `StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf` (https://huggingface.co/StudioYebisu-ship-it/Drama-3-Japanese-speech-cpp-gguf)
- **適用ライセンス**: **Fish Audio Community License 1.0**（**非商用の研究および個人利用に限定**。商用利用には別途 39 AI, INC. とのライセンス契約が必要です）。

コード・バイナリ・モデル重み・生成音声を同一のライセンス条件と混同せず、必ず各配布元の最新の `LICENSE` および `NOTICE` を確認してください。
