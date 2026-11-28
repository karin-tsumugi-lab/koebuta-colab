# Koebuta v3 ASMR音声・バイノーラル脚本制作ガイド

Irodori-TTS と `audio_mix/irodori_mix.py` のバイノーラル空間化機能を組み合わせ、耳元で語りかけられるような臨場感のある **ASMR・シチュエーションボイス作品** を制作するための脚本設計とミキシング手順です。

---

## 1. 通常の朗読とASMRボイスの違い

| 要素 | 通常の朗読・ボイスドラマ | ASMR・シチュエーションボイス |
|---|---|---|
| **聞き手の立場** | 物語を外から聴く「観客」 | その場に居合わせる「当事者（一人称視点）」 |
| **声の配置** | 原則センター固定（`center`） | 距離と左右位置が変化する（`right_close`, `move_...` 等） |
| **発話間の「間」** | テンポ重視（`250 〜 400 ms`） | 余韻と呼吸重視（**`600 〜 1500 ms`**） |
| **基準音量（RMS）** | はっきり聴かせる（`-18 dBFS` 前後） | 静けさと吐息を活かす（**`-20 〜 -22 dBFS`** 前後） |
| **状況説明の手段** | 地の文（ト書き）で説明する | **足音・衣擦れSE ＋ 声の距離変化**で体感させる |

---

## 2. 声の準備（クローン元WAVと設定のコツ）

ASMRらしさの7〜8割は、空間加工の前の**元音声の声質（吐息量・声の張り）**で決まります。

1. **参照音声WAV（`voices/`）の選び方**  
   ハキハキと張った朗読声ではなく、息の成分が多く柔らかい近距離ボイスを用意します。[参照音声作成キット](../voice_kit/README.md) を使う場合は、`--preset whisper_sister`（包容力のあるお姉さん・囁き寄り）や `gentle_girl` をベースに試作するのが適しています。
2. **`settings.json` の `baseCaption`**  
   作品全体の土台となる `baseCaption` にも、声量を抑えた近距離トーンを指定します。
   ```json
   "baseCaption": "柔らかく息遣いの近い大人の女性の声。声量を抑え、穏やかで親密な距離感でゆっくりと話す。"
   ```

---

## 3. ASMR脚本（`scenario.json`）の作り方・5つの鉄則

### ① 地の文を排し、「二人称の語りかけ＋音」で構成する
「彼女はベッドの右側へ歩いてきて腰掛けた」と地の文で説明するのではなく、**セリフ＋スリッパの足音SE＋ベッドのきしみSE＋声の位置移動（`move_center_to_right`）** で表現します。Koebuta の設定上は一人芝居（`speakers` 1人、`kind: "narrator"`、`narratorEmotion: true`）として作ると管理しやすくなります。

### ② 「距離のコントラスト（緩急）」を設計する
最初から最後までずっと耳元ベタ付き（`right_close` / `left_close`）にすると、聴き手の耳が慣れてしまいゾクゾク感（トリガー）が薄れます。
- **導入**: 扉越しや少し離れた位置（`far_center` / `left_mid` / `right_mid`）から始める。
- **接近**: `move_center_to_right` や衣擦れSEを挟んで距離を縮める。
- **見せ場（トリガー）**: 甘やかす一言や秘密の囁きだけを **`right_close` / `left_close`**（`emotion: "whisper"`）に落とす。

### ③ 1発話は短め（20〜50文字）にし、間（`pause_after_ms`）を広くとる
早口の長文はASMRの空気を壊します。読点（`、`）を適度に入れてゆったり読ませ、発話の終わりには `pause_after_ms: 600` 〜 `1500` を設定して「静かな呼吸の余白」を作ります。

### ④ 非言語音タグ（吐息・ため息・リップ音）は「1発話1〜2個」に絞る
`tts_text` の文頭や読点直後に位置指定絵文字を入れると生々しい息遣いが出ますが、詰め込みすぎると不自然な異音になります。ここぞという箇所に絞って配置します。
- `🌬️`（呼吸・吐息） / `😮‍💨`（優しい安堵のため息） / `💋`（リップ音・耳元のニュアンス） / `🤭`（小さな微笑） / `⏸️`（文中の溜め）
- 発話全体の `emotion` は `whisper`（囁き）、`kind`（優しさ）、`relieved`（安堵）、`sleepy`（眠気）、`slow`（ゆっくり）、`tease`（からかい）が特に相性良好です。

### ⑤ `notes` に空間位置とSEの設計メモを残す
シナリオ作成時点で各発話の `notes` に空間プリセット名と効果音メモを書いておくと、`irodori_mix.py --init-plan` を実行した際に `mix_plan.json` へそのまま転記され、ミキシング作業で迷いません。

```json
{
  "id": "t0030",
  "speaker_id": "alice",
  "text": "あと五分だけ、なんておっしゃってもダメですわ。ほら、目を覚ましてくださいませ。",
  "tts_text": "🌬️あと五分だけ、⏸️なんておっしゃってもダメですわ。ほら、目を覚ましてくださいませ。",
  "emotion": "whisper",
  "acting_description": "右耳のすぐそばで、息を多く含ませて柔らかく囁くように",
  "pause_after_ms": 900,
  "notes": [
    "[空間] right_close（右耳元で囁き）",
    "[効果音] 直後に布団の衣擦れ音（微細フォリー）"
  ]
}
```

### チャットAIでASMR脚本を作るときの追加指示コピペ
[prompts/02_CHAT_PROMPT.md](../prompts/02_CHAT_PROMPT.md) の末尾にある【ユーザー指定欄】へ、以下を貼り付けて依頼するとASMR向きのシナリオが出力されます。

```text
朗読形式（必須）：一人朗読（地の文なしの二人称シチュエーションボイス）
演出・声の方針（任意）：ASMR・バイノーラル作品向け。1発話は20〜55文字程度と短めに区切り、pause_after_msは600〜1200msを中心にゆったり取る。距離の変化（扉越し→接近→右耳元→左耳元など）を意識し、見せ場の囁きには emotion: "whisper" と少数の位置指定タグ（🌬️、😮‍💨、🤭、⏸️）を使う。各発話の notes に推奨する空間配置（["[空間] right_close"] 等）と挟むべき生活音・衣擦れSEの指示を記載すること。
```

---

## 4. `audio_mix/irodori_mix.py` によるASMRミキシング手順

### Step 1：通常どおり Colab CLI で音声を生成する

```bash
python3 cli/irodori_generate.py \
  --scenario works/my_asmr/scenario.json \
  --settings works/my_asmr/settings.json \
  --session asmr-sess --job run01 --out works/my_asmr/run01 \
  --new --gpu T4 --stop-after-download
```

### Step 2：`mix_plan.json` のひな形を作る

```bash
python3 audio_mix/irodori_mix.py \
  --init-plan works/my_asmr/mix_plan.json \
  --run-dir works/my_asmr/run01 \
  --scenario works/my_asmr/scenario.json
```

### Step 3：`target_tts_rms_db` と各発話の `position` を設定する

`mix_plan.json` を開き、全体の基準音量を少し控えめな **`-20.0` 〜 `-22.0`** に設定し、各発話（およびモノラルSE）に `"position"` を指定します。

```json
{
  "target_tts_rms_db": -21.0,
  "sample_rate": 48000,
  "segments_zip": "run01/segments.zip",
  "leading_pause_ms": 500,
  "trailing_pause_ms": 1000,
  "utterances": [
    {
      "id": "t0010",
      "file": "audio/t0010_xxxx.wav",
      "position": "far_center",
      "pause_after_ms": 800,
      "insert_after": [
        {
          "wav": "sfx/knock_mono.wav",
          "category": "action",
          "position": "far_center",
          "pre_gap_ms": 250,
          "post_gap_ms": 400
        },
        {
          "wav": "sfx/binaural_footsteps_2ch.wav",
          "category": "foley",
          "pre_gap_ms": 100,
          "post_gap_ms": 400
        }
      ]
    },
    {
      "id": "t0020",
      "file": "audio/t0020_yyyy.wav",
      "position": "move_center_to_right",
      "pause_after_ms": 700
    },
    {
      "id": "t0030",
      "file": "audio/t0030_zzzz.wav",
      "position": "right_close",
      "pause_after_ms": 1000
    }
  ],
  "overlays": []
}
```

> **重要：バイノーラル収録済みSE（2chダミーヘッド素材）の扱い**  
> もともとダミーヘッド（黒耳など）で2chバイノーラル収録されたSEには、原則 **`"position"` を指定しないでください**（指定なしなら元の2ch立体音響がそのまま保持されます）。なお、万一2chステレオ素材に `"position"` を指定した場合でも、左右チャンネルの位相差を検知してモノラル統合を自動スキップし、元の立体位相を壊さず距離減衰・音量バランスのみを適用する保護機構が働きます。1chモノラルの効果音（ノック音や単一マイクの衣擦れなど）を声と同じ方向から鳴らしたい場合に `"position": "right_mid"` 等を指定してください。

### 使用できる空間プリセット一覧（`position`）

| プリセット名 | 動き・位置 | 内部で行われる音響処理 |
|---|---|---|
| `center` | 正面中央（既定） | 加工なし（L=R） |
| `far_center` | 少し離れた正面・扉越し | 音量 `-4.5 dB` ＋ 高域ローパス（`4.2 kHz`）で距離感を演出 |
| `left_mid` / `right_mid` | 左斜め前 ／ 右斜め前（会話距離） | 中程度のITD・等パワーILD・1次頭部陰影LPF ＋ 前方耳介EQ・軽い近接感（`proximity: 0.40`） |
| `left_close` / `right_close` | **左耳元 ／ 右耳元（極近接）** | 斜め前寄り配置（`pan: ±0.82`）＋ 強ILD・1次頭部陰影LPF ＋ **近耳前方プレゼンス（`3.2 kHz`）・極微初期反射・呼吸レベルの微小揺らぎ**（後頭部寄りへの前後混同を防止）＋ 近接低域（`180 Hz`）・吐息Air（`9.5 kHz`）・歯擦音抑制（`7.4 kHz`） |
| `move_center_to_right` | 正面 → 右側へ移動 | 発話中に中央から右へ等パワーのまま滑らかに移動（cosイージング） |
| `move_center_to_left` | 正面 → 左側へ移動 | 発話中に中央から左へ等パワーのまま滑らかに移動 |
| `move_right_to_left` | 右耳元 → 左耳元へ移動 | 発話中に右耳側から正面を通って左耳側へ音量膨張・位相段差なく回り込む |
| `move_left_to_right` | 左耳元 → 右耳元へ移動 | 発話中に左耳側から正面を通って右耳側へ音量膨張・位相段差なく回り込む |

さらに細かく指定したい場合は、オブジェクト形式で直接パラメータを渡せます（使用可能キー：`preset`, `pan_start`, `pan_end`, `proximity`, `distance_db`, `far_lpf_hz`, `micro_motion`。未定義キーや不正なプリセット名は `--dry-run` 時点で検証エラーになります）。時計の秒針やオルゴールなど、人間のような呼吸揺らぎを止めたい近接モノラルSEには `"micro_motion": 0.0` を併用してください。
```json
"position": {"preset": "right_close", "pan_start": 0.78, "pan_end": 0.86, "proximity": 0.9, "distance_db": 0.0}
```

### Step 4：ステレオWAVへ書き出してイヤホンで試聴する

```bash
python3 audio_mix/irodori_mix.py \
  --plan works/my_asmr/mix_plan.json \
  --out works/my_asmr/result_asmr.wav
```
