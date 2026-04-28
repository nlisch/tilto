#!/usr/bin/env python
"""Local CLI: resolve email -> user_id without ever sending the email to an LLM.

Run from your terminal, paste the user_id into Claude Desktop. The email
stays in your shell, never crosses the MCP/Anthropic boundary.

Usage:
    /Users/nlisch/github/tilto/flask/bin/python bin/lookup.py contact@marie.fr
"""

import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: lookup.py <email>", file=sys.stderr)
        return 1

    email = sys.argv[1].strip().lower()

    conn = pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 3306)),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM users WHERE LOWER(email) = %s LIMIT 1",
                (email,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        print("not found", file=sys.stderr)
        return 2

    print(row[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
