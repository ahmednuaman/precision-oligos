"""Command-line entrypoint for local development and operations.

Runs the same pipeline steps in-process (no Step Functions required), which is
useful for testing agents and rule-packs against a configured knowledge base.

Examples:
    oligos-agents serve
    oligos-agents run "Check QC conflicts for batch B-2024-0419-003"
    oligos-agents show run-abc123
    oligos-agents approve run-abc123 --sub reviewer-1 --role QCManager
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from oligos_agents.deps import AgentDeps
from oligos_agents.models import Role
from oligos_agents.steps import pipeline
from oligos_agents.store import load_run
from oligos_agents.workflows.conflict_resynthesis import create_run, run_pipeline


def _cmd_run(args: argparse.Namespace) -> int:
    deps = AgentDeps()
    run = create_run(deps, args.query, submitter_sub=args.sub)
    result = asyncio.run(run_pipeline(deps, run.run_id))
    print(result.model_dump_json(indent=2))  # noqa: T201 - CLI output
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    deps = AgentDeps()
    run = load_run(deps, args.run_id)
    if run is None:
        print(f"Run not found: {args.run_id}", file=sys.stderr)  # noqa: T201
        return 1
    print(run.model_dump_json(indent=2))  # noqa: T201
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    deps = AgentDeps()
    run = pipeline.apply_approval(
        deps,
        args.run_id,
        approver_sub=args.sub,
        approver_roles=[Role(args.role)],
        approved=not args.reject,
        comment=args.comment,
    )
    print(run.model_dump_json(indent=2))  # noqa: T201
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("oligos_agents.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oligos-agents", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run the pipeline in-process for a query.")
    p_run.add_argument("query")
    p_run.add_argument("--sub", default="cli-user", help="Submitter identity (Cognito sub).")
    p_run.set_defaults(func=_cmd_run)

    p_show = sub.add_parser("show", help="Print a run's current state.")
    p_show.add_argument("run_id")
    p_show.set_defaults(func=_cmd_show)

    p_approve = sub.add_parser("approve", help="Approve or reject a pending re-synthesis order.")
    p_approve.add_argument("run_id")
    p_approve.add_argument("--sub", required=True, help="Approver identity (must differ).")
    p_approve.add_argument("--role", default=Role.QC_MANAGER.value)
    p_approve.add_argument("--reject", action="store_true")
    p_approve.add_argument("--comment", default=None)
    p_approve.set_defaults(func=_cmd_approve)

    p_serve = sub.add_parser("serve", help="Run the FastAPI control-plane.")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
