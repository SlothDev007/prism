#!/usr/bin/env python3
"""Prism — AI Cost Dashboard for Hermes Agent.

Reads local Hermes state.db files and serves a web dashboard with
spend analytics: by day, model, platform, tools, and individual sessions.
"""

import glob
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(title="Prism", description="AI Cost Dashboard for Hermes Agent")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])

# ---------------------------------------------------------------------------
# Database discovery
# ---------------------------------------------------------------------------

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

def discover_databases() -> list[str]:
    """Find all state.db files: main + profile databases."""
    dbs: list[str] = []
    main_db = HERMES_HOME / "state.db"
    if main_db.exists():
        dbs.append(str(main_db))
    profile_dir = HERMES_HOME / "profiles"
    if profile_dir.exists():
        for profile_path in sorted(profile_dir.iterdir()):
            if profile_path.is_dir():
                profile_db = profile_path / "state.db"
                if profile_db.exists():
                    dbs.append(str(profile_db))
    return dbs

@contextmanager
def get_db(db_path: str):
    """Context manager that yields a sqlite3 connection with row factory."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def _profile_name(db_path: str) -> str:
    """Extract profile name from db path. 'main' for root db."""
    parts = Path(db_path).parts
    try:
        idx = parts.index("profiles")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return "main"

# ---------------------------------------------------------------------------
# Data queries
# ---------------------------------------------------------------------------

SESSION_COLUMNS = (
    "id, source, user_id, model, started_at, ended_at, "
    "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, "
    "estimated_cost_usd, actual_cost_usd, cost_status, title, "
    "message_count, tool_call_count, api_call_count"
)

def _safe_source(row: dict) -> str:
    return (row.get("source") or "unknown").strip() or "unknown"

def _fetch_all_sessions() -> list[dict]:
    """Merge sessions from all databases, adding profile name."""
    dbs = discover_databases()
    all_sessions: list[dict] = []
    for db_path in dbs:
        profile = _profile_name(db_path)
        try:
            with get_db(db_path) as conn:
                rows = conn.execute(f"SELECT {SESSION_COLUMNS} FROM sessions").fetchall()
                for r in rows:
                    d = {**dict(r), "profile": profile}
                    d["source"] = _safe_source(d)
                    all_sessions.append(d)
        except Exception:
            continue
    return sorted(all_sessions, key=lambda s: s["started_at"], reverse=True)

def _safe_cost(row: dict) -> float:
    return (row.get("estimated_cost_usd") or row.get("actual_cost_usd") or 0.0) or 0.0

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

# Simple in-memory cache with TTL
_cache: dict = {}
CACHE_TTL = 15  # seconds

def _get_cached_or_fetch(key: str, fetch_fn):
    """Return cached result if fresh, otherwise call fetch_fn and cache it."""
    now = time.time()
    cached = _cache.get(key)
    if cached and (now - cached["at"]) < CACHE_TTL:
        return cached["data"]
    data = fetch_fn()
    _cache[key] = {"data": data, "at": now}
    return data

def _invalidate_cache():
    _cache.clear()

@app.get("/api/overview")
def overview(days: int = Query(default=30, ge=1, le=9999)):
    def _compute():
        sessions = _fetch_all_sessions()
        cutoff = time.time() - (days * 86400)
        filtered = [s for s in sessions if s["started_at"] >= cutoff]

        total_cost = sum(_safe_cost(s) for s in filtered)
        total_sessions = len(filtered)
        total_input = sum(s.get("input_tokens") or 0 for s in filtered)
        total_output = sum(s.get("output_tokens") or 0 for s in filtered)
        models = sorted(set(s.get("model") for s in filtered if s.get("model")))
        sources = sorted(set(s.get("source") for s in filtered if s.get("source")))

        active_days = len(set(
            datetime.fromtimestamp(s["started_at"]).strftime("%Y-%m-%d")
            for s in filtered
        ))

        prev_start = cutoff - (days * 86400)
        prev = [s for s in sessions if prev_start <= s["started_at"] < cutoff]
        prev_cost = sum(_safe_cost(s) for s in prev)
        cost_delta = round(((total_cost - prev_cost) / prev_cost * 100) if prev_cost > 0 else 0, 1)
        avg_cost_per_session = round(total_cost / total_sessions, 4) if total_sessions > 0 else 0

        if filtered:
            latest = max(s["started_at"] for s in filtered)
            earliest = min(s["started_at"] for s in filtered)
            date_range = f"{datetime.fromtimestamp(earliest).strftime('%b %d')} — {datetime.fromtimestamp(latest).strftime('%b %d, %Y')}"
        else:
            date_range = "No sessions found"

        return {
            "total_cost": round(total_cost, 2),
            "total_sessions": total_sessions,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "models": models,
            "sources": sources,
            "active_days": active_days,
            "avg_cost_per_session": avg_cost_per_session,
            "cost_delta_pct": cost_delta,
            "prev_period_cost": round(prev_cost, 2),
            "date_range": date_range,
            "profiles": sorted(set(s["profile"] for s in filtered)),
            "last_updated": datetime.now().isoformat(),
        }

    return _get_cached_or_fetch(f"overview:{days}", _compute)

@app.get("/api/daily")
def daily(days: int = Query(default=30, ge=1, le=9999)):
    def _compute():
        sessions = _fetch_all_sessions()
        cutoff = time.time() - (days * 86400)
        filtered = [s for s in sessions if s["started_at"] >= cutoff]

        daily_map: dict[str, float] = {}
        for s in filtered:
            day = datetime.fromtimestamp(s["started_at"]).strftime("%Y-%m-%d")
            daily_map[day] = daily_map.get(day, 0) + _safe_cost(s)

        # Ensure all dates are present (fill gaps with 0)
        end = datetime.now().date()
        start = end - timedelta(days=days - 1)
        result = []
        current = start
        while current <= end:
            key = current.isoformat()
            result.append({"date": key, "cost": round(daily_map.get(key, 0), 2)})
            current += timedelta(days=1)

        return result

    return _get_cached_or_fetch(f"daily:{days}", _compute)

@app.get("/api/models")
def models():
    return _get_cached_or_fetch("models", lambda: sorted(_compute_models(), key=lambda x: x["cost"], reverse=True))

def _compute_models():
    sessions = _fetch_all_sessions()
    model_map: dict[str, dict] = {}
    for s in sessions:
        name = s.get("model") or "unknown"
        if name not in model_map:
            model_map[name] = {
                "model": name,
                "sessions": 0, "input_tokens": 0, "output_tokens": 0,
                "cost": 0, "cache_read": 0, "cache_write": 0,
            }
        m = model_map[name]
        m["sessions"] += 1
        m["input_tokens"] += s.get("input_tokens") or 0
        m["output_tokens"] += s.get("output_tokens") or 0
        m["cost"] += _safe_cost(s)
        m["cache_read"] += s.get("cache_read_tokens") or 0
        m["cache_write"] += s.get("cache_write_tokens") or 0

    return [
        {"model": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items() if kk != "model"}}
        for k, v in model_map.items()
    ]

@app.get("/api/sources")
def sources():
    return _get_cached_or_fetch("sources", _compute_sources)

def _compute_sources():
    sessions = _fetch_all_sessions()
    src_map: dict[str, dict] = {}
    for s in sessions:
        name = s.get("source") or "unknown"
        if name not in src_map:
            src_map[name] = {"source": name, "sessions": 0, "cost": 0}
        src_map[name]["sessions"] += 1
        src_map[name]["cost"] += _safe_cost(s)

    return sorted(
        [{"source": k, "sessions": v["sessions"], "cost": round(v["cost"], 2)} for k, v in src_map.items()],
        key=lambda x: x["cost"], reverse=True,
    )

@app.get("/api/sessions")
def sessions(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    all_s = _fetch_all_sessions()
    page = all_s[offset : offset + limit]

    result = []
    for s in page:
        cost = _safe_cost(s)
        duration = (s["ended_at"] - s["started_at"]) if s.get("ended_at") else None
        result.append({
            "id": s["id"],
            "profile": s["profile"],
            "source": s.get("source", "unknown"),
            "model": s.get("model", "unknown"),
            "title": s.get("title", ""),
            "started_at": datetime.fromtimestamp(s["started_at"]).isoformat(),
            "duration_seconds": round(duration, 0) if duration else None,
            "input_tokens": s.get("input_tokens") or 0,
            "output_tokens": s.get("output_tokens") or 0,
            "cost": round(cost, 4),
            "message_count": s.get("message_count") or 0,
            "tool_call_count": s.get("tool_call_count") or 0,
        })

    return {"sessions": result, "total": len(all_s)}

@app.get("/api/expensive")
def expensive(limit: int = Query(default=20, ge=1, le=100)):
    sessions = _fetch_all_sessions()
    sorted_s = sorted(sessions, key=lambda s: _safe_cost(s), reverse=True)

    result = []
    for s in sorted_s[:limit]:
        cost = _safe_cost(s)
        duration = (s["ended_at"] - s["started_at"]) if s.get("ended_at") else None
        result.append({
            "id": s["id"],
            "profile": s["profile"],
            "model": s.get("model", "unknown"),
            "title": s.get("title", ""),
            "started_at": datetime.fromtimestamp(s["started_at"]).isoformat(),
            "duration_seconds": round(duration, 0) if duration else None,
            "input_tokens": s.get("input_tokens") or 0,
            "output_tokens": s.get("output_tokens") or 0,
            "cost": round(cost, 4),
        })

    return result

@app.get("/api/databases")
def databases():
    """List discovered databases with session counts."""
    dbs = discover_databases()
    result = []
    for db_path in dbs:
        profile = _profile_name(db_path)
        try:
            with get_db(db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                size_kb = round(os.path.getsize(db_path) / 1024, 1)
                result.append({
                    "profile": profile,
                    "path": db_path,
                    "sessions": count,
                    "size_kb": size_kb,
                })
        except Exception:
            result.append({"profile": profile, "path": db_path, "error": "unreadable"})
    return result

# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, uvicorn

    parser = argparse.ArgumentParser(description="Prism — AI Cost Dashboard for Hermes Agent")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PRISM_PORT", 8081)),
                        help="Port to serve on (default: 8081 or $PRISM_PORT)")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    port = args.port

    dbs = discover_databases()
    total_sessions = 0
    total_cost = 0.0
    for db_path in dbs:
        profile = _profile_name(db_path)
        try:
            with get_db(db_path) as conn:
                stats = conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(COALESCE(estimated_cost_usd, actual_cost_usd, 0)), 0) FROM sessions"
                ).fetchone()
                total_sessions += stats[0]
                total_cost += stats[1]
                print(f"  ✓ {profile}: {stats[0]} sessions, ${stats[1]:.2f}")
        except Exception as e:
            print(f"  ✗ {profile}: {e}")

    print(f"\n  📊 Discovered {len(dbs)} databases | {total_sessions} sessions | ${total_cost:.2f} total")
    print(f"  🚀 Serving at http://localhost:{port}  (Ctrl+C to stop)\n")

    uvicorn.run(app, host=args.host, port=port)
