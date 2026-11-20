"""seasonal: 季節ごとの詩的なプレイリストの、曲の選び方とタイトルの作り方.

API を呼ばない純粋な処理だけを置く（splab.py の cmd_seasonal から使う）。
"""

from __future__ import annotations

import hashlib
import random
import re
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

# ── 季節 ──────────────────────────────────────────────

SEASONS = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}
SEASON_JA = {"winter": "冬", "spring": "春", "summer": "夏", "autumn": "秋"}


def season_of(d: date) -> str:
    return SEASONS[d.month]


def season_key(d: date) -> str:
    """同じ季節の判定用キー（12月は翌年の冬に数える）. 例: 2026-autumn, 2027-winter."""
    year = d.year + 1 if d.month == 12 else d.year
    return f"{year}-{season_of(d)}"


# ── 日付 ──────────────────────────────────────────────


def parse_added_at(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_release_date(s: str) -> str:
    """'2024' / '2024-01' / '2024-01-15' を 'YYYY-MM-DD' にそろえる（不明なら空）."""
    if not s:
        return ""
    if re.fullmatch(r"\d{4}", s):
        return s + "-01-01"
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return s + "-01"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return ""


def primary_artist(t: dict) -> str:
    return t["artist"].split(", ")[0]


def track_key(artist: str, name: str) -> str:
    return f"{artist.lower().strip()}|{name.lower().strip()}"


# ── お気に入りの3つのプール ───────────────────────────


def recent_added(tracks: list[dict], since: datetime) -> list[dict]:
    """1. 最近お気に入りに追加した曲（新しい順）."""
    out = [(parse_added_at(t.get("added_at", "")), t) for t in tracks]
    out = [(dt, t) for dt, t in out if dt and dt >= since]
    out.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in out]


def recent_released(tracks: list[dict], since: date) -> list[dict]:
    """2. 最近リリースされた曲（お気に入りの中から。新しい順）."""
    s = since.isoformat()
    out = [(normalize_release_date(t.get("release_date", "")), t) for t in tracks]
    out = [(rd, t) for rd, t in out if rd and rd >= s]
    out.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in out]


def by_artists(tracks: list[dict], artist_names: set[str]) -> list[dict]:
    """3. 指定したアーティスト（最近フォローした・最近好きになった）の曲（新しく追加した順）."""
    names = {a.lower() for a in artist_names}
    out = [t for t in tracks if any(a.lower() in names for a in t["artist"].split(", "))]
    out.sort(key=lambda t: t.get("added_at", ""), reverse=True)
    return out


def newly_loved_artists(tracks: list[dict], since: datetime) -> set[str]:
    """お気に入りに初めて入ったのが since 以降のアーティスト（フォロー一覧が取れない時の代わり）."""
    first: dict[str, datetime] = {}
    for t in tracks:
        dt = parse_added_at(t.get("added_at", ""))
        if not dt:
            continue
        for a in t["artist"].split(", "):
            if a not in first or dt < first[a]:
                first[a] = dt
    return {a for a, dt in first.items() if dt >= since}


def update_follow_state(state: dict, followed: list[dict], today: str, first_run: bool | None = None) -> dict:
    """フォロー一覧の記録を更新する.

    state: {artist_id: {"name": ..., "first_seen": 見つけた日時（ISO 形式） or "baseline"}}
    初回（first_run。省略時は state が空かどうか）は全員を "baseline"（いつフォローしたか分からない）にする。
    フォローが0組でも記録を始めていれば初回ではないので、呼び出し側で first_run を渡す。
    2回目からは、新しく出てきたアーティストに今日の日付を付ける。
    フォローを外したアーティストは消す。
    """
    if first_run is None:
        first_run = not state
    new_state = {}
    for a in followed:
        prev = state.get(a["id"])
        if prev:
            new_state[a["id"]] = {"name": a["name"], "first_seen": prev["first_seen"]}
        else:
            new_state[a["id"]] = {"name": a["name"], "first_seen": "baseline" if first_run else today}
    return new_state


def parse_seen(s: str) -> datetime | None:
    """first_seen（'YYYY-MM-DDTHH:MM:SS+09:00'。古い記録は 'YYYY-MM-DD' で、その日の 0 時 JST とみなす）."""
    if not s or s == "baseline":
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=JST)


def recently_followed(state: dict, since: datetime) -> set[str]:
    """since より後（同じ時刻は含めない）に初めて見つけたアーティスト.

    since に前回の実行の時刻を渡すと、前回の実行で見つけた（＝前回のプレイリストに使った）アーティストは入らない。
    """
    out = set()
    for v in state.values():
        dt = parse_seen(v["first_seen"])
        if dt and dt > since:
            out.add(v["name"])
    return out


def pick_favorites(pools: dict[str, list[dict]], quotas: dict[str, int], total: int,
                   per_artist: int | None = None, taken: dict[str, int] | None = None) -> list[dict]:
    """3つのプールから、割り当て（quotas）どおりに重複なしで選ぶ.

    あるプールが足りない時は、残りをほかのプールから順番に埋める。
    per_artist を指定すると、同じアーティスト（primary_artist）は per_artist 曲までにする。
    taken は、ほかで選んだ曲のアーティストごとの数（per_artist の数に含める）。
    各曲に "_source"（added / released / followed）を付ける。
    """
    chosen: list[dict] = []
    seen: set[str] = set()
    per: dict[str, int] = dict(taken or {})

    def take(name: str, n: int) -> int:
        got = 0
        for t in pools.get(name, []):
            if got >= n or len(chosen) >= total:
                break
            if t["id"] in seen:
                continue
            a = primary_artist(t).lower()
            if per_artist is not None and per.get(a, 0) >= per_artist:
                continue
            per[a] = per.get(a, 0) + 1
            seen.add(t["id"])
            chosen.append({**t, "_source": name})
            got += 1
        return got

    for name, q in quotas.items():
        take(name, q)
    # 割り当てに届かない枠や端数の分を、ほかのプールの残りから埋める
    for name in quotas:
        if len(chosen) >= total:
            break
        take(name, total - len(chosen))
    return chosen[:total]


def artist_counts(tracks: list[dict]) -> dict[str, int]:
    """曲のリストを、アーティスト（primary_artist、小文字）ごとに数える."""
    per: dict[str, int] = {}
    for t in tracks:
        a = primary_artist(t).lower()
        per[a] = per.get(a, 0) + 1
    return per


def cap_per_artist(tracks: list[dict], per_artist: int | None) -> list[dict]:
    """同じアーティストの曲を、前から per_artist 曲までに減らす（None なら、そのまま）."""
    if per_artist is None:
        return list(tracks)
    per: dict[str, int] = {}
    out = []
    for t in tracks:
        a = primary_artist(t).lower()
        if per.get(a, 0) >= per_artist:
            continue
        per[a] = per.get(a, 0) + 1
        out.append(t)
    return out


def split_quotas(total: int, ratios: dict[str, float]) -> dict[str, int]:
    """total を ratios の割合で分ける（端数は大きい順に配り、合計が必ず total になる）."""
    raw = {k: total * r for k, r in ratios.items()}
    out = {k: int(v) for k, v in raw.items()}
    rest = total - sum(out.values())
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:rest]:
        out[k] += 1
    return out


def interleave(favorites: list[dict], recs: list[dict]) -> list[dict]:
    """お気に入りとおすすめを、割合を保って交互に並べる."""
    if not favorites or not recs:
        return favorites + recs
    out = []
    n_f, n_r = len(favorites), len(recs)
    i = j = 0
    while i < n_f or j < n_r:
        # 進み具合が遅れている方を先に出す
        if j >= n_r or (i < n_f and i / n_f <= j / n_r):
            out.append(favorites[i])
            i += 1
        else:
            out.append(recs[j])
            j += 1
    return out


def rank_candidates(cands: dict[str, dict], liked_keys: set[str], per_artist: int = 2) -> list[dict]:
    """おすすめ候補を点数順に並べる（お気に入り済みを除き、同じアーティストは per_artist 曲まで）.

    cands: {track_key: {"artist", "name", "score"}}
    """
    items = [c for k, c in cands.items() if k not in liked_keys]
    items.sort(key=lambda c: -c["score"])
    per: dict[str, int] = {}
    out = []
    for c in items:
        a = c["artist"].lower()
        if per.get(a, 0) >= per_artist:
            continue
        per[a] = per.get(a, 0) + 1
        out.append(c)
    return out


# ── 雰囲気（Last.fm タグ） ─────────────────────────────

MOODS: dict[str, set[str]] = {
    "bright": {"dance", "dance-pop", "electropop", "disco", "house", "party", "k-pop", "kpop",
               "pop", "funk", "jersey club", "future house", "french house", "happy", "summer", "upbeat",
               "j-pop", "edm"},
    "electric": {"rock", "alternative rock", "hard rock", "nu metal", "metal", "punk", "punk rock",
                 "emo", "pop punk", "grunge", "post-hardcore", "metalcore", "garage rock"},
    "dreamy": {"synthpop", "new wave", "dream pop", "shoegaze", "indie", "indie pop", "indie rock",
               "city pop", "alternative", "electronic", "ambient", "techno", "chillwave", "80s"},
    "mellow": {"chill", "acoustic", "ballad", "piano", "lo-fi", "lofi", "folk", "singer-songwriter",
               "soul", "rnb", "r&b", "jazz", "soft rock", "sleep", "relax", "mellow", "sad"},
}
MOOD_JA = {"bright": "明るく踊れる", "electric": "ギターが鳴る", "dreamy": "夢見心地", "mellow": "しっとり"}


def detect_mood(tracks: list[dict]) -> tuple[str, dict[str, int]]:
    """曲のタグから、いちばん多い雰囲気を選ぶ（タグがなければ dreamy）."""
    score = {m: 0 for m in MOODS}
    for t in tracks:
        tags = {x.lower() for x in t.get("tags", [])[:5]}
        for m, words in MOODS.items():
            if tags & words:
                score[m] += 1
    best = max(score, key=lambda m: (score[m], m == "dreamy"))
    if score[best] == 0:
        best = "dreamy"
    return best, score


# ── 詩的なタイトル ─────────────────────────────────────
# 「Sunshine in Stereo」のように、季節の言葉 × 音・雰囲気の言葉を組み合わせる。

SEASON_WORDS = {
    "winter": {
        "nouns": ["Snowfall", "Frost", "Midnight", "Starlight", "Hearthlight", "Silver", "Northern Lights",
                  "Candlelight", "Velvet Snow", "Winter Moon", "Ice", "December"],
        "adjs": ["Frosted", "Silent", "Silver", "Starlit", "Snowbound", "Crystal", "Midwinter", "Pale"],
        "places": ["the Snow", "the Cold", "a Winter Window", "the Long Night", "White Noise"],
    },
    "spring": {
        "nouns": ["Blossom", "Petals", "Morning Rain", "Bloom", "April", "Sakura", "First Light",
                  "Green", "Breeze", "Daybreak", "Spring Rain"],
        "adjs": ["Blooming", "Fresh", "Pastel", "Budding", "Soft", "Dewy", "Bright", "Early"],
        "places": ["the Bloom", "Full Bloom", "the Morning", "the Rain", "Open Windows"],
    },
    "summer": {
        "nouns": ["Sunshine", "Heatwave", "Seaside", "Saltwater", "Sunburst", "Golden Hour", "Fireworks",
                  "Summer Haze", "Daylight", "Tidal", "Lemonade"],
        "adjs": ["Golden", "Sunlit", "Endless", "Sun-Kissed", "Tropical", "Burning", "Salty", "Bright"],
        "places": ["the Sun", "the Shoreline", "a Long Summer", "the Heat", "Neon Nights"],
    },
    "autumn": {
        "nouns": ["Amber", "Maple", "Harvest Moon", "Ember", "Falling Leaves", "October", "Copper",
                  "Twilight", "Rust", "Autumn Rain", "Bonfire"],
        "adjs": ["Amber", "Golden", "Fading", "Smoky", "Copper", "Crimson", "Late", "Burnished"],
        "places": ["the Leaves", "the Fall", "the Harvest", "the Dusk", "a Quiet Street"],
    },
}

MOOD_WORDS = {
    "bright": {"sound": ["Stereo", "Disco", "Neon", "Rhythm", "Motion", "Sparkle", "Glitter", "Groove"],
               "adjs": ["Electric", "Dancing", "Neon", "Bouncing", "Shimmering"]},
    "electric": {"sound": ["Static", "Overdrive", "Feedback", "Thunder", "Voltage", "Distortion", "Amplifiers"],
                 "adjs": ["Electric", "Loud", "Restless", "Wild", "Burning"]},
    "dreamy": {"sound": ["Reverie", "Echoes", "Daydreams", "Haze", "Satellites", "Afterglow", "Cassette"],
               "adjs": ["Dreaming", "Drifting", "Hazy", "Floating", "Distant"]},
    "mellow": {"sound": ["Lullabies", "Whispers", "Slow Motion", "Vinyl", "Velvet", "Murmurs", "Hush"],
               "adjs": ["Quiet", "Gentle", "Slow", "Tender", "Hushed"]},
}

TEMPLATES = [
    "{s_noun} in {m_sound}",        # Sunshine in Stereo
    "{m_sound} of {s_noun}",        # Echoes of Amber
    "{s_adj} {m_sound}",            # Frosted Static
    "{m_adj} {s_noun}",             # Electric Snowfall
    "{m_sound} in {s_place}",       # Disco in the Snow
    "{s_noun} & {m_sound}",         # Ember & Echoes
]


def _initial(word: str) -> str:
    w = re.sub(r"^(the|a|an)\s+", "", word.strip(), flags=re.I)
    return w[:1].lower()


def _title_score(title: str, parts: list[str]) -> int:
    """頭韻（Sunshine / Stereo のように頭の音がそろう）を好む."""
    initials = [_initial(p) for p in parts]
    score = 0
    if len(initials) >= 2 and initials[0] == initials[-1]:
        score += 3
    if len(title) <= 22:
        score += 1
    # 同じ単語の繰り返しは避ける（Golden Golden など）
    words = [w.lower() for w in re.findall(r"[A-Za-z-]+", title)]
    if len(words) != len(set(words)):
        score -= 5
    return score


def title_candidates(season: str, mood: str) -> list[tuple[str, int]]:
    sw, mw = SEASON_WORDS[season], MOOD_WORDS[mood]
    out: dict[str, int] = {}
    for tpl in TEMPLATES:
        slots = {
            "s_noun": sw["nouns"], "s_adj": sw["adjs"], "s_place": sw["places"],
            "m_sound": mw["sound"], "m_adj": mw["adjs"],
        }
        keys = re.findall(r"\{(\w+)\}", tpl)
        combos = [[]]
        for k in keys:
            combos = [c + [w] for c in combos for w in slots[k]]
        for c in combos:
            title = tpl.format(**dict(zip(keys, c)))
            out[title] = max(out.get(title, -99), _title_score(title, c))
    return list(out.items())


def make_title(season: str, mood: str, avoid: set[str], seed: str) -> str:
    """季節と雰囲気から、詩的なタイトルを1つ選ぶ.

    avoid（既存のプレイリスト名・過去に作った名前）とは、大文字小文字を無視して重ならないものにする。
    seed が同じなら同じ結果（dry-run と本番で同じ名前になる）。
    """
    avoid_l = {a.lower().strip() for a in avoid}
    cands = [(t, s) for t, s in title_candidates(season, mood) if t.lower() not in avoid_l]
    if not cands:
        base = f"{season.title()} {MOOD_WORDS[mood]['sound'][0]}"
        n = 2
        while f"{base} {n}".lower() in avoid_l:
            n += 1
        return f"{base} {n}"
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest(), 16))
    rng.shuffle(cands)
    best = max(s for _, s in cands)
    # 点数の高いものの中から選ぶ（いつも同じ型にならないよう、上位にゆとりを持たせる）
    top = [t for t, s in cands if s >= best - 1]
    return top[0]
