"""Build space/agentic.html: the Agentic Enterprise walkthrough page for the Hugging Face Space.

Reads the demo CSVs in agentforce/data/out (the same files loaded into Snowflake) and, if present,
agentforce/data/transcripts.json with conversations captured from the live agents.

    python agentforce/data/build_space_page.py
"""
from __future__ import annotations

import csv
import html
import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
PAGE = HERE.parent.parent / "space" / "agentic.html"
ACCOUNT = "OMEGA"
WORKLOADS = ["Data Engineering", "BI & Analytics", "AI (Cortex)", "Data Science & ML", "Data Sharing & Apps"]
COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--series-5)"]


def rows(name: str) -> list[dict]:
    with open(OUT / name, newline="") as f:
        return list(csv.DictReader(f))


def esc(s) -> str:
    return html.escape(str(s))


def fmt(n: float) -> str:
    return f"{n:,.0f}"


def compute() -> dict:
    daily = [r for r in rows("daily_consumption.csv")]
    as_of = max(date.fromisoformat(r["USAGE_DATE"]) for r in daily)
    omega = [r for r in daily if r["ACCOUNT_KEY"] == ACCOUNT]
    for r in omega:
        r["d"] = date.fromisoformat(r["USAGE_DATE"])
        r["c"] = float(r["CREDITS"])
    k = next(r for r in rows("contracts.csv") if r["ACCOUNT_KEY"] == ACCOUNT)
    term_start, term_end, annual = date.fromisoformat(k["TERM_START"]), date.fromisoformat(k["TERM_END"]), float(k["ANNUAL_CREDITS"])

    def total(lo_days: int, hi_days: int, wl: str | None = None) -> float:
        lo, hi = as_of - timedelta(days=lo_days), as_of - timedelta(days=hi_days)
        return sum(r["c"] for r in omega if hi >= r["d"] > lo and (wl is None or r["WORKLOAD"] == wl))

    t12, p12 = total(365, 0), total(730, 365)
    run_rate = total(30, 0) / 30
    in_term = sum(r["c"] for r in omega if r["d"] >= term_start)
    days_left = max((term_end - as_of).days, 0)
    exhaustion = as_of + timedelta(days=math.ceil((annual - in_term) / run_rate))
    growth = {wl: 100 * (total(90, 0, wl) / total(180, 90, wl) - 1) for wl in WORKLOADS}

    burn, cum = [], 0.0
    by_day = defaultdict(float)
    for r in omega:
        if r["d"] >= term_start:
            by_day[r["d"]] += r["c"]
    d = term_start
    while d <= as_of:
        cum += by_day.get(d, 0.0)
        burn.append((d, cum))
        d += timedelta(days=1)

    monthly = defaultdict(float)
    for r in omega:
        monthly[(r["d"].strftime("%Y-%m"), r["WORKLOAD"])] += r["c"]
    months = sorted({m for m, _ in monthly})

    accounts = {r["ACCOUNT_KEY"]: r for r in rows("accounts.csv")}
    adoption = rows("customer_use_cases.csv")
    catalog = {r["USE_CASE_ID"]: r for r in rows("use_case_catalog.csv")}
    studies = {r["USE_CASE_ID"]: r for r in rows("case_studies.csv")}
    industry = accounts[ACCOUNT]["INDUSTRY"]
    mine = {r["USE_CASE_ID"] for r in adoption if r["ACCOUNT_KEY"] == ACCOUNT}
    peers = defaultdict(list)
    for r in adoption:
        a = accounts[r["ACCOUNT_KEY"]]
        if r["ACCOUNT_KEY"] != ACCOUNT and a["INDUSTRY"] == industry and r["STATUS"] == "Live" and r["USE_CASE_ID"] not in mine:
            peers[r["USE_CASE_ID"]].append((a["ACCOUNT_NAME"], float(r["ANNUAL_CREDITS"])))
    recs = sorted(peers.items(), key=lambda kv: (-len(kv[1]), -median(c for _, c in kv[1])))[:3]
    recommendations = [{
        "id": uc, "name": catalog[uc]["NAME"], "peers": len(p), "peer_names": ", ".join(sorted(n for n, _ in p)),
        "credits": round(median(c for _, c in p), -2), "weeks": catalog[uc]["TIME_TO_VALUE_WEEKS"],
        "outcome": catalog[uc]["TYPICAL_OUTCOME"], "study": studies.get(uc, {}).get("TITLE", ""),
    } for uc, p in recs]

    return {
        "as_of": as_of, "t12": t12, "yoy": 100 * (t12 / p12 - 1), "annual": annual, "in_term": in_term,
        "util": 100 * in_term / annual, "proj": 100 * (in_term + run_rate * days_left) / annual, "run_rate": run_rate,
        "term_start": term_start, "term_end": term_end, "exhaustion": exhaustion, "growth": growth,
        "burn": burn, "monthly": monthly, "months": months, "recommendations": recommendations,
    }


def burn_chart(f: dict) -> str:
    w, h, left, right, top, bottom = 960, 300, 64, 24, 16, 36
    x0, x1 = f["term_start"], f["term_end"]
    ymax = max(f["annual"] * 1.2, f["in_term"] + f["run_rate"] * (x1 - f["as_of"]).days) * 1.05
    sx = lambda d: left + (w - left - right) * (d - x0).days / (x1 - x0).days
    sy = lambda v: top + (h - top - bottom) * (1 - v / ymax)
    parts = []
    for i in range(0, 6):
        v = ymax * i / 5
        parts.append(f'<line x1="{left}" x2="{w-right}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="var(--grid)"/>'
                     f'<text x="{left-8}" y="{sy(v)+4:.1f}" text-anchor="end" font-size="12" fill="var(--text-muted)">{fmt(round(v, -3))}</text>')
    d = date(x0.year, x0.month, 1)
    while d <= x1:
        if d >= x0:
            parts.append(f'<text x="{sx(d):.1f}" y="{h-12}" text-anchor="middle" font-size="12" fill="var(--text-muted)">{d.strftime("%b")}</text>')
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    parts.append(f'<line x1="{left}" x2="{w-right}" y1="{sy(f["annual"]):.1f}" y2="{sy(f["annual"]):.1f}" stroke="var(--critical)" stroke-dasharray="6 4"/>'
                 f'<text x="{left+8}" y="{sy(f["annual"])-6:.1f}" text-anchor="start" font-size="12" fill="var(--critical)">Contract {fmt(f["annual"])} credits</text>')
    pts = " ".join(f"{sx(d):.1f},{sy(v):.1f}" for d, v in f["burn"])
    parts.append(f'<polyline points="{pts}" fill="none" stroke="var(--series-1)" stroke-width="2.5"/>')
    end_v = f["in_term"] + f["run_rate"] * (x1 - f["as_of"]).days
    parts.append(f'<line x1="{sx(f["as_of"]):.1f}" y1="{sy(f["in_term"]):.1f}" x2="{sx(x1):.1f}" y2="{sy(end_v):.1f}" stroke="var(--series-1)" stroke-width="2" stroke-dasharray="4 4"/>')
    ex = f["exhaustion"]
    parts.append(f'<circle cx="{sx(ex):.1f}" cy="{sy(f["annual"]):.1f}" r="5" fill="var(--critical)"/>'
                 f'<text x="{sx(ex)-10:.1f}" y="{sy(f["annual"])-10:.1f}" text-anchor="end" font-size="12" fill="var(--text-primary)">Runs out about {ex.strftime("%b %-d")}</text>')
    parts.append(f'<circle cx="{sx(f["as_of"]):.1f}" cy="{sy(f["in_term"]):.1f}" r="4" fill="var(--series-1)"/>'
                 f'<text x="{sx(f["as_of"])-8:.1f}" y="{sy(f["in_term"])-10:.1f}" text-anchor="end" font-size="12" fill="var(--text-secondary)">Today {fmt(f["in_term"])}</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Cumulative credits this term against the contract">{"".join(parts)}</svg>'


def monthly_chart(f: dict) -> str:
    w, h, left, right, top, bottom = 960, 300, 56, 24, 16, 36
    months = f["months"][:-1] if f["as_of"].day < 28 else f["months"]
    ymax = max(f["monthly"][(m, wl)] for m in months for wl in WORKLOADS) * 1.1
    sx = lambda i: left + (w - left - right) * i / (len(months) - 1)
    sy = lambda v: top + (h - top - bottom) * (1 - v / ymax)
    parts = []
    for i in range(0, 5):
        v = ymax * i / 4
        parts.append(f'<line x1="{left}" x2="{w-right}" y1="{sy(v):.1f}" y2="{sy(v):.1f}" stroke="var(--grid)"/>'
                     f'<text x="{left-8}" y="{sy(v)+4:.1f}" text-anchor="end" font-size="12" fill="var(--text-muted)">{fmt(round(v, -2))}</text>')
    for i, m in enumerate(months):
        if i % 3 == 0 or i == len(months) - 1:
            label = date.fromisoformat(m + "-01").strftime("%b %y")
            parts.append(f'<text x="{sx(i):.1f}" y="{h-12}" text-anchor="middle" font-size="12" fill="var(--text-muted)">{label}</text>')
    for wl, color in zip(WORKLOADS, COLORS):
        pts = " ".join(f"{sx(i):.1f},{sy(f['monthly'][(m, wl)]):.1f}" for i, m in enumerate(months))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Monthly credits by workload">{"".join(parts)}</svg>'


def transcripts() -> str:
    path = HERE / "transcripts.json"
    if not path.exists():
        return '<p class="sub">Conversation captures from the live org go here after the next run.</p>'
    out = []
    for convo in json.loads(path.read_text()):
        turns = "".join(
            f'<div class="turn {esc(t["role"])}"><div class="who">{"You" if t["role"] == "user" else esc(convo["agent"])}</div>'
            f'<div class="msg">{esc(t["text"]).replace(chr(10), "<br>")}</div></div>' for t in convo["turns"])
        out.append(f'<div class="card convo"><h3>{esc(convo["title"])}</h3>{turns}</div>')
    return "".join(out)


def page(f: dict) -> str:
    g = f["growth"]
    recs = "".join(
        f'<tr><td class="num">{i}</td><td><b>{esc(r["name"])}</b><br><span class="muted">{esc(r["outcome"])}</span></td>'
        f'<td class="num">{r["peers"]}</td><td>{esc(r["peer_names"])}</td><td class="num">{fmt(r["credits"])}</td>'
        f'<td class="num">{esc(r["weeks"])}</td><td>{esc(r["study"])}</td></tr>'
        for i, r in enumerate(f["recommendations"], 1))
    legend = "".join(f'<span><i style="background:{c}"></i>{esc(wl)}</span>' for wl, c in zip(WORKLOADS, COLORS))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agentic Enterprise Demo</title>
<style>
:root {{
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb; --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
  --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #8b5cf6; --series-5: #a3a29a;
  --critical: #d03b3b; --user: #eef3fb; --agent: #f3f2ee;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #a78bfa; --series-5: #6f6e68;
    --critical: #e25555; --user: #16263d; --agent: #23231f;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--page); color: var(--text-primary); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1120px; margin: 0 auto; padding: 32px 16px 64px; }}
h1 {{ font-size: 28px; line-height: 1.2; margin: 0 0 6px; font-weight: 650; }}
h2 {{ font-size: 20px; margin: 40px 0 4px; font-weight: 650; }}
h3 {{ font-size: 15px; margin: 0 0 8px; font-weight: 600; }}
a {{ color: var(--series-1); }}
p.lead {{ color: var(--text-secondary); margin: 0 0 20px; max-width: 780px; }}
.sub, .muted {{ color: var(--text-secondary); }}
.sub {{ margin: 0 0 16px; }}
.card {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 20px 0 8px; }}
.tile .label {{ color: var(--text-secondary); font-size: 13px; }}
.tile .value {{ font-size: 26px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }}
.tile .delta {{ font-size: 13px; color: var(--text-secondary); }}
svg {{ display: block; width: 100%; height: auto; overflow: visible; }}
.chart {{ overflow-x: auto; }}
.chart svg {{ min-width: 640px; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 16px; font-size: 13px; color: var(--text-secondary); margin: 4px 0 8px; }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.legend i {{ display: inline-block; width: 16px; height: 3px; border-radius: 2px; }}
.wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid var(--grid); vertical-align: top; }}
th {{ color: var(--text-secondary); font-weight: 600; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.agents {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; }}
.agents ul {{ margin: 6px 0 0; padding-left: 18px; color: var(--text-secondary); font-size: 14px; }}
.tag {{ display: inline-block; font-size: 12px; color: var(--text-secondary); border: 1px solid var(--border); border-radius: 999px; padding: 1px 8px; margin: 0 4px 6px 0; }}
.flow {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }}
.flow li {{ margin: 4px 0; }}
.convo {{ margin-bottom: 12px; }}
.turn {{ border-radius: 10px; padding: 8px 12px; margin: 8px 0; max-width: 860px; }}
.turn.user {{ background: var(--user); margin-left: auto; max-width: 640px; }}
.turn.agent {{ background: var(--agent); }}
.turn .who {{ font-size: 12px; color: var(--text-muted); }}
.turn .msg {{ font-size: 14px; }}
footer {{ margin-top: 48px; color: var(--text-muted); font-size: 13px; }}
</style>
</head>
<body>
<main>
  <h1>Agentic Enterprise: Agentforce, Claude and Snowflake</h1>
  <p class="lead">Four agents work one account, Omega Inc. Salesforce Agentforce reasons over CRM data and reads product telemetry live from Snowflake without copying it. Claude writes the briefs, emails and account plans through Prompt Builder and answers analytics questions inside Snowflake as a Cortex agent. The account score comes from the scoring agents on the <a href="index.html">lifecycle dashboard</a>. Fictional data.</p>

  <div class="tiles">
    <div class="card tile"><div class="label">Trailing 12 months</div><div class="value">{fmt(f["t12"])}</div><div class="delta">credits, {f["yoy"]:+.0f}% year over year</div></div>
    <div class="card tile"><div class="label">Contract used</div><div class="value">{f["util"]:.0f}%</div><div class="delta">{fmt(f["in_term"])} of {fmt(f["annual"])} credits, term ends {f["term_end"].strftime("%b %-d")}</div></div>
    <div class="card tile"><div class="label">Capacity runs out</div><div class="value">{f["exhaustion"].strftime("%b %-d")}</div><div class="delta">{(f["term_end"] - f["exhaustion"]).days} days early; {f["proj"]:.0f}% by term end</div></div>
    <div class="card tile"><div class="label">AI (Cortex) workload</div><div class="value">{g["AI (Cortex)"]:+.0f}%</div><div class="delta">last 90 days; Data Science and ML {g["Data Science & ML"]:+.0f}%</div></div>
    <div class="card tile"><div class="label">CRM score</div><div class="value">94.3</div><div class="delta">tier A, champion model account-v12</div></div>
  </div>

  <h2>The renewal signal</h2>
  <p class="sub">Cumulative credits this term against the 60,000-credit contract. Dashed: the current run rate of {f["run_rate"]:.0f} credits a day.</p>
  <div class="card chart">{burn_chart(f)}</div>

  <h2>What is growing and what is not</h2>
  <p class="sub">Monthly credits by workload. AI is taking off. Data Science and ML is falling while the ML team evaluates another platform.</p>
  <div class="card"><div class="legend">{legend}</div><div class="chart">{monthly_chart(f)}</div></div>

  <h2>What to sell next</h2>
  <p class="sub">Use cases that technology peers run live and Omega does not, from <code>V_USE_CASE_RECOMMENDATIONS</code> in Snowflake. Case studies are found with Cortex Search.</p>
  <div class="card wrap"><table>
    <thead><tr><th class="num">#</th><th>Use case</th><th class="num">Peers live</th><th>Peers</th><th class="num">Credits a year</th><th class="num">Weeks to value</th><th>Case study</th></tr></thead>
    <tbody>{recs}</tbody>
  </table></div>

  <h2>The four agents</h2>
  <div class="agents">
    <div class="card"><h3>Sales Strategy Assistant</h3><span class="tag">Agentforce employee agent</span><span class="tag">Agent Script</span>
      <ul><li>Briefs the rep with a Claude-written summary grounded in CRM and live telemetry</li><li>Reads consumption through the Snowflake SQL API</li><li>Asks Snowflake's Cortex agent ad hoc questions</li><li>Recommends use cases with peer proof</li><li>Drafts outreach; the rep sends</li><li>Routes pricing to Deal Desk, never quotes it</li></ul></div>
    <div class="card"><h3>Account Plan Autofill</h3><span class="tag">Record-triggered flow</span><span class="tag">Prompt Builder</span>
      <ul><li>One click creates the plan</li><li>Grounds it in Snowflake once, saves the exact data used</li><li>Claude drafts trends, use cases, landscape, SWOT and vision</li><li>Fills in section by section, then notifies the owner</li></ul></div>
    <div class="card"><h3>Support Intake Agent</h3><span class="tag">Agentforce service agent</span><span class="tag">Cortex Search</span>
      <ul><li>Verifies the customer by email</li><li>Answers only from knowledge articles in Snowflake</li><li>Opens routed cases: tier A plus high severity goes to Tier 2</li><li>Sends pricing questions to the account team</li></ul></div>
    <div class="card"><h3>Observability and audit</h3><span class="tag">Agent Audit Log</span><span class="tag">Snowflake query history</span>
      <ul><li>Every action logged with source, latency and guardrail</li><li>Snowflake query Ids tie each answer to the exact read</li><li>Fallbacks to cached data are labelled</li><li>Feedback captured in the same table</li></ul></div>
  </div>

  <h2>How it fits together</h2>
  <div class="flow">
    <div class="card"><h3>Salesforce</h3><ul><li>Agent Script agents and Apex actions</li><li>Prompt Builder templates on Claude, through the Einstein Trust Layer</li><li>Named credential with a Snowflake programmatic access token</li><li>Custom objects: Account Plan, Consumption Snapshot, Agent Audit Log</li></ul></div>
    <div class="card"><h3>Snowflake</h3><ul><li>Telemetry, contracts and peer adoption tables</li><li>Views the agents read, as a read-only service user</li><li>Cortex Search over case studies and the support KB</li><li>Semantic view and a Cortex agent on claude-sonnet-4-6</li><li>Cortex Code (CoCo) for analysts in Snowsight</li></ul></div>
    <div class="card"><h3>Hugging Face</h3><ul><li>The scoring agents' lifecycle dashboard</li><li>The model history behind the CRM tier: every version, its gates and who approved it</li><li>This page and the <a href="https://huggingface.co/datasets/dsoosai/agentic-enterprise-demo">demo dataset</a></li></ul></div>
  </div>

  <h2>Conversations</h2>
  {transcripts()}

  <footer>Telemetry as of {f["as_of"].strftime("%b %-d, %Y")}. Fictional data. Source: <a href="https://github.com/dsoosai/crm-scoring-agents">github.com/dsoosai/crm-scoring-agents</a> (agentforce/ and snowflake/agentic/).</footer>
</main>
</body>
</html>
"""


if __name__ == "__main__":
    facts = compute()
    PAGE.write_text(page(facts))
    print(f"Wrote {PAGE} ({PAGE.stat().st_size:,} bytes); exhaustion {facts['exhaustion']}, recs {[r['id'] for r in facts['recommendations']]}")
