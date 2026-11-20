import unittest
from datetime import date, datetime

import seasonal as seas


def T(i, artist="A", added="2026-11-01T00:00:00Z", rel="2026-10-01", tags=None):
    return {"id": f"id{i}", "name": f"Song {i}", "artist": artist, "uri": f"spotify:track:{i}",
            "added_at": added, "release_date": rel, "tags": tags or []}


class SeasonTest(unittest.TestCase):
    def test_season_key(self):
        self.assertEqual(seas.season_key(date(2026, 12, 5)), "2027-winter")
        self.assertEqual(seas.season_key(date(2027, 2, 28)), "2027-winter")
        self.assertEqual(seas.season_key(date(2026, 11, 19)), "2026-autumn")

    def test_release_date(self):
        self.assertEqual(seas.normalize_release_date("2024"), "2024-01-01")
        self.assertEqual(seas.normalize_release_date("2024-05"), "2024-05-01")
        self.assertEqual(seas.normalize_release_date(""), "")


class PoolTest(unittest.TestCase):
    def test_recent_added_and_released(self):
        tracks = [T(1, added="2026-11-10T00:00:00Z"), T(2, added="2025-01-01T00:00:00Z", rel="2020")]
        since = datetime.fromisoformat("2026-09-01T00:00:00+09:00")
        self.assertEqual([t["id"] for t in seas.recent_added(tracks, since)], ["id1"])
        self.assertEqual([t["id"] for t in seas.recent_released(tracks, date(2026, 6, 1))], ["id1"])

    def test_newly_loved(self):
        tracks = [T(1, "Old", added="2024-01-01T00:00:00Z"), T(2, "Old", added="2026-11-01T00:00:00Z"),
                  T(3, "New", added="2026-11-01T00:00:00Z")]
        since = datetime.fromisoformat("2026-09-01T00:00:00+00:00")
        self.assertEqual(seas.newly_loved_artists(tracks, since), {"New"})

    def test_follow_state(self):
        s = seas.update_follow_state({}, [{"id": "a", "name": "A"}], "2026-11-01")
        self.assertEqual(s["a"]["first_seen"], "baseline")
        s = seas.update_follow_state(s, [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}], "2026-12-01")
        self.assertEqual(s["b"]["first_seen"], "2026-12-01")
        self.assertEqual(seas.recently_followed(s, datetime(2026, 11, 15, tzinfo=seas.JST)), {"B"})
        s = seas.update_follow_state(s, [{"id": "b", "name": "B"}], "2027-01-01")
        self.assertNotIn("a", s)

    def test_follow_state_from_empty_list(self):
        # 記録を始めた時はフォロー0組 → 次に新しくフォローしたら「最近フォロー」になる
        s = seas.update_follow_state({}, [], "2026-11-01", first_run=True)
        self.assertEqual(s, {})
        s = seas.update_follow_state(s, [{"id": "c", "name": "C"}], "2026-12-01", first_run=False)
        self.assertEqual(s["c"]["first_seen"], "2026-12-01")
        self.assertEqual(seas.recently_followed(s, datetime(2026, 11, 15, tzinfo=seas.JST)), {"C"})

    def test_follow_seen_in_previous_run_is_not_reused(self):
        # 12/1 9:00 の実行で見つけたアーティストは、その実行の時刻を期間の始まりにする次の回には入らない
        run_at = "2026-12-01T09:00:00+09:00"
        s = seas.update_follow_state({"a": {"name": "A", "first_seen": "baseline"}},
                                     [{"id": "a", "name": "A"}, {"id": "d", "name": "D"}], run_at, first_run=False)
        self.assertEqual(seas.recently_followed(s, seas.parse_seen(run_at)), set())
        self.assertEqual(seas.recently_followed(s, datetime(2026, 11, 1, tzinfo=seas.JST)), {"D"})
        # 古い記録（日付だけ）も読める
        self.assertEqual(seas.parse_seen("2026-12-01"), datetime(2026, 12, 1, tzinfo=seas.JST))

    def test_pick_favorites_fills_shortage(self):
        pools = {"added": [T(1), T(2)], "released": [T(2), T(3), T(4), T(5)], "followed": []}
        got = seas.pick_favorites(pools, {"added": 2, "released": 1, "followed": 2}, 5)
        self.assertEqual([t["id"] for t in got], ["id1", "id2", "id3", "id4", "id5"])
        self.assertEqual(len({t["id"] for t in got}), 5)

    def test_pick_favorites_fills_rounding(self):
        pools = {"added": [T(i) for i in range(10)], "released": [], "followed": []}
        quotas = seas.split_quotas(8, {"added": 0.4, "released": 0.3, "followed": 0.3})
        self.assertEqual(sum(quotas.values()), 8)
        self.assertEqual(len(seas.pick_favorites(pools, quotas, 8)), 8)
        self.assertEqual(sum(seas.split_quotas(1, {"a": 0.4, "b": 0.3, "c": 0.3}).values()), 1)

    def test_pick_favorites_prefix_is_stable(self):
        pools = {"added": [T(i) for i in range(5)], "released": [T(i) for i in range(5, 10)], "followed": []}
        q = {"added": 2, "released": 2, "followed": 0}
        small = seas.pick_favorites(pools, q, 4)
        big = seas.pick_favorites(pools, q, 8)
        self.assertEqual(big[:4], small)
        self.assertEqual(len(big), 8)

    def test_pick_favorites_per_artist(self):
        pools = {"added": [T(i, artist="X") for i in range(5)] + [T(9, artist="Y")],
                 "released": [T(i, artist="X, Z") for i in range(5, 8)], "followed": []}
        got = seas.pick_favorites(pools, {"added": 4, "released": 2, "followed": 0}, 6, per_artist=2)
        # X は「X, Z」の曲も含めて 2 曲まで。足りない分は Y で埋める
        self.assertEqual([t["id"] for t in got], ["id0", "id1", "id9"])
        # ほかで選んだ曲（taken）も数に入る
        got = seas.pick_favorites(pools, {"added": 4, "released": 0, "followed": 0}, 4, per_artist=2,
                                  taken={"x": 1})
        self.assertEqual([t["id"] for t in got], ["id0", "id9"])

    def test_cap_per_artist(self):
        tracks = [T(1, artist="X"), T(2, artist="Y"), T(3, artist="x"), T(4, artist="X, Y")]
        self.assertEqual([t["id"] for t in seas.cap_per_artist(tracks, 2)], ["id1", "id2", "id3"])
        self.assertEqual(len(seas.cap_per_artist(tracks, None)), 4)
        self.assertEqual(seas.artist_counts(tracks), {"x": 3, "y": 1})

    def test_interleave(self):
        out = seas.interleave([1, 2, 3, 4], ["a", "b"])
        self.assertEqual(out, [1, "a", 2, 3, "b", 4])
        self.assertEqual(seas.interleave([], ["a"]), ["a"])

    def test_rank_candidates(self):
        cands = {
            "x|1": {"artist": "X", "name": "1", "score": 3},
            "x|2": {"artist": "X", "name": "2", "score": 2},
            "x|3": {"artist": "X", "name": "3", "score": 1},
            "y|1": {"artist": "Y", "name": "1", "score": 5},
        }
        out = seas.rank_candidates(cands, liked_keys={"y|1"}, per_artist=2)
        self.assertEqual([c["name"] for c in out], ["1", "2"])


class TitleTest(unittest.TestCase):
    def test_mood(self):
        tracks = [T(1, tags=["rock", "hard rock"]), T(2, tags=["nu metal"]), T(3, tags=["pop"])]
        self.assertEqual(seas.detect_mood(tracks)[0], "electric")
        self.assertEqual(seas.detect_mood([T(1)])[0], "dreamy")

    def test_title_avoids_and_is_stable(self):
        a = seas.make_title("summer", "bright", {"Sunshine in Stereo"}, seed="2026-summer-0")
        b = seas.make_title("summer", "bright", {"Sunshine in Stereo"}, seed="2026-summer-0")
        self.assertEqual(a, b)
        self.assertNotEqual(a.lower(), "sunshine in stereo")

    def test_title_never_collides(self):
        avoid = {t for t, _ in seas.title_candidates("autumn", "mellow")}
        t = seas.make_title("autumn", "mellow", avoid, seed="x")
        self.assertNotIn(t, avoid)


if __name__ == "__main__":
    unittest.main()
