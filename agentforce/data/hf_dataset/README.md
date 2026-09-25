---
license: mit
pretty_name: Agentic Enterprise Demo (Omega Inc.)
language:
- en
tags:
- synthetic
- salesforce
- agentforce
- snowflake
- crm
- customer-success
size_categories:
- 10K<n<100K
configs:
- config_name: daily_consumption
  data_files: daily_consumption.csv
- config_name: accounts
  data_files: accounts.csv
- config_name: contracts
  data_files: contracts.csv
- config_name: use_case_catalog
  data_files: use_case_catalog.csv
- config_name: customer_use_cases
  data_files: customer_use_cases.csv
- config_name: case_studies
  data_files: case_studies.csv
- config_name: support_kb
  data_files: support_kb.csv
---

# Agentic Enterprise demo data

Fictional data behind the Agentforce, Claude and Snowflake demo in
[github.com/dsoosai/crm-scoring-agents](https://github.com/dsoosai/crm-scoring-agents) (`agentforce/` and `snowflake/agentic/`).
The walkthrough is on the [CRM Scoring Agents Space](https://huggingface.co/spaces/dsoosai/crm-scoring-agents/blob/main/agentic.html).

A data-platform vendor sells capacity contracts to twelve customer accounts. The featured account, Omega Inc., is
on pace to run out of contracted credits five weeks before its renewal, its AI workload is up sharply and its data
science workload is falling while its ML team evaluates another platform.

| File | Rows | What it is |
|---|---|---|
| `accounts.csv` | 12 | Customer accounts. `SF_EXT_ID` matches `Account.CRM_Score_Ext_Id__c` in Salesforce. |
| `contracts.csv` | 12 | Annual capacity contracts and a fictional list rate. |
| `daily_consumption.csv` | 35,821 | Daily credits, queries and active users by account, workload and warehouse, Jan 2025 to Sep 2026. |
| `use_case_catalog.csv` | 12 | Use cases the vendor sells, with typical outcomes and footprint. |
| `customer_use_cases.csv` | 29 | Which customers run which use cases, with results. |
| `case_studies.csv` | 12 | Short case studies. Indexed with Snowflake Cortex Search. |
| `support_kb.csv` | 18 | Support knowledge articles. Indexed with Snowflake Cortex Search. |

In the demo these tables live in Snowflake (`AGENTIC_DEMO.GTM`). Salesforce Agentforce reads them live through the
Snowflake SQL API and Cortex Search; nothing is copied into Salesforce except a small cached snapshot.

Regenerate with `python agentforce/data/generate_demo_data.py`. The generator is seeded, so the output is identical on every run.
All names, companies and numbers are invented.
