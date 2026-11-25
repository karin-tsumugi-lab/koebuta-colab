# Yomibuta (Drama-3 対応版) 移植・拡張設計書

本書は、Koebuta v3（`koebuta-colab`）の朗読生成パイプラインを基盤とし、**`Aratako/Drama-3-Japanese`**（Fish Audio Drama 3 日本語特化モデル）を駆動するためのアーキテクチャ設計・シナリオ拡張規格（`schema_version: 2`）・段階的実装計画を定める。

---

## 1. 設計方針とスコープ

1. **パイプライン骨格の完全継承**
   - Colab CLI のセッション管理、忠実生成契約（ホスト／遠隔の計画署名一致）、発話単位の部分再生成（`--ids`）、WAV 検証（SHA256・フレーム数）、中断リカバリ、効果音ミキシング（`audio_mix`）はそのまま流用する。
2. **マルチエンジン共存と下位互換**
   - `schema_version: 1` の既存シナリオおよび Irodori-TTS バックエンドの動作を壊さず、エンジン層を抽象化して Drama-3 バックエンドを追加する。
3. **サンプリングレート統一（44.1 kHz）**
   - Drama-3（Fish Audio コーデック）のネイティブ出力である **44.1 kHz** を Yomibuta（Drama-3 系統）の標準サンプリングレートとして統一する。不要なリサンプルによる音質劣化を避け、結合処理および `audio_mix` も 44.1 kHz 基準で動作させる（Irodori 48 kHz 出力との共存時はジョブの `sample_rate` メタデータに追従する設計とする）。
4. **電子透かしチェック（SilentCipher）の分離**
   - SilentCipher の強制検証（`tts_dependencies.py`）は Irodori-TTS 固有の責務とする。Drama-3 バックエンドには電子透かし機構が存在しないため、検証を適用しない。
5. **ルビ自動判定（`auto_select`）の後回し**
   - 既存の `RuntimeSpanScorer` は Irodori-TTS 内部のテキストエンコーダ特徴量（`cos_cond`）に強く依存しているため、初期移植（Phase 1）では対象外とする。
   - Phase 1 では **作者ルビ** と **手動確定（`kana` / `surface`）** のみを適用し、`selection: "auto"` は元表記維持＋診断警告（`W_RUBY_AUTO_DEFERRED`）とする。

---

## 2. バックエンド戦略（開発テストと本番の二段構え）

Drama-3 は総パラメータ約 35B（アクティブ約 3B）の MoE モデルであり、実行環境に応じて明確に2系統のバックエンドを用意する。

| プロファイル | 想定用途 | 対象 GPU（Colab） | 推論バックエンド | モデル形式 | 備考 |
|---|---|---|---|---|---|
| **`speech_cpp_gguf`** | **実装テスト・CU節約運用** | T4 (16GB) / L4 (24GB) | `speech.cpp`（CUDAビルド） | GGUF（CUDA 標準: `IQ3_XXS` 約9.76GB ※現行 `ggml-cuda` では `Q4_K`/`Q5_K` が FP16 オーバーフローを起こすため CUDA 実行は `IQ3_XXS` に固定） | 事前ビルド済みバイナリ（`bin/speech_cuda13_sm75_89.gz`）と常駐 `speech serve` により T4 でも実時間超えで動作（詳細は `docs/BENCHMARKS.md`） |
| **`official`** | **本番・高品質生成** | A100 (80GB) / G4 等 | 公式推論エンジン（`fish_omni` / `sglang-omni` / `vllm-omni` 等） | 公式非量子化ウェイト（FP8 / BF16） | 大容量 GPU を使う場合、CU コスパ上あえて量子化を選ぶ理由がないため非量子化を標準とする |

### 常駐モデル保持と Colab セットアップの注意点
- **1発話ごとのモデル再ロード禁止**：9GB〜40GB のモデルを発話ごとに読み直すと実用に耐えないため、既存の `resident.py` と同様にセッション内でモデルを常駐保持する。
  - `speech.cpp` 経路では、ワーカー管理下でローカル専用（`127.0.0.1` の動的ポートまたは制御ラッパー）の `speech serve` を起動・監視し、ジョブ完了またはアンロード時に確実にプロセスを終了して CUDA コンテキストを解放する。
- **ビルド時間対策**：Colab 新規セッションごとの `speech.cpp` CUDA ビルド時間を短縮するため、将来的にはビルド済みバイナリのキャッシュ／リリース取得（SHA256 検証付き）へ移行できる構造を `prepare.py` に持たせる。

---

## 3. シナリオ JSON 拡張規格（`schema_version: 2`）

既存の `schema_version: 1` との下位互換を保ちつつ、Drama-3 の入力仕様（日本語インライン演技タグ・音響環境キャプション・AR モデルの発話特性）と矛盾なく噛み合うよう拡張を行う。

### 3.1 `schema_version: 1` と `2` の差分

| 項目 | `schema_version: 1`（現行） | `schema_version: 2`（Drama-3 拡張） |
|---|---|---|
| **バージョン識別子** | `"schema_version": 1` | `"schema_version": 2` |
| **`emotion` フィールド** | 必須（34種の固定ID） | **任意**（省略時は `neutral`）。v1 互換および粗い感情ラベル・フォールバック用途として維持 |
| **インライン演技タグ** | 絵文字タグ（`emoji_tags.py`） | `tts_text` 内の **日本語インラインタグ**（例：`[笑いながら]`, `[驚いて]`, `[怒りを込めて]`, `[囁き]`, `[耳元で]`, `[吐息]`）を正式要素として許容 |
| **音響環境・空間指定** | なし（`acting_description` に混在） | 発話（および任意でトップレベル／場面）に **`scene_caption`**（任意文字列）を追加。「静かな部屋で」「耳元で」「フォーマルな場で」等の空間・距離感を独立して記述可能 |
| **分割・文字数計算** | 絵文字タグを不可分・文字数除外。<br>20〜80文字推奨（10文字未満回避） | `[...]` 形式のインラインタグも不可分（`_safe_boundary` で分断禁止）かつ `spoken_length` から除外。<br>AR モデル向けに**短文（「うん。」「えっ？」等）の単独生成を許容** |
| **追加ルビ（`koebuta_added_ruby`）** | `auto` / `kana` / `surface` | 構造は完全継承。Drama-3 Phase 1 では `auto` を `surface` 扱い＋警告（`W_RUBY_AUTO_DEFERRED`） |
| **編集メモ（`notes`）** | 自由記述配列（TTS非送信） | 変更なし |

### 3.2 入力衝突・制御トークン保護規則（重要）
1. **原文の半角角括弧 `[...]` との衝突防止**：
   - `tts_text` に明示された `[...]` は Drama-3 の演技タグとして送信する。
   - `tts_text` 未指定で原文 `text` に半角 `[...]`（例：`[注]`、`[転送]`）が含まれている場合、モデルが演技タグと誤認する恐れがあるため、`--dry-run` 時に警告（`W_RAW_BRACKET_IN_TEXT`）を出す（必要なら `tts_text` で全角 `［...］` へ逃がす運用とする）。
2. **ベースモデル特殊トークンの混入禁止**：
   - Fish Audio Drama 3 ベースモデルの複数話者トークン（`<|speaker:0|>` 〜 `<|speaker:15|>`）や特殊制御トークン `<|...|>` が `text` / `tts_text` に含まれる場合、`Aratako/Drama-3-Japanese`（単一話者特化）での誤動作を防ぐため、計画段階でエラー（`E_FORBIDDEN_CONTROL_TOKEN`）とする。
3. **エンジン間フォールバック規則**：
   - **v1 シナリオ → Drama-3**：`emotion` を新設の `drama3_tags.py` で日本語インラインタグへ自動変換する（`settings.emotion: true` 時）。テキスト中の Irodori 用絵文字は対応タグへ置換または除去し、診断ログに記録する。
   - **v2 シナリオ → Irodori-TTS**：既定では `[...]` タグが含まれる場合はエラー（`E_UNSUPPORTED_TAG`）とし、明示オプション指定時のみタグ除去フォールバックを許可する。

### 3.3 `schema_version: 2` シナリオ記述例

```json
{
  "schema_version": 2,
  "speakers": {
    "narrator": {
      "name": "語り手",
      "kind": "narrator",
      "voice_caption": "落ち着いた大人の女性。明瞭で柔らかい声。"
    }
  },
  "segments": [
    {
      "id": "t0010",
      "speaker_id": "narrator",
      "text": "「ねえ、そんなに急がないで。ちゃんと、こっち見ててね」",
      "tts_text": "[囁き]ねえ、そんなに急がないで。[吐息]ちゃんと、こっち見ててね。",
      "scene_caption": "静かな部屋、耳元に近い距離感。",
      "acting_description": "親密な相手に優しく語りかけるように",
      "pause_after_ms": 400,
      "koebuta_added_ruby": [],
      "notes": ["[環境音] 雨音をうっすら敷く"]
    }
  ]
}
```

---

## 4. 生成設定 JSON（`settings.json`）の拡張

### 4.1 エンジン・バックエンド・生成パラメータ

```json
{
  "title": "作品名",
  "ttsEngine": "drama3",
  "ttsModel": "Aratako/Drama-3-Japanese",
  "backend": "speech_cpp_gguf",
  "quant": "IQ3_XXS",
  "sampleRate": 44100,
  "voiceMode": "clone",
  "reading": "shared",
  "voices": {
    "voice_a": [
      {
        "wav": "voices/narrator_01.wav",
        "transcript": "窓の外では静かに雨が降り続いていた。"
      },
      {
        "wav": "voices/narrator_02.wav",
        "transcript": "「ねえ、これからどこへ向かうつもりなの？」"
      }
    ]
  },
  "baseCaption": "落ち着いた明瞭な日本語の朗読。",
  "cloneCaption": false,
  "acting": true,
  "emotion": true,
  "narratorEmotion": true,
  "seed": 314,
  "pause": 0.28,
  "engineOptions": {
    "temperature": 0.8,
    "top_p": 0.85,
    "top_k": 30,
    "max_seconds": 47.55,
    "max_pause_frames": 36,
    "experts_on_cpu": false
  }
}
```

### 4.2 参照音声（`voices`）の拡張仕様（最大3クリップ＋文字起こし）
Drama-3 のゼロショット／フューショット音声クローンは、**同一話者につき最大 3 クリップ**の参照音声と、各クリップに対応する**文字起こし（`transcript`）**を受け取る。

* **受理形式**：
  1. 単一オブジェクト：`{"wav": "voices/a.wav", "transcript": "..."}`
  2. 配列（1〜3 要素）：`[{"wav": "...", "transcript": "..."}, ...]`（4 要素以上はエラー）
  3. 文字列単体（v1 下位互換）：`"voices/a.wav"`
* **Drama-3 クローン時の `transcript` 必須化**：
  - Koebuta の忠実生成ポリシーに従い、`ttsEngine == "drama3"` かつ `voiceMode == "clone"` の場合、各参照クリップの `transcript` が空または未指定であれば **`--dry-run` 時点でエラー（`E_REFERENCE_TRANSCRIPT_REQUIRED`）** とする（無断の自動文字起こしや空文字フォールバックは行わない）。
* **`voice_kit` 連携**：`voice_kit` で試作・採用した参照 WAV には試聴セリフ（`--text`）が `voice_meta.json` に記録されているため、`--write-settings` 時に `transcript` を自動転記する。

### 4.3 エンジン別パラメータ検証
- `steps`（`20 / 40 / 60`）：`ttsEngine == "irodori"` のみ検証対象。
- `engineOptions`（`ttsEngine == "drama3"`、`plan.py` 実装および `speech.cpp` 実測チューニング準拠）：
  - `temperature`（既定 `0.8`、範囲 `0.0 < x <= 2.0`）：`IQ3_XXS` での読み崩れを抑える安定値。
  - `top_p`（既定 `0.85`、範囲 `0.0 < x <= 1.0`）
  - `top_k`（既定 `30`、範囲 `1〜4097`）
  - **`max_seconds`**（既定 `47.55`、範囲 `0.0 < x <= 95.11`）：自己回帰モデルの暴走・無限無音を防ぐための必須安全上限。
  - `max_pause_frames`（既定 `36`）：環境変数 `SPEECH_DRAMA3_MAX_PAUSE_FRAMES` による長無音クランプ（`18` では読点での早期 EOS 切断が起きやすいため `36` を既定とする）。
  - `experts_on_cpu`（既定 `false`）：GPU 全載せ指定（`speech.cpp` 既定は `true` のため明示的に `false` を渡す）。
  - ※`cloneCaption`（トップレベル設定、既定 `false`）：`voiceMode == "clone"` 時に自由記述 `[caption]` を先頭付与すると読み誤りを誘発するため、クローン時は既定で抑制し `TAG_LIST.md` の公式インラインタグのみで演出する。
  - ※`repetition_penalty` は `speech.cpp` の Drama-3 モデルでは非対応（渡すとエラーになるため、公式推論バックエンド専用とする）。
- `sampleRate`：Drama-3 の既定は `44100`（Irodori は `48000`）。

---

## 5. Scenario Inspector（HTML エディタ）の変更影響

`Koebuta_Scenario_Inspector_v3.html` を確認した結果、`schema_version: 2` および「参照音声 3 クリップ＋`transcript`」対応に伴い、以下の箇所が変更対象となる（Phase 2 で実施）。

1. **`schema_version` 検証の拡張**：現行の `schema_version !== 1` 固定チェック（2箇所）を `1` / `2` 受理へ拡張。
2. **話者パネルの参照音声 UI（3 クリップ＋`transcript`）**：
   - 現行は話者ごとの `reference_wav`（単一パス）および `koebuta_settings.shared_reference_wav`（単一パス）のみを保持・試聴する構造。
   - v2 対応では、最大 3 件の参照クリップ（WAV パス＋`transcript` 入力欄＋個別試聴ボタン）を扱える `reference_clips`（または `settings.json` エクスポート連携）へ拡張する（既存の単一 `reference_wav` も下位互換で読み込めるようにする）。
3. **発話エディタ・マージ／分割ロジックの拡張**：
   - `known` フィールド一覧に `scene_caption` を追加し、発話の分割・結合時に引き継ぐ。
   - `emotion` 未指定（v2 任意）を警告ではなく正常扱いとし、インラインタグ `[...]` の入力補助・文字数カウント除外・短文警告閾値（`low` / `high`）のプリセット切替を追加。

---

## 6. モジュール移植・変更影響マップ

`koebuta-colab/cli/` の構造をベースに、Yomibuta 側での責務分離を以下の方針で行う。

| コンポーネント | 方針 | 変更内容 |
|---|---|---|
| `connection.py` / `jobs.py` / `recovery.py` / `terminal.py` / `colab_usage.py` | **流用** | ほぼ無改造でそのまま使用（ジョブ管理・転送・WAV検証・リカバリ） |
| `environments.py` | **拡張** | `ENGINES` に `'drama3_gguf'` / `'drama3_official'` を追加。バージョン・ハッシュ固定契約を定義 |
| `prepare.py` | **拡張** | `drama3_gguf` 用に `speech.cpp` の取得・CUDA ビルド（または検証済みバイナリ配置）と GGUF 取得手順を追加 |
| `faithful.py` | **拡張** | `schema_version: 2` 受理、`[...]` 保護・`<|...|>` 禁止、`scene_caption` 結合、`ttsEngine` 別の設定検証、`voices` の配列・`transcript` 必須チェック |
| `drama3_tags.py` | **新規** | Drama-3 日本語インラインタグの正規表現パターン、`spoken_length` 計算、v1 `emotion` → Drama-3 タグ変換マップ |
| `faithful_worker.py` | **拡張** | `runtime_infer` を `ttsEngine` でディスパッチ。Drama-3 時は SilentCipher チェックを通さず `drama3_worker` へ委譲 |
| `drama3_worker.py` | **新規** | `speech.cpp`（`speech voice` による話者プロファイル前処理＋常駐 `speech serve` 推論）および将来の公式推論アダプタを実装。出力 WAV（44.1 kHz / PCM_16）を保証 |
| `ruby_bridge.py` / `ruby_core.py` | **段階対応** | Phase 1 では Drama-3 実行時の `auto_select` を無効化し、`kana` / `surface` / 作者ルビのみ展開＋`W_RUBY_AUTO_DEFERRED` 警告 |
| `audio_mix/irodori_mix.py` | **小改修** | 44.1 kHz を標準対応（`mix_plan.json` の `sample_rate` をジョブ出力から自動引き継ぎ） |

---

## 7. 段階的実装ロードマップ

### Phase 0：Colab 実機スパイク（最小疎通検証）
* **目的**：本実装に入る前に、Colab T4 / L4 上での `speech.cpp` + `IQ3_XXS` の現実的な制約と CLI 仕様を実測・裏取りする。
* **確認項目**：
  1. Colab T4 / L4 での `speech.cpp`（CUDA）ビルド所要時間と必要パッケージ
  2. `IQ3_XXS` GGUF ダウンロード時間・ピーク VRAM・1発話（50文字程度）の生成時間
  3. 出力 WAV のサンプリングレート（44.1 kHz 実測）・チャンネル数・音量レベル（RMS / Peak）
  4. **`speech.cpp` の仕様裏取り**：
     - 参照音声クローン（`.voice.gguf`）と日本語キャプション（スタイル指定）の同時併用可否
     - 同一話者に対する最大 3 クリップの渡し方（`speech voice` の複数WAV結合仕様）
     - `seed` 指定による再現性の有無と `max_new_tokens` 相当のオプション名

### Phase 1：MVP パイプライン統合（`IQ3_XXS` テスト経路）
* `koebuta-colab` の必要最小限の骨格を `Yomibuta-colab` へ移植。
* `schema_version: 2` パーサー、`drama3_tags.py`、`voices` 拡張、`drama3_worker.py`（`speech_cpp_gguf`）を実装。
* `--dry-run` および T4 / L4 上での数発話の連続生成 → 44.1 kHz `result.wav` / `segments.zip` 回収までを一気通貫で検証。

### Phase 2：本番バックエンド・制作周辺ツールの拡張
* A100 / G4 向け公式推論バックエンド（`backend: "official"`）の実装と切替検証。
* Scenario Inspector HTML エディタの `schema_version: 2`・3 クリップ＋`transcript`・`scene_caption` 対応。
* AI シナリオ化プロンプト（`prompts/`）の Drama-3 タグ対応版作成。
* `voice_kit` の Drama-3 対応（`transcript` 自動出力）および `audio_mix` の 44.1 kHz 標準化。

### Phase 3：ルビ自動判定の再検討（必要時のみ）
* Phase 1〜2 の実生成音声で Drama-3 の誤読傾向を確認したうえで、軽量な外部判定器または LLM 事前レビューの導入要否を判断する。
