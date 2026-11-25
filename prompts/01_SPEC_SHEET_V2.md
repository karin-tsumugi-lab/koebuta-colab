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
5. **非言語タグ単独発話の禁止**
   - インラインタグを除去した後の読み上げ文字数が 0 文字の発話（例：`"[ため息]"` のみ）は無音・暴走防止のためエラーとなる。必ず発話本文と結合して記述する。

---

## 4. 読み・ルビ規則（Phase 1〜2）

- **原文の作者ルビ**および **`tts_text` の青空文庫ルビ（`｜親文字《読み》`）**：常に指定の読みへ展開する。
- **`tts_text` と `koebuta_added_ruby` の関係（重要）**：
  - `tts_text` が指定されている発話では `tts_text` が最終読み上げ原稿として優先され、`koebuta_added_ruby` は適用されない（同時指定時は構文検証のうえ `W_ADDED_RUBY_IGNORED_BY_TTS_TEXT` 警告が出る）。インライン演技タグ等で `tts_text` を使う発話では、難読語の読みも `tts_text` 側へ直接書き込むこと。
- **`koebuta_added_ruby`（`tts_text` 省略時に適用）**：
  - `selection: "kana"`：常に指定の仮名へ展開する（確実に読ませたい固有名詞・旧仮名・当て字・同形異音語は `"kana"` を推奨）。
  - `selection: "surface"`：元表記を維持する。
  - `selection: "auto"`：自動判定は Phase 3 へ延期しているため、元表記を維持しつつ `W_RUBY_AUTO_DEFERRED` 警告を出す。

---

## 5. 発話後の間（ポーズ解決規則）

旧 Koebuta CLI（`faithful.py`）との下位互換を維持するため、境界ごとの無音長は以下の優先順位で単一値に解決する（合算は行わない）。

1. 発話の `pause_after_ms`（`0〜10000` の整数ミリ秒）が明示されていればその値を採用する。
2. 発話に未指定で、直後の `segment_type: "separator"` 行に `pause_after_ms` が明示されていればその最大値（共通ポーズ未満の短い値も含む）を採用する（複数指定が競合する場合は `W_PAUSE_CONFLICT` 警告）。
3. 上記がいずれも未指定で、発話の `blank_lines_after > 0` かつ発話の `blank_line_pause_ms` または `settings.json` の `blankLinePauseMs`（既定 `null`）が明示設定されている場合のみ、その空行ポーズを採用する。
4. それ以外（`pause_after_ms` を省略した `separator` を含む）は、`settings.json` の共通 `pause`（既定 `0.28` 秒 ＝ `280` ms）を採用する。
