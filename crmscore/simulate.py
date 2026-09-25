"""Replay history: bootstrap, then run every monthly lead cycle and quarterly account cycle."""
from __future__ import annotations

import os
import time

from .agents.a2a import InProcessTransport
from .agents.orchestrator import run_cycle
from .features import period_range, spec_for
from .service import build_lifecycle, load_demo_data


def simulate(objects=("lead", "account"), workdir: str = "demo_run", transport=None, verbose: bool = True,
             approver: str = "RevOps (simulated)", leave_last: bool = False) -> dict:
    """Fresh warehouse, bootstrap champions, then every cycle in order.

    DuckDB allows one writing process, so the replay always runs in-process.
    Use leave_last=True and run the final cycle over A2A afterwards.
    """
    for f in ("warehouse.duckdb", "mock_org.duckdb"):
        path = os.path.join(workdir, f)
        if os.path.exists(path):
            os.remove(path)
    lc = build_lifecycle(workdir=workdir)
    lc.wh.reset_lifecycle()  # no-op on a fresh DuckDB file; clears old runs in Snowflake
    info = load_demo_data(lc)
    transport = transport or InProcessTransport(lc)
    out = {"data": info, "cycles": {}}
    for obj in objects:
        s, c = spec_for(obj), lc.ocfg(obj)
        v1 = lc.bootstrap(obj)
        if verbose:
            print(f"\n=== {obj}: bootstrap champion {v1}")
            print(f"{'period':8} {'status':8} {'champ AUC':>9} {'frozen v1':>9} {'rules v0':>8}  decision")
        recs = []
        periods = period_range(c["first_cycle"], c["last_cycle"], s.period_freq)
        if leave_last:
            periods = periods[:-1]
        for period in periods:
            t0 = time.time()
            rec = run_cycle(transport, obj, period, approve=True, approver=approver)
            recs.append(rec)
            if verbose:
                perf = rec["champion_perf"].get("auc")
                d = rec["decision"]
                what = f"promote {d['champion']} ({next(ch['method'] for ch in rec['challengers'] if ch['version'] == d['champion'])})" \
                    if d["action"] == "promote" else d["action"]
                print(f"{period:8} {rec['monitor']['status']:8} {perf or 0:9.3f} {rec['monitor']['frozen_v1_auc'] or 0:9.3f} "
                      f"{rec['monitor']['rules_v0_auc'] or 0:8.3f}  {what}  [{time.time() - t0:.1f}s]")
        out["cycles"][obj] = recs
    return out


if __name__ == "__main__":
    simulate()
