#!/usr/bin/env python3
"""Prism — AI Cost Dashboard for Hermes Agent.

Reads local Hermes state.db files and serves a web dashboard with
spend analytics: by day, model, platform, tools, and individual sessions.
"""

import os
import sqlite3
import statistics
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

app = FastAPI(title="Prism", description="AI Cost Dashboard for Hermes Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# CORS fix for 422 validation errors (not covered by CORSMiddleware)
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
        headers={"Access-Control-Allow-Origin": "*"},
    )


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
    "message_count, tool_call_count, api_call_count, end_reason"
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
                rows = conn.execute(
                    f"SELECT {SESSION_COLUMNS} FROM sessions"
                ).fetchall()
                for r in rows:
                    d = {**dict(r), "profile": profile}
                    d["source"] = _safe_source(d)
                    all_sessions.append(d)
        except Exception:
            continue
    return sorted(all_sessions, key=lambda s: s["started_at"], reverse=True)


def _safe_cost(row: dict) -> float:
    return (
        row.get("estimated_cost_usd") or row.get("actual_cost_usd") or 0.0
    ) or 0.0


# ---------------------------------------------------------------------------
# In-memory cache with TTL
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

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
        models = sorted(
            set(s.get("model") for s in filtered if s.get("model"))
        )
        sources = sorted(
            set(s.get("source") for s in filtered if s.get("source"))
        )

        active_days = len(
            set(
                datetime.fromtimestamp(s["started_at"]).strftime("%Y-%m-%d")
                for s in filtered
            )
        )

        prev_start = cutoff - (days * 86400)
        prev = [s for s in sessions if prev_start <= s["started_at"] < cutoff]
        prev_cost = sum(_safe_cost(s) for s in prev)
        cost_delta = round(
            ((total_cost - prev_cost) / prev_cost * 100)
            if prev_cost > 0
            else 0,
            1,
        )
        avg_cost_per_session = (
            round(total_cost / total_sessions, 4)
            if total_sessions > 0
            else 0
        )

        if filtered:
            latest = max(s["started_at"] for s in filtered)
            earliest = min(s["started_at"] for s in filtered)
            date_range = (
                f"{datetime.fromtimestamp(earliest).strftime('%b %d')} — "
                f"{datetime.fromtimestamp(latest).strftime('%b %d, %Y')}"
            )
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
            day = datetime.fromtimestamp(s["started_at"]).strftime(
                "%Y-%m-%d"
            )
            daily_map[day] = daily_map.get(day, 0) + _safe_cost(s)

        # Ensure all dates are present (fill gaps with 0)
        end = datetime.now().date()
        start = end - timedelta(days=days - 1)
        result = []
        current = start
        while current <= end:
            key = current.isoformat()
            result.append(
                {"date": key, "cost": round(daily_map.get(key, 0), 2)}
            )
            current += timedelta(days=1)

        return result

    return _get_cached_or_fetch(f"daily:{days}", _compute)


@app.get("/api/models")
def models():
    return _get_cached_or_fetch(
        "models",
        lambda: sorted(
            _compute_models(), key=lambda x: x["cost"], reverse=True
        ),
    )


def _compute_models():
    sessions = _fetch_all_sessions()
    model_map: dict[str, dict] = {}
    for s in sessions:
        name = s.get("model") or "unknown"
        if name not in model_map:
            model_map[name] = {
                "model": name,
                "sessions": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost": 0,
                "cache_read": 0,
                "cache_write": 0,
            }
        m = model_map[name]
        m["sessions"] += 1
        m["input_tokens"] += s.get("input_tokens") or 0
        m["output_tokens"] += s.get("output_tokens") or 0
        m["cost"] += _safe_cost(s)
        m["cache_read"] += s.get("cache_read_tokens") or 0
        m["cache_write"] += s.get("cache_write_tokens") or 0

    return [
        {
            "model": k,
            **{
                kk: round(vv, 2) if isinstance(vv, float) else vv
                for kk, vv in v.items()
                if kk != "model"
            },
        }
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
        [
            {
                "source": k,
                "sessions": v["sessions"],
                "cost": round(v["cost"], 2),
            }
            for k, v in src_map.items()
        ],
        key=lambda x: x["cost"],
        reverse=True,
    )


@app.get("/api/sessions")
def sessions(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    def _compute():
        all_s = _fetch_all_sessions()
        page = all_s[offset : offset + limit]

        result = []
        for s in page:
            cost = _safe_cost(s)
            duration = (
                (s["ended_at"] - s["started_at"])
                if s.get("ended_at")
                else None
            )
            result.append(
                {
                    "id": s["id"],
                    "profile": s["profile"],
                    "source": s.get("source", "unknown"),
                    "model": s.get("model", "unknown"),
                    "title": s.get("title", ""),
                    "started_at": datetime.fromtimestamp(
                        s["started_at"]
                    ).isoformat(),
                    "duration_seconds": round(duration, 0)
                    if duration
                    else None,
                    "input_tokens": s.get("input_tokens") or 0,
                    "output_tokens": s.get("output_tokens") or 0,
                    "cost": round(cost, 4),
                    "message_count": s.get("message_count") or 0,
                    "tool_call_count": s.get("tool_call_count") or 0,
                    "end_reason": s.get("end_reason") or None,
                }
            )

        return {"sessions": result, "total": len(all_s)}

    return _get_cached_or_fetch(
        f"sessions:{limit}:{offset}", _compute
    )


@app.get("/api/expensive")
def expensive(limit: int = Query(default=20, ge=1, le=100)):
    def _compute():
        sessions = _fetch_all_sessions()
        sorted_s = sorted(
            sessions, key=lambda s: _safe_cost(s), reverse=True
        )

        result = []
        for s in sorted_s[:limit]:
            cost = _safe_cost(s)
            duration = (
                (s["ended_at"] - s["started_at"])
                if s.get("ended_at")
                else None
            )
            result.append(
                {
                    "id": s["id"],
                    "profile": s["profile"],
                    "source": s.get("source", "unknown"),
                    "model": s.get("model", "unknown"),
                    "title": s.get("title", ""),
                    "started_at": datetime.fromtimestamp(
                        s["started_at"]
                    ).isoformat(),
                    "duration_seconds": round(duration, 0)
                    if duration
                    else None,
                    "input_tokens": s.get("input_tokens") or 0,
                    "output_tokens": s.get("output_tokens") or 0,
                    "cost": round(cost, 4),
                    "message_count": s.get("message_count") or 0,
                    "end_reason": s.get("end_reason") or None,
                }
            )

        return result

    return _get_cached_or_fetch(f"expensive:{limit}", _compute)


# ---------------------------------------------------------------------------
# Analytics endpoints
# ---------------------------------------------------------------------------

@app.get("/api/efficiency")
def efficiency():
    def _compute():
        all_sessions = _fetch_all_sessions()

        # Pre-compute cost per message
        for s in all_sessions:
            mc = s.get("message_count") or 0
            s["_cpm"] = _safe_cost(s) / mc if mc > 0 else 0

        # Inefficient sessions: highest cost/message_count ratio, top 20
        sessions_with_cpm = [
            s for s in all_sessions if s.get("message_count", 0) > 0
        ]
        sorted_by_cpm = sorted(
            sessions_with_cpm, key=lambda s: s["_cpm"], reverse=True
        )

        inefficient_sessions = []
        for s in sorted_by_cpm[:20]:
            duration = (
                (s["ended_at"] - s["started_at"])
                if s.get("ended_at")
                else None
            )
            inefficient_sessions.append(
                {
                    "id": s["id"],
                    "model": s.get("model", "unknown"),
                    "source": s.get("source", "unknown"),
                    "title": s.get("title", ""),
                    "started_at": datetime.fromtimestamp(
                        s["started_at"]
                    ).isoformat(),
                    "cost": round(_safe_cost(s), 4),
                    "message_count": s.get("message_count") or 0,
                    "cost_per_message": round(s["_cpm"], 6),
                    "duration_seconds": round(duration, 0)
                    if duration
                    else None,
                }
            )

        # Stuck sessions: tool_call_count > 10 AND output_tokens < 1000
        stuck = []
        for s in all_sessions:
            tool_count = s.get("tool_call_count") or 0
            output_tokens = s.get("output_tokens") or 0
            if tool_count > 10 and output_tokens < 1000:
                duration = (
                    (s["ended_at"] - s["started_at"])
                    if s.get("ended_at")
                    else None
                )
                stuck.append(
                    {
                        "id": s["id"],
                        "model": s.get("model", "unknown"),
                        "source": s.get("source", "unknown"),
                        "title": s.get("title", ""),
                        "started_at": datetime.fromtimestamp(
                            s["started_at"]
                        ).isoformat(),
                        "cost": round(_safe_cost(s), 4),
                        "message_count": s.get("message_count") or 0,
                        "tool_call_count": tool_count,
                        "output_tokens": output_tokens,
                        "duration_seconds": round(duration, 0)
                        if duration
                        else None,
                    }
                )
        stuck.sort(key=lambda x: x["tool_call_count"], reverse=True)
        stuck_sessions = stuck[:20]

        # Cache inefficiency: per-model analysis
        model_cache: dict[str, dict] = {}
        for s in all_sessions:
            model = s.get("model") or "unknown"
            if model not in model_cache:
                model_cache[model] = {
                    "model": model,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                }
            model_cache[model]["cache_read_tokens"] += (
                s.get("cache_read_tokens") or 0
            )
            model_cache[model]["cache_write_tokens"] += (
                s.get("cache_write_tokens") or 0
            )

        cache_inefficiency = []
        total_read = 0
        total_write = 0
        for model, data in sorted(
            model_cache.items(),
            key=lambda x: x[1]["cache_write_tokens"],
            reverse=True,
        ):
            cr = data["cache_read_tokens"]
            cw = data["cache_write_tokens"]
            total = cr + cw
            ratio = round(cr / total, 2) if total > 0 else 0.0
            cache_inefficiency.append(
                {
                    "model": data["model"],
                    "cache_read_tokens": cr,
                    "cache_write_tokens": cw,
                    "cache_hit_ratio": ratio,
                }
            )
            total_read += cr
            total_write += cw

        # Summary
        cpms = [
            _safe_cost(s) / s["message_count"]
            for s in all_sessions
            if s.get("message_count", 0) > 0
        ]
        median_cpm = statistics.median(cpms) if cpms else 0

        total_cost = sum(_safe_cost(s) for s in all_sessions)
        total_messages = sum(
            s.get("message_count") or 0 for s in all_sessions
        )
        avg_cost_per_message = (
            round(total_cost / total_messages, 4)
            if total_messages > 0
            else 0
        )

        total_stuck = len(stuck)
        total_inefficient = sum(
            1
            for s in all_sessions
            if s.get("message_count", 0) > 0 and s["_cpm"] > median_cpm
        )

        overall_total = total_read + total_write
        cache_hit_rate = (
            round(total_read / overall_total, 4)
            if overall_total > 0
            else 0.0
        )

        return {
            "inefficient_sessions": inefficient_sessions,
            "stuck_sessions": stuck_sessions,
            "cache_inefficiency": cache_inefficiency,
            "summary": {
                "avg_cost_per_message": avg_cost_per_message,
                "total_stuck_sessions": total_stuck,
                "total_inefficient_sessions": total_inefficient,
                "cache_hit_rate": cache_hit_rate,
            },
        }

    return _get_cached_or_fetch("efficiency", _compute)


@app.get("/api/bottlenecks")
def bottlenecks():
    def _compute():
        all_sessions = _fetch_all_sessions()

        # Cost per message for sessions with messages
        cpms = []
        for s in all_sessions:
            mc = s.get("message_count") or 0
            if mc > 0:
                cpms.append(_safe_cost(s) / mc)
                s["_cpm"] = _safe_cost(s) / mc
            else:
                s["_cpm"] = 0

        median_cpm = statistics.median(cpms) if cpms else 0

        # Wasted sessions percent: sessions with cpm above median
        wasted_count = sum(1 for c in cpms if c > median_cpm)
        wasted_percent = (
            round((wasted_count / len(cpms)) * 100, 2) if cpms else 0
        )

        # Avg cost per message
        total_cost = sum(_safe_cost(s) for s in all_sessions)
        total_messages = sum(
            s.get("message_count") or 0 for s in all_sessions
        )
        avg_cost_per_message = (
            round(total_cost / total_messages, 4)
            if total_messages > 0
            else 0
        )

        # Stuck sessions
        stuck_sessions = [
            s
            for s in all_sessions
            if (s.get("tool_call_count") or 0) > 10
            and (s.get("output_tokens") or 0) < 1000
        ]
        stuck_session_count = len(stuck_sessions)

        # Most expensive model by waste
        stuck_model_costs: dict[str, float] = {}
        for s in stuck_sessions:
            model = s.get("model") or "unknown"
            stuck_model_costs[model] = (
                stuck_model_costs.get(model, 0) + _safe_cost(s)
            )
        most_expensive_model_by_waste = (
            max(stuck_model_costs, key=stuck_model_costs.get)
            if stuck_model_costs
            else None
        )

        # Inefficient sessions: cpm > median
        inefficient_sessions = [
            s
            for s in all_sessions
            if s.get("message_count", 0) > 0 and s["_cpm"] > median_cpm
        ]

        # Top 5 models by total cost in inefficient sessions
        ineff_model_costs: dict[str, float] = {}
        for s in inefficient_sessions:
            model = s.get("model") or "unknown"
            ineff_model_costs[model] = (
                ineff_model_costs.get(model, 0) + _safe_cost(s)
            )
        top_waste_models = [
            {"model": m, "total_cost": round(c, 4)}
            for m, c in sorted(
                ineff_model_costs.items(), key=lambda x: x[1], reverse=True
            )[:5]
        ]

        return {
            "wasted_sessions_percent": wasted_percent,
            "avg_cost_per_message": avg_cost_per_message,
            "most_expensive_model_by_waste": most_expensive_model_by_waste,
            "stuck_session_count": stuck_session_count,
            "top_waste_models": top_waste_models,
        }

    return _get_cached_or_fetch("bottlenecks", _compute)


@app.get("/api/context")
def context():
    def _compute():
        all_sessions = _fetch_all_sessions()

        # Compression events
        compression_events = sum(
            1
            for s in all_sessions
            if s.get("end_reason")
            and "compression" in str(s["end_reason"]).lower()
        )

        # Reset events
        reset_events = sum(
            1
            for s in all_sessions
            if s.get("end_reason")
            and "reset" in str(s["end_reason"]).lower()
        )

        # Sessions with context pressure: message_count > 100
        sessions_with_context_pressure = sum(
            1 for s in all_sessions if (s.get("message_count") or 0) > 100
        )

        # Context pressure by model
        model_ctx: dict[str, dict] = {}
        for s in all_sessions:
            model = s.get("model") or "unknown"
            if model not in model_ctx:
                model_ctx[model] = {
                    "model": model,
                    "total_messages": 0,
                    "session_count": 0,
                    "compression_reset_count": 0,
                }
            mc = model_ctx[model]
            mc["total_messages"] += s.get("message_count") or 0
            mc["session_count"] += 1
            end_reason = str(s.get("end_reason") or "").lower()
            if "compression" in end_reason or "reset" in end_reason:
                mc["compression_reset_count"] += 1

        context_pressure_by_model = []
        for model, data in sorted(model_ctx.items()):
            avg_msgs = (
                round(data["total_messages"] / data["session_count"], 2)
                if data["session_count"] > 0
                else 0
            )
            cr_rate = (
                round(
                    (data["compression_reset_count"] / data["session_count"])
                    * 100,
                    2,
                )
                if data["session_count"] > 0
                else 0
            )
            context_pressure_by_model.append(
                {
                    "model": model,
                    "avg_messages_per_session": avg_msgs,
                    "compression_reset_rate": cr_rate,
                    "session_count": data["session_count"],
                }
            )
        context_pressure_by_model.sort(
            key=lambda x: x["avg_messages_per_session"], reverse=True
        )

        # Message count distribution
        bucket_defs = [
            ("0-20", 0, 20),
            ("21-50", 21, 50),
            ("51-100", 51, 100),
            ("101-200", 101, 200),
            ("200+", 201, float("inf")),
        ]
        buckets = {name: 0 for name, _, _ in bucket_defs}
        for s in all_sessions:
            mc = s.get("message_count") or 0
            for name, lo, hi in bucket_defs:
                if lo <= mc <= hi:
                    buckets[name] += 1
                    break
        message_count_distribution = [
            {"bucket": name, "count": count}
            for name, count in [(n, buckets[n]) for n, _, _ in bucket_defs]
        ]

        # Longest sessions: top 10 by message_count
        sorted_by_msgs = sorted(
            all_sessions, key=lambda s: s.get("message_count") or 0, reverse=True
        )
        longest_sessions = []
        for s in sorted_by_msgs[:10]:
            duration = (
                (s["ended_at"] - s["started_at"])
                if s.get("ended_at")
                else None
            )
            longest_sessions.append(
                {
                    "id": s["id"],
                    "model": s.get("model", "unknown"),
                    "source": s.get("source", "unknown"),
                    "title": s.get("title", ""),
                    "message_count": s.get("message_count") or 0,
                    "duration_seconds": round(duration, 0)
                    if duration
                    else None,
                    "cost": round(_safe_cost(s), 4),
                }
            )

        # End reason distribution
        end_reason_dist: dict[str, int] = {}
        for s in all_sessions:
            reason = s.get("end_reason")
            if reason and str(reason).strip():
                reason_str = str(reason).strip()
            else:
                reason_str = "none"
            end_reason_dist[reason_str] = (
                end_reason_dist.get(reason_str, 0) + 1
            )
        end_reason_distribution = [
            {"reason": k, "count": v}
            for k, v in sorted(
                end_reason_dist.items(), key=lambda x: x[1], reverse=True
            )
        ]

        return {
            "compression_events": compression_events,
            "reset_events": reset_events,
            "sessions_with_context_pressure": sessions_with_context_pressure,
            "context_pressure_by_model": context_pressure_by_model,
            "message_count_distribution": message_count_distribution,
            "longest_sessions": longest_sessions,
            "end_reason_distribution": end_reason_distribution,
        }

    return _get_cached_or_fetch("context", _compute)


# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------

@app.get("/api/databases")
def databases():
    """List discovered databases with session counts."""
    dbs = discover_databases()
    result = []
    for db_path in dbs:
        profile = _profile_name(db_path)
        try:
            with get_db(db_path) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM sessions"
                ).fetchone()[0]
                size_kb = round(os.path.getsize(db_path) / 1024, 1)
                result.append(
                    {
                        "profile": profile,
                        "path": db_path,
                        "sessions": count,
                        "size_kb": size_kb,
                    }
                )
        except Exception:
            result.append(
                {
                    "profile": profile,
                    "path": db_path,
                    "error": "unreadable",
                }
            )
    return result


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "static", "index.html")
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, uvicorn

    parser = argparse.ArgumentParser(
        description="Prism — AI Cost Dashboard for Hermes Agent"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PRISM_PORT", 8081)),
        help="Port to serve on (default: 8081 or $PRISM_PORT)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
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

    print(
        f"\n  📊 Discovered {len(dbs)} databases | {total_sessions} sessions | ${total_cost:.2f} total"
    )
    print(
        f"  🚀 Serving at http://localhost:{port}  (Ctrl+C to stop)\n"
    )

    uvicorn.run(app, host=args.host, port=port)
