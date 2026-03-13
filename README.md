# SpotifyPlaylistLab

SpotifyPlaylistLab は、Spotify
のライブラリ（主に「お気に入りの曲」）を分析し、\
BPM（tempo）だけでなく様々な **Audio Features**
を利用して自動でプレイリストを生成する Python ツールです。

ランニング用、掃除用、集中用など、**目的別プレイリスト**を自動生成することを目的としています。

------------------------------------------------------------------------

# 主な機能

-   Spotify API を使用して **お気に入りの曲 (Liked Songs)** を取得

-   Spotify の **Audio Features** を取得

-   曲を以下の要素で分析

    -   tempo (BPM)
    -   energy
    -   danceability
    -   valence（明るさ）
    -   acousticness
    -   instrumentalness
    -   speechiness
    -   liveness

-   ルールベースでプレイリストを自動生成

-   プレイリストを自動更新

------------------------------------------------------------------------

# 想定ユースケース

例：

  プレイリスト   条件例
  -------------- ------------------------------------
  Running        tempo \> 150 && energy \> 0.8
  Cleaning       tempo 110〜140 && valence \> 0.6
  Focus          instrumentalness \> 0.7
  Relax          tempo \< 90 && acousticness \> 0.5

これらの条件は **rules ファイルで自由に定義**できます。

------------------------------------------------------------------------

# ディレクトリ構成（例）

    SpotifyPlaylistLab
    │
    ├─ spotify_client.py
    ├─ collect_liked_songs.py
    ├─ analyze_tracks.py
    ├─ generate_playlists.py
    │
    ├─ rules
    │   ├─ running.yaml
    │   ├─ cleaning.yaml
    │   └─ focus.yaml
    │
    └─ data
        └─ tracks.json

------------------------------------------------------------------------

# 必要環境

Python 3.10 以上

推奨ライブラリ

    spotipy
    python-dotenv
    pandas
    pyyaml

インストール

    pip install spotipy python-dotenv pandas pyyaml

------------------------------------------------------------------------

# Spotify API の設定

1.  Spotify Developer Dashboard にアクセス

https://developer.spotify.com/dashboard

2.  アプリを作成

3.  以下の情報を取得

-   Client ID
-   Client Secret

4.  環境変数を設定

```{=html}
<!-- -->
```
    SPOTIFY_CLIENT_ID=your_client_id
    SPOTIFY_CLIENT_SECRET=your_client_secret
    SPOTIFY_REDIRECT_URI=http://localhost:8888/callback

------------------------------------------------------------------------

# 使い方

お気に入りの曲を取得

    python collect_liked_songs.py

曲の Audio Features を分析

    python analyze_tracks.py

プレイリスト生成

    python generate_playlists.py

------------------------------------------------------------------------

# 今後の拡張アイデア

-   BPMクラスタリング
-   ジャンル自動分類
-   ムード分類
-   自動プレイリスト更新（cron / GitHub Actions）
-   Web UI
-   AIによるプレイリスト生成

------------------------------------------------------------------------

# ライセンス

MIT
