from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List

# Preferred filenames that already contain parent+embedded comments.
PARENT_FILES = [
    "parents_with_comments.json",
    "parents.json",
    "items.json",
    "results.json",
]


def _resolve_run_dir(out_root: Path, run_id: str) -> Path:
    """
    Resolve the physical run directory. We commonly have either:
      <out_root>/<run_id>     (standard)
      <out_root>/out/<run_id> (cli_out packaging)
    Prefer an existing directory; otherwise fall back to primary.
    """
    primary = out_root / run_id
    alt = out_root / "out" / run_id
    if primary.exists():
        return primary
    if alt.exists():
        return alt
    return primary


def _infer_topic(manifest: dict, run_dir: Path) -> str:
    """
    Best-effort topic extraction:
    - manifest.knobs.topic
    - manifest.topic
    - parse from knobs.cli (--topic VALUE)
    - run_manifest.json topic (if present)
    """
    knobs = manifest.get("knobs", {}) if isinstance(manifest, dict) else {}
    topic = knobs.get("topic") or manifest.get("topic") or ""
    if topic:
        return topic
    cli_str = knobs.get("cli") or ""
    if "--topic" in cli_str:
        try:
            parts = cli_str.split("--topic", 1)[1].strip().split()
            if parts:
                topic = parts[0].strip().strip('"').strip("'")
                if topic:
                    return topic
        except Exception:
            pass
    rm = run_dir / "run_manifest.json"
    if rm.exists():
        try:
            mdata = json.loads(rm.read_text("utf-8"))
            topic = mdata.get("topic") or ""
            if topic:
                return topic
        except Exception:
            pass
    return ""


def _latest_cli_leaf(cli_out_root: Path) -> Path:
    """
    Given <run>/cli_out, return the leaf directory that actually contains artifacts.
    The CLI creates a timestamped subdir under cli_out; fall back to cli_out itself.
    """
    if not cli_out_root.exists():
        return cli_out_root
    latest_link = cli_out_root / "latest"
    if latest_link.exists():
        try:
            target = latest_link.resolve()
            if target.exists():
                return target
        except Exception:
            pass
    subdirs = [p for p in cli_out_root.iterdir() if p.is_dir()]
    if not subdirs:
        return cli_out_root
    return sorted(subdirs, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def list_runs(out_root: Path) -> list[dict]:
    out_root.mkdir(parents=True, exist_ok=True)
    runs = []
    # Collect candidates from root and optional /out sibling
    candidates = []
    for p in out_root.iterdir():
        if p.is_dir() and not p.is_symlink():
            candidates.append(p)
    out_subdir = out_root / "out"
    if out_subdir.exists() and out_subdir.is_dir():
        for p in out_subdir.iterdir():
            if p.is_dir() and not p.is_symlink():
                candidates.append(p)

    seen_ids = set()
    for d in sorted(candidates, key=lambda p: p.name, reverse=True):
        # Skip symlinks like "latest"
        if d.is_symlink():
            continue
        run_id = d.name
        if run_id in seen_ids:
            continue
        seen_ids.add(run_id)
            
        run_json = d / "run.json"
        if run_json.exists():
            try:
                obj = json.loads(run_json.read_text("utf-8"))
                items = obj.get("manifest", {}).get("items", [])
                total_comments = sum(len(it.get("comments", [])) for it in items)
                manifest = obj.get("manifest", {})
                topic = (
                    manifest.get("knobs", {}).get("topic")
                    or manifest.get("topic")
                    or ""
                )
                # Fallback: parse topic from CLI string if present
                if not topic:
                    cli_str = manifest.get("knobs", {}).get("cli") or ""
                    if "--topic" in cli_str:
                        try:
                            parts = cli_str.split("--topic", 1)[1].strip().split()
                            if parts:
                                topic = parts[0].strip().strip('"').strip("'")
                        except Exception:
                            pass
                runs.append({
                    "id": obj.get("id") or d.name,
                    "started_at": manifest.get("started_at"),
                    "topic": topic,
                    "items": len(items),
                    "comments": total_comments,
                })
                continue
            except Exception:
                pass
        
        # Try run_manifest.json for metadata (CLI output format)
        manifest_json = d / "run_manifest.json"
        started_at = None
        topic = ""
        item_count = 0
        comment_count = 0
        
        if manifest_json.exists():
            try:
                mdata = json.loads(manifest_json.read_text("utf-8"))
                started_at = mdata.get("created_at")
                topic = mdata.get("topic", "")
                # Get parent count from manifest - sum video/post counts, NOT total (which includes comments)
                counts = mdata.get("counts", {})
                item_count = (
                    counts.get("youtube_video", 0) + 
                    counts.get("reddit_post", 0)
                )
                comment_count = (
                    counts.get("youtube_comment", 0) +
                    counts.get("reddit_comment", 0)
                )
            except Exception:
                pass
        
        # If no item count from manifest, try to count from raw.jsonl or cli_out
        if item_count == 0:
            # Try raw.jsonl at root first - count parents and comments separately
            raw_jsonl = d / "raw.jsonl"
            if raw_jsonl.exists():
                try:
                    with raw_jsonl.open(encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                                entry_id = entry.get("id", "")
                                # Parents: YouTube videos have "title" field, Reddit posts start with "t3_"
                                if entry.get("title"):
                                    item_count += 1
                                elif isinstance(entry_id, str) and entry_id.startswith("t3_"):
                                    item_count += 1
                                else:
                                    # Everything else is a comment
                                    comment_count += 1
                            except Exception:
                                continue
                except Exception:
                    pass
            
            # Fallback to cli_out
            if item_count == 0:
                parents = _try_load_parents(d / "cli_out")
                item_count = len(parents)
                # Count comments from parents
                for p in parents:
                    comment_count += len(p.get("comments", []))
        
        runs.append({
            "id": d.name,
            "started_at": started_at,
            "topic": topic,
            "items": item_count,
            "comments": comment_count,
        })
    return runs


def _try_load_parents(cli_out: Path) -> list[dict]:
    leaf = _latest_cli_leaf(cli_out)
    if not leaf.exists():
        return []
    # Try preferred files
    for name in PARENT_FILES:
        f = leaf / name
        if f.exists():
            try:
                obj = json.loads(f.read_text("utf-8"))
                if isinstance(obj, dict) and "items" in obj:
                    return obj["items"]
                if isinstance(obj, list):
                    return obj
            except Exception:
                continue
    # Try raw.jsonl
    raw = leaf / "raw.jsonl"
    if raw.exists():
        items = []
        try:
            with raw.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        items.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            items = []
        if items:
            return map_items(items)
    # Try any .json (largest list)
    best: list = []
    for f in leaf.glob("*.json"):
        try:
            obj = json.loads(f.read_text("utf-8"))
            cand = obj.get("items") if isinstance(obj, dict) else (obj if isinstance(obj, list) else [])
            if isinstance(cand, list) and len(cand) > len(best):
                best = cand
        except Exception:
            pass
    return best


def _make_parent(entry: Dict[str, Any]) -> Dict[str, Any]:
    platform = entry.get("platform")
    if platform == "youtube":
        context = entry.get("context") or {}
        channel_id = context.get("channelId") or ""
        channel_url = f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""
        lang = entry.get("lang") or entry.get("language") or ""
        return {
            "platform": "youtube",
            "kind": "video",
            "id": entry.get("id"),
            "url": entry.get("url"),
            "author": entry.get("author") or "",
            "authorUrl": channel_url,
            "created_at": entry.get("created_at") or "",
            "title": entry.get("title") or "",
            "text": entry.get("text") or "",
            "metrics": entry.get("metrics") or {},
            "context": {"channel": entry.get("author") or "", "channelUrl": channel_url, "lang": lang},
            "comments": [],
            "transcript": "",
        }
    context = entry.get("context") or {}
    subreddit = context.get("subreddit") or ""
    subreddit_url = f"https://www.reddit.com/{subreddit}" if subreddit else ""
    return {
        "platform": "reddit",
        "kind": "post",
        "id": entry.get("id"),
        "url": entry.get("url"),
        "author": entry.get("author") or "",
        "authorUrl": entry.get("author") and f"https://www.reddit.com/u/{entry['author']}" or "",
        "created_at": entry.get("created_at") or "",
        "title": entry.get("title") or "",
        "text": entry.get("text") or "",
        "metrics": entry.get("metrics") or {},
        "context": {"subreddit": subreddit, "subredditUrl": subreddit_url},
        "comments": [],
        "transcript": "",
    }


def _attach_comment(parent: Dict[str, Any], entry: Dict[str, Any]) -> None:
    platform = parent.get("platform", "")
    author = entry.get("author") or ""
    
    # Generate author URL based on platform
    author_url = ""
    if author:
        if platform == "youtube":
            # YouTube comment authors can be linked via channel handle/name
            # The entry might have authorUrl in context or direct field
            author_url = entry.get("authorUrl") or entry.get("context", {}).get("channelUrl") or ""
            if not author_url and author.startswith("@"):
                author_url = f"https://www.youtube.com/{author}"
        elif platform == "reddit":
            # Reddit users are at /u/username
            clean_author = author.replace("u_", "").replace("u/", "")
            author_url = f"https://www.reddit.com/u/{clean_author}"
    
    parent.setdefault("comments", []).append({
        "id": entry.get("id"),
        "author": author,
        "authorUrl": author_url,
        "text": entry.get("text") or "",
        "likes": (entry.get("metrics") or {}).get("likes") or (entry.get("metrics") or {}).get("score"),
        "created_at": entry.get("created_at") or "",
        "url": entry.get("url"),
    })


def _attach_transcript(parent: Dict[str, Any], entry: Dict[str, Any]) -> None:
    parent["transcript"] = entry.get("text") or ""


def map_items(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    parents: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []

    for entry in raw_items:
        entry_id = entry.get("id")
        if entry.get("platform") == "youtube":
            is_transcript = entry.get("title") == "Transcript" or (
                isinstance(entry_id, str) and entry_id.endswith(":transcript")
            )
            if is_transcript:
                continue
        if entry.get("platform") == "youtube" and entry.get("title") and isinstance(entry_id, str):
            if entry_id not in parents:
                order.append(entry_id)
            parents[entry_id] = _make_parent(entry)
            continue
        if isinstance(entry_id, str) and entry_id.startswith("t3_"):
            if entry_id not in parents:
                order.append(entry_id)
            parents[entry_id] = _make_parent(entry)

    for entry in raw_items:
        platform = entry.get("platform")
        entry_id = entry.get("id")
        if platform == "youtube":
            if entry.get("title") == "Transcript" or (isinstance(entry_id, str) and entry_id.endswith(":transcript")):
                parent_key = entry_id.split(":")[0] if entry_id else entry.get("context", {}).get("videoId")
                parent = parents.get(parent_key)
                if parent:
                    _attach_transcript(parent, entry)
                continue
            parent_key = entry.get("context", {}).get("videoId")
            parent = parents.get(parent_key)
            if parent:
                _attach_comment(parent, entry)
            continue
        # Reddit
        if isinstance(entry_id, str) and entry_id.startswith("t3_"):
            continue
        parent_key = entry.get("context", {}).get("post_id")
        parent = parents.get(parent_key)
        if parent:
            _attach_comment(parent, entry)
    return [parents[key] for key in order]


def build_ui_run(run_id: str, run_dir: Path, knobs: dict) -> dict:
    """
    Create the v15 UI run object:
      { id, manifest:{ started_at, knobs, items:[parents-with-embedded-comments] }, stats:{ dropped:{...} } }
    """
    # Try cli_out subdirectory first, then run_dir directly
    parents = _try_load_parents(run_dir / "cli_out")
    if not parents:
        parents = _try_load_parents(run_dir)
    # Ensure topic is set
    if not knobs.get("topic"):
        knobs["topic"] = _infer_topic({"knobs": knobs}, run_dir)
    run = {
        "id": run_id,
        "manifest": {
            "started_at": time_iso(),
            "knobs": knobs,
            "items": parents,
        },
        "stats": {
            "dropped": {"low_views": 0, "low_score": 0, "lang_mismatch": 0}
        }
    }
    (run_dir / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    (run_dir / "run.log").write_text("", encoding="utf-8")
    return run


def time_iso():
    import datetime as _dt
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def load_run(run_id: str, out_root: Path) -> dict | None:
    """
    Load a full run by its ID from the out directory.
    Returns the v15 UI run object shape:
      { id, manifest:{ started_at, knobs, items:[...] }, stats:{ dropped:{...} } }
    Returns None if run not found.
    """
    run_dir = _resolve_run_dir(out_root, run_id)
    if not run_dir.exists() or not run_dir.is_dir():
        return None

    # Try to load from run.json first (created by build_ui_run)
    run_json = run_dir / "run.json"
    if run_json.exists():
        try:
            data = json.loads(run_json.read_text("utf-8"))
            manifest = data.get("manifest", {})
            knobs = manifest.get("knobs", {})
            topic = _infer_topic(manifest, run_dir)
            if topic and not knobs.get("topic"):
                knobs["topic"] = topic
                manifest["knobs"] = knobs
                data["manifest"] = manifest
                # Persist topic fix so future loads show it
                run_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return data
        except Exception:
            pass

    # Otherwise, build from raw data
    # Check for run_manifest.json for metadata
    manifest_json = run_dir / "run_manifest.json"
    knobs: dict = {}
    started_at = ""
    if manifest_json.exists():
        try:
            mdata = json.loads(manifest_json.read_text("utf-8"))
            knobs = {
                "topic": mdata.get("topic", ""),
                "since": mdata.get("since", ""),
            }
            started_at = mdata.get("created_at", "")
        except Exception:
            pass

    # Load items - try multiple locations
    items: list = []

    # First try the run directory itself (for raw.jsonl at root)
    raw_jsonl = run_dir / "raw.jsonl"
    if raw_jsonl.exists():
        items = _load_raw_jsonl(raw_jsonl)

    # Also check cli_out subdirectory
    if not items:
        items = _try_load_parents(run_dir / "cli_out")

    # If still no items, check if there's a direct parents file
    if not items:
        items = _try_load_parents(run_dir)

    # Load stats if available
    stats_json = run_dir / "stats.json"
    stats: dict = {"dropped": {"low_views": 0, "low_score": 0, "lang_mismatch": 0}}
    if stats_json.exists():
        try:
            sdata = json.loads(stats_json.read_text("utf-8"))
            # Map CLI stats format to UI format if needed
            stats = {"dropped": sdata.get("dropped", stats["dropped"])}
        except Exception:
            pass

    manifest = {
        "started_at": started_at or time_iso(),
        "knobs": knobs,
        "items": items,
    }
    topic = _infer_topic(manifest, run_dir)
    if topic and not manifest.get("knobs", {}).get("topic"):
        manifest.setdefault("knobs", {})["topic"] = topic

    return {
        "id": run_id,
        "manifest": manifest,
        "stats": stats,
    }


def _load_raw_jsonl(path: Path) -> list[dict]:
    """Load raw.jsonl and convert to UI item format with embedded comments."""
    items: list = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return map_items(items) if items else []


def get_paste_ready(run_id: str, out_root: Path) -> str | None:
    """
    Load the paste-ready.txt file for a run.
    Returns the file contents or None if not found.
    """
    run_dir = out_root / run_id
    paste_file = run_dir / "paste-ready.txt"
    if paste_file.exists():
        try:
            return paste_file.read_text("utf-8")
        except Exception:
            pass
    # Check cli_out subdirectory
    cli_out = run_dir / "cli_out"
    if cli_out.exists():
        leaf = _latest_cli_leaf(cli_out)
        paste_file = leaf / "paste-ready.txt"
        if paste_file.exists():
            try:
                return paste_file.read_text("utf-8")
            except Exception:
                pass
    return None


def update_item_transcript(run_id: str, item_id: str, transcript: str, out_root: Path) -> bool:
    """
    Update the transcript field for a specific item in the run.json file.
    Creates run.json from raw data if it doesn't exist.
    Returns True if successful, False otherwise.
    """
    run_dir = _resolve_run_dir(out_root, run_id)
    run_json = run_dir / "run.json"
    
    # If run.json doesn't exist, create it from raw data
    if not run_json.exists():
        run_data = load_run(run_id, out_root)
        if not run_data:
            return False
        # Save the loaded run data as run.json
        run_json.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
    
    try:
        run_data = json.loads(run_json.read_text("utf-8"))
        items = run_data.get("manifest", {}).get("items", [])
        
        # Find and update the item
        for item in items:
            if item.get("id") == item_id:
                item["transcript"] = transcript
                # Save back to file
                run_json.write_text(json.dumps(run_data, indent=2), encoding="utf-8")
                return True
        
        return False
    except Exception:
        return False
