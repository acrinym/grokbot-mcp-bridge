# grokbot-mcp-bridge

[English](README.md) | 日本語

**何をするものか:** Poke（または任意の MCP クライアント）から Grok Bot に質問を投げ、回答を通常のツール結果として受け取れるようにする。Grok Bot は webhook コールバックで非同期にしか返せないが、その差を吸収する。

**誰向けか:** Fly.io に小さなアプリをデプロイでき、Web webhook トリガ付きの Grok Bot ルーチンを持っている人。MCP の内部知識は不要。下のクイックスタートはコピペで進められる。

**どうやるか:** Cursor の webhook URL／キーはブリッジ側にだけ持つので、Poke が見るのはブリッジの URL と自分で生成する API キー 1 つだけ。

## 流れ

```mermaid
sequenceDiagram
    participant P as Poke（MCP クライアント）
    participant B as ブリッジ（https://<app>.fly.dev）
    participant G as Grok Bot ルーチン
    P->>B: tools/call ask_grokbot（Bearer MCP_API_KEY）
    B->>G: Webhook POST（run_id, callback_url）
    G-->>B: POST /callbacks/{token}（回答, run_id）
    B-->>P: answer_text
```

## ドキュメント

| ドキュメント | English | 日本語 |
|---|---|---|
| 概要（このファイル） | [README.md](README.md) | [README.ja.md](README.ja.md) |
| ブリッジの仕様と運用 | [SPEC.md](SPEC.md) | [SPEC.ja.md](SPEC.ja.md) |
| Poke から Grok Bot を呼び出す | [poke-invocation.md](poke-invocation.md) | [poke-invocation.ja.md](poke-invocation.ja.md) |

## クイックスタート（Poke → Grok Bot を 4 ステップで）

以下の `<app>` は `fly.toml` の `app`（既定は `grokbot-mcp-bridge`）。

### 0. どの値をどこに入れるか

#### 必須（秘密 3 つ + URL 1 つ）

| 値 | どこで取得するか | どこに入れるか |
|---|---|---|
| `CURSOR_WEBHOOK_URL` | Grok Bot アプリ → **Web webhook** トリガのルーチン → 「POST先」（`https://api2.cursor.sh/automations/webhook/…`） | ブリッジの Fly secret（手順 2） |
| `CURSOR_WEBHOOK_API_KEY` | 同じ画面 → 「キー」（`crsr_…`）。`Authorization: Bearer` の行ではなくキーの値だけをコピー | ブリッジの Fly secret（手順 2） |
| `MCP_API_KEY` | 自分で生成（`openssl rand -hex 32`） | Fly secret（手順 2）**と** Poke → New Integration → 「API Key」（手順 3）— 両方に同じ値 |
| `https://<app>.fly.dev/mcp` | ブリッジ固定 | Poke → New Integration → 「Server URL」（手順 3） |
| Grok Bot ルーチンの指示 | このリポジトリ: [poke-invocation.ja.md § 4](poke-invocation.ja.md#4-webhook-着信ブリッジ--grok-bot)（貼るだけテンプレート） | Grok Bot アプリ → 同じルーチン → 「指示」欄 |

ルーチン画面: チャット見出し → 情報パネル → Routines → Web webhook.

#### 任意（初回は不要）

| 値 | どこで取得するか | どこに入れるか |
|---|---|---|
| `INBOUND_WEBHOOK_SECRET` | 自分で生成（任意） | Fly secret（手順 2）、`POST /hooks/grokbot` を使う場合は Grok Bot 側のプッシュルーチンにも |
| `CALLBACK_ALLOWED_HOSTS` | 受信 `callback_url` の宛先を許可するホスト名（カンマ区切り。例: `callback.example.com`） | Fly secret（手順 2）。プッシュ配信のみ |

`POST /hooks/grokbot`（`list_grokbot_events`）によるプッシュ配信だけに必要。`ask_grokbot` には不要。

### 1. Grok Bot 側の webhook を用意する

Grok Bot を動かしている Cursor automation で webhook トリガーを有効にし、URL と `crsr_…` API キーを控える。これが `CURSOR_WEBHOOK_URL` / `CURSOR_WEBHOOK_API_KEY` になり、ブリッジ側にだけ保存される（Poke には渡らない）。

ルーチンの「指示」欄には、Grok Bot が `run_id` をエコーして `callback_url` に回答を POST するよう書く必要がある。[poke-invocation.ja.md § 4](poke-invocation.ja.md#4-webhook-着信ブリッジ--grok-bot) のテンプレートをそのまま貼る。

### 2. ブリッジを Fly.io にデプロイする

`flyctl auth login` でログインするか、非対話利用なら https://fly.io/tokens でトークンを作成して `FLY_API_TOKEN` に export する（トークンには作成時に選ぶ有効期限がある。切れる前に更新すること）。

```bash
export MCP_API_KEY="$(openssl rand -hex 32)"            # この値を控える: 手順 3 で Poke に必要
export INBOUND_WEBHOOK_SECRET="$(openssl rand -hex 32)" # 任意（プッシュ配信のみ）
flyctl apps create <app>
flyctl volumes create bridge_data -r <region> -s 1 -a <app> --yes   # SQLite を /data に置く
flyctl secrets set -a <app> \
  CURSOR_WEBHOOK_URL="$CURSOR_WEBHOOK_URL" \
  CURSOR_WEBHOOK_API_KEY="$CURSOR_WEBHOOK_API_KEY" \
  MCP_API_KEY="$MCP_API_KEY" \
  INBOUND_WEBHOOK_SECRET="$INBOUND_WEBHOOK_SECRET" \
  ALLOWED_HOSTS=<app>.fly.dev \
  DB_PATH=/data/bridge.db
flyctl deploy --remote-only --ha=false -a <app>
```

- `MCP_API_KEY` と `INBOUND_WEBHOOK_SECRET` は Poke や Cursor から発行されるものでは**なく**、自分で生成する値。`echo "$MCP_API_KEY"` で同じシェル内で確認できる（手順 3 で Poke に同じ値を入れる。Fly はシークレットの値を再表示しない）。
- `INBOUND_WEBHOOK_SECRET` は任意。未設定でも `ask_grokbot` は動くが、`POST /hooks/grokbot` が 503 になり、`bridge_status` の `inbound_webhook_secret_configured` が `false` になる。
- `POST /hooks/grokbot` のプッシュ配信では `CALLBACK_ALLOWED_HOSTS` も必要。値は Grok Bot のルーチンが webhook 本文に入れる `callback_url` のホスト名（複数はカンマ区切り。`example.com` と書くと `api.example.com` も含む）。過去のイベントで使われた宛先は、Poke から `list_grokbot_events` → `get_grokbot_event(id)` を呼んで `body.callback_url` / `reply_url` / `response_url` を見れば分かる。

  ```bash
  flyctl secrets set -a <app> CALLBACK_ALLOWED_HOSTS=callback.example.com
  ```

  未設定の場合、受信した `callback_url` はすべて拒否される（正しい https URL なら `callback_error: "allowed_hosts_not_configured"`。それ以外の URL はより前の検査で拒否）。イベント自体は記録され、`ask_grokbot` には影響なし。

### 3. Poke を接続する

Poke で MCP インテグレーションを追加し、次を入力する。

| 項目 | 値 |
|---|---|
| Name | 任意のラベル。例: `grokbot-mcp-bridge` |
| Server URL | `https://<app>.fly.dev/mcp`（Streamable HTTP）。クライアントが SSE しか扱えない場合は `https://<app>.fly.dev/sse` |
| API Key | `MCP_API_KEY` の値（`Bearer ` は付けない）。Poke では任意扱いだが、空にすると OAuth を試みて失敗するので必ず設定する |

### 4. 疎通を確認する

1. `GET https://<app>.fly.dev/healthz` → `200 {"ok":true}`
2. Poke から `bridge_status` を呼ぶ → `webhook_url_configured` と `webhook_api_key_configured` が `true`（任意の秘密を飛ばした場合 `inbound_webhook_secret_configured` は `false` で問題ない）
3. Poke から `ask_grokbot` を `payload={"message": "短く自己紹介してください。"}`、`wait_seconds=60` で呼ぶ
   - `answer_status: "answered"` → `answer_text` に回答が入る
   - `answer_status: "pending"` → `wait_for_grokbot_answer(run_id)` を呼ぶ（既定 60 秒、上限 `MAX_WAIT_SECONDS`）。止めるなら `cancel_run`
   - `answer_status: "cancelled"` / `"expired"` → 待たず、必要なら新しい `ask_grokbot` を始める

   応答例:

   ```json
   {
     "ok": true,
     "run_id": "06eec502-cf7b-468d-8307-8dcf945e1f17",
     "answer_status": "answered",
     "answer_text": "…回答本文…",
     "summary": "Grok Bot answered: …"
   }
   ```

4. `flyctl logs -a <app>` に `run created` → `callback resolved` → `trigger returning` が並ぶ

Grok Bot 側の契約（`run_id` のエコー、`callback_url` への POST）とトラブルシューティングは [poke-invocation.ja.md](poke-invocation.ja.md) を参照。

## エンドポイント

- `GET /healthz`
- `GET /`
- `POST /mcp`（認証付き MCP）
- `GET /sse` と `POST /messages/`（認証付き MCP）
- `POST /hooks/grokbot`（署名付きの Grok Bot 受信イベント）
- `POST /callbacks/{token}`（Grok Bot からの回答）

## MCP ツール

- `bridge_status`
- `ask_grokbot`
- `get_grokbot_run`
- `wait_for_grokbot_answer`
- `cancel_run`
- `list_grokbot_runs`
- `list_grokbot_events`
- `get_grokbot_event`

リソースは `grokbot://events` と `grokbot://runs` で参照できます。

## 環境変数

`CURSOR_WEBHOOK_URL`, `CURSOR_WEBHOOK_API_KEY`, `MCP_API_KEY`,
`INBOUND_WEBHOOK_SECRET`, `DB_PATH`, `ALLOWED_HOSTS`, `PUBLIC_BASE_URL`,
`CALLBACK_TTL_SECONDS`, `CALLBACK_ALLOW_HTTP`, `CALLBACK_ALLOWED_HOSTS`,
`RUN_RETENTION_SECONDS`, `EVENT_RETENTION_SECONDS`, `CLEANUP_INTERVAL_SECONDS`,
`RATE_LIMIT_PER_MINUTE`, `MAX_WAIT_SECONDS`。既定値は [SPEC.ja.md](SPEC.ja.md) 7 章
（キー名のみ。シークレットの値はドキュメントや `.env.example` に書かない）。

## コールバック契約

Grok Bot は次のような JSON を POST します。

```json
{"ok": true, "answer": "...", "run_id": "<エコーした UUID>"}
```

`run_id`（または `request_id`）には、`ask_grokbot` が送った UUID をそのまま返す必要があります。
受信 webhook にコールバック URL がない場合、ブリッジは `「コールバックURLなし」` を返し、
コールバックは送らずにイベントだけ記録します。

## コマンド

```bash
uv run --extra dev pytest -q               # テスト
uv lock && uv export --no-dev --format requirements-txt --no-emit-project -o requirements.txt   # 依存関係のピン留めを更新
flyctl deploy --remote-only --ha=false     # デプロイ（app / region は fly.toml）
```

## ライセンス

MIT — [LICENSE](LICENSE) を参照。

## ローカル stdio MCP（デスクトップ AI クライアント向け）

Fly.io 上に MCP サーバーを設置せず、ローカルの **stdio MCP** としてブリッジを起動できます。HTTP 版と同じ 8 つの Grok Bot ツールに加え、ローカル専用の Keymaster 非秘密オーナー受信箱ツールを 2 つ（合計 10 ツール）公開し、Grok Bot の非同期コールバックを受け取るために `127.0.0.1:PORT` の**ループバック専用** HTTP 受信口も起動します。MCP 通信自体は標準入出力を使い、公開 HTTP MCP やローカル接続用の `MCP_API_KEY` は不要です。

選択した Python 環境にリポジトリをインストールし、対応するローカル AI クライアントから `grokbot-mcp-stdio` を起動してください。

```shell
python -m pip install -e .
grokbot-mcp-stdio
# このリポジトリ内から直接起動する場合:
python -m app.stdio
# 任意の作業ディレクトリから（パッケージのインストール不要）:
python /absolute/path/to/grokbot-mcp-bridge/scripts/grokbot-mcp-stdio.py
```

`CURSOR_WEBHOOK_URL` と `CURSOR_WEBHOOK_API_KEY` は、所有者が管理する秘密情報の保管方法から**プロセス環境変数**へ渡してください。チャット、Git 管理下の MCP 設定、コマンド引数、リポジトリの `.env` に実際の値を書かないでください。未設定の場合も 8 ツールの列挙は可能で、`bridge_status` は Grok Bot の実行が未設定であることを正しく返します。

**非同期コールバックの前提条件:** リモートの Cursor automation から PC の `127.0.0.1` へはアクセスできません。実際の返答を受け取るには、所有者が管理する外部から到達可能な **HTTPS** ホスト名を `PUBLIC_BASE_URL` に設定し、その `/callbacks/{token}` をローカル `PORT` へ安全に転送する必要があります。リバースプロキシ、トンネル、TLS、DNS、外部公開は自動構築されません。到達可能なコールバックがなければ、送信に成功しても `ask_grokbot` は pending を返すことがあります。公開するのはコールバック用パスのみとし、必要であれば署名検証付きの `/hooks/grokbot` を追加します。Keymaster の所有者認証・秘密情報とは別の境界です。

実行履歴の DB は既定で Git 作業ツリー外のユーザー専用 OS 保存先（Windows: `%LOCALAPPDATA%/GrokBOTMCPBridge/bridge.db`、Unix: `~/.local/state/grokbot-mcp-bridge/bridge.db`）に置かれます。`DB_PATH` を上書きする場合は保護された保存先を使用してください。コールバック受信口に HTTP `/mcp` はありません。 `GET /` は `stdio` / `loopback_only` を示します。ネットワーク MCP には従来の HTTP/SSE 版を使用してください。

### ローカル MCP 登録の例

インストール後、デスクトップ AI クライアントの stdio サーバーコマンドを `grokbot-mcp-stdio`（または実行ファイルの絶対パス）に設定します。秘密情報を引数に渡さないでください。Keymaster のローカル stdio MCP を併用する場合は `keymaster` という**別のサーバー**として登録します。双方を登録しても、Keymaster の Windows 保管庫が Grok Bot のリモート実行環境につながることも、AI への秘密情報の利用権限が与えられることもありません。GrokBOT の**ローカル stdio** サーバーは、実行中の Windows Keymaster に非秘密の受信箱状態確認と**未認証のオーナー確認リクエスト**を送信できますが、AI 登録・承認・秘密取得・プロバイダ操作はできません。

### Keymaster ローカル所有者受信箱ツール（Windows の stdio 専用）

追加の 2 ツールは**ローカル stdio プロセスのみ**で公開されます。ネットワーク HTTP/SSE ブリッジの Grok Bot ツールは従来どおり 8 つです。

| ローカルツール | 安全な動作 | 制限 |
| --- | --- | --- |
| `keymaster_local_inbox_status` | ネイティブ受信箱の可用性と保留件数のみを取得 | クライアント ID・保管庫メタデータ・鍵・承認は取得しない |
| `keymaster_request_owner_review` | `credential_id`、`purpose`、`mode`、必要なら `action` で**非秘密**の確認提案を送信 | 表示名は **GrokBOT local MCP (UNVERIFIED)**。受信しただけでは認証・承認・許可・秘密の開示・プロバイダ実行にならない |

`credential_id` は英数字・ドット・アンダースコア・ハイフンの ASCII 識別子（最大 128 バイト）です。`purpose` は短い人間向け説明（最大 180 バイト）で、**秘密鍵、パスワード、トークン、URL、アカウント詳細や承認指示を入れないでください**。`mode="reveal"` は将来の Mode 1 に対する確認提案であり `action` はありません。`mode="invoke"` は `hetzner.list_servers`、`coolify.list_applications`、`porkbun.list_domains` のいずれかが必須です。未知のフィールドを Keymaster に転送せず、未対応のアクションは拒否します。これらのツールはプロバイダに接続しません。

受信には所有者の Windows Keymaster デスクトップが実際に起動中である必要があります。**Credential vault → Review proposals in Windows** から**未認証**の保留リクエストを確認できます。Keymaster の画面は非秘密の受信イベントによって件数を自動更新します。React に提案内容を送信しません。受信箱はメモリ上にあり、アプリ終了で消えます。Windows 以外、または Keymaster 停止中は unavailable です。リモートプロキシや別の保管庫を作りません。

これは**ローカルでの確認提案配送**であり、リモート Grok Bot の本人確認ではありません。リモート Grok Bot automation と HTTP ブリッジからは Windows の名前付きパイプにアクセスできません。認証・所有者による個別権限・暗号化監査・Mode 1/Mode 2 実行・安全なリモート接続は今後の Keymaster 実装が必要です。

### Keymaster ネイティブ通信の互換性

Windows 専用のローカル Keymaster アダプターは、従来の非秘密パイプ応答と、新しい任意の `ackRequired:true` 応答の両方に対応します。新しい応答では、サイズ制限内の返信をすべて読み取った後に `KMA1` という固定の受信確認を送ります。これによりサーバー側の無期限フラッシュ待機を避け、起動中の旧版 Keymaster とも互換性を保ちます。この確認は AI の本人確認・権限・所有者の承認ではなく、秘密やプロバイダー操作も扱いません。
