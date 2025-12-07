from insight_mine.cli.output import apply_variety_guard


def test_variety_guard_limits_youtube_comments_per_video():
    items = [
        {"platform": "youtube", "context": {"videoId": "v1"}, "title": None, "metrics": {"likes": 100}},
        {"platform": "youtube", "context": {"videoId": "v1"}, "title": None, "metrics": {"likes": 50}},
        {"platform": "youtube", "context": {"videoId": "v1"}, "title": None, "metrics": {"likes": 10}},
        {"platform": "youtube", "context": {"videoId": "v2"}, "title": None, "metrics": {"likes": 5}},
    ]

    result = apply_variety_guard(items, yt_share=0.5, rd_share=None)

    # Should keep at most 50% of comments per video (ceil to at least 1)
    kept_v1 = [it for it in result if it["context"]["videoId"] == "v1"]
    kept_v2 = [it for it in result if it["context"]["videoId"] == "v2"]
    assert len(kept_v1) == 1
    assert len(kept_v2) == 1


def test_variety_guard_limits_reddit_comments_per_post():
    items = [
        {"platform": "reddit", "id": "t1_c1", "context": {"post_id": "p1"}, "metrics": {"score": 10}},
        {"platform": "reddit", "id": "t1_c2", "context": {"post_id": "p1"}, "metrics": {"score": 5}},
        {"platform": "reddit", "id": "t1_c3", "context": {"post_id": "p1"}, "metrics": {"score": 1}},
        {"platform": "reddit", "id": "t1_c4", "context": {"post_id": "p2"}, "metrics": {"score": 2}},
    ]

    result = apply_variety_guard(items, yt_share=None, rd_share=0.5)

    kept_p1 = [it for it in result if it["context"]["post_id"] == "p1"]
    kept_p2 = [it for it in result if it["context"]["post_id"] == "p2"]
    assert len(kept_p1) == 1
    assert len(kept_p2) == 1
