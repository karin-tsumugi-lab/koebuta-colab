# 03C 読み上げ文・追加ルビの追加調整（Koebuta v3・任意モジュール）

古典表記・難読語・当て字が多い作品や、なろう由来の丸括弧（ルビと補足の判別）、または CLI の `--ruby-preflight` で要確認となった語を後からまとめて調整したいときに使います。

## LLMへ追加する依頼文

```text
Koebuta v3シナリオの「読み」と「追加ルビ」だけを調整します。
入力シナリオの text、speaker_id、id、発話順、emotion、acting_description、pause_after_ms、notes は変更しないでください。

【調整ルール】
1. 読み方針（未指定時はB）：A=作者ルビ中心 ／ B=難読語・固有名詞・旧表記を補助 ／ C=許可範囲で古い表記を読み上げ文（tts_text）上で平易化。
2. 原文ルビ・同語への横展開・丸括弧：
   - カクヨム・なろう・pixiv形式の原文ルビや、作者ルビと同じ読みを他箇所へ補う場合は、青空文庫形式（｜親文字《読み》）で発話全文の tts_text に記述します。
   - 丸括弧は文脈からルビか補足かを判断し、曖昧な重要語だけ発話ID・原文・候補を示して確認します。
   - 既存の tts_text にある位置指定絵文字はそのまま保持します。
3. 追加ルビ（koebuta_added_ruby）：
   - 原文にない読み補助は `{"start": 開始, "end": 終了, "surface": "表記", "reading": "よみ", "selection": "auto|kana|surface"}` で指定します（`text[start:end] == surface`）。
   - 確実に仮名で読ませる語は `"kana"`、漢字表記を維持する語は `"surface"`、自動判定に委ねる語は `"auto"` とします。

変更が必要な発話の `id` と、更新後の `koebuta_added_ruby`（および `tts_text` を変更する場合は発話全文の `tts_text`）だけを次の形式で出力してください。変更不要な発話は省略します。
```

## 返答の例

```json
{
  "reading_updates": [
    {
      "id": "t0003",
      "koebuta_added_ruby": [
        {"start": 0, "end": 2, "surface": "蒲団", "reading": "ふとん", "selection": "kana"}
      ]
    }
  ]
}
```
