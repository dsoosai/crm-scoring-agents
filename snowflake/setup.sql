-- One-time setup for live mode in a Snowflake trial account.
-- Run as ACCOUNTADMIN in a Snowsight worksheet.
-- The agents create their own tables on first run, as role CRM_AGENT.

USE ROLE ACCOUNTADMIN;

CREATE WAREHOUSE IF NOT EXISTS CRM_WH
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS CRM_SCORING;
CREATE SCHEMA IF NOT EXISTS CRM_SCORING.LIFECYCLE;

CREATE ROLE IF NOT EXISTS CRM_AGENT;
GRANT USAGE ON WAREHOUSE CRM_WH TO ROLE CRM_AGENT;
GRANT USAGE ON DATABASE CRM_SCORING TO ROLE CRM_AGENT;
GRANT USAGE, CREATE TABLE, CREATE VIEW, CREATE STAGE, CREATE FILE FORMAT
  ON SCHEMA CRM_SCORING.LIFECYCLE TO ROLE CRM_AGENT;

-- Service user for the agents. Key-pair auth; service users cannot log in with a password.
-- Generate a key on your Mac:
--   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
--   openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
CREATE USER IF NOT EXISTS CRM_AGENT_SVC
  TYPE = SERVICE DEFAULT_ROLE = CRM_AGENT DEFAULT_WAREHOUSE = CRM_WH
  COMMENT = 'CRM scoring lifecycle agents';
-- Paste the key body (no BEGIN/END lines) and run:
-- ALTER USER CRM_AGENT_SVC SET RSA_PUBLIC_KEY = 'MIIBIjANBgkqh...';
GRANT ROLE CRM_AGENT TO USER CRM_AGENT_SVC;

-- Let yourself look at what the agents write.
GRANT ROLE CRM_AGENT TO ROLE SYSADMIN;
