# Koebuta v3

Koebutaは、原稿を話者・読み・感情・演技指示付きのシナリオJSONに整理し、Irodori-TTSで朗読音声を生成するためのツール群です。

制作の本線は次の4ステップです。

1. **AIで原稿をシナリオJSONにする**（`works/my_book/scenario.json`）
2. **HTMLエディタで内容を確認・調整する(任意)**
4. **CLIで朗読音声を検査・生成する**（`works/my_book/settings.json` → `result.wav`）
5. **試聴して保存・必要なら部分再生成する**

> **AIエージェントへ制作をまとめて委託する場合**  
> [AIエージェント向け制作手順](docs/AGENT_WORKFLOW.md) の依頼欄を埋め、原稿と一緒にエージェント（Claude Code / Codex 等）へ渡してください。声の試作からシナリオ作成、CLIでの音声生成・回収までを一貫して案内しています。

---

## 用意するもの

- 読ませたい原稿
- ChatGPTやGeminiなど、ファイルや長文を扱えるチャット型AI（またはAIエージェント）
- Google Colabを利用できるGoogleアカウントとGPU利用枠（ホスト側は標準Python 3.10以上と認証済みColab CLI）

Colabを利用する場合は、原稿や参照音声をアップロードし、GPU利用枠を消費します。開始前に [Colabの利用条件](docs/COLAB_USAGE.md)、[ライセンス](LICENSE)、[第三者の権利表示](THIRD_PARTY_NOTICES.md) を確認してください。

**手元のGPUで生成したい場合**は、Irodori-TTSで短い一文を試す手順と、Koebutaのシナリオから連続生成するために必要な変更をまとめた [ローカルGPUへの移植案内](docs/LOCAL_GPU_PORTING.md) をご覧ください。

---

## 事前分岐：声の用意（3つの方法から選ぶ）

朗読に使う声は、次の3通りのいずれかで用意します。ここでは作品フォルダーを `works/my_book/` とする例で統一します。

- **方法A：手持ちの参照音声WAVを使う**  
  利用権限のあるWAVファイルを `works/my_book/voices/narrator.wav`（複数人朗読なら話者ごと）に配置し、**「1. 原稿をシナリオJSONにする」** へ進みます。
- **方法B：参照音声作成キット（`voice_kit/`）で新しく声を作る**  
  参照音声がない場合や登場人物に合う声を作りたい場合は、**[参照音声作成キット](voice_kit/README.md)** を使います。
  1. [声づくり対話プロンプト](voice_kit/VOICE_PROMPT.md) でAIと対話して声の説明文と試聴セリフを決めます（または12種の定番プリセットから選びます）。
  2. `voice_kit/irodori_voice_kit.py` でシード違いのサンプル音声を生成して聴き比べます。
  3. 気に入ったシードを `--adopt` で選び、`--save-to` と `--write-settings` で参照WAVと本番設定の保存先を指定します。
- **方法C：参照音声WAVを使わず、声の説明文（VoiceDesign）で直接生成する**  
  [VoiceDesign用の設定例](cli/irodori_cli_examples/generate_settings.json)を `works/my_book/settings.json` にコピーし、`baseCaption` に声の説明を記入します。

---

## 1. AIで原稿をシナリオJSONにする

チャット型AIに、次の2点を渡してください（依頼プロンプト単体で必要なJSON構造・感情ID・ルビ規則をすべて含んでいます）。

1. [シナリオ化の依頼プロンプト](prompts/02_CHAT_PROMPT.md)
2. 読ませたい原稿

（詳細なデータ仕様リファレンスは [シナリオJSON仕様書](prompts/01_SPEC_SHEET.md) を参照してください）

依頼時に **一人朗読／複数人朗読** を指定してください（その他の項目は「おまかせ」でも進められます）。  
AIが出力したJSONを **`works/my_book/scenario.json`** として保存します（JSONのフォーマット識別子は `"schema_version": 1` です）。

- 長い作品や難読語が多い作品には、追加指示も併用できます：
  - [03A 長編シナリオ化追加指示](prompts/03A_LONG_FORM_ADDON.md)
  - [03B エージェント向け追加指示](prompts/03B_AGENT_ADDON.md)
  - [03C 読み上げ文・追加ルビの追加調整](prompts/03C_READING_ADDON.md)

---

## 2. HTMLエディタで内容を確認・調整する

[Scenario Inspector v3](Koebuta_Scenario_Inspector_v3.html) を手元のブラウザー（Chrome / Edge推奨）で開き、`works/my_book/scenario.json` を読み込みます。画面でできる操作とJSON側で修正する項目の詳細は [エディタ利用案内](docs/EDITOR_GUIDE.md) を参照してください。

主に次の点を確認・修正します。

- **話者の割り当て**（誰の台詞・地の文か）
- **本文と読み上げ文**（作者ルビの保持、AIが補った追加ルビ `🔖` の採用状態 `自動 / 仮名 / 元表記` の切り替え）
- **感情・演技指示・間**（絵文字タグや `pause_after_ms`）
- **編集指示メモ（`notes`）**（生成後に効果音を重ねる位置などの自由記述メモ。TTS生成には影響しません）
- **発話の長さ**（**20〜80文字程度**が推奨目安です。15文字未満の短文や80文字超の長文は、意味や演出の切れ目で調整を検討してください）

確認が済んだら、`works/my_book/scenario.json` を上書き保存します。

---

## 3. CLIで朗読音声を検査・生成する

音声生成には **`cli/irodori_generate.py`** を使用します。詳しいオプションは **[CLI朗読生成ガイド](cli/README.md)** を参照してください。

1. **生成設定 `works/my_book/settings.json` を用意する**。方法Aの共通参照WAVには下の例を使います。方法B・Cで用意した設定はそのまま使い、手順2へ進みます。
   （`voice_kit` の `--adopt ... --write-settings works/my_book/settings.json` で作成済みの場合はそのまま使えます。`voices` の相対パスは `settings.json` のある `works/my_book/` を基準に解決されます）
   ```json
   {
     "title": "作品名",
     "voiceMode": "clone",
     "reading": "shared",
     "voices": {"voice_a": "voices/narrator.wav"},
     "baseCaption": "落ち着いた明瞭な日本語の朗読。",
     "acting": true,
     "emotion": true,
     "narratorEmotion": true,
     "ttsModel": "Aratako/Irodori-TTS-v4.1-Small",
     "seed": 314,
     "steps": 40,
     "pause": 0.28
   }
   ```

2. **`--dry-run` で生成計画と読みを確認する（GPU不使用）**
   ```bash
   python3 cli/irodori_generate.py \
     --scenario works/my_book/scenario.json \
     --settings works/my_book/settings.json \
     --dry-run
   ```

3. **Colab GPUで音声を生成・回収する**
   ```bash
   python3 cli/irodori_generate.py \
     --scenario works/my_book/scenario.json \
     --settings works/my_book/settings.json \
     --session work-sess --job run01 --out works/my_book/run01 \
     --new --gpu T4 --stop-after-download
   ```

---

## 4. 試聴して保存・必要なら部分再生成する

生成が完了すると、`works/my_book/run01/` に結合済みの完成音声 **`result.wav`** と、発話IDごとの個別WAVを収めた **`segments.zip`** が保存されます。

完成音声を試聴し、読みやイントネーションを直したい発話があれば、`scenario.json` を修正したうえで `--ids t0010,t0020` のように発話IDを指定し、新しい `--job` と `--out`（例：`--job retry01 --out works/my_book/retry01`）へ部分再生成できます。

### 効果音・環境音を付ける（任意）

シナリオの `notes` を見ながら、別途用意した効果音を発話の間に挿入したり、環境音を朗読に重ねたりできます。ミキシング補助ツールはCLIの個別WAVを使い、合成結果を別のステレオWAVへ書き出します。[効果音・環境音ミキシングガイド](audio_mix/README.md)

---

## 関連資料

- [参照音声作成キット（声づくりガイド）](voice_kit/README.md)
- [CLI朗読生成ガイド](cli/README.md)
- [エディタ（Scenario Inspector v3）利用案内](docs/EDITOR_GUIDE.md)
- [AIエージェント向け制作手順](docs/AGENT_WORKFLOW.md)
- [シナリオJSON仕様書](prompts/01_SPEC_SHEET.md) / [v3シナリオ詳細仕様](docs/V3_SCENARIO_SPEC.md)
- [Colabの利用条件](docs/COLAB_USAGE.md) / [ライセンス](LICENSE) / [第三者の権利表示](THIRD_PARTY_NOTICES.md) / [収録元と検証範囲](docs/PROVENANCE.md)
