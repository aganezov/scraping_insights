from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _arg_value(argv: list[str], flag: str, default: str = "") -> str:
    for i, arg in enumerate(argv[:-1]):
        if arg == flag:
            return argv[i + 1]
    return default


def _int_value(argv: list[str], flag: str, default: int = 0) -> int:
    value = _arg_value(argv, flag, str(default))
    try:
        return int(value)
    except Exception:
        return default


def _youtube_rows() -> list[dict]:
    return [
        {
            "id": "yt:abc123xyz09",
            "platform": "youtube",
            "title": "Charging myths that still confuse drivers",
            "author": "Signal EV",
            "text": "Most charging pain comes from planning anxiety, not actual charging speed.",
            "url": "https://www.youtube.com/watch?v=abc123xyz09",
            "created_at": "2026-03-14T10:00:00",
            "views": 120345,
            "comments": [
                {
                    "id": "yt:abc123xyz09:c1",
                    "platform": "youtube",
                    "author": "reader_one",
                    "text": "The map confidence issue is real for road trips.",
                    "url": "https://www.youtube.com/watch?v=abc123xyz09&lc=c1",
                    "created_at": "2026-03-14T10:05:00",
                },
                {
                    "id": "yt:abc123xyz09:c2",
                    "platform": "youtube",
                    "author": "reader_two",
                    "text": "Apartment charging is still the blocker where I live.",
                    "url": "https://www.youtube.com/watch?v=abc123xyz09&lc=c2",
                    "created_at": "2026-03-14T10:09:00",
                },
            ],
        }
    ]


def _reddit_rows() -> list[dict]:
    return [
        {
            "id": "t3_fakepost1",
            "platform": "reddit",
            "title": "What still causes charging anxiety for you?",
            "author": "ev_forum",
            "text": "I can handle slower charging, but not uncertain charger availability.",
            "url": "https://reddit.com/r/electricvehicles/comments/fakepost1",
            "created_at": "2026-03-16T08:00:00",
            "score": 124,
            "comments": [
                {
                    "id": "t1_fakecomment1",
                    "platform": "reddit",
                    "author": "reply_author",
                    "text": "Reliable status data would remove half the stress.",
                    "url": "https://reddit.com/r/electricvehicles/comments/fakepost1/comment/fakecomment1",
                    "created_at": "2026-03-16T08:10:00",
                    "score": 19,
                }
            ],
        }
    ]


def _flatten(rows: list[dict]) -> list[dict]:
    flat: list[dict] = []
    for row in rows:
        comments = row.get("comments", [])
        flat.append({k: v for k, v in row.items() if k != "comments"})
        flat.extend(comments)
    return flat


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    payload = "\n".join(json.dumps(row, ensure_ascii=True) for row in rows) + "\n"
    path.write_text(payload, encoding="utf-8")


def _write_manifest(run_dir: Path, topic: str, since: str, rows: list[dict]) -> None:
    manifest = {
        "run_id": run_dir.name,
        "topic": topic,
        "since": since,
        "preset": "fake-gui-smoke",
        "counts": {
            "total": len(rows),
            "youtube_video": sum(1 for row in rows if row["platform"] == "youtube" and row.get("title")),
            "youtube_comment": sum(1 for row in rows if row["platform"] == "youtube" and not row.get("title")),
            "reddit_post": sum(1 for row in rows if row["platform"] == "reddit" and str(row.get("id", "")).startswith("t3_")),
            "reddit_comment": sum(1 for row in rows if row["platform"] == "reddit" and str(row.get("id", "")).startswith("t1_")),
        },
        "created_at": "2026-04-10T10:00:00",
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "stats.json").write_text(
        json.dumps({"dropped": {"low_views": 1, "low_score": 1, "lang_mismatch": 0}}, indent=2),
        encoding="utf-8",
    )


def _write_paste_ready(path: Path, rows: list[dict]) -> None:
    lines: list[str] = []
    for row in rows:
        title = f"{row['title']} - " if row.get("title") else ""
        lines.append(f"[{row['platform']}] {title}{row.get('text', '')}\n{row['url']}")
    path.write_text("\n\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv)
    if len(argv) < 2 or argv[1] != "collect":
        print("insight-mine-fake-cli only supports `collect`", flush=True)
        return 2

    out_dir_value = _arg_value(argv, "--out")
    if not out_dir_value:
        print("missing --out", flush=True)
        return 2

    out_dir = Path(out_dir_value).expanduser()
    topic = _arg_value(argv, "--topic", "fake topic")
    since = _arg_value(argv, "--since", "1970-01-01")
    run_dir = out_dir / time.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    if _int_value(argv, "--yt-videos", 0) > 0:
        rows.extend(_flatten(_youtube_rows()))
    if _int_value(argv, "--reddit-limit", 0) > 0 and _arg_value(argv, "--reddit-mode", "off") != "off":
        rows.extend(_flatten(_reddit_rows()))

    print('{"event":"progress","overall":5,"youtube":0,"reddit":0}', flush=True)
    time.sleep(0.15)
    if any(row["platform"] == "youtube" for row in rows):
        print("Telemetry (YouTube): yt_video_kept:1, yt_comment_kept:2", flush=True)
        print('{"event":"progress","overall":45,"youtube":35,"reddit":0}', flush=True)
        time.sleep(0.15)
    if any(row["platform"] == "reddit" for row in rows):
        print("Telemetry (Reddit scrape): rd_post_kept:1, rd_comment_kept:1", flush=True)
        print('{"event":"progress","overall":80,"youtube":40,"reddit":100}', flush=True)
        time.sleep(0.15)

    _write_jsonl(run_dir / "raw.jsonl", rows)
    _write_manifest(run_dir, topic, since, rows)
    _write_paste_ready(run_dir / "paste-ready.txt", rows)

    latest = out_dir / "latest"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        latest.symlink_to(run_dir.name)
    except Exception:
        pass

    print(f"Wrote {len(rows)} items", flush=True)
    print('{"event":"progress","overall":100,"youtube":100,"reddit":100}', flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
