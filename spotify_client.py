import json
import os

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

SCOPE = "user-library-read playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private"
# フォロー中のアーティスト一覧（seasonal の「最近フォローしたアーティスト」）に使う。
# 既存のトークンを無効にしないよう、キャッシュのトークンがこのスコープを持つ時だけ要求する。
FOLLOW_SCOPE = "user-follow-read"
FULL_SCOPE = f"{SCOPE} {FOLLOW_SCOPE}"
CACHE_PATH = ".cache"


class _LimitedRetry(Retry):
    """Retry-After が長すぎる場合はリトライしない."""

    def sleep_for_retry(self, response=None):
        retry_after = self.get_retry_after(response)
        if retry_after and retry_after > 5:
            # 5秒以上の待ちはリトライせずに例外を投げる
            raise SpotifyRateLimitError(f"Spotify rate limit: retry after {retry_after}s")
        return super().sleep_for_retry(response)


class SpotifyRateLimitError(Exception):
    """Spotify レート制限エラー（長時間待ち）."""
    pass


class SpotifyAuthError(Exception):
    """対話なしでは Spotify にログインできない（トークンがない・更新できない）."""
    pass


def _cached_scopes() -> set[str]:
    """キャッシュのトークンが持つスコープ（なければ空）."""
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            token = json.load(f)
        return set((token.get("scope") or "").split())
    except (OSError, ValueError):
        return set()


def has_follow_scope() -> bool:
    """キャッシュのトークンに user-follow-read が入っているか."""
    return FOLLOW_SCOPE in _cached_scopes()


def _make_oauth(scope: str, open_browser: bool = True) -> SpotifyOAuth:
    return SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
        scope=scope,
        cache_path=CACHE_PATH,
        open_browser=open_browser,
    )


def get_spotify_client(full_scope: bool = False, interactive: bool = True) -> spotipy.Spotify:
    """Spotify クライアントを作る.

    full_scope=True: user-follow-read も要求する（login コマンド用。再ログインになる）。
    full_scope=False: キャッシュのトークンが user-follow-read を持っていればそれも、なければ従来のスコープ。
    interactive=False: ブラウザでのログインが要る時は待たずに SpotifyAuthError を投げる（cron 用）。
    """
    scope = FULL_SCOPE if (full_scope or has_follow_scope()) else SCOPE
    auth = _make_oauth(scope, open_browser=interactive)
    if not interactive:
        try:
            token = auth.validate_token(auth.cache_handler.get_cached_token())
        except Exception as e:  # リフレッシュトークンの失効など
            raise SpotifyAuthError(f"トークンを更新できません: {e}") from e
        if not token:
            raise SpotifyAuthError("有効なトークンがありません（.cache がないか、スコープが足りない）")
    client = spotipy.Spotify(
        auth_manager=auth,
        retries=0,  # spotipy のデフォルトリトライを無効化
    )
    # requests セッションに短い Retry-After 制限付きのリトライを設定
    retry = _LimitedRetry(
        total=3,
        status_forcelist=[500, 502, 503],
        # 429 は _LimitedRetry で制御するのでここに含めない
        backoff_factor=0.3,
    )
    adapter = HTTPAdapter(max_retries=retry)
    client._session.mount("https://", adapter)
    client._session.mount("http://", adapter)
    return client
