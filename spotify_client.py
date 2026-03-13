import os

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

SCOPE = "user-library-read playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private"


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


def get_spotify_client() -> spotipy.Spotify:
    client = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
            scope=SCOPE,
        ),
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
