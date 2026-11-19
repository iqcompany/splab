# SpotifyPlaylistLab

Spotify のお気に入り曲をもとに、目的別プレイリストを自動生成する対話型 CLI ツールです。

- **generate**: お気に入り曲を YAML ルールでフィルタリングしてプレイリスト作成
- **auto**: Last.fm のタグデータベースから曲を探し、Spotify プレイリストとして登録
- **seasonal**: 季節ごとに、最近のお気に入りとおすすめの曲を混ぜた詩的なプレイリストを作成（cron で自動化できる）

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
├── seasonal.py           # seasonal の曲の選び方・タイトルの作り方
├── tests/                # python -m unittest discover -s tests
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
│   ├── tracks.json       # 取得したお気に入り曲データ
│   ├── seasonal_state.json  # seasonal の実行記録・フォロー一覧の記録
│   └── seasonal_plan.json   # seasonal で最後に作った（作る予定の）一覧
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
| `seasonal [オプション]` | 季節ごとの詩的なプレイリストを作成（[詳しく](#seasonal-コマンド季節ごとの詩的なプレイリスト)） |
| `login` | フォロー一覧も読めるスコープでログインし直す |
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

## seasonal コマンド（季節ごとの詩的なプレイリスト）

数か月ごとに、その季節の「いま好きな曲」と「まだお気に入りに入れていないおすすめの曲」を混ぜた、約 100 曲のプレイリストを作ります。タイトルは、季節（JST の日付）と曲の雰囲気（Last.fm のタグ）から作ります（例: `Amber & Afterglow`、`Disco in the Dusk`、`Starlight in Slow Motion`）。

```
splab> seasonal --dry-run     # 作る予定の一覧だけ見る（Spotify には作らない）
splab> seasonal               # 一覧を見て、y で Spotify に作る
```

```
python splab.py seasonal --dry-run   # 対話なしで一覧だけ
python splab.py seasonal --yes       # 対話なしで作る（cron 用）
```

### 曲の選び方（100 曲の場合）

| 枠 | 曲数 | 選び方 |
|----|-----:|--------|
| お気に入り: 最近追加した曲 | 20 | 前回の実行から（初回は 90 日以内）お気に入りに追加した曲。新しい順 |
| お気に入り: 最近リリースされた曲 | 15 | リリースから 180 日以内の曲 |
| お気に入り: 最近フォローしたアーティストの曲 | 15 | 最近フォローした（または、初めてお気に入りに入れた）アーティストの曲 |
| おすすめ（お気に入りにない曲） | 50 | 上で選んだ曲に似た曲（Last.fm `track.getSimilar`）、最近フォローしたアーティストの人気曲、似ているアーティストの人気曲。同じアーティストは 2 曲まで |

- ある枠の曲が足りない時は、ほかの枠の残りで埋めます。
- お気に入りとおすすめは、交互に並べます。
- Spotify の recommendations / audio-features API は新しいアプリでは使えないため、おすすめと雰囲気の判定は Last.fm で行います。

### オプション

| オプション | 説明 |
|-----------|------|
| `--yes` | 確認なしで Spotify に作る |
| `--dry-run` | 一覧を表示して `data/seasonal_plan.json` に保存するだけ |
| `--size N` | 全体の曲数（デフォルト 100） |
| `--fav-ratio R` | お気に入りの割合（デフォルト 0.5） |
| `--days N` | 「最近追加」「最近フォロー」の期間（デフォルト 90。前回の実行があればそこから） |
| `--release-days N` | 「最近リリース」の期間（デフォルト 180） |
| `--name 名前` | タイトルを自分で決める |
| `--no-fetch` | お気に入りを取り直さず、`data/tracks.json` を使う |
| `--force` | 同じ季節にもう作っていても、もう1つ作る |

### タイトル

- 季節（12〜2月: 冬、3〜5月: 春、6〜8月: 夏、9〜11月: 秋）の言葉と、雰囲気（明るく踊れる・ギターが鳴る・夢見心地・しっとり）の言葉を組み合わせます。頭の音がそろう組み合わせ（Sunshine in Stereo のような）を優先します。
- 自分の Spotify のプレイリスト（全件）と、過去に seasonal で作った名前とは、重ならないようにします。
- LLM は使いません（API キーがいらず、cron でも同じように動きます）。

### 最近フォローしたアーティスト（スコープの追加）

Spotify はフォローした日付を返さないので、フォロー一覧を `data/seasonal_state.json` に記録し、前回との差分で「最近フォローした」を判定します（記録を始めた時のフォローは「いつか分からない」扱い）。

フォロー一覧を読むには `user-follow-read` スコープが要ります。一度だけ、ブラウザが使える PC でログインし直してください。

```
python splab.py login     # ブラウザで許可 → .cache ができる
```

できた `.cache` を、splab を動かす場所にコピーします。スコープを足していない `.cache` のままでも動き、その時は「初めてお気に入りに入れたアーティスト」を代わりに使います。

### 定期実行（cron）

季節の始め（3・6・9・12 月の 1 日 9:00 JST）に作る例です。同じ季節に2回は作らないので、再実行しても重複しません。

```
# cron の時刻が UTC の場合（9:00 JST = 0:00 UTC）
0 0 1 3,6,9,12 * cd /path/to/splab && .venv/bin/python splab.py seasonal --yes >> data/seasonal.log 2>&1
```

- `.cache`（トークン）は `cd` した場所から読むので、必ず splab のフォルダに `cd` してから実行します。

- 対話なしの時は、ブラウザでのログインを待ちません。トークンがない・更新できない時は、終了コード 2 で止まり、ログに「手元の PC で `python splab.py login` を実行し、.cache をコピーする」と書きます。
- Spotify のリフレッシュトークンは、アプリの許可を取り消さない限り、ふだんは使い続けられます。
- 終了コード: 0 = 作成した（か、この季節は作成済みでスキップ）、1 = 失敗、2 = ログインが要る。
- cron と手動の実行が重ならないよう、`data/seasonal.lock` でロックします（実行中なら、あとの方は終了コード 1 で止まります）。
- プレイリストを作ったあと、曲の追加の途中で失敗した時は、次の実行がそのプレイリストに残りの曲を追加して完了にします（同じ名前のプレイリストを作り直しません）。

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
