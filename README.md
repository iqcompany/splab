# SpotifyPlaylistLab

Spotify のお気に入り曲をもとに、目的別プレイリストを自動生成する対話型 CLI ツールです。

- **generate**: お気に入り曲を YAML ルールでフィルタリングしてプレイリスト作成
- **auto**: Last.fm のタグデータベースから曲を探し、Spotify プレイリストとして登録

------------------------------------------------------------------------

## 必要環境

- Python 3.10 以上
- Spotify アカウント
- Last.fm API キー（auto / enrich 機能に必要）

```
pip install spotipy pyyaml python-dotenv
```

------------------------------------------------------------------------

## API キーの取得

### Spotify API

1. [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) にアクセス
2. 「Create App」でアプリを作成（Web API にチェック）
3. Settings > Redirect URIs に `https://127.0.0.1:8888/callback` を追加
4. Client ID と Client Secret をメモ

### Last.fm API

1. [Last.fm API アカウント作成ページ](https://www.last.fm/api/account/create) にアクセス
2. Application name に適当な名前を入力（例: `SpotifyPlaylistLab`）
3. Callback URL は空欄または `https://localhost` でOK
4. 「Submit」で API Key が発行される

### .env の設定

プロジェクトルートに `.env` ファイルを作成：

```
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=https://127.0.0.1:8888/callback
LASTFM_API_KEY=your_lastfm_api_key
```

------------------------------------------------------------------------

## ディレクトリ構成

```
SpotifyPlaylistLab/
├── splab.py              # メイン（対話型 CLI）
├── spotify_client.py     # Spotify API クライアント
├── rules/
│   ├── running.yaml      # generate 用ルール
│   ├── cleaning.yaml
│   ├── focus.yaml
│   ├── relax.yaml
│   ├── ...
│   └── auto/
│       ├── running.yaml  # auto 用ルール (Last.fm タグ検索)
│       ├── cleaning.yaml
│       ├── focus.yaml
│       └── relax.yaml
├── data/
│   └── tracks.json       # 取得したお気に入り曲データ
└── .env                  # API 認証情報
```

------------------------------------------------------------------------

## 使い方

### 起動

```
python splab.py
```

初回はブラウザで Spotify 認証が必要です。

### コマンド一覧

| コマンド | 説明 |
|---------|------|
| `fetch` | お気に入り曲を Spotify から取得して保存 |
| `load` | 保存済みの曲データを読み込む |
| `enrich [force]` | Last.fm からタグ・再生回数を取得 |
| `liked [N]` | お気に入り曲を一覧表示（N件） |
| `search キーワード` | 曲名・アーティスト・アルバムで検索 |
| `stats` | ライブラリの統計情報（タグ分布含む） |
| `rules` | ルールファイル一覧と内容を表示 |
| `generate [名/all]` | お気に入りからルールでプレイリスト生成 |
| `auto [名/all]` | Last.fm タグ検索でプレイリスト生成 |
| `discover [N+/N-]` | お気に入りアーティストの未発見曲を検索 |
| `discover similar [アーティスト/N+/N-]` | 似たアーティストの曲を検索 |
| `preview [名]` | 生成済みプレイリストの全曲を確認 |
| `apply [名/all]` | Spotify にプレイリスト反映 |
| `playlists` | Spotify プレイリスト一覧 |
| `help` | コマンド一覧を表示 |
| `quit` | 終了 |

### 基本的な流れ

```
splab> fetch                  # 1. お気に入り曲を取得
splab> enrich                 # 2. Last.fm からタグ情報を取得（約2分）
splab> stats                  # 3. タグ分布などの統計を確認
splab> rules                  # 4. ルール内容を確認
splab> generate all           # 5. 全ルールでプレイリスト生成
splab> auto all               # 6. Last.fm タグ検索でプレイリスト生成
splab> preview Running        # 7. 特定プレイリストの全曲を確認
splab> apply all              # 8. 全プレイリストを Spotify に反映
splab> playlists              # 9. Spotify で確認
```

------------------------------------------------------------------------

## ルールファイルの書き方

### generate ルール (`rules/*.yaml`)

お気に入り曲をフィルタリングしてプレイリストを作成します。

#### type: filter（デフォルト）

曲のメタデータとタグで絞り込み：

```yaml
playlist_name: "Running"
description: "ランニング用 - アップテンポなロック・エレクトロ系"
max_duration_min: 5
tags_include: ["rock", "electronic", "dance", "punk"]
```

使用可能なフィルタ条件：

| パラメータ | 説明 |
|-----------|------|
| `artist_include` | アーティスト名に含むキーワード（OR） |
| `artist_exclude` | アーティスト名に含むキーワードを除外 |
| `name_include` | 曲名に含むキーワード（OR） |
| `album_include` | アルバム名に含むキーワード（OR） |
| `min_duration_min` | 最小曲長（分） |
| `max_duration_min` | 最大曲長（分） |
| `tags_include` | Last.fm タグに一致するもの（OR）※enrich 必要 |
| `tags_exclude` | Last.fm タグに一致するものを除外 ※enrich 必要 |
| `min_playcount` | Last.fm 最小再生回数 ※enrich 必要 |
| `explicit` | true/false で明示的コンテンツをフィルタ |
| `limit` | 最大曲数 |

#### type: artist_count

アーティストのお気に入り曲数で絞り込み：

```yaml
playlist_name: "Core Favorites"
description: "お気に入りアーティストの曲"
type: artist_count
min_artist_tracks: 3
```

#### type: duration

曲の長さで絞り込み：

```yaml
playlist_name: "Short & Sweet"
description: "3分以下のサクッと聴ける曲"
type: duration
max_minutes: 3
```

#### type: album_count

同じアルバムからの曲数で絞り込み：

```yaml
playlist_name: "Album Dives"
description: "同じアルバムから3曲以上お気に入りしたアルバム"
type: album_count
min_album_tracks: 3
```

### auto ルール (`rules/auto/*.yaml`)

Last.fm のタグデータベースから曲を検索し、Spotify で見つけてプレイリストに追加します。
お気に入りに入っていない新しい曲を発見できます。

```yaml
playlist_name: "Auto: Running"
description: "ランニング用 - EDM・ダンス系の高エネルギー曲"
tags:
  - "edm"
  - "dance"
  - "electronic"
  - "workout"
tracks_per_tag: 15
limit: 50
```

| パラメータ | 説明 |
|-----------|------|
| `tags` | Last.fm タグ（ジャンル/ムード）のリスト |
| `tracks_per_tag` | タグごとの取得曲数（デフォルト 20） |
| `limit` | プレイリスト最大曲数（デフォルト 50） |
| `exclude_liked` | true でお気に入り済みの曲を除外 |
| `min_duration_min` | 最小曲長（分） |
| `max_duration_min` | 最大曲長（分） |
| `artist_exclude` | 除外するアーティスト名のリスト |
| `tags_exclude` | 除外するタグのリスト（Last.fm で確認） |

------------------------------------------------------------------------

## 同梱ルール

### generate ルール

| ファイル | プレイリスト名 | 内容 |
|---------|--------------|------|
| running.yaml | Running | アップテンポなロック・エレクトロ系 |
| cleaning.yaml | Cleaning | ポップ・ファンク・ディスコ系 |
| focus.yaml | Focus | インスト・アンビエント・長めの曲 |
| relax.yaml | Relax | アコースティック・チル系 |
| core_favorites.yaml | Core Favorites | 3曲以上お気に入りしたアーティスト |
| discovery.yaml | Discovery | 1曲だけの新規開拓アーティスト |
| hidden_gems.yaml | Hidden Gems | 少数派アーティストの曲 |
| hits.yaml | Hits | よく聴くアーティストの曲 |
| short_and_sweet.yaml | Short & Sweet | 3分以下の曲 |
| long_listens.yaml | Long Listens | 6分以上の曲 |
| album_dives.yaml | Album Dives | 同アルバムから3曲以上 |
| chill_rock.yaml | Chill Rock | オルタナ・インディー系ロック（メタル除外） |
| kpop.yaml | K-POP | K-POP・Korean 系 |
| electro_pop.yaml | Electro Pop | エレクトロポップ・シンセポップ系 |
| emo_punk.yaml | Emo & Punk | エモ・パンク・ポップパンク系 |
| heavy.yaml | Heavy | メタル・ニューメタル・ハードロック系 |
| hiphop_rnb.yaml | Hip-Hop & R&B | ヒップホップ・R&B・ラップ系 |
| party.yaml | Party | パーティー・ダンス・ディスコ系 |

### auto ルール

| ファイル | プレイリスト名 | 検索タグ |
|---------|--------------|---------|
| running.yaml | Auto: Running | edm, dance, electronic, workout |
| cleaning.yaml | Auto: Cleaning | pop, funk, disco, dance pop |
| focus.yaml | Auto: Focus | ambient, classical, lo-fi, instrumental |
| relax.yaml | Auto: Relax | acoustic, chill, jazz, bossa nova |

------------------------------------------------------------------------

## discover コマンド

お気に入りアーティストの未発見曲や、似たアーティストの曲を探すコマンドです。
Last.fm API を使って類似アーティストを検索し、Spotify で曲を見つけます。

### discover [N+/N-]

お気に入りアーティストの、まだお気に入りに入っていない曲を検索します。

```
splab> discover          # 3曲以上お気に入りしたアーティスト
splab> discover 5+       # 5曲以上お気に入りしたアーティスト
splab> discover 2-       # 2曲以下のアーティスト（新規開拓向き）
```

### discover similar [アーティスト/N+/N-]

Last.fm の類似アーティスト機能を使って、似たテイストの曲を探します。

```
splab> discover similar          # 3曲以上のアーティストの類似
splab> discover similar Muse     # Muse に似たアーティストの曲
splab> discover similar 5+       # 5曲以上のアーティストの類似
splab> discover similar 1-       # 1曲以下のアーティストの類似
```

- 対象アーティストが多い場合、自動的にランダムで最大30組（discover）/ 15組（similar）に絞ります
- Last.fm のレート制限に達した場合、Spotify 検索にフォールバックします

------------------------------------------------------------------------

## enrich について

`enrich` コマンドは Last.fm API を使って、お気に入り曲にタグ（ジャンル/ムード）と再生回数を付与します。

- 初回実行で全曲を処理（632曲で約2分）
- 結果は `data/tracks.json` に保存され、次回起動時に自動読み込み
- 新しく追加した曲だけ差分取得（`enrich force` で全曲再取得）

enrich 後は `stats` コマンドでタグ分布が確認でき、ルールで `tags_include` / `tags_exclude` が使えるようになります。

------------------------------------------------------------------------

## ライセンス

MIT
