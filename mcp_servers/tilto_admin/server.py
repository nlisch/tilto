"""Tilto admin MCP server — read-only tools for querying Tilto data from Claude Desktop.

Connects to the dev DB via the project's .env file. Read-only by convention
(SELECT statements only). No PII in tool inputs or outputs by design:
sensitive fields (email, name, phone, address, free-text quiz answers,
order notes) are stripped server-side via field whitelisting before any
data leaves this process.
"""

import sys
import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import pymysql
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
sys.path.insert(0, str(PROJECT_ROOT))

from services.user_context_service import UserContextService  # noqa: E402

mcp = FastMCP("tilto-admin")


# ─────────────────────────────────────────────────────────────
# DB connection (read-only by convention)
# ─────────────────────────────────────────────────────────────

@contextmanager
def _db_cursor():
    conn = pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
    )
    try:
        yield conn.cursor()
    finally:
        conn.close()


def _coerce(v: Any) -> Any:
    """JSON-safe coercion for DB values (datetime, Decimal, bytes)."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


def _pick(row: dict, fields: set[str]) -> dict:
    """Return a copy of `row` with only whitelisted fields, JSON-safe."""
    return {k: _coerce(v) for k, v in row.items() if k in fields}


# ─────────────────────────────────────────────────────────────
# PII whitelists (server-side filtering before any data leaves)
# ─────────────────────────────────────────────────────────────

# Excluded from `users`: username, firstname, lastname, email, phone_number,
# address, profile_picture, two_factor_secret, access_token, invite_token,
# invite_expiry, lead_notes (free-text, may contain PII).
SAFE_USER_FIELDS = {
    "user_id", "country_code", "user_status",
    "lead_source", "lead_status", "lead_interest",
    "nb_accompagnement", "onboarding_stage", "is_google_user",
    "newsletter_subscription", "partner_consent", "privacy_policy_accepted",
    "last_login", "last_contacted", "created_at", "updated_at",
}

SAFE_QUIZ_FIELDS = {
    "quiz_session_id", "quiz_id", "quiz_type", "quiz_status",
    "start_time", "end_time", "session_duration",
    "questions_answered_count", "created_at", "updated_at",
}

SAFE_ANALYSIS_FIELDS = {
    "result_id", "result_step_id", "quiz_id", "generator_type", "is_active",
    "generation_time_seconds", "api_call_time_seconds", "created_at",
    "result_size",
}

# Excluded from `orders`: notes (free-text, may contain PII).
SAFE_ORDER_FIELDS = {
    "order_id", "order_number", "order_amount", "discount_amount",
    "currency", "status", "payment_method", "discount_code",
    "created_at", "updated_at",
}

SAFE_BOOKING_FIELDS = {
    "booking_id", "product_id", "status", "scheduled_at",
    "created_at", "updated_at",
}


# ─────────────────────────────────────────────────────────────
# Tools
# ─────────────────────────────────────────────────────────────

@mcp.tool()
def ping(message: str = "pong") -> dict:
    """Health check. Echoes the message back with a server timestamp."""
    return {
        "server": "tilto-admin",
        "echo": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@mcp.tool()
def list_recent_quizzes(
    days: int = 7,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """List recent quiz sessions, most recent first. No PII in the response.

    Useful queries:
    - "quizzes in the last 24h" → days=1
    - "completed quizzes this week" → days=7, status='completed'

    Args:
        days: Lookback window in days (default 7).
        status: Optional filter on quiz_status.
        limit: Max rows (default 50, capped at 200).
    """
    limit = max(1, min(limit, 200))
    sql = """
        SELECT
            qu.user_id, qu.quiz_session_id, qu.quiz_id, qc.quiz_type,
            qu.quiz_status, qu.start_time, qu.end_time,
            qu.session_duration, qu.questions_answered_count, qu.created_at
        FROM quiz_user qu
        LEFT JOIN quiz_catalog qc ON qu.quiz_id = qc.quiz_id
        WHERE qu.created_at >= (NOW() - INTERVAL %s DAY)
    """
    params: list = [days]
    if status:
        sql += " AND qu.quiz_status = %s"
        params.append(status)
    sql += " ORDER BY qu.created_at DESC LIMIT %s"
    params.append(limit)

    with _db_cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [{k: _coerce(v) for k, v in r.items()} for r in rows]


@mcp.tool()
def get_user_summary(user_id: int) -> dict:
    """360° view of a user, with all PII stripped server-side.

    Returns: profile metadata (status, lead info, dates), aggregated stats
    (quiz count, paid orders, total spent, etc.), and metadata of recent
    quizzes, analyses, orders, bookings.

    Does NOT return: email, name, phone, address, free-text quiz answers,
    order notes, raw chat messages. These are dropped by a whitelist before
    leaving the MCP server.

    Use list_recent_quizzes first to find a user_id by context.

    Args:
        user_id: The user's numeric id.
    """
    with _db_cursor() as cur:
        ctx = UserContextService(cur, user_id)
        full = ctx.get_full_context()

    if not full:
        return {"error": f"User {user_id} not found", "user_id": user_id}

    return {
        "user_id": user_id,
        "profile": _pick(full.get("user", {}), SAFE_USER_FIELDS),
        "stats": {k: _coerce(v) for k, v in full.get("stats", {}).items()},
        "recent_quizzes": [_pick(q, SAFE_QUIZ_FIELDS) for q in full.get("quiz_sessions", [])[:10]],
        "recent_analyses": [_pick(a, SAFE_ANALYSIS_FIELDS) for a in full.get("analysis_results", [])[:10]],
        "orders": [_pick(o, SAFE_ORDER_FIELDS) for o in full.get("orders", [])],
        "bookings": [_pick(b, SAFE_BOOKING_FIELDS) for b in full.get("bookings", [])],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
