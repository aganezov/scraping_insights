# ruff: noqa: E402
import pytest

hypothesis = pytest.importorskip("hypothesis")
given = hypothesis.given
st = hypothesis.strategies

from insight_mine.cli.output import apply_variety_guard
from insight_mine.utils.text import dedupe_items


def _yt_comment():
    return st.fixed_dictionaries(
        {
            "platform": st.just("youtube"),
            "id": st.text(min_size=1, max_size=20),
            "title": st.just(None),
            "text": st.text(min_size=0, max_size=50),
            "metrics": st.fixed_dictionaries({"likes": st.integers(min_value=0, max_value=10), "score": st.integers(min_value=0, max_value=10), "replies": st.integers(min_value=0, max_value=5), "views": st.one_of(st.none(), st.integers(min_value=0, max_value=1000))}),
            "context": st.fixed_dictionaries({"videoId": st.text(min_size=3, max_size=10)}),
            "url": st.just("http://example.com"),
            "author": st.just("a"),
            "created_at": st.just("now"),
        }
    )


@given(st.lists(_yt_comment(), max_size=20))
def test_variety_guard_never_increases_count(items):
    out = apply_variety_guard(items, yt_share=0.5, rd_share=None)
    assert len(out) <= len(items)


@given(st.lists(_yt_comment(), max_size=20))
def test_dedupe_is_idempotent(items):
    once = dedupe_items(items)
    twice = dedupe_items(once)
    assert once == twice
