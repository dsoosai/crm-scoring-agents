"""Synthetic data for the Agentic Enterprise demo (Omega Inc.).

One source of truth for every system in the demo:
  - Snowflake: accounts, contracts, daily consumption telemetry, a use-case catalog,
    peer adoption, case studies and a support knowledge base (CSV files).
  - Salesforce: Omega Inc. and its contacts, opportunities, cases and activities
    (an anonymous Apex seed script).
  - Hugging Face: the same CSVs, published as a dataset.

Everything here is fictional. The seller is a data-platform vendor that bills in
credits; its CRM is Salesforce and its product telemetry lives in Snowflake.

    python agentforce/data/generate_demo_data.py            # writes agentforce/data/out/
"""
from __future__ import annotations

import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
START = date(2025, 1, 1)
AS_OF = date(2026, 9, 24)
PRICE_PER_CREDIT = 3.00  # fictional list rate, used only for non-binding estimates

WORKLOADS = ["Data Engineering", "BI & Analytics", "Data Science & ML", "AI (Cortex)", "Data Sharing & Apps"]
WAREHOUSE = {"Data Engineering": "ELT_WH", "BI & Analytics": "BI_WH", "Data Science & ML": "DS_WH",
             "AI (Cortex)": "AI_WH", "Data Sharing & Apps": "APPS_WH"}

# --------------------------------------------------------------------------- accounts
ACCOUNTS = [
    # key, name, industry, employees, region, customer_since, annual contract credits, term start
    ("OMEGA", "Omega Inc.", "Technology", 4200, "US West", "2023-03-01", 60000, "2025-12-20"),
    ("NORTHWIND", "Northwind Analytics", "Technology", 1800, "US East", "2022-06-15", 42000, "2026-02-01"),
    ("HELIX", "Helix Software", "Technology", 3100, "US West", "2021-11-01", 75000, "2025-11-01"),
    ("QUANTA", "Quanta Systems", "Technology", 5200, "EMEA", "2023-01-20", 90000, "2026-01-20"),
    ("PINECREST", "Pinecrest Labs", "Technology", 950, "US Central", "2024-02-10", 24000, "2026-02-10"),
    ("ORBIT", "Orbit Payments", "Financial Services", 2600, "US East", "2022-09-01", 68000, "2025-09-01"),
    ("KEYSTONE", "Keystone Financial", "Financial Services", 7400, "US East", "2021-05-01", 120000, "2026-05-01"),
    ("BRIGHTLINE", "Brightline Health", "Healthcare", 6100, "US Central", "2023-07-01", 52000, "2025-07-01"),
    ("COBALT", "Cobalt Retail Group", "Retail", 12000, "US West", "2022-03-15", 96000, "2026-03-15"),
    ("VERTEX", "Vertex Manufacturing", "Manufacturing", 8800, "APAC", "2023-10-01", 58000, "2025-10-01"),
    ("LUMEN", "Lumen Media", "Media", 1400, "US West", "2024-04-01", 30000, "2026-04-01"),
    ("SUMMIT", "Summit Insurance", "Insurance", 5600, "US East", "2022-12-01", 64000, "2025-12-01"),
]

# daily credit shape per workload: (base per day at START, monthly growth, weekend factor,
#                                   month-end multiplier, start date or None, special shape)
DEFAULT_MIX = {
    "Data Engineering": (0.45, 0.012, 0.65, 1.0, None, None),
    "BI & Analytics": (0.25, 0.008, 0.40, 1.8, None, None),
    "Data Science & ML": (0.15, 0.010, 0.70, 1.0, None, None),
    "AI (Cortex)": (0.05, 0.080, 0.80, 1.0, "2025-06-01", None),
    "Data Sharing & Apps": (0.10, 0.004, 0.90, 1.0, None, None),
}
OMEGA_MIX = {
    "Data Engineering": (84.0, 0.016, 0.62, 1.0, None, None),
    "BI & Analytics": (46.0, 0.010, 0.35, 2.3, None, None),
    "Data Science & ML": (19.0, 0.004, 0.70, 1.0, None, "ml_decline"),
    "AI (Cortex)": (2.5, 0.0, 0.85, 1.0, "2026-03-15", "ai_ramp"),
    "Data Sharing & Apps": (5.0, 0.003, 0.95, 1.0, None, None),
}

# --------------------------------------------------------------------------- use cases
USE_CASES = [
    ("UC01", "Predictive Lead and Account Scoring", "Revenue Operations", "Technology;Financial Services;Media",
     "Score every lead and account on the likelihood to convert or expand, with drift monitoring and gated model updates, "
     "and write scores and reasons back to the CRM.",
     9000, "Pipeline conversion up 12 to 20 percent; reps work the right accounts first", 6,
     "CRM history with outcomes; product usage telemetry"),
    ("UC02", "Revenue Forecasting and Pipeline Analytics", "Revenue Operations", "Technology;Financial Services;Retail",
     "Blend CRM pipeline with usage and billing data to forecast bookings and consumption revenue by segment.",
     7500, "Forecast error down about 30 percent; one number for sales and finance", 8,
     "Opportunity history; consumption and billing data"),
    ("UC03", "Customer Churn and Expansion Prediction", "Customer Success", "Technology;Insurance;Media;Financial Services",
     "Predict churn and expansion risk from usage trends, support signals and contract dates.",
     8000, "Gross retention up 2 to 4 points; earlier save plays", 8,
     "Usage telemetry; support cases; contract data"),
    ("UC04", "AI Support Copilot", "Customer Support", "Technology;Healthcare;Retail;Financial Services",
     "Retrieval-augmented support assistant over tickets and documentation using vector search and a managed LLM.",
     12000, "First response time down 50 to 60 percent", 6,
     "Ticket history; knowledge articles"),
    ("UC05", "Customer 360 with CRM Zero-Copy", "Sales and Marketing", "Retail;Financial Services;Media;Technology",
     "Share governed customer profiles between the CRM and the data platform without copying rows.",
     10000, "One governed customer view across sales, service and marketing", 10,
     "CRM data platform connection; identity keys"),
    ("UC06", "Real-Time Product Usage Analytics", "Product", "Technology;Media",
     "Stream product events and model feature adoption, activation and health daily.",
     14000, "Daily feature-adoption insight instead of monthly", 8,
     "Event stream; product catalog"),
    ("UC07", "Marketing Attribution and Spend Optimization", "Marketing", "Retail;Media;Technology",
     "Multi-touch attribution joining ad spend, web analytics and CRM outcomes.",
     6000, "Customer acquisition cost down about 10 percent", 8,
     "Ad platform exports; web analytics; CRM outcomes"),
    ("UC08", "Document AI for Contracts and Invoices", "Finance and Legal", "Healthcare;Insurance;Manufacturing",
     "Extract fields from contracts and invoices with document AI and route exceptions.",
     5000, "Manual review time down about 70 percent", 6,
     "PDF archives; ERP reference data"),
    ("UC09", "Supply Chain Demand Forecasting", "Operations", "Manufacturing;Retail",
     "Forecast demand at SKU and location level and feed replenishment planning.",
     15000, "Forecast accuracy up 6 to 10 points", 12,
     "Sales history; inventory; promotions"),
    ("UC10", "Fraud and Anomaly Detection", "Risk", "Financial Services;Insurance",
     "Near-real-time scoring of transactions and claims for anomalies.",
     11000, "Fraud losses down 15 to 25 percent", 10,
     "Transaction stream; labeled fraud outcomes"),
    ("UC11", "Secure Data Sharing and Data Products", "Partnerships", "Financial Services;Healthcare;Media",
     "Publish governed data products to partners and customers without moving data.",
     4000, "New partner data revenue; fewer file transfers", 6,
     "Curated data products; sharing agreements"),
    ("UC12", "FinOps Credit Governance", "Platform", "Technology;Retail;Financial Services;Manufacturing;Healthcare;Media;Insurance",
     "Resource monitors, budgets and chargeback dashboards for platform spend.",
     2000, "Spend variance under 5 percent; no surprise overages", 3,
     "Account usage views"),
]

ADOPTION = [
    # account, use case, status, go-live, annual credits, outcome
    ("OMEGA", "UC06", "Live", "2023-09-15", 13500, "Daily product adoption dashboards for 40 product managers"),
    ("OMEGA", "UC12", "Live", "2024-02-01", 1800, "Budgets and monitors on every warehouse"),
    ("OMEGA", "UC04", "Pilot", "2026-04-01", 9000, "Support copilot pilot on 2 product lines"),
    ("NORTHWIND", "UC01", "Live", "2024-05-01", 9400, "Lead-to-opportunity conversion up 18 percent"),
    ("NORTHWIND", "UC02", "Live", "2024-09-01", 7200, "Forecast error down 29 percent"),
    ("NORTHWIND", "UC12", "Live", "2023-01-10", 1500, "Chargeback by team"),
    ("HELIX", "UC04", "Live", "2025-02-01", 13800, "First response time down 58 percent"),
    ("HELIX", "UC01", "Live", "2024-11-01", 8800, "Account expansion pipeline up 22 percent"),
    ("HELIX", "UC03", "Live", "2025-06-01", 8100, "Gross retention up 3 points"),
    ("QUANTA", "UC02", "Live", "2024-03-01", 8600, "Forecast error down 32 percent"),
    ("QUANTA", "UC01", "Live", "2024-08-01", 10200, "Rep capacity on top-tier accounts up 25 percent"),
    ("QUANTA", "UC06", "Live", "2023-06-01", 16000, "Activation funnel visible daily"),
    ("PINECREST", "UC01", "Live", "2025-01-15", 6100, "Win rate on scored leads up 14 percent"),
    ("PINECREST", "UC03", "Live", "2025-04-01", 5400, "Churn flagged 60 days earlier"),
    ("PINECREST", "UC02", "Pilot", "2026-06-01", 4000, "Forecast pilot for two segments"),
    ("ORBIT", "UC10", "Live", "2023-04-01", 12500, "Fraud losses down 21 percent"),
    ("ORBIT", "UC01", "Live", "2024-10-01", 7900, "SMB lead conversion up 11 percent"),
    ("KEYSTONE", "UC10", "Live", "2022-08-01", 15500, "Alert precision doubled"),
    ("KEYSTONE", "UC05", "Live", "2025-03-01", 11200, "Advisor 360 view across three CRMs"),
    ("BRIGHTLINE", "UC08", "Live", "2024-06-01", 5200, "Claims intake review time down 68 percent"),
    ("BRIGHTLINE", "UC04", "Live", "2025-05-01", 10400, "Nurse line answers grounded in policy"),
    ("COBALT", "UC09", "Live", "2023-09-01", 17800, "Forecast accuracy up 9 points"),
    ("COBALT", "UC07", "Live", "2024-04-01", 6600, "Paid media efficiency up 12 percent"),
    ("VERTEX", "UC09", "Live", "2024-05-01", 14200, "Expedite costs down 17 percent"),
    ("VERTEX", "UC08", "Pilot", "2026-02-01", 3000, "Supplier invoice extraction pilot"),
    ("LUMEN", "UC07", "Live", "2025-01-01", 5100, "Attribution across 11 channels"),
    ("LUMEN", "UC03", "Live", "2025-08-01", 4800, "Subscriber churn down 2 points"),
    ("SUMMIT", "UC03", "Live", "2024-02-01", 7400, "Policy lapse down 3 points"),
    ("SUMMIT", "UC10", "Live", "2023-11-01", 9800, "Claims fraud referrals up 30 percent"),
]

CASE_STUDIES = [
    ("CS-01", "Northwind Analytics turns lead scoring into a managed agent", "Northwind Analytics", "Technology", "UC01",
     "Northwind Analytics sells analytics software to mid-market finance teams. Its revenue operations team scored leads "
     "with hand-set rules that nobody trusted. The team moved scoring onto the data platform: CRM history and product "
     "usage in one place, a gradient-boosted model retrained monthly, and a gate that only promotes a new model when it "
     "beats the current one on a held-out month. Scores and the top three reasons are written back to the CRM every "
     "night. Within two quarters lead-to-opportunity conversion rose 18 percent and reps stopped maintaining their own "
     "spreadsheets. The workload runs on about 9,400 credits a year. Sponsor: the VP of Revenue Operations."),
    ("CS-02", "Helix Software cuts first response time with an AI support copilot", "Helix Software", "Technology", "UC04",
     "Helix Software supports 6,000 business customers. Agents searched four systems to answer a ticket. Helix indexed "
     "tickets and documentation with vector search and put a grounded assistant in front of support engineers, with a "
     "confidence threshold and a human handoff. First response time fell 58 percent and escalations fell 21 percent. "
     "The copilot uses about 13,800 credits a year, most of it retrieval and model inference."),
    ("CS-03", "Quanta Systems gets one forecast for sales and finance", "Quanta Systems", "Technology", "UC02",
     "Quanta Systems had three forecasts: the CRM roll-up, finance's model and the CRO's gut. Quanta blended pipeline "
     "history with consumption and billing data on the data platform and published one forecast with ranges, by segment. "
     "Forecast error fell 32 percent in the first two quarters and the weekly forecast call dropped from 90 to 30 minutes. "
     "About 8,600 credits a year."),
    ("CS-04", "Pinecrest Labs scores leads and flags churn with a two-person team", "Pinecrest Labs", "Technology", "UC01",
     "Pinecrest Labs is a 950-person developer-tools company. A two-person RevOps team built lead scoring in six weeks "
     "and added churn prediction a quarter later using the same features. Win rate on scored leads rose 14 percent and "
     "churn risk is now flagged 60 days earlier. Combined, the two workloads run on about 11,500 credits a year."),
    ("CS-05", "Helix Software predicts churn from usage trends", "Helix Software", "Technology", "UC03",
     "Helix combined product usage, support signals and renewal dates to predict churn and expansion. Customer success "
     "managers get a weekly list with reasons. Gross retention rose 3 points in a year. About 8,100 credits a year."),
    ("CS-06", "Orbit Payments stops fraud in near real time", "Orbit Payments", "Financial Services", "UC10",
     "Orbit Payments scores every transaction within seconds using streaming ingestion and a model retrained weekly. "
     "Fraud losses fell 21 percent while false positives held flat. About 12,500 credits a year."),
    ("CS-07", "Keystone Financial builds an advisor 360 without copying data", "Keystone Financial", "Financial Services", "UC05",
     "Keystone Financial runs three CRMs. It shared governed customer profiles between the CRM platform and the data "
     "platform with zero-copy federation, so advisors see holdings and service history in one view. No nightly ETL, "
     "no duplicate copies. About 11,200 credits a year."),
    ("CS-08", "Cobalt Retail Group forecasts demand by store and SKU", "Cobalt Retail Group", "Retail", "UC09",
     "Cobalt forecasts demand for 40,000 SKUs across 900 stores. Moving forecasting onto the data platform improved "
     "accuracy by 9 points and cut stockouts on promoted items by a third. About 17,800 credits a year."),
    ("CS-09", "Brightline Health reads claims documents with document AI", "Brightline Health", "Healthcare", "UC08",
     "Brightline Health extracts fields from claims attachments with document AI and routes low-confidence documents "
     "to reviewers. Review time fell 68 percent. About 5,200 credits a year."),
    ("CS-10", "Lumen Media finds which channels actually drive subscribers", "Lumen Media", "Media", "UC07",
     "Lumen Media joined ad spend, web analytics and subscription outcomes for multi-touch attribution across 11 channels "
     "and moved 15 percent of spend to the channels that convert. About 5,100 credits a year."),
    ("CS-11", "Vertex Manufacturing cuts expedite costs with better forecasts", "Vertex Manufacturing", "Manufacturing", "UC09",
     "Vertex forecasts component demand across four plants and feeds replenishment planning. Expedite costs fell 17 "
     "percent in the first year. About 14,200 credits a year."),
    ("CS-12", "Summit Insurance lowers policy lapse with churn prediction", "Summit Insurance", "Insurance", "UC03",
     "Summit predicts policy lapse from payment behavior and service contacts, and agents call the riskiest customers "
     "first. Lapse fell 3 points. About 7,400 credits a year."),
]

KB = [
    ("KB-1001", "Queries queue during peak hours or month-end close", "Performance",
     "Symptom: queries wait in queue on a busy warehouse, often at month-end. Cause: concurrency exceeds what one cluster "
     "can run. Fix: 1) Check queued time in query history for the warehouse. 2) Turn the warehouse into a multi-cluster "
     "warehouse with a minimum of 1 and a maximum of 3 to 5 clusters and the Standard scaling policy. 3) Split heavy "
     "batch jobs onto their own warehouse so dashboards are not blocked. 4) Consider query acceleration for large scans. "
     "Multi-cluster warehouses add credits only while extra clusters run. If queuing continues after scaling, open a "
     "case with the query IDs."),
    ("KB-1002", "Auto-ingest pipe is slow or files load late", "Data Loading",
     "Symptom: files land in cloud storage but rows arrive minutes or hours later. Checks: 1) Confirm event notifications "
     "are configured for the bucket prefix. 2) Check the pipe status for pendingFileCount and lastIngestedTimestamp. "
     "3) Large numbers of tiny files slow ingestion; aim for 100 to 250 MB compressed files. 4) Look for load errors in "
     "copy history. If notifications are missing, refresh the pipe for the affected time window."),
    ("KB-1003", "SSO group changes do not update roles (SCIM sync)", "Security and Access",
     "Symptom: a user was added to an identity-provider group but has no new role. Checks: 1) Confirm the SCIM "
     "integration is active and its token has not expired. 2) Group-to-role mapping only applies to groups pushed by "
     "SCIM. 3) Push the group again from the identity provider. 4) Role grants for SCIM-managed users should be made "
     "in the identity provider, not by hand. Support cannot change roles on your behalf."),
    ("KB-1004", "Set up budgets, resource monitors and credit alerts", "Cost Management",
     "Use resource monitors to notify or suspend warehouses at credit thresholds, and budgets to track spend by team. "
     "Steps: 1) Create a monitor with notify at 75 and 90 percent and suspend at 110 percent for non-production. "
     "2) Assign monitors to warehouses. 3) Add account-level budget alerts for finance. Questions about contract "
     "capacity, pricing or renewals go to your account team."),
    ("KB-1005", "Long-running query times out", "Performance",
     "Symptom: a query is cancelled after the statement timeout. Checks: 1) Review the query profile for spilling or "
     "full table scans. 2) Add filters on clustered columns to improve pruning. 3) Size up the warehouse for the job "
     "rather than raising the timeout. 4) Raise the statement timeout for the specific warehouse only when the job is "
     "known to be long."),
    ("KB-1006", "User locked out or needs an MFA reset", "Security and Access",
     "Only an account administrator in your organization can unlock users or reset multi-factor authentication. "
     "Support cannot reset credentials on your behalf and will never ask for a password. Ask your administrator to "
     "reset MFA for the user, then have the user enroll again at next sign-in."),
    ("KB-1007", "Connections blocked by a network policy", "Security and Access",
     "Symptom: logins or drivers fail with an IP not allowed error. Cause: a network policy on the account or user. "
     "Fix: your administrator adds the client's egress IP range to the allowed list. For service users, attach a "
     "user-level policy rather than changing the account policy."),
    ("KB-1008", "Recover a dropped table or earlier data", "Data Recovery",
     "Within the Time Travel retention period you can restore a dropped table with UNDROP, or query data as of a "
     "timestamp and clone it. After retention ends, data moves to fail-safe and recovery requires a support case."),
    ("KB-1009", "Dynamic table refresh falls behind its target lag", "Data Pipelines",
     "Check refresh history for failed or long refreshes, confirm the warehouse is sized for the refresh, and look for "
     "upstream tables that changed shape. Incremental refresh needs deterministic queries."),
    ("KB-1010", "Set up a vector search service over documents", "AI and ML",
     "Create a search service on a text column with a target lag and a warehouse for refreshes. Keep chunks to roughly "
     "a few hundred words, include title and source columns as attributes, and grant usage on the service to the "
     "querying role."),
    ("KB-1011", "Data share consumer cannot see objects", "Data Sharing",
     "Confirm the provider granted the objects to the share, the consumer created a database from the share, and the "
     "consumer's role has imported privileges on that database. Secure views must be used for views in a share."),
    ("KB-1012", "Understanding your invoice and credit statement", "Billing",
     "Your statement shows credits by warehouse and service, storage and data transfer. For questions about pricing, "
     "discounts, contract capacity, renewals or credits, contact your account team. Support does not quote prices or "
     "change contracts."),
    ("KB-1013", "Driver fails after upgrade (TLS or certificate errors)", "Connectivity",
     "Upgrade to a supported driver version, make sure the client trusts current certificate authorities, and check "
     "that proxies do not intercept TLS to the platform endpoints."),
    ("KB-1014", "Rotate key-pair credentials for a service user", "Security and Access",
     "Service users authenticate with a key pair or a programmatic access token. Set a second public key, move clients "
     "to the new private key, then unset the old key. Never share private keys in a support case."),
    ("KB-1015", "Unexpected credit spike from runaway queries", "Cost Management",
     "Find the top queries by credits in the last day, check for cartesian joins or missing filters, set statement "
     "timeouts on ad hoc warehouses and add a resource monitor. Contract or billing adjustments go to your account team."),
    ("KB-1016", "Replication and failover setup", "Business Continuity",
     "Create a replication group for databases and account objects, schedule refreshes, and test failover to the "
     "secondary account. Client redirect needs a connection object."),
    ("KB-1017", "Support severity levels and response targets", "Support Policy",
     "Severity 1: production down, no workaround, 1-hour response. Severity 2: major degradation, 4-hour response. "
     "Severity 3: partial impact or how-to, next business day. Severity 4: general question, 2 business days. "
     "Severity 1 cases are always handed to an on-call engineer."),
    ("KB-1018", "Month-end reporting runs slowly on shared warehouses", "Performance",
     "Month-end close concentrates dashboard and batch load. Schedule batch jobs outside business hours, give finance "
     "dashboards their own multi-cluster warehouse, and use result caching for repeated reports. See KB-1001 for "
     "scaling steps."),
]


# --------------------------------------------------------------------------- telemetry
def _mix_for(key: str, contract: int) -> dict:
    if key == "OMEGA":
        return OMEGA_MIX
    per_day = contract / 365.0 * 0.92
    return {w: (share * per_day, g, wk, me, st, sp) for w, (share, g, wk, me, st, sp) in DEFAULT_MIX.items()}


def _is_month_end(d: date) -> bool:
    nxt = d + timedelta(days=3)
    return nxt.month != d.month and d.weekday() < 5


def consumption_rows(rng: random.Random):
    rows = []
    for key, name, *_rest in ACCOUNTS:
        contract = _rest[-2]
        mix = _mix_for(key, contract)
        d = START
        while d <= AS_OF:
            months = (d - START).days / 30.44
            for w in WORKLOADS:
                base, growth, weekend, month_end, start, special = mix[w]
                if start and d < date.fromisoformat(start):
                    continue
                v = base * (1 + growth) ** months
                if special == "ml_decline" and d >= date(2026, 5, 1):
                    # Data science workloads drift off the platform while the ML team evaluates another vendor.
                    v *= max(0.55, 1 - (d - date(2026, 5, 1)).days / 300)
                if special == "ai_ramp":
                    days_in = (d - date.fromisoformat(start)).days
                    v = 2.5 + 36.0 / (1 + math.exp(-(days_in - 120) / 28))
                if d.weekday() >= 5:
                    v *= weekend
                if _is_month_end(d):
                    v *= month_end
                v *= rng.uniform(0.88, 1.12)
                credits = round(v, 2)
                queries = int(credits * rng.uniform(55, 90))
                users = max(1, int(math.sqrt(credits) * rng.uniform(2.0, 3.2)))
                rows.append((key, d.isoformat(), w, WAREHOUSE[w], credits, queries, users))
            d += timedelta(days=1)
    return rows


# --------------------------------------------------------------------------- salesforce seed
OMEGA_SF = {
    "account": {
        "Name": "Omega Inc.", "Industry": "Technology", "Type": "Customer - Direct", "NumberOfEmployees": 4200,
        "AnnualRevenue": 1250000000, "Website": "https://omega-inc.example", "BillingCity": "San Francisco",
        "BillingStateCode": "CA", "BillingCountryCode": "US", "CRM_Score_Ext_Id__c": "A-OMEGA",
        "Description": "Fictional demo account. B2B SaaS company (customer since 2023). Platform powers product "
                       "analytics, ELT and BI; AI support copilot in pilot. Contract renews 2026-12-19.",
    },
    "contacts": [
        ("Chris", "Post", "VP, Revenue Operations", "chris.post@omega-inc.example", "Owns forecasting, scoring and CRM ops. Frustrated by manual lead routing."),
        ("Priya", "Raman", "Chief Data Officer", "priya.raman@omega-inc.example", "Executive sponsor. Wants AI in production by FY27."),
        ("Marcus", "Lee", "Director, Data Engineering", "marcus.lee@omega-inc.example", "Runs the platform team and the month-end pipelines."),
        ("Alicia", "Gomez", "ML Engineering Lead", "alicia.gomez@omega-inc.example", "Evaluating a separate ML platform for model training."),
        ("Dana", "Whitfield", "Senior Manager, Procurement", "dana.whitfield@omega-inc.example", "Runs the renewal process; wants budget predictability."),
    ],
    "opportunities": [
        ("Omega - FY27 Capacity Renewal and Expansion", "Negotiation/Review", 540000, "2026-12-15", 70,
         "Renewal of 60,000 credits plus expansion. Omega is on pace to exhaust FY26 capacity before term end. "
         "Procurement wants budget predictability. Competitor: the ML team is evaluating a separate ML platform "
         "for training workloads."),
        ("Omega - AI Support Copilot Production Rollout", "Qualification", 96000, "2026-11-30", 20,
         "Pilot live on two product lines since April. Decision on production rollout after pilot review in October."),
        ("Omega - FY26 Capacity", "Closed Won", 360000, "2025-12-20", 100, "FY26 capacity of 60,000 credits."),
        ("Omega - Marketplace Data Listing", "Closed Lost", 40000, "2025-06-30", 0, "Lost on budget timing."),
    ],
    "cases": [
        ("Warehouse queuing during month-end close", "High", "New", "Performance",
         "Finance dashboards queue for 10 to 20 minutes on the last three business days of the month. BI_WH is a "
         "single-cluster Large warehouse."),
        ("Auto-ingest pipe lagging on events table", "Medium", "Working", "Data Loading",
         "Product events land 40 to 60 minutes late since the bucket prefix changed."),
        ("Question about SSO group sync", "Low", "New", "Security and Access",
         "New analysts added to the BI group in the identity provider did not get the analyst role."),
        ("Query timeout on large join", "Medium", "Closed", "Performance",
         "Resolved by adding a clustering key and moving the job to a larger warehouse."),
    ],
    "tasks": [
        ("QBR with Priya Raman and Chris Post", "2026-09-10", "Completed",
         "Priya wants AI in production by FY27. Chris asked how peers score leads and forecast consumption; his team "
         "still routes leads by hand. Marcus raised month-end queuing. Next step: send use-case ideas and a proposal."),
        ("Call with Dana Whitfield on renewal timeline", "2026-09-17", "Completed",
         "Procurement wants the renewal proposal by October 31 and a single number for FY27 capacity."),
    ],
}


def omega_features() -> dict:
    """Omega's feature snapshot for the account-scoring model (same schema as ACCOUNT_SNAPSHOTS)."""
    return {"account_id": "A-OMEGA", "account_name": "Omega Inc.", "period": "2026Q3", "industry": "Technology",
            "department": "Operations", "employees": 4200, "sales": 310000.0, "revenue": 402000.0, "profit": 88000.0,
            "transactions": 38, "product_usage_pct": 91.5, "support_tickets": 3, "csat": 4.3,
            "days_since_last_activity": 2, "open_opps": 2}


def apex_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def omega_seed_apex(score: dict | None) -> str:
    a = dict(OMEGA_SF["account"])
    if score:
        a.update(score)
    lines = [
        "// Seed Omega Inc. for the Agentic Enterprise demo. Safe to re-run: it deletes the previous Omega records first.",
        "delete [SELECT Id FROM Account_Plan__c WHERE Account__r.CRM_Score_Ext_Id__c = 'A-OMEGA'];",
        "delete [SELECT Id FROM Consumption_Snapshot__c WHERE Account__r.CRM_Score_Ext_Id__c = 'A-OMEGA'];",
        "delete [SELECT Id FROM Case WHERE Account.CRM_Score_Ext_Id__c = 'A-OMEGA'];",
        "delete [SELECT Id FROM Opportunity WHERE Account.CRM_Score_Ext_Id__c = 'A-OMEGA'];",
        "delete [SELECT Id FROM Contact WHERE Account.CRM_Score_Ext_Id__c = 'A-OMEGA'];",
        "delete [SELECT Id FROM Account WHERE CRM_Score_Ext_Id__c = 'A-OMEGA'];",
        "Account a = new Account();",
    ]
    for k, v in a.items():
        if isinstance(v, str) and k != "Score_Updated__c":
            lines.append(f"a.{k} = {apex_str(v)};")
        elif k == "Score_Updated__c":
            lines.append(f"a.{k} = Datetime.now();")
        else:
            lines.append(f"a.{k} = {v};")
    lines.append("insert a;")
    lines.append("List<Contact> cs = new List<Contact>();")
    for fn, ln, title, email, desc in OMEGA_SF["contacts"]:
        lines.append(f"cs.add(new Contact(AccountId = a.Id, FirstName = {apex_str(fn)}, LastName = {apex_str(ln)}, "
                     f"Title = {apex_str(title)}, Email = {apex_str(email)}, Description = {apex_str(desc)}));")
    lines.append("insert cs;")
    lines.append("List<Opportunity> os = new List<Opportunity>();")
    for name, stage, amount, close, prob, desc in OMEGA_SF["opportunities"]:
        y, m, d = close.split("-")
        lines.append(f"os.add(new Opportunity(AccountId = a.Id, Name = {apex_str(name)}, StageName = {apex_str(stage)}, "
                     f"Amount = {amount}, CloseDate = Date.newInstance({int(y)}, {int(m)}, {int(d)}), "
                     f"Probability = {prob}, Description = {apex_str(desc)}));")
    lines.append("insert os;")
    lines.append("List<Case> cases = new List<Case>();")
    for subj, prio, status, area, desc in OMEGA_SF["cases"]:
        lines.append(f"cases.add(new Case(AccountId = a.Id, ContactId = cs[2].Id, Subject = {apex_str(subj)}, "
                     f"Priority = {apex_str(prio)}, Status = {apex_str(status)}, Origin = 'Web', "
                     f"Product_Area__c = {apex_str(area)}, Description = {apex_str(desc)}));")
    lines.append("insert cases;")
    lines.append("List<Task> ts = new List<Task>();")
    for subj, when, status, desc in OMEGA_SF["tasks"]:
        y, m, d = when.split("-")
        who = 4 if "Dana" in subj else 0  # the procurement call was with Dana Whitfield
        lines.append(f"ts.add(new Task(WhatId = a.Id, WhoId = cs[{who}].Id, Subject = {apex_str(subj)}, Status = {apex_str(status)}, "
                     f"ActivityDate = Date.newInstance({int(y)}, {int(m)}, {int(d)}), Description = {apex_str(desc)}));")
    lines.append("insert ts;")
    # A second support contact on a lower-tier account, to show standard (Tier 1) routing.
    lines += [
        "delete [SELECT Id FROM Case WHERE Contact.Email = 'jordan.patel@brightline.example'];",
        "delete [SELECT Id FROM Contact WHERE Email = 'jordan.patel@brightline.example'];",
        "List<Account> lowTier = [SELECT Id FROM Account WHERE Account_Tier__c IN ('C', 'D') AND CRM_Score_Ext_Id__c != 'A-OMEGA' ORDER BY Account_Score__c LIMIT 1];",
        "if (!lowTier.isEmpty()) {",
        "    insert new Contact(AccountId = lowTier[0].Id, FirstName = 'Jordan', LastName = 'Patel', Title = 'Analytics Engineer', Email = 'jordan.patel@brightline.example');",
        "}",
    ]
    lines.append("System.debug('Omega seeded: ' + a.Id);")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- main
def write_csv(name: str, header: list[str], rows) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return p


def main(score: dict | None = None) -> None:
    rng = random.Random(20260924)
    write_csv("accounts.csv", ["ACCOUNT_KEY", "ACCOUNT_NAME", "INDUSTRY", "EMPLOYEES", "REGION", "CUSTOMER_SINCE",
                               "SF_EXT_ID"],
              [(k, n, i, e, r, cs, f"A-{k}") for k, n, i, e, r, cs, _c, _t in ACCOUNTS])
    contracts = []
    for k, n, i, e, r, cs, credits, term in ACCOUNTS:
        start = date.fromisoformat(term)
        end = date(start.year + 1, start.month, start.day) - timedelta(days=1)
        contracts.append((k, start.isoformat(), end.isoformat(), credits, PRICE_PER_CREDIT))
    write_csv("contracts.csv", ["ACCOUNT_KEY", "TERM_START", "TERM_END", "ANNUAL_CREDITS", "LIST_PRICE_PER_CREDIT"], contracts)
    write_csv("daily_consumption.csv", ["ACCOUNT_KEY", "USAGE_DATE", "WORKLOAD", "WAREHOUSE_NAME", "CREDITS", "QUERIES",
                                        "ACTIVE_USERS"], consumption_rows(rng))
    write_csv("use_case_catalog.csv", ["USE_CASE_ID", "NAME", "BUSINESS_UNIT", "INDUSTRIES", "DESCRIPTION",
                                       "TYPICAL_ANNUAL_CREDITS", "TYPICAL_OUTCOME", "TIME_TO_VALUE_WEEKS", "PREREQUISITES"],
              USE_CASES)
    write_csv("customer_use_cases.csv", ["ACCOUNT_KEY", "USE_CASE_ID", "STATUS", "GO_LIVE_DATE", "ANNUAL_CREDITS",
                                         "OUTCOME"], ADOPTION)
    write_csv("case_studies.csv", ["STUDY_ID", "TITLE", "CUSTOMER", "INDUSTRY", "USE_CASE_ID", "BODY"], CASE_STUDIES)
    write_csv("support_kb.csv", ["ARTICLE_ID", "TITLE", "PRODUCT_AREA", "BODY"], KB)
    (OUT / "omega_features.json").write_text(json.dumps(omega_features(), indent=2))
    (OUT.parent.parent / "scripts" / "seed_omega.apex").write_text(omega_seed_apex(score))
    print(f"Wrote demo data to {OUT}")


if __name__ == "__main__":
    import sys
    main(json.loads(sys.argv[1]) if len(sys.argv) > 1 else None)
