"""Synthetic CRM data with real outcomes and scripted drift.

The original notebooks (CustomerAccountScoring.ipynb, LeadScoring.ipynb) scored
random data with hand-set weights and no outcomes. A lifecycle needs outcomes,
so this generator produces:

* Accounts: quarterly snapshots 2024Q1 to 2026Q3. Label = expanded_next_q.
* Leads: monthly cohorts 2025-01 to 2026-09. Label = converted_30d.

Feature names keep the notebooks' vocabulary (Sales, Revenue, Profit,
Transactions, Industry, Department, Role, SiteVisits, Google keyword).

Scripted drift events, so the agents have something real to find:

* Leads 2025-11: a paid campaign inflates site visits on Web leads with no
  change in intent. Covariate drift plus concept drift (visits mean less).
* Leads 2026-03: a new search keyword, "AI Agents", appears and converts well.
  An unseen category. Only a full retrain can learn it.
* Leads 2026-06: lead source mix shifts toward Partner.
* Accounts 2025Q4: product usage becomes a much stronger expansion signal and
  margin a weaker one. Concept drift.
* Accounts 2026Q1: a new industry, "Public Sector", starts landing and expands
  fast. An unseen category.
* Accounts 2026Q2: revenue steps up 15% across the book. A mild shift (PSI
  well under 0.10) that the monitor should see and correctly not act on.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

INDUSTRIES = ["Retail", "Finance", "Healthcare", "Technology", "Manufacturing"]
DEPARTMENTS = ["Sales", "Operations", "Support", "Finance", "IT"]
ROLES = ["Decision Maker", "Influencer", "User", "Gatekeeper"]
KEYWORDS = ["CRM", "ERP", "Cloud", "Analytics", "Security"]
SOURCES = ["Web", "Event", "Partner", "Outbound"]

_NAME_A = ["Blue", "North", "Summit", "Harbor", "Pine", "Granite", "Silver", "Cedar", "Atlas",
           "Beacon", "Crescent", "Evergreen", "Falcon", "Golden", "Horizon", "Iron", "Juniper",
           "Keystone", "Lakeside", "Meridian", "Nova", "Orchard", "Pioneer", "Quarry", "Redwood",
           "Sierra", "Tidewater", "Union", "Vista", "Willow"]
_NAME_B = ["Labs", "Retail", "Foods", "Systems", "Health", "Logistics", "Capital", "Works",
           "Outfitters", "Analytics", "Energy", "Apparel", "Markets", "Brands", "Supply",
           "Clinics", "Financial", "Networks", "Goods", "Partners"]


def _company_names(n: int, rng: np.random.Generator) -> list[str]:
    names = []
    for i in range(n):
        names.append(f"{_NAME_A[rng.integers(len(_NAME_A))]} {_NAME_B[rng.integers(len(_NAME_B))]} {i + 1:04d}")
    return names


def quarter_labels(start: str = "2024Q1", end: str = "2026Q3") -> list[str]:
    periods = pd.period_range(pd.Period(start, freq="Q"), pd.Period(end, freq="Q"), freq="Q")
    return [str(p) for p in periods]


def month_labels(start: str = "2025-01", end: str = "2026-09") -> list[str]:
    periods = pd.period_range(pd.Period(start, freq="M"), pd.Period(end, freq="M"), freq="M")
    return [str(p) for p in periods]


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


# --------------------------------------------------------------------------- accounts

def generate_accounts(seed: int = 7, n_start: int = 2400, new_per_quarter: int = 60,
                      new_per_quarter_2026: int = 150) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    quarters = quarter_labels()
    q_index = {q: i for i, q in enumerate(quarters)}
    t_concept = q_index["2025Q4"]
    t_public = q_index["2026Q1"]
    t_macro = q_index["2026Q2"]

    # New logos per quarter. Landing speeds up in 2026 and most new logos are Public Sector.
    adds = [0] + [new_per_quarter_2026 if t >= t_public else new_per_quarter for t in range(1, len(quarters))]
    n_total = n_start + sum(adds)
    names = _company_names(n_total, rng)
    industry = rng.choice(INDUSTRIES, size=n_total, p=[0.22, 0.2, 0.18, 0.25, 0.15]).astype(object)
    department = rng.choice(DEPARTMENTS, size=n_total).astype(object)
    size = rng.lognormal(mean=0.0, sigma=0.8, size=n_total)          # relative company size
    first_q = np.repeat(np.arange(len(quarters)), [n_start] + adds[1:])
    for k in range(n_start, n_total):
        if first_q[k] >= t_public and rng.random() < 0.6:
            industry[k] = "Public Sector"
    health = rng.normal(0, 1, n_total)
    adoption = rng.normal(0, 1, n_total)   # feature adoption, mostly independent of account health

    ind_eff = {"Technology": 0.3, "Finance": 0.2, "Healthcare": 0.1, "Retail": -0.1,
               "Manufacturing": -0.2, "Public Sector": 0.9}
    dept_eff = {"IT": 0.2, "Operations": 0.1, "Sales": 0.0, "Support": -0.1, "Finance": -0.1}

    rows = []
    for t, q in enumerate(quarters):
        if t > 0:
            health = 0.8 * health + 0.6 * rng.normal(0, 1, n_total)
            adoption = 0.8 * adoption + 0.6 * rng.normal(0, 1, n_total)
        active = first_q <= t
        idx = np.where(active)[0]
        h = health[idx]
        macro = 1.15 if t >= t_macro else 1.0
        growth = 1.0 + 0.02 * t
        employees = np.round(250 * size[idx] * growth * rng.lognormal(0, 0.1, len(idx))).astype(int) + 5
        revenue = 60_000 * size[idx] * macro * np.exp(0.35 * h + rng.normal(0, 0.25, len(idx)))
        sales = revenue * rng.uniform(0.8, 1.4, len(idx))
        margin = 0.15 + 0.08 * h + rng.normal(0, 0.08, len(idx))
        profit = revenue * margin
        transactions = rng.poisson(10 + 8 * np.exp(0.3 * h))
        usage = np.clip(55 + 6 * h + 14 * adoption[idx] + rng.normal(0, 6, len(idx)), 0, 100)
        tickets = rng.poisson(np.exp(1.2 - 0.4 * h))
        csat = np.clip(np.round(3.6 + 0.5 * h + rng.normal(0, 0.5, len(idx)), 1), 1, 5)
        days_idle = np.round(rng.exponential(20 * np.exp(-0.5 * h))).astype(int)
        open_opps = rng.poisson(0.6 + 0.4 * np.clip(h, 0, None))

        # Label: fixed population scaling so covariate shift is real.
        z_usage = (usage - 55) / 18
        z_rev = (np.log(revenue) - np.log(60_000)) / 0.9
        z_margin = (margin - 0.15) / 0.11
        z_trans = (transactions - 19) / 5
        z_tickets = (tickets - 3.5) / 2
        z_idle = (days_idle - 22) / 22
        # Before 2025Q4 margin drives expansion. After the AI product launch, adoption does.
        b_usage, b_margin = (1.5, 0.0) if t >= t_concept else (0.4, 0.9)
        logit = (-2.0 + b_usage * z_usage + 0.35 * z_rev + b_margin * z_margin + 0.25 * z_trans
                 - 0.35 * z_tickets - 0.45 * z_idle + 0.35 * np.minimum(open_opps, 3)
                 + np.array([ind_eff[i] for i in industry[idx]])
                 + np.array([dept_eff[d] for d in department[idx]]))
        label = (rng.random(len(idx)) < _sigmoid(logit)).astype(float)
        if t == len(quarters) - 1:
            label[:] = np.nan  # next quarter has not happened yet

        rows.append(pd.DataFrame({
            "account_id": [f"A-{k + 1:05d}" for k in idx],
            "account_name": [names[k] for k in idx],
            "period": q,
            "industry": industry[idx],
            "department": department[idx],
            "employees": employees,
            "sales": sales.round(2),
            "revenue": revenue.round(2),
            "profit": profit.round(2),
            "transactions": transactions,
            "product_usage_pct": usage.round(1),
            "support_tickets": tickets,
            "csat": csat,
            "days_since_last_activity": days_idle,
            "open_opps": open_opps,
            "expanded_next_q": label,
        }))
    return pd.concat(rows, ignore_index=True)


# --------------------------------------------------------------------------- leads

def generate_leads(seed: int = 11, per_month: int = 1200) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    months = month_labels()
    m_index = {m: i for i, m in enumerate(months)}
    t_campaign = m_index["2025-11"]
    t_ai = m_index["2026-03"]
    t_partner = m_index["2026-06"]

    role_eff = {"Decision Maker": 1.0, "Influencer": 0.35, "User": -0.2, "Gatekeeper": -0.6}
    ind_eff = {"Technology": 0.35, "Finance": 0.2, "Healthcare": 0.0, "Retail": -0.05, "Manufacturing": -0.2}
    kw_eff = {"CRM": 0.4, "Analytics": 0.3, "Cloud": 0.1, "ERP": 0.0, "Security": -0.1, "AI Agents": 1.2}
    src_eff = {"Partner": 0.6, "Event": 0.4, "Web": 0.0, "Outbound": -0.4}

    rows = []
    counter = 0
    for t, m in enumerate(months):
        n = int(rng.poisson(per_month))
        # Keyword mix, with the new "AI Agents" keyword ramping in.
        ai_share = 0.0
        if t >= t_ai:
            ai_share = {0: 0.12, 1: 0.20, 2: 0.25}.get(t - t_ai, 0.28)
        base_kw = np.array([0.25, 0.15, 0.2, 0.25, 0.15])
        kw_p = np.append(base_kw * (1 - ai_share), ai_share)
        keywords = rng.choice(KEYWORDS + ["AI Agents"], size=n, p=kw_p)
        src_p = [0.35, 0.12, 0.33, 0.20] if t >= t_partner else [0.45, 0.15, 0.15, 0.25]
        sources = rng.choice(SOURCES, size=n, p=src_p)
        industries = rng.choice(INDUSTRIES, size=n, p=[0.2, 0.2, 0.2, 0.25, 0.15])
        roles = rng.choice(ROLES, size=n, p=[0.2, 0.3, 0.35, 0.15])
        intent = rng.normal(0, 1, n)
        visits = rng.poisson(np.exp(1.2 + 0.55 * intent))
        if t >= t_campaign:
            # Paid campaign: lots of visits, no extra intent.
            campaign = (sources == "Web") & (rng.random(n) < 0.55)
            visits = visits + np.where(campaign, rng.poisson(12, n), 0)
        opens = rng.poisson(np.exp(0.6 + 0.5 * intent))
        company_size = np.round(rng.lognormal(5.5, 1.3, n)).astype(int) + 1
        first_touch = np.where(sources == "Outbound", 0, np.round(rng.exponential(4, n))).astype(int)

        logit = (-3.2 + 1.4 * intent
                 + np.array([role_eff[r] for r in roles])
                 + np.array([ind_eff[i] for i in industries])
                 + np.array([kw_eff[k] for k in keywords])
                 + np.array([src_eff[s] for s in sources])
                 + 0.2 * np.log10(company_size) - 0.06 * first_touch)
        label = (rng.random(n) < _sigmoid(logit)).astype(float)
        if t == len(months) - 1:
            label[:] = np.nan  # 30 days have not passed yet

        ids = [f"L-{m.replace('-', '')}-{counter + i + 1:05d}" for i in range(n)]
        counter += n
        rows.append(pd.DataFrame({
            "lead_id": ids,
            "company": _company_names(n, rng),
            "contact": [f"Contact {i[-5:]}" for i in ids],
            "period": m,
            "industry": industries,
            "role": roles,
            "keyword": keywords,
            "lead_source": sources,
            "site_visits": visits,
            "email_opens": opens,
            "company_size": company_size,
            "days_to_first_touch": first_touch,
            "converted_30d": label,
        }))
    return pd.concat(rows, ignore_index=True)


if __name__ == "__main__":
    a = generate_accounts()
    l = generate_leads()
    print(a.groupby("period")["expanded_next_q"].agg(["size", "mean"]))
    print(l.groupby("period")["converted_30d"].agg(["size", "mean"]))
