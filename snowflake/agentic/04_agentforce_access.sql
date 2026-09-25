-- Run before or after 03_cortex.sql. Least-privilege access for Agentforce: a read-only role, a service user and a
-- programmatic access token (PAT). Salesforce calls the SQL API and the Cortex Search
-- REST API with this token through a named credential.
USE ROLE ACCOUNTADMIN;
USE SCHEMA AGENTIC_DEMO.GTM;

CREATE ROLE IF NOT EXISTS AGENTFORCE_READER COMMENT = 'Read-only role for Agentforce actions';
GRANT USAGE ON WAREHOUSE AGENTIC_WH TO ROLE AGENTFORCE_READER;
GRANT USAGE ON DATABASE AGENTIC_DEMO TO ROLE AGENTFORCE_READER;
GRANT USAGE ON SCHEMA AGENTIC_DEMO.GTM TO ROLE AGENTFORCE_READER;
GRANT SELECT ON ALL TABLES IN SCHEMA AGENTIC_DEMO.GTM TO ROLE AGENTFORCE_READER;
GRANT SELECT ON ALL VIEWS IN SCHEMA AGENTIC_DEMO.GTM TO ROLE AGENTFORCE_READER;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE AGENTFORCE_READER;
GRANT SELECT ON FUTURE VIEWS IN SCHEMA AGENTIC_DEMO.GTM TO ROLE AGENTFORCE_READER;
-- Grants on the Cortex Search services, semantic view and Cortex agent are at the end of 03_cortex.sql.
GRANT ROLE AGENTFORCE_READER TO ROLE SYSADMIN;

CREATE USER IF NOT EXISTS AGENTFORCE_SVC
  TYPE = SERVICE DEFAULT_ROLE = AGENTFORCE_READER DEFAULT_WAREHOUSE = AGENTIC_WH
  COMMENT = 'Agentforce actions in the Salesforce Developer Edition org';
GRANT ROLE AGENTFORCE_READER TO USER AGENTFORCE_SVC;

-- Salesforce calls come from many IP ranges. For this demo the token is not tied to a
-- network policy; it is limited instead by a read-only role, a service user and a
-- 30-day expiry. In production, attach a network policy with Salesforce's egress ranges.
CREATE AUTHENTICATION POLICY IF NOT EXISTS AGENTIC_DEMO.GTM.AGENTFORCE_PAT_POLICY
  AUTHENTICATION_METHODS = ('PROGRAMMATIC_ACCESS_TOKEN')
  PAT_POLICY = (NETWORK_POLICY_EVALUATION = ENFORCED_NOT_REQUIRED)
  COMMENT = 'PAT-only sign-in for the Agentforce service user';
ALTER USER AGENTFORCE_SVC SET AUTHENTICATION POLICY AGENTIC_DEMO.GTM.AGENTFORCE_PAT_POLICY;

-- Run this last, yourself. The result shows the token secret once: copy it straight into
-- Salesforce (Setup > Named Credentials > External Credentials > Snowflake PAT > Principals >
-- AgentforcePrincipal > Authentication Parameters > token).
-- ALTER USER AGENTFORCE_SVC ADD PROGRAMMATIC ACCESS TOKEN AGENTFORCE_PAT
--   ROLE_RESTRICTION = 'AGENTFORCE_READER' DAYS_TO_EXPIRY = 30 COMMENT = 'Agentforce demo';

-- Observability: every Agentforce read, as Snowflake sees it.
-- SELECT START_TIME, TOTAL_ELAPSED_TIME, ROWS_PRODUCED, LEFT(QUERY_TEXT, 120) AS QUERY
-- FROM TABLE(AGENTIC_DEMO.INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER(USER_NAME => 'AGENTFORCE_SVC', RESULT_LIMIT => 50))
-- ORDER BY START_TIME DESC;
