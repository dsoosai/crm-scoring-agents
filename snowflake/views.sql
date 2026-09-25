-- Run after the first simulate or cycle, once the tables exist.
USE ROLE CRM_AGENT;
USE SCHEMA CRM_SCORING.LIFECYCLE;

-- Latest score per record. The table a Data 360 zero-copy connection would read.
CREATE OR REPLACE VIEW SCORES_LATEST AS
SELECT object, record_id, period, model_version, score, tier, reasons, scored_at
FROM SCORES
QUALIFY ROW_NUMBER() OVER (PARTITION BY object, record_id ORDER BY scored_at DESC, period DESC) = 1;

-- Champion history, one row per promotion.
CREATE OR REPLACE VIEW CHAMPION_HISTORY AS
SELECT object, version, method, parent_version, train_window, holdout_period,
       TRY_PARSE_JSON(metrics):holdout:auc::FLOAT AS holdout_auc,
       approved_by, promoted_at, retired_at, status
FROM MODEL_REGISTRY
WHERE promoted_at <> ''
ORDER BY object, promoted_at;

-- Every agent action, newest first.
CREATE OR REPLACE VIEW AGENT_ACTIONS AS
SELECT ts, agent, action, object, period, version, TRY_PARSE_JSON(detail) AS detail
FROM AUDIT_LOG
ORDER BY ts DESC;
