"""`arena db ...` commands."""

import argparse

from bot_arena.db import repository as repo


def register(subparsers: argparse._SubParsersAction) -> None:
    db = subparsers.add_parser("db", help="database commands").add_subparsers(required=True)

    p = db.add_parser("migrate", help="create or update the database schema")
    p.set_defaults(func=cmd_migrate)

    p = db.add_parser("runs", help="list recent runs and their leaderboards")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=cmd_runs)

    p = db.add_parser("kill", help="global kill switch: stops all order flow")
    p.add_argument("action", choices=["on", "off", "status"])
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_kill)


def cmd_migrate(args: argparse.Namespace) -> None:
    with repo.connect() as conn:
        applied = repo.migrate(conn)
    print(f"Applied: {', '.join(applied)}" if applied else "Schema is up to date.")


def cmd_runs(args: argparse.Namespace) -> None:
    with repo.connect() as conn:
        for run_id, kind, started, start, end in repo.recent_runs(conn, args.limit):
            print(f"\nRun #{run_id} ({kind}) {start} -> {end}, saved {started:%Y-%m-%d %H:%M}")
            for name, emoji, status, equity in repo.leaderboard(conn, run_id):
                mark = "" if status == "active" else f"  [{status}]"
                print(f"  {emoji} {name:<18}${equity:>10,.2f}{mark}")


def cmd_kill(args: argparse.Namespace) -> None:
    with repo.connect() as conn:
        if args.action != "status":
            repo.set_kill_switch(conn, args.action == "on", args.reason)
        engaged, reason = repo.get_kill_switch(conn)
    state = "ENGAGED: all order flow stopped" if engaged else "off"
    print(f"Kill switch {state}" + (f" ({reason})" if reason else ""))
