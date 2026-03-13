"""SpotifyPlaylistLab - 対話型プレイリスト生成ツール."""

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from dotenv import load_dotenv

from spotify_client import get_spotify_client

load_dotenv()
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")

DATA_DIR = "data"
DATA_FILE = os.path.join(DATA_DIR, "tracks.json")
RULES_DIR = "rules"

# 状態管理
sp = None
user_id = None
liked_tracks: list[dict] = []
generated: dict[str, list[dict]] = {}  # プレイリスト名 -> 曲リスト


# ── ユーティリティ ──────────────────────────────────────


def ensure_login():
    global sp, user_id
    if sp is None:
        print("Spotify にログイン中...")
        sp = get_spotify_client()
        user_id = sp.current_user()["id"]
        print(f"ログイン成功: {user_id}")


def ensure_liked():
    if not liked_tracks:
        print("先に fetch を実行してお気に入り曲を取得してください。")
        return False
    return True


def _fmt_duration(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def _print_track(i: int, t: dict):
    dur = _fmt_duration(t.get("duration_ms", 0))
    tags = t.get("tags", [])
    tag_str = f"  [{', '.join(tags[:3])}]" if tags else ""
    print(f"  {i:3d}. {t['artist']} - {t['name']}  ({dur}){tag_str}")


def _save_tracks():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(liked_tracks, f, ensure_ascii=False, indent=2)


def _build_stats() -> tuple[dict[str, int], dict[str, list[dict]], list[int]]:
    """集計データを構築."""
    artist_count: dict[str, int] = {}
    for t in liked_tracks:
        for a in t["artist"].split(", "):
            artist_count[a] = artist_count.get(a, 0) + 1

    album_tracks: dict[str, list[dict]] = {}
    for t in liked_tracks:
        key = f"{t['artist']} - {t.get('album', '')}"
        album_tracks.setdefault(key, []).append(t)

    return artist_count, album_tracks


# ── ルールエンジン ──────────────────────────────────────


def _apply_rule(rule: dict, artist_count: dict, album_tracks: dict) -> list[dict]:
    """ルール1件を適用してマッチ曲リストを返す."""
    rule_type = rule.get("type", "filter")

    if rule_type == "filter":
        return [t for t in liked_tracks if _match_filter(t, rule)]

    elif rule_type == "artist_count":
        min_t = rule.get("min_artist_tracks")
        max_t = rule.get("max_artist_tracks")
        if min_t is not None:
            target = {a for a, c in artist_count.items() if c >= min_t}
            return [t for t in liked_tracks
                    if any(a in target for a in t["artist"].split(", "))]
        elif max_t is not None:
            target = {a for a, c in artist_count.items() if c <= max_t}
            return [t for t in liked_tracks
                    if all(a in target for a in t["artist"].split(", "))]

    elif rule_type == "duration":
        min_min = rule.get("min_minutes")
        max_min = rule.get("max_minutes")
        result = list(liked_tracks)
        if min_min is not None:
            result = [t for t in result if t.get("duration_ms", 0) >= min_min * 60000]
        if max_min is not None:
            result = [t for t in result if t.get("duration_ms", 0) <= max_min * 60000]
        return result

    elif rule_type == "album_count":
        min_t = rule.get("min_album_tracks", 3)
        result = []
        for key, tracks in album_tracks.items():
            if len(tracks) >= min_t:
                result.extend(tracks)
        return result

    return []


def _match_filter(track: dict, rule: dict) -> bool:
    """type: filter 用のマッチ判定."""
    artist_include = rule.get("artist_include", [])
    if artist_include:
        if not any(kw.lower() in track["artist"].lower() for kw in artist_include):
            return False

    artist_exclude = rule.get("artist_exclude", [])
    if artist_exclude:
        if any(kw.lower() in track["artist"].lower() for kw in artist_exclude):
            return False

    name_include = rule.get("name_include", [])
    if name_include:
        if not any(kw.lower() in track["name"].lower() for kw in name_include):
            return False

    album_include = rule.get("album_include", [])
    if album_include:
        if not any(kw.lower() in track.get("album", "").lower() for kw in album_include):
            return False

    dur_min = track.get("duration_ms", 0) / 60000
    if rule.get("min_duration_min") is not None and dur_min < rule["min_duration_min"]:
        return False
    if rule.get("max_duration_min") is not None and dur_min > rule["max_duration_min"]:
        return False

    if "explicit" in rule:
        if track.get("explicit") != rule["explicit"]:
            return False

    tags_include = rule.get("tags_include", [])
    if tags_include:
        track_tags = [t.lower() for t in track.get("tags", [])]
        if not any(tag.lower() in track_tags for tag in tags_include):
            return False

    tags_exclude = rule.get("tags_exclude", [])
    if tags_exclude:
        track_tags = [t.lower() for t in track.get("tags", [])]
        if any(tag.lower() in track_tags for tag in tags_exclude):
            return False

    if rule.get("min_playcount") is not None:
        if track.get("playcount", 0) < rule["min_playcount"]:
            return False

    return True


# ── Last.fm ───────────────────────────────────────────


class RateLimitError(Exception):
    """Last.fm レート制限エラー."""

    def is_long_wait(self) -> bool:
        """Retry が長時間（60秒以上）のレート制限か判定."""
        import re
        m = re.search(r"Retry will occur after:\s*(\d+)", str(self))
        return m is not None and int(m.group(1)) > 60


def _lastfm_get(method: str, **params) -> dict:
    """Last.fm API を呼び出す."""
    params.update({"method": method, "api_key": LASTFM_API_KEY, "format": "json"})
    url = "https://ws.audioscrobbler.com/2.0/?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 429 or "rate" in body.lower() or "retry" in body.lower():
            raise RateLimitError(f"HTTP {e.code}: {body[:200]}")
        raise
    if "error" in data:
        if data.get("error") == 29:
            raise RateLimitError(data.get("message", "Rate limit exceeded"))
        msg = data.get("message", "")
        if "rate" in msg.lower() or "retry" in msg.lower():
            raise RateLimitError(msg)
    return data


def _lastfm_track_info(artist: str, track: str) -> tuple[list[str], int]:
    """Last.fm から曲のタグと再生回数を取得. RateLimitError は呼び出し元に伝播."""
    try:
        data = _lastfm_get("track.getInfo", artist=artist, track=track)
        info = data.get("track", {})
        playcount = int(info.get("playcount", 0))
        tags = [t["name"].lower() for t in info.get("toptags", {}).get("tag", [])]
        return tags, playcount
    except RateLimitError:
        raise
    except Exception:
        return [], 0


# ── コマンド実装 ────────────────────────────────────────


def cmd_fetch():
    """お気に入りの曲を Spotify から取得."""
    global liked_tracks
    ensure_login()

    tracks = []
    offset = 0
    print("お気に入りの曲を取得中...")
    while True:
        results = sp.current_user_saved_tracks(limit=50, offset=offset)
        items = results["items"]
        if not items:
            break
        for item in items:
            t = item["track"]
            tracks.append({
                "id": t["id"],
                "name": t["name"],
                "artist": ", ".join(a["name"] for a in t["artists"]),
                "album": t["album"]["name"],
                "uri": t["uri"],
                "duration_ms": t.get("duration_ms", 0),
                "explicit": t.get("explicit", False),
            })
        offset += 50
        print(f"  {len(tracks)} 曲取得済み...")

    liked_tracks = tracks
    _save_tracks()
    print(f"合計 {len(tracks)} 曲を取得・保存しました。")


def cmd_load():
    """保存済みの tracks.json を読み込む."""
    global liked_tracks
    if not os.path.exists(DATA_FILE):
        print(f"{DATA_FILE} が見つかりません。先に fetch を実行してください。")
        return
    with open(DATA_FILE, encoding="utf-8") as f:
        liked_tracks = json.load(f)
    print(f"{len(liked_tracks)} 曲を読み込みました。")


def cmd_enrich(args: str):
    """Last.fm からタグ・再生回数を取得して曲データを拡充."""
    if not ensure_liked():
        return
    if not LASTFM_API_KEY:
        print("LASTFM_API_KEY が .env に設定されていません。")
        print("https://www.last.fm/api/account/create で API key を取得してください。")
        return

    # 未取得の曲だけ処理 (force で全曲再取得)
    force = args.strip().lower() == "force" if args else False
    targets = liked_tracks if force else [t for t in liked_tracks if "tags" not in t]

    if not targets:
        print("全曲のタグ情報は取得済みです。(enrich force で再取得)")
        return

    print(f"Last.fm からタグ情報を取得中... ({len(targets)} 曲)")
    enriched = 0
    rate_limited = False
    for i, t in enumerate(targets, 1):
        artist = t["artist"].split(", ")[0]
        if not rate_limited:
            try:
                tags, playcount = _lastfm_track_info(artist, t["name"])
            except RateLimitError as e:
                if e.is_long_wait():
                    print(f"\n  Last.fm レート制限（長時間）: {e}")
                    print("  処理を中断します。後で enrich を再実行してください。")
                    _save_tracks()
                    return
                print(f"\n  Last.fm レート制限に達しました。残りはスキップします。")
                rate_limited = True
                _save_tracks()
                break
        else:
            break
        t["tags"] = tags
        t["playcount"] = playcount
        enriched += 1

        if i % 50 == 0 or i == len(targets):
            _save_tracks()  # 50曲ごとに途中保存
            print(f"  {i}/{len(targets)} 処理済み...")

        time.sleep(0.2)

    _save_tracks()
    print(f"{enriched} 曲のタグ情報を取得・保存しました。")
    if rate_limited:
        print("  (一部タグ未取得。後で enrich を再実行すると差分取得できます)")

    # タグ集計を表示
    tag_count: dict[str, int] = {}
    for t in liked_tracks:
        for tag in t.get("tags", []):
            tag_count[tag] = tag_count.get(tag, 0) + 1
    top_tags = sorted(tag_count.items(), key=lambda x: -x[1])[:20]
    if top_tags:
        print(f"\n  よく出るタグ (Top 20):")
        for tag, c in top_tags:
            print(f"    {c:3d} 曲  {tag}")


def cmd_liked(args: str):
    """お気に入り曲の一覧を表示. 引数: 表示件数 (デフォルト 20)."""
    if not ensure_liked():
        return
    try:
        n = int(args) if args else 20
    except ValueError:
        n = 20
    print(f"\n--- お気に入り曲 (全 {len(liked_tracks)} 曲中 先頭 {n} 件) ---")
    for i, t in enumerate(liked_tracks[:n], 1):
        _print_track(i, t)
    if len(liked_tracks) > n:
        print(f"  ... 他 {len(liked_tracks) - n} 曲")


def cmd_search(args: str):
    """お気に入り曲をキーワード検索 (曲名・アーティスト名・アルバム名)."""
    if not ensure_liked():
        return
    if not args:
        print("使い方: search <キーワード>")
        return

    keyword = args.lower()
    results = []
    for t in liked_tracks:
        if (keyword in t["name"].lower()
                or keyword in t["artist"].lower()
                or keyword in t.get("album", "").lower()):
            results.append(t)

    print(f"\n--- 検索結果: '{args}' ({len(results)} 曲) ---")
    for i, t in enumerate(results[:30], 1):
        _print_track(i, t)
    if len(results) > 30:
        print(f"  ... 他 {len(results) - 30} 曲")


def cmd_stats():
    """ライブラリの統計情報を表示."""
    if not ensure_liked():
        return

    durs = [t.get("duration_ms", 0) for t in liked_tracks]
    avg_dur = sum(durs) / len(durs) if durs else 0

    artist_count: dict[str, int] = {}
    for t in liked_tracks:
        for a in t["artist"].split(", "):
            artist_count[a] = artist_count.get(a, 0) + 1
    top_artists = sorted(artist_count.items(), key=lambda x: -x[1])[:15]

    dur_buckets = {"~3分": 0, "3~5分": 0, "5~7分": 0, "7分~": 0}
    for d in durs:
        m = d / 60000
        if m < 3:
            dur_buckets["~3分"] += 1
        elif m < 5:
            dur_buckets["3~5分"] += 1
        elif m < 7:
            dur_buckets["5~7分"] += 1
        else:
            dur_buckets["7分~"] += 1

    print(f"\n--- ライブラリ統計 ---")
    print(f"  総曲数: {len(liked_tracks)}")
    print(f"  平均曲長: {_fmt_duration(int(avg_dur))}")
    print(f"  アーティスト数: {len(artist_count)}")
    print(f"  曲長分布:")
    for label, count in dur_buckets.items():
        print(f"    {label}: {count} 曲")
    print(f"\n  よく聴くアーティスト (Top 15):")
    for a, c in top_artists:
        print(f"    {c:3d} 曲  {a}")

    # タグ統計 (enrich済みの場合)
    tag_count: dict[str, int] = {}
    for t in liked_tracks:
        for tag in t.get("tags", []):
            tag_count[tag] = tag_count.get(tag, 0) + 1
    if tag_count:
        top_tags = sorted(tag_count.items(), key=lambda x: -x[1])[:15]
        print(f"\n  よく出るタグ (Top 15):")
        for tag, c in top_tags:
            print(f"    {c:3d} 曲  {tag}")


def cmd_rules():
    """ルールファイルの一覧と内容を表示."""
    paths = sorted(Path(RULES_DIR).glob("*.yaml"))
    auto_dir = Path(RULES_DIR) / "auto"
    auto_paths = sorted(auto_dir.glob("*.yaml")) if auto_dir.exists() else []
    if not paths and not auto_paths:
        print("rules/ ディレクトリにルールファイルがありません。")
        return
    print(f"\n--- generate ルール ({len(paths)} 件) ---")
    for path in paths:
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        name = rule.get("playlist_name", path.stem)
        desc = rule.get("description", "")
        rtype = rule.get("type", "filter")
        print(f"\n  [{name}] {desc}  (type: {rtype})")

        # type 別パラメータ表示
        if rtype == "filter":
            for key in ("artist_include", "artist_exclude", "name_include", "album_include"):
                if rule.get(key):
                    print(f"    {key}: {', '.join(rule[key])}")
            for key in ("min_duration_min", "max_duration_min", "min_playcount"):
                if rule.get(key) is not None:
                    print(f"    {key}: {rule[key]}")
            for key in ("tags_include", "tags_exclude"):
                if rule.get(key):
                    print(f"    {key}: {', '.join(rule[key])}")
        elif rtype == "artist_count":
            for key in ("min_artist_tracks", "max_artist_tracks"):
                if rule.get(key) is not None:
                    print(f"    {key}: {rule[key]}")
        elif rtype == "duration":
            for key in ("min_minutes", "max_minutes"):
                if rule.get(key) is not None:
                    print(f"    {key}: {rule[key]}")
        elif rtype == "album_count":
            if rule.get("min_album_tracks") is not None:
                print(f"    min_album_tracks: {rule['min_album_tracks']}")

        if rule.get("limit"):
            print(f"    limit: {rule['limit']}")

    if auto_paths:
        print(f"\n--- auto ルール ({len(auto_paths)} 件) ---")
        for path in auto_paths:
            with open(path, encoding="utf-8") as f:
                rule = yaml.safe_load(f)
            name = rule.get("playlist_name", path.stem)
            desc = rule.get("description", "")
            tags = rule.get("tags", rule.get("queries", []))
            limit = rule.get("limit", 50)
            print(f"\n  [{name}] {desc}")
            print(f"    tags: {', '.join(tags)}")
            if rule.get("tags_exclude"):
                print(f"    tags_exclude: {', '.join(rule['tags_exclude'])}")
            if rule.get("artist_exclude"):
                print(f"    artist_exclude: {', '.join(rule['artist_exclude'])}")
            if rule.get("exclude_liked"):
                print(f"    exclude_liked: true")
            for key in ("min_duration_min", "max_duration_min"):
                if rule.get(key) is not None:
                    print(f"    {key}: {rule[key]}")
            print(f"    limit: {limit}")


def cmd_generate(args: str):
    """ルールに基づいてプレイリスト生成. 引数: ルール名 / all."""
    if not ensure_liked():
        return

    paths = sorted(Path(RULES_DIR).glob("*.yaml"))
    rules = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
        rule["_file"] = path.stem
        rules.append(rule)

    if not rules:
        print("rules/ ディレクトリにルールファイルがありません。")
        return

    if args and args.lower() != "all":
        rules = [r for r in rules if r["_file"] == args or r.get("playlist_name") == args]
        if not rules:
            print(f"ルール '{args}' が見つかりません。rules コマンドで確認してください。")
            return

    artist_count, album_tracks = _build_stats()

    for rule in rules:
        name = rule["playlist_name"]
        limit = rule.get("limit")

        matched = _apply_rule(rule, artist_count, album_tracks)
        if limit:
            matched = matched[:limit]

        generated[name] = matched
        print(f"\n[{name}] {len(matched)} 曲がマッチしました。")

        for i, t in enumerate(matched[:10], 1):
            _print_track(i, t)
        if len(matched) > 10:
            print(f"    ... 他 {len(matched) - 10} 曲")

    print(f"\nプレビュー完了。apply コマンドで Spotify に反映できます。")


def cmd_preview(args: str):
    """生成済みプレイリストの全曲を表示. 引数: プレイリスト名."""
    if not generated:
        print("先に generate を実行してください。")
        return
    if args and args in generated:
        tracks = generated[args]
        print(f"\n--- [{args}] 全 {len(tracks)} 曲 ---")
        for i, t in enumerate(tracks, 1):
            _print_track(i, t)
    else:
        print(f"\n--- 生成済みプレイリスト ---")
        for name, tracks in generated.items():
            print(f"  [{name}] {len(tracks)} 曲")
        print("\n詳細を見るには: preview <プレイリスト名>")


def cmd_apply(args: str):
    """生成済みプレイリストを Spotify に反映. 引数: プレイリスト名 / all."""
    if not generated:
        print("先に generate を実行してください。")
        return
    ensure_login()

    targets = {}
    if args and args.lower() != "all":
        if args not in generated:
            print(f"'{args}' は生成されていません。preview で確認してください。")
            return
        targets[args] = generated[args]
    else:
        targets = dict(generated)

    # 確認
    print("\n以下のプレイリストを Spotify に反映します:")
    for name, tracks in targets.items():
        print(f"  [{name}] {len(tracks)} 曲")
    answer = input("\n実行しますか？ (y/n): ").strip().lower()
    if answer not in ("y", "yes"):
        print("キャンセルしました。")
        return

    for name, tracks in targets.items():
        if not tracks:
            print(f"  [{name}] 曲がないためスキップ。")
            continue

        uris = [t["uri"] for t in tracks]

        # 既存プレイリスト検索
        playlists = sp.current_user_playlists(limit=50)
        playlist_id = None
        for pl in playlists["items"]:
            if pl["name"] == name and pl["owner"]["id"] == user_id:
                playlist_id = pl["id"]
                break

        if playlist_id:
            sp.playlist_replace_items(playlist_id, [])
            action = "更新"
        else:
            result = sp._post("me/playlists", payload={
                "name": name,
                "public": False,
                "description": "",
            })
            playlist_id = result["id"]
            action = "作成"

        for i in range(0, len(uris), 100):
            sp.playlist_add_items(playlist_id, uris[i : i + 100])

        print(f"  [{name}] {len(uris)} 曲を{action}しました。")

    print("\nSpotify への反映が完了しました！")


def cmd_discover(args: str):
    """お気に入りアーティストの未発見曲 / 似たアーティストの曲を探す."""
    ensure_login()

    if not LASTFM_API_KEY:
        print("LASTFM_API_KEY が .env に設定されていません。")
        return

    # サブコマンド判定
    parts = args.strip().split(maxsplit=1) if args else []
    subcmd = parts[0].lower() if parts else ""
    sub_args = parts[1] if len(parts) > 1 else ""

    if subcmd == "similar":
        _discover_similar(sub_args)
    else:
        _discover_tracks(args)


def _discover_tracks(args: str):
    """お気に入りアーティストの未発見曲を探す."""
    if not ensure_liked():
        return

    # お気に入りアーティストの曲数を集計
    artist_count: dict[str, int] = {}
    for t in liked_tracks:
        for a in t["artist"].split(", "):
            artist_count[a] = artist_count.get(a, 0) + 1

    # 引数: "3" or "3+" = 3曲以上, "3-" = 3曲以下
    mode = "min"
    threshold = 3
    if args:
        args = args.strip()
        if args.endswith("-"):
            mode = "max"
            threshold = int(args[:-1])
        elif args.endswith("+"):
            threshold = int(args[:-1])
        else:
            try:
                threshold = int(args)
            except ValueError:
                threshold = 3

    if mode == "min":
        target_artists = [a for a, c in sorted(artist_count.items(), key=lambda x: -x[1]) if c >= threshold]
        label = f"{threshold} 曲以上"
    else:
        target_artists = [a for a, c in sorted(artist_count.items(), key=lambda x: -x[1]) if c <= threshold]
        label = f"{threshold} 曲以下"

    import random
    # 上限30組（多すぎるとレート制限に引っかかる）
    max_artists = 30
    if len(target_artists) > max_artists:
        print(f"\n対象 {len(target_artists)} 組 → ランダムに {max_artists} 組を選択")
        target_artists = random.sample(target_artists, max_artists)

    if not target_artists:
        print(f"お気に入り {label} のアーティストがいません。")
        return

    print(f"\nお気に入り {label} のアーティスト ({len(target_artists)} 組) の未発見曲を検索中...")

    liked_ids = {t["id"] for t in liked_tracks}
    liked_keys = {f"{t['artist'].split(', ')[0].lower()}|{t['name'].lower()}" for t in liked_tracks}

    found_tracks = []
    seen_ids = set()

    for artist in target_artists:
        try:
            data = _lastfm_get("artist.getTopTracks", artist=artist, limit=10)
            tracks = data.get("toptracks", {}).get("track", [])
        except RateLimitError as e:
            if e.is_long_wait():
                print(f"\n  Last.fm レート制限（長時間）: {e}")
                print("  コマンドを終了します。")
                return
            print(f"\n  Last.fm レート制限 - Spotify 直接検索に切り替えます")
            # Last.fm が使えない場合は Spotify で検索
            try:
                results = sp.search(q=f"artist:{artist}", type="track", limit=10)
                items = results.get("tracks", {}).get("items", [])
                for item in items:
                    if item["id"] not in liked_ids and item["id"] not in seen_ids:
                        seen_ids.add(item["id"])
                        found_tracks.append({
                            "id": item["id"],
                            "name": item["name"],
                            "artist": ", ".join(a["name"] for a in item["artists"]),
                            "album": item["album"]["name"],
                            "uri": item["uri"],
                            "duration_ms": item.get("duration_ms", 0),
                        })
                        time.sleep(0.2)
            except Exception:
                pass
            continue
        except Exception:
            tracks = []

        new_count = 0
        for lt in tracks:
            lt_name = lt.get("name", "")
            key = f"{artist.lower()}|{lt_name.lower()}"
            if key in liked_keys:
                continue

            track = _spotify_search_track(artist, lt_name)
            if not track or track["id"] in liked_ids or track["id"] in seen_ids:
                time.sleep(0.2)
                continue

            seen_ids.add(track["id"])
            found_tracks.append(track)
            new_count += 1
            time.sleep(0.2)

        if new_count > 0:
            print(f"    {artist}: {new_count} 曲発見")
        time.sleep(0.3)  # アーティスト間の間隔

    playlist_name = "Discover: My Artists"
    generated[playlist_name] = found_tracks

    print(f"\n[{playlist_name}] {len(found_tracks)} 曲が見つかりました。")
    for i, t in enumerate(found_tracks[:15], 1):
        _print_track(i, t)
    if len(found_tracks) > 15:
        print(f"    ... 他 {len(found_tracks) - 15} 曲")
    print(f"\napply '{playlist_name}' で Spotify に反映できます。")


def _discover_similar(args: str):
    """似たアーティストの曲を探す."""
    liked_ids = {t["id"] for t in liked_tracks} if liked_tracks else set()

    # 引数パターン:
    #   "Muse"     → そのアーティストの類似
    #   "5"  "5+"  → お気に入り5曲以上のアーティストの類似
    #   "2-"       → お気に入り2曲以下のアーティストの類似
    #   (なし)     → お気に入り3曲以上のアーティストの類似
    args = args.strip() if args else ""

    # 数値パターンか判定
    is_number = False
    if args:
        test = args.rstrip("+-")
        if test.isdigit():
            is_number = True

    if args and not is_number:
        # アーティスト名指定
        source_artists = [args]
        playlist_name = f"Similar: {args}"
    else:
        if not ensure_liked():
            return
        artist_count: dict[str, int] = {}
        for t in liked_tracks:
            for a in t["artist"].split(", "):
                artist_count[a] = artist_count.get(a, 0) + 1

        import random
        mode = "min"
        threshold = 3
        if args:
            if args.endswith("-"):
                mode = "max"
                threshold = int(args[:-1])
            elif args.endswith("+"):
                threshold = int(args[:-1])
            else:
                threshold = int(args)

        if mode == "min":
            candidates = [a for a, c in sorted(artist_count.items(), key=lambda x: -x[1]) if c >= threshold]
            label = f"{threshold} 曲以上"
        else:
            candidates = [a for a, c in sorted(artist_count.items(), key=lambda x: -x[1]) if c <= threshold]
            label = f"{threshold} 曲以下"

        max_artists = 15
        if len(candidates) > max_artists:
            source_artists = random.sample(candidates, max_artists)
            print(f"\n対象 {len(candidates)} 組 → ランダムに {max_artists} 組を選択")
        else:
            source_artists = candidates

        playlist_name = f"Discover: Similar ({label})"

    if not source_artists:
        print("対象アーティストがいません。")
        return

    found_tracks = []
    seen_ids = set()
    seen_similar = set()

    lastfm_ok = True
    for src in source_artists:
        print(f"\n  {src} の類似アーティストを検索中...")

        similar_artists = []
        if lastfm_ok:
            try:
                data = _lastfm_get("artist.getSimilar", artist=src, limit=10)
                similar_artists = data.get("similarartists", {}).get("artist", [])
            except RateLimitError as e:
                if e.is_long_wait():
                    print(f"\n  Last.fm レート制限（長時間）: {e}")
                    print("  コマンドを終了します。")
                    return
                print(f"  Last.fm レート制限 - Spotify 検索に切り替えます")
                lastfm_ok = False
            except Exception:
                pass

        if not similar_artists:
            # Last.fm が使えない場合は Spotify でアーティスト名検索
            try:
                results = sp.search(q=f"artist:{src}", type="track", limit=10)
                for item in results.get("tracks", {}).get("items", []):
                    if item["id"] not in seen_ids and item["id"] not in liked_ids:
                        seen_ids.add(item["id"])
                        found_tracks.append({
                            "id": item["id"],
                            "name": item["name"],
                            "artist": ", ".join(a["name"] for a in item["artists"]),
                            "album": item["album"]["name"],
                            "uri": item["uri"],
                            "duration_ms": item.get("duration_ms", 0),
                        })
                        time.sleep(0.2)
            except Exception:
                pass
            continue

        for sa in similar_artists:
            sa_name = sa.get("name", "")
            if sa_name.lower() in seen_similar:
                continue
            seen_similar.add(sa_name.lower())

            tracks = []
            if lastfm_ok:
                try:
                    td = _lastfm_get("artist.getTopTracks", artist=sa_name, limit=5)
                    tracks = td.get("toptracks", {}).get("track", [])
                except RateLimitError as e:
                    if e.is_long_wait():
                        print(f"\n  Last.fm レート制限（長時間）: {e}")
                        print("  コマンドを終了します。")
                        return
                    print(f"  Last.fm レート制限 - Spotify 検索に切り替えます")
                    lastfm_ok = False
                except Exception:
                    pass

            if not tracks:
                try:
                    results = sp.search(q=f"artist:{sa_name}", type="track", limit=5)
                    for item in results.get("tracks", {}).get("items", []):
                        if item["id"] not in seen_ids and item["id"] not in liked_ids:
                            seen_ids.add(item["id"])
                            found_tracks.append({
                                "id": item["id"],
                                "name": item["name"],
                                "artist": ", ".join(a["name"] for a in item["artists"]),
                                "album": item["album"]["name"],
                                "uri": item["uri"],
                                "duration_ms": item.get("duration_ms", 0),
                            })
                    time.sleep(0.2)
                except Exception:
                    pass
                continue

            added = 0
            for lt in tracks:
                lt_name = lt.get("name", "")
                track = _spotify_search_track(sa_name, lt_name)
                if not track or track["id"] in seen_ids or track["id"] in liked_ids:
                    time.sleep(0.2)
                    continue

                seen_ids.add(track["id"])
                found_tracks.append(track)
                added += 1
                time.sleep(0.2)

            if added > 0:
                print(f"    {sa_name}: {added} 曲")
            time.sleep(0.3)

    generated[playlist_name] = found_tracks

    print(f"\n[{playlist_name}] {len(found_tracks)} 曲が見つかりました。")
    for i, t in enumerate(found_tracks[:15], 1):
        _print_track(i, t)
    if len(found_tracks) > 15:
        print(f"    ... 他 {len(found_tracks) - 15} 曲")
    print(f"\napply '{playlist_name}' で Spotify に反映できます。")


def _lastfm_tag_tracks(tag: str, limit: int = 50, page: int = 1) -> list[dict]:
    """Last.fm の tag.getTopTracks で曲一覧を取得."""
    try:
        data = _lastfm_get("tag.getTopTracks", tag=tag, limit=limit, page=page)
        return data.get("tracks", {}).get("track", [])
    except RateLimitError:
        raise
    except Exception:
        return []


def _spotify_search_track(artist: str, track_name: str) -> dict | None:
    """Spotify で曲を検索して最初のマッチを返す."""
    try:
        q = f"artist:{artist} track:{track_name}"
        results = sp.search(q=q, type="track", limit=1)
        items = results.get("tracks", {}).get("items", [])
        if items:
            item = items[0]
            return {
                "id": item["id"],
                "name": item["name"],
                "artist": ", ".join(a["name"] for a in item["artists"]),
                "album": item["album"]["name"],
                "uri": item["uri"],
                "duration_ms": item.get("duration_ms", 0),
            }
    except Exception:
        pass
    return None


def cmd_auto(args: str):
    """rules/auto/*.yaml のタグで Last.fm から曲を探し Spotify に登録."""
    ensure_login()

    if not LASTFM_API_KEY:
        print("LASTFM_API_KEY が .env に設定されていません。")
        return

    import random

    auto_dir = Path(RULES_DIR) / "auto"
    paths = sorted(auto_dir.glob("*.yaml")) if auto_dir.exists() else []
    if not paths:
        print("rules/auto/ ディレクトリにルールファイルがありません。")
        return

    if args and args.lower() != "all":
        paths = [p for p in paths if p.stem == args]
        if not paths:
            print(f"ルール '{args}' が見つかりません。")
            return

    for path in paths:
        with open(path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)

        name = rule["playlist_name"]
        desc = rule.get("description", "")
        tags = rule.get("tags", rule.get("queries", []))
        per_tag = rule.get("tracks_per_tag", rule.get("tracks_per_query", 20))
        limit = rule.get("limit", 50)
        exclude_liked = rule.get("exclude_liked", False)
        min_dur = rule.get("min_duration_min")
        max_dur = rule.get("max_duration_min")
        artist_exclude = [a.lower() for a in rule.get("artist_exclude", [])]
        tags_exclude = [t.lower() for t in rule.get("tags_exclude", [])]

        # exclude_liked 用にお気に入りIDセットを構築
        liked_ids = set()
        if exclude_liked and liked_tracks:
            liked_ids = {t["id"] for t in liked_tracks}

        print(f"\n[{name}] Last.fm + Spotify で検索中... ({desc})")

        seen = set()
        found_tracks = []

        for tag in tags:
            # ランダムページで毎回違う結果に
            page = random.randint(1, 3)
            try:
                lastfm_tracks = _lastfm_tag_tracks(tag, limit=per_tag, page=page)
            except RateLimitError as e:
                if e.is_long_wait():
                    print(f"\n  Last.fm レート制限（長時間）: {e}")
                    print("  コマンドを終了します。")
                    return
                lastfm_tracks = []
            print(f"    {tag}: Last.fm で {len(lastfm_tracks)} 曲取得")

            for lt in lastfm_tracks:
                lt_name = lt.get("name", "")
                lt_artist = lt.get("artist", {}).get("name", "")
                key = f"{lt_artist}|{lt_name}".lower()
                if key in seen:
                    continue
                seen.add(key)

                # tags_exclude: Last.fm のタグを確認
                if tags_exclude:
                    lt_tags = [t["name"].lower() for t in lt.get("tag", [])] if isinstance(lt.get("tag"), list) else []
                    # tag.getTopTracks にはタグが含まれないので track.getInfo で取得
                    if not lt_tags:
                        try:
                            info = _lastfm_get("track.getInfo", artist=lt_artist, track=lt_name)
                            lt_tags = [t["name"].lower() for t in info.get("track", {}).get("toptags", {}).get("tag", [])]
                        except RateLimitError as e:
                            if e.is_long_wait():
                                print(f"\n  Last.fm レート制限（長時間）: {e}")
                                print("  コマンドを終了します。")
                                return
                            lt_tags = []
                        except Exception:
                            lt_tags = []
                        time.sleep(0.1)
                    if any(et in lt_tags for et in tags_exclude):
                        continue

                # artist_exclude
                if artist_exclude and any(ex in lt_artist.lower() for ex in artist_exclude):
                    continue

                # Spotify で検索
                track = _spotify_search_track(lt_artist, lt_name)
                if not track or track["id"] in seen:
                    time.sleep(0.1)
                    continue
                seen.add(track["id"])

                # exclude_liked
                if exclude_liked and track["id"] in liked_ids:
                    continue

                # duration フィルタ
                dur_m = track["duration_ms"] / 60000
                if min_dur is not None and dur_m < min_dur:
                    continue
                if max_dur is not None and dur_m > max_dur:
                    continue

                found_tracks.append(track)
                time.sleep(0.1)  # レート制限

                if len(found_tracks) >= limit:
                    break

            if len(found_tracks) >= limit:
                break

        found_tracks = found_tracks[:limit]

        generated[name] = found_tracks
        print(f"  {len(found_tracks)} 曲が見つかりました。")
        for i, t in enumerate(found_tracks[:10], 1):
            _print_track(i, t)
        if len(found_tracks) > 10:
            print(f"    ... 他 {len(found_tracks) - 10} 曲")

    print(f"\nプレビュー完了。apply コマンドで Spotify に反映できます。")


def cmd_playlists():
    """自分の Spotify プレイリスト一覧を表示."""
    ensure_login()
    print("\n--- Spotify プレイリスト一覧 ---")
    offset = 0
    count = 0
    while True:
        results = sp.current_user_playlists(limit=50, offset=offset)
        items = results["items"]
        if not items:
            break
        for pl in items:
            count += 1
            owner = (pl.get("owner") or {}).get("display_name") or (pl.get("owner") or {}).get("id", "?")
            total = (pl.get("tracks") or {}).get("total", "?")
            print(f"  {count:3d}. {pl['name']} ({total} 曲) - by {owner}")
        offset += 50
    print(f"\n合計 {count} プレイリスト")


def cmd_help():
    """コマンド一覧を表示."""
    print("""
  SpotifyPlaylistLab - コマンド一覧
  ----------------------------------------

  fetch              お気に入り曲を Spotify から取得
  load               保存済みデータを読み込む
  enrich [force]     Last.fm からタグ・再生回数を取得

  liked [N]          お気に入り曲一覧 (N件表示)
  search キーワード   曲名・アーティスト・アルバムで検索
  stats              ライブラリの統計情報

  rules              ルールファイル一覧と内容
  generate [名/all]  ルールでお気に入りからプレイリスト生成
  auto [名/all]      Last.fm タグ検索で新曲プレイリスト生成
  discover [N+/N-]   お気に入りアーティストの未発見曲
  discover similar [アーティスト/N+/N-]
                     似たアーティストの曲を検索
                     アーティスト名: そのアーティストの類似
                     N+ : お気に入りN曲以上のアーティストの類似
                     N- : お気に入りN曲以下のアーティストの類似
                     省略時: 3曲以上のアーティストの類似
  preview [名]       生成済みプレイリスト確認

  apply [名/all]     Spotify にプレイリスト反映
  playlists          Spotify プレイリスト一覧

  help               このヘルプを表示
  quit               終了
""")


# ── メインループ ────────────────────────────────────────

COMMANDS = {
    "fetch": lambda a: cmd_fetch(),
    "load": lambda a: cmd_load(),
    "enrich": cmd_enrich,
    "liked": cmd_liked,
    "search": cmd_search,
    "stats": lambda a: cmd_stats(),
    "rules": lambda a: cmd_rules(),
    "generate": cmd_generate,
    "auto": cmd_auto,
    "discover": cmd_discover,
    "preview": cmd_preview,
    "apply": cmd_apply,
    "playlists": lambda a: cmd_playlists(),
    "help": lambda a: cmd_help(),
}


def main():
    print("=" * 50)
    print("  SpotifyPlaylistLab")
    print("  対話型プレイリスト生成ツール")
    print("=" * 50)
    print("  help でコマンド一覧を表示\n")

    # 保存データがあれば自動読み込み
    if os.path.exists(DATA_FILE):
        cmd_load()

    while True:
        try:
            line = input("splab> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not line:
            continue

        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "q"):
            print("Bye!")
            break

        handler = COMMANDS.get(cmd)
        if handler:
            try:
                handler(args)
            except Exception as e:
                print(f"エラー: {e}")
        else:
            print(f"不明なコマンド: {cmd} (help でコマンド一覧を表示)")


if __name__ == "__main__":
    main()
