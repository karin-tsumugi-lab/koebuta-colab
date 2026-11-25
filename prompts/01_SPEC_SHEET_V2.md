# Yomibuta（Drama-3 対応版）朗読シナリオ JSON 仕様書（`schema_version: 2`）

本書は、Drama-3-Japanese（および下位互換として Irodori-TTS）による朗読制作のためのシナリオ交換形式 **`schema_version: 2`** の仕様を定める。
`schema_version: 1`（Koebuta v3）との完全な下位互換を維持しつつ、Drama-3 の日本語インライン演技タグ・音響環境キャプション・AR モデルの発話特性に合わせて拡張されている。

---

## 1. `schema_version: 1` からの主な拡張点

| 項目 | `schema_version: 1` | `schema_version: 2` |
|---|---|---|
| バージョン識別子 | `"schema_version": 1` | `"schema_version": 2` |
| `emotion` | 必須（34 種固定 ID） | **任意**（省略時は `"neutral"`）。粗い感情ラベルや v1 フォールバック用途として維持 |
| インライン演技タグ | 絵文字タグ | `tts_text` 内の **公式日本語インラインタグ**（[TAG_LIST.md](TAG_LIST.md)：`[囁き]` `[耳元で]` `[笑いながら]` `[吐息]` 等） |
| 音響環境・空間指定 | なし | 発話に **`scene_caption`**（任意）を追加（VoiceDesign 時に使用） |
| 発話長の目安 | 20〜80 文字推奨（10 文字未満回避） | AR モデル向けに **短文（「うん。」「えっ？」等）の単独生成を許容**。長文は 100 文字以内を目安に自然な切れ目で分割 |
| 出力サンプリングレート | 48 kHz（Irodori） | **44.1 kHz 統一**（Drama-3 ネイティブ） |

---

## 2. 標準 JSON 構造

```json
{
  "schema_version": 2,
  "speakers": {
    "narrator": {
      "name": "地の文",
      "kind": "narrator",
      "voice_caption": "落ち着いた明瞭な声の成人女性。静かな部屋で丁寧に朗読している。"
    }
  },
  "segments": [
    {
      "id": "t0010",
      "speaker_id": "narrator",
      "text": "深夜の図書館は静かで、ページをめくる音だけが規則正しく響いていた。",
      "pause_after_ms": 450
    },
    {
      "id": "t0020",
      "speaker_id": "narrator",
      "text": "「ねえ、少しだけ声を落として。誰にも聞こえないように、今の話を続けよう」",
      "tts_text": "[耳元で][囁き]ねえ、少しだけ声を落として。[吐息]誰にも聞こえないように、今の話を続けよう。",
      "pause_after_ms": 500,
      "notes": ["[環境音] 静かな室内の空気感"]
    },
    {
      "id": "t0030",
      "speaker_id": "narrator",
      "text": "窓の外では冷い雨が降り続いていた。",
      "koebuta_added_ruby": [
        {"start": 5, "end": 7, "surface": "冷い", "reading": "つめたい", "selection": "kana"}
      ]
    }
  ]
}
```

---

## 3. インラインタグと禁止トークン規則（重要）

1. **公式タグのみを使用する（[TAG_LIST.md](TAG_LIST.md)）**
   - `tts_text` 内の `[...]` は Drama-3 の学習済みタグ（`[囁き]`, `[笑いながら]`, `[吐息]`, `[怒りを込めて]`, `[電話越しに]` 等）を使用する。
   - `TAG_LIST.md` に存在しない自由記述を `[...]` で書くと、特に量子化モデル（`IQ3_XXS`）で読み崩れの原因になるため、CLI は `W_UNKNOWN_INLINE_TAG` 警告を出す。
2. **クローンモード時の自由文キャプション抑止**
   - `voiceMode: "clone"` では、話者の `acting_description` や `scene_caption` を先頭 `[...]` として自動連結しない（既定 `cloneCaption: false`）。演技は `tts_text` の公式インラインタグで行う。
3. **原文の半角角括弧 `[...]`**
   - `tts_text` 未指定で原文 `text` に `[注]` のような半角角括弧が含まれる場合、CLI は `W_RAW_BRACKET_IN_TEXT` 警告を出す。必要に応じて `tts_text` で全角 `［注］` へ逃がすか削除する。
4. **ベースモデル制御トークンの禁止**
   - `<|speaker:0|>` 等の `<|...|>` トークンは `Aratako/Drama-3-Japanese`（単一話者特化）で誤動作するため、`E_FORBIDDEN_CONTROL_TOKEN` エラーとして拒否する。

---

## 4. 読み・ルビ規則（Phase 1〜2）

- **原文の作者ルビ**および **`tts_text` の青空文庫ルビ（`｜親文字《読み》`）**：常に指定の読みへ展開する。
- **`koebuta_added_ruby`**：
  - `selection: "kana"`：常に指定の仮名へ展開する（確実に読ませたい固有名詞・旧仮名・当て字・同形異音語は `"kana"` を推奨）。
  - `selection: "surface"`：元表記を維持する。
  - `selection: "auto"`：自動判定は Phase 3 へ延期しているため、元表記を維持しつつ `W_RUBY_AUTO_DEFERRED` 警告を出す。
