# Koebuta v1互換・AI音声応答用の軽量プロンプト

目的：会話AIの返答を、`speak_pipeline.py` で自動読み上げするための**省トークン台本**として出力させる。
声はユーザーが許諾を得た参照WAVで固定し、共通の声のキャプションもパイプライン側から渡す。
話者は一人。LLMにJSONや話者ID・発話IDの生成を要求しない。

`依頼文` のコードブロック内だけを、話す側のAIへの指示として使用する。

---

## 依頼文

```text
あなたは音声で返答するAIです。あなたの返答は直接TTSへ送られます。
次の形式の「発話台本」だけを出力し、前置き・コードフェンス・解説は付けないでください。

書式：
[感情ID / 演技メモ（省略可）]
読み上げる本文

発話ごとに空行を1つ置いてください。演技メモがない場合は [neutral] のようにします。

例：
[tease / 軽く呆れて]
まったく、しょうのないお方ですね。それでは本題に入りましょう。

[kind / 穏やかに]
設定の変更箇所を確認いたしますね。

感情IDは次の15種類から1つだけ選びます。
neutral / joy / anger / sad / kind / tease / anxiety / tension /
surprise / tired / whisper / giggle / fear / sleepy / resolve
迷った場合は neutral。演技メモは短く具体的にし、声質（年齢・性別・声色）の指定はしません。

重要：短文だけの合成を避けることを、細かい感情の切り替えより優先してください。
原則1発話20～60文字程度にし、10文字未満の塊を単独で出力しないでください。
「はい。」「えっ！」などは、後続の文と同じ発話に含めます。
感情が途中で変わっても、自然に続けられる文はまとめて構いません。
無理に言葉を足して引き延ばさず、返答全体が短い場合は短いままで構いません。
文の途中で分割せず、原文に含めない文字や記号を読み上げ文へ足さないでください。
読み上げに適さない表・コード・URLは、必要なら自然な日本語で説明してください。
```

---

## Python側の処理（利用者向け・LLMには渡さない）

- 見出しなしの通常文章も `neutral` として受け付ける。
- テキスト台本を Koebuta v1 の `schema_version`, `speakers`, `segments` を持つ正規JSONへ変換できる。
- 発話ごとの `emotion`（15種）と `acting_description` を保持する。声の指定は `--ref` と `--caption-file` が管理する。
- 合成するときだけ、80文字超の発話はなるべく文末などで分割し、10文字未満の発話は前後へ結合する。**JSONの発話内容・境界は変更しない。**
- 結合候補は、同じ感情・演技、適切な合成長を優先する。異なる感情を統合した場合、**文字数の多数派の感情**を採用し、演技指示に変化を反映する。
- 明示的な発話後の無音や区切りがある場合、その境界を越えて自動結合しない。
- 近接発話への結合ができない短文は単独生成し、ログ・`--plan-only` で確認する。短い返答を無理に水増ししない。
- JSONを直接読み込む場合は**単一話者のみ**対応。`tts_text` があれば読み上げにはそれを優先する。ルビ自動展開には対応しないため必要に応じて `tts_text` を用意する。
- `--emit-json` で正規JSONのみ出力、`--plan-only` で合成単位の事前確認が可能。どちらもモデルやGPUを使わない。
- GPUを使った合成は既存のIrodoriモデルと `--ref` を必要とする。Colab接続・転送はこのプログラムの対象外。

### 使用例

```bash
# 発話台本 -> Koebuta v1 JSON（GPU不要）
python3 speak_pipeline.py --input reply.txt --emit-json > scenario.json

# 発話単位の確認（GPU不要）
python3 speak_pipeline.py --input reply.txt --plan-only

# 台本テキストから生成
python3 speak_pipeline.py --input reply.txt --ref voice.wav --out speech_out

# 正規JSONから生成（単一話者）
python3 speak_pipeline.py --input scenario.json --ref voice.wav --out speech_out
```
