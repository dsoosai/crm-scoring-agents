-- Cortex layer: vector search over case studies and the support KB, a semantic view for
-- natural-language questions (Cortex Analyst, CoCo), and a Cortex agent on Claude.
-- Needs AI features enabled on the account (a trial account needs a card on file) and
-- cross-region inference for Claude.
USE ROLE ACCOUNTADMIN;
USE WAREHOUSE AGENTIC_WH;
USE SCHEMA AGENTIC_DEMO.GTM;

SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;
ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'AWS_US';

-- 1. Vector search (hybrid: vector plus keyword) over unstructured text.
CREATE OR REPLACE CORTEX SEARCH SERVICE CASE_STUDY_SEARCH
  ON BODY
  ATTRIBUTES INDUSTRY, USE_CASE_ID
  WAREHOUSE = AGENTIC_WH
  TARGET_LAG = '1 day'
  COMMENT = 'Customer case studies, for grounding use-case recommendations'
AS (SELECT STUDY_ID, TITLE, CUSTOMER, INDUSTRY, USE_CASE_ID, BODY FROM CASE_STUDIES);

CREATE OR REPLACE CORTEX SEARCH SERVICE SUPPORT_KB_SEARCH
  ON BODY
  ATTRIBUTES PRODUCT_AREA
  WAREHOUSE = AGENTIC_WH
  TARGET_LAG = '1 day'
  COMMENT = 'Support knowledge base, for grounding the support intake agent'
AS (SELECT ARTICLE_ID, TITLE, PRODUCT_AREA, BODY FROM SUPPORT_KB);

-- 2. Semantic view: business names, synonyms and metrics over the telemetry tables.
CREATE OR REPLACE SEMANTIC VIEW GTM_CONSUMPTION_SV
  TABLES (
    accounts AS AGENTIC_DEMO.GTM.ACCOUNTS PRIMARY KEY (ACCOUNT_KEY)
      WITH SYNONYMS = ('customers', 'clients') COMMENT = 'Customer accounts',
    usage AS AGENTIC_DEMO.GTM.DAILY_CONSUMPTION
      WITH SYNONYMS = ('consumption', 'telemetry', 'credit usage') COMMENT = 'Daily credits by workload',
    contracts AS AGENTIC_DEMO.GTM.CONTRACTS PRIMARY KEY (ACCOUNT_KEY)
      COMMENT = 'Capacity contracts',
    adoption AS AGENTIC_DEMO.GTM.CUSTOMER_USE_CASES
      COMMENT = 'Use cases each customer runs'
  )
  RELATIONSHIPS (
    usage_to_accounts AS usage (ACCOUNT_KEY) REFERENCES accounts,
    contracts_to_accounts AS contracts (ACCOUNT_KEY) REFERENCES accounts,
    adoption_to_accounts AS adoption (ACCOUNT_KEY) REFERENCES accounts
  )
  FACTS (
    usage.credits AS usage.CREDITS,
    usage.query_count AS usage.QUERIES,
    usage.active_users AS usage.ACTIVE_USERS,
    contracts.annual_credits AS contracts.ANNUAL_CREDITS
  )
  DIMENSIONS (
    accounts.account_name AS accounts.ACCOUNT_NAME WITH SYNONYMS = ('customer', 'company'),
    accounts.industry AS accounts.INDUSTRY WITH SYNONYMS = ('vertical', 'segment'),
    accounts.region AS accounts.REGION,
    usage.workload AS usage.WORKLOAD WITH SYNONYMS = ('workload type', 'use'),
    usage.warehouse_name AS usage.WAREHOUSE_NAME,
    usage.usage_date AS usage.USAGE_DATE,
    usage.usage_month AS DATE_TRUNC('month', usage.USAGE_DATE),
    contracts.term_end AS contracts.TERM_END WITH SYNONYMS = ('renewal date'),
    adoption.use_case_id AS adoption.USE_CASE_ID,
    adoption.status AS adoption.STATUS
  )
  METRICS (
    usage.total_credits AS SUM(usage.CREDITS) WITH SYNONYMS = ('consumption', 'spend in credits')
      COMMENT = 'Credits consumed',
    usage.total_queries AS SUM(usage.QUERIES),
    usage.avg_active_users AS AVG(usage.ACTIVE_USERS),
    contracts.contracted_credits AS SUM(contracts.ANNUAL_CREDITS) COMMENT = 'Committed annual capacity'
  )
  COMMENT = 'Consumption, contracts and use-case adoption for the Agentic Enterprise demo';

-- Quick checks.
SELECT * FROM SEMANTIC_VIEW(GTM_CONSUMPTION_SV DIMENSIONS usage.workload METRICS usage.total_credits
  WHERE accounts.account_name = 'Omega Inc.') ORDER BY 2 DESC;
SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW('AGENTIC_DEMO.GTM.CASE_STUDY_SEARCH',
  '{"query": "lead scoring for revenue operations", "columns": ["TITLE", "CUSTOMER"], "limit": 3}'))['results'];
SELECT AI_COMPLETE('claude-sonnet-4-6', 'In one sentence: why would a RevOps leader care about predictive lead scoring?');

-- 3. A Cortex agent on Claude: Cortex Analyst over the semantic view plus Cortex Search.
-- Re-running CREATE OR REPLACE drops the agent's grants. Run steps 4 and 5 again after it.
CREATE OR REPLACE AGENT CONSUMPTION_ANALYST
  COMMENT = 'Answers consumption and use-case questions for account teams'
  PROFILE = '{"display_name": "Consumption Analyst"}'
  FROM SPECIFICATION
  $$
  models:
    orchestration: claude-sonnet-4-6
  instructions:
    response: "Answer in at most five sentences. The latest month is month to date: say so, and never call it a decline or a pullback. Give numbers with units (credits, percent, dates). Name the source: telemetry or case studies. Never quote prices, discounts or contract terms."
    orchestration: "Use Consumption for any question about credits, workloads, growth, contracts or adoption. Use CaseStudies for evidence from other customers. Answer only from tool results."
  tools:
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "Consumption"
        description: "Credits by account, workload, warehouse and month; contract capacity and renewal dates; use-case adoption"
    - tool_spec:
        type: "cortex_search"
        name: "CaseStudies"
        description: "Customer case studies with outcomes and credit footprints by use case"
  tool_resources:
    Consumption:
      semantic_view: "AGENTIC_DEMO.GTM.GTM_CONSUMPTION_SV"
      execution_environment:
        type: "warehouse"
        warehouse: "AGENTIC_WH"
    CaseStudies:
      search_service: "AGENTIC_DEMO.GTM.CASE_STUDY_SEARCH"
      max_results: "4"
      id_column: "STUDY_ID"
      title_column: "TITLE"
  $$;

SELECT TRY_PARSE_JSON(SNOWFLAKE.CORTEX.DATA_AGENT_RUN('AGENTIC_DEMO.GTM.CONSUMPTION_ANALYST',
  $${"messages":[{"role":"user","content":[{"type":"text","text":"Which Omega Inc. workload grew fastest in the last 90 days?"}]}]}$$));

-- 4. Make the agent available in CoWork (formerly Snowflake Intelligence).
CREATE SNOWFLAKE INTELLIGENCE IF NOT EXISTS SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT;
GRANT USAGE ON SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT TO ROLE PUBLIC;
ALTER SNOWFLAKE INTELLIGENCE SNOWFLAKE_INTELLIGENCE_OBJECT_DEFAULT ADD AGENT AGENTIC_DEMO.GTM.CONSUMPTION_ANALYST;

-- 5. Let the Agentforce service role use the Cortex objects (the role is created in 04_agentforce_access.sql).
CREATE ROLE IF NOT EXISTS AGENTFORCE_READER COMMENT = 'Read-only role for Agentforce actions';
GRANT USAGE ON CORTEX SEARCH SERVICE CASE_STUDY_SEARCH TO ROLE AGENTFORCE_READER;
GRANT USAGE ON CORTEX SEARCH SERVICE SUPPORT_KB_SEARCH TO ROLE AGENTFORCE_READER;
GRANT SELECT ON SEMANTIC VIEW GTM_CONSUMPTION_SV TO ROLE AGENTFORCE_READER;
GRANT USAGE ON AGENT CONSUMPTION_ANALYST TO ROLE AGENTFORCE_READER;
