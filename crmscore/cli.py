"""crm-agent command line.

    crm-agent simulate                     replay 15 lead months and 6 account quarters, end to end
    crm-agent dashboard                    render space/index.html from the last run
    crm-agent cycle lead 2026-09           one live cycle (add --approve --approver NAME for accounts)
    crm-agent registry lead                model registry
    crm-agent card lead-v21                model card
    crm-agent explain lead L-202609-24011  why a record scored what it did
    crm-agent rollback lead --reason "..." restore the previous champion
    crm-agent approve account-v13 --approver "Jane, RevOps"
    crm-agent simulate --leave-last        replay history but leave the last period to run live
    crm-agent a2a-serve                    run the three agents as A2A HTTP services
    crm-agent cycle lead 2026-09 --transport a2a   (in a second terminal)
    crm-agent mcp                          run the MCP server on stdio
    crm-agent sf-seed --accounts 300 --leads 500   seed a Salesforce Developer Edition org
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _print(obj):
    from .agents.a2a import to_jsonable
    print(json.dumps(to_jsonable(obj), indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="crm-agent", description="Agent lifecycle management for CRM scoring models")
    ap.add_argument("--workdir", default=os.getenv("CRM_WORKDIR", "demo_run"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("simulate")
    sp.add_argument("--objects", nargs="+", default=["lead", "account"])
    sp.add_argument("--leave-last", action="store_true",
                    help="skip the final cycle so you can run it live (in-process or over A2A)")

    sub.add_parser("dashboard")

    sp = sub.add_parser("cycle")
    sp.add_argument("obj", choices=["lead", "account"])
    sp.add_argument("period")
    sp.add_argument("--approve", action="store_true")
    sp.add_argument("--approver", default="")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--transport", choices=["in-process", "a2a"], default="in-process")
    sp.add_argument("--a2a-url", default="http://127.0.0.1:9100")

    sp = sub.add_parser("registry")
    sp.add_argument("obj", choices=["lead", "account"])

    sp = sub.add_parser("card")
    sp.add_argument("version")

    sp = sub.add_parser("explain")
    sp.add_argument("obj", choices=["lead", "account"])
    sp.add_argument("record_id")

    sp = sub.add_parser("rollback")
    sp.add_argument("obj", choices=["lead", "account"])
    sp.add_argument("--reason", default="manual rollback")
    sp.add_argument("--a2a-url", default="", help="send to the running governance agent instead of the local store")

    sp = sub.add_parser("approve")
    sp.add_argument("version")
    sp.add_argument("--approver", required=True)
    sp.add_argument("--a2a-url", default="", help="send to the running governance agent instead of the local store")

    sp = sub.add_parser("a2a-serve")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=9100)

    sub.add_parser("mcp")

    sp = sub.add_parser("sf-seed")
    sp.add_argument("--accounts", type=int, default=300)
    sp.add_argument("--leads", type=int, default=500)

    args = ap.parse_args(argv)
    os.environ.setdefault("CRM_WORKDIR", args.workdir)

    if args.cmd == "simulate":
        from .simulate import simulate
        simulate(objects=tuple(args.objects), workdir=args.workdir, leave_last=args.leave_last)
        from .dashboard import render
        # A partial replay must not overwrite the published dashboard.
        out = os.path.join(args.workdir, "dashboard.html") if args.leave_last else None
        path = render(workdir=args.workdir, out=out)
        print(f"\nDashboard written to {path}")
        return

    if args.cmd == "dashboard":
        from .dashboard import render
        print(render(workdir=args.workdir))
        return

    if args.cmd == "a2a-serve":
        import uvicorn
        from .agents.a2a import create_app
        app = create_app(base_url=f"http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        return

    if args.cmd == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()
        return

    from .service import build_lifecycle

    if args.cmd in ("approve", "rollback") and args.a2a_url:
        from .agents.a2a import A2ATransport
        tx = A2ATransport(args.a2a_url)
        if args.cmd == "approve":
            _print(tx.send("governance-agent", "approve", {"version": args.version, "approver": args.approver}))
        else:
            _print(tx.send("governance-agent", "rollback", {"obj": args.obj, "reason": args.reason}))
        return

    if args.cmd == "cycle":
        from .agents.orchestrator import run_cycle
        if args.transport == "a2a":
            from .agents.a2a import A2ATransport
            transport = A2ATransport(args.a2a_url)
        else:
            from .agents.a2a import InProcessTransport
            transport = InProcessTransport(build_lifecycle(workdir=args.workdir))
        rec = run_cycle(transport, args.obj, args.period, approve=args.approve, approver=args.approver,
                        dry_run=args.dry_run)
        print(rec["summary"])
        _print({k: rec[k] for k in ("monitor", "plan", "challengers", "decision", "scoring", "messages")})
        return

    lc = build_lifecycle(workdir=args.workdir)
    if args.cmd == "registry":
        reg = lc.registry(args.obj)
        cols = ["version", "status", "method", "train_window", "holdout_period", "approved_by"]
        print(reg[cols].to_string(index=False))
    elif args.cmd == "card":
        print(lc.model_card(args.version))
    elif args.cmd == "explain":
        _print(lc.explain_record(args.obj, args.record_id))
    elif args.cmd == "rollback":
        _print(lc.rollback(args.obj, args.reason, actor="human"))
    elif args.cmd == "approve":
        _print(lc.approve(args.version, args.approver))
    elif args.cmd == "sf-seed":
        from .crm import SalesforceCRM
        from .features import ACCOUNT, LEAD
        crm = SalesforceCRM()
        acc = lc.data("account")
        acc = acc[acc["period"] == acc["period"].max()].sample(args.accounts, random_state=1)
        leads = lc.data("lead")
        leads = leads[leads["period"] == leads["period"].max()].sample(args.leads, random_state=1)
        _print({"accounts_inserted": crm.seed("account", acc, ACCOUNT.id_col, ACCOUNT.name_col),
                "leads_inserted": crm.seed("lead", leads, LEAD.id_col, LEAD.name_col)})


if __name__ == "__main__":
    sys.exit(main())
