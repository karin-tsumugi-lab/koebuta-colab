# Yomibuta（Drama-3-Japanese 対応版）

Yomibuta は、Koebuta v3 の朗読生成パイプラインを基盤に、**`Aratako/Drama-3-Japanese`**（Fish Audio Drama 3 日本語特化モデル）を Google Colab GPU 上で連続駆動・結合して朗読音声（**44.1 kHz / 1ch / 16bit PCM**）を制作するツール群です。

---

## バックエンドの使い分け

| モード | 設定 (`backend` / `quant`) | 推奨 Colab GPU | 特徴 |
|---|---|---|---|
| **CU 節約・テスト／実用軽量** | `speech_cpp_gguf` / `IQ3_XXS` | **T4 (16 GB)** / L4 | 同梱の事前ビルド済み単体バイナリ（`bin/speech_cuda13_sm75_89.gz`）により **0 秒ビルド**。常駐 `speech serve` での発話合成は **T4 で RTFx 1.07〜1.41**、**L4 で合成部 RTFx 約 1.9**（初回 GGUF 取得・モデルロード除く。単発コールド CLI 等の内訳は [実測ベンチマーク](docs/BENCHMARKS.md) 参照） |
| **本番・最高品質（非量子化）** | `official` / `none` | **A100 (80 GB)** / G4 等 | `sglang-omni`（PyPI 安定版／コミット固定可）で `Aratako/Drama-3-Japanese` 公式非量子化ウェイトを直接推論 |

---

## 制作フロー（4 ステップ）

1. **声を用意する（`voice_kit/`）**
   - [voice_kit/README.md](voice_kit/README.md) の手順でシード違いの候補 WAV を試作し、`--adopt` で `transcript` 自動転記済みの `settings.json` を生成します（最大 3 クリップまで拡張可）。
2. **原稿を `schema_version: 2` シナリオ JSON にする（`prompts/`）**
   - [02_CHAT_PROMPT_DRAMA3.md](prompts/02_CHAT_PROMPT_DRAMA3.md) と原稿をチャット AI へ渡します。
   - 演技・非言語表現は [TAG_LIST.md](prompts/TAG_LIST.md) の公式タグを `tts_text` へ記述します（`schema_version: 1` シナリオも下位互換で読み込み可能）。
3. **HTML エディタで確認・調整する（任意）**
   - [Yomibuta_Scenario_Inspector_v4.html](Yomibuta_Scenario_Inspector_v4.html) をブラウザで開き、`schema_version: 1 / 2`、追加ルビ、`scene_caption`、3 クリップ参照音声＋`transcript` を編集します。
   - 話者欄で設定した `speakers[].reference_clips` は `settings.json` 側で `voices` を省略した場合に CLI がそのまま参照します。また「⚙ 生成設定」ダイアログの **「📤 CLI settings.json 出力」** から CLI 用の `settings.json` を直接書き出せます（シナリオ内の `koebuta_settings` 自体はエディタ／Notebook 用の保持項目であり、CLI 実行時は `--settings` の JSON が正となります）。
4. **CLI で朗読音声を検査・生成する（`cli/`）**
   ```bash
   # 事前検査（GPU 不使用：構文・未学習タグ・参照 transcript・ルビ確認）
   python3 cli/yomibuta_generate.py \
     --scenario examples/mvp_scenario_v2.json \
     --settings examples/mvp_settings_clone.json \
     --dry-run

   # Colab T4 で生成・回収・SHA-256 二重検証・ランタイム自動停止
   python3 cli/yomibuta_generate.py \
     --scenario examples/mvp_scenario_v2.json \
     --settings examples/mvp_settings_clone.json \
     --session work-sess --job run01 --out works/my_book/run01 \
     --new --gpu T4 --stop-after-download

   # 通信断などで回収前に中断した出力フォルダーからの回収専用リカバリ
   python3 cli/yomibuta_generate.py \
     --recover works/my_book/run01 --stop-after-download
   ```
   - 部分再生成は `--ids t0010,t0040` で発話単位指定が可能です。同一 `--session`・`--job` での再実行時は、遠隔に残っている検証済み発話 WAV を自動再利用して途中再開します。
   - 効果音・環境音のミキシングは [audio_mix/yomibuta_mix.py](audio_mix/yomibuta_mix.py)（44.1 kHz 標準対応）を使用します。

---

## 関連ドキュメント・ライセンス
- [移植・拡張設計書](docs/DRAMA3_PORTING_DESIGN.md) / [実測ベンチマーク記録](docs/BENCHMARKS.md)
- [シナリオ JSON 仕様書 v2](prompts/01_SPEC_SHEET_V2.md) / [公式タグ一覧](prompts/TAG_LIST.md)
- [参照音声作成キット](voice_kit/README.md) / [効果音・環境音ミキシングガイド](audio_mix/README.md)
- [ライセンス](LICENSE) / [第三者のコード・モデルと利用条件](THIRD_PARTY_NOTICES.md)（*Built with Fish Audio.* モデル重みは Fish Audio Community License 1.0 に従い非商用・個人／研究用途限定）
