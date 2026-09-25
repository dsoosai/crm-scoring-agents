/**
 * Settings for the Agentic Enterprise demo. One place to change the Snowflake account objects,
 * agent names and the model label shown in the audit log.
 */
public with sharing class AgenticDemoConfig {
    public static final String NAMED_CREDENTIAL = 'Snowflake_API';
    public static final String DATABASE_NAME = 'AGENTIC_DEMO';
    public static final String SCHEMA_NAME = 'GTM';
    public static final String WAREHOUSE_NAME = 'AGENTIC_WH';
    public static final String ROLE_NAME = 'AGENTFORCE_READER';
    public static final String CORTEX_AGENT = 'AGENTIC_DEMO.GTM.CONSUMPTION_ANALYST';
    public static final String CASE_STUDY_SEARCH = 'CASE_STUDY_SEARCH';
    public static final String SUPPORT_KB_SEARCH = 'SUPPORT_KB_SEARCH';

    public static final String SALES_AGENT = 'Sales_Strategy_Assistant';
    public static final String SUPPORT_AGENT = 'Support_Intake_Agent';
    public static final String PLAN_GENERATOR = 'Account_Plan_Autofill';

    public static final String PROMPT_MODEL = 'Claude Sonnet via Prompt Builder';
    public static final String CORTEX_MODEL = 'claude-sonnet-4-6 via Cortex Agent';

    public static final Integer HTTP_TIMEOUT_MS = 60000;
    public static final String DEFAULT_FISCAL_YEAR = 'FY27';

    private static Map<String, Id> queueIds;

    /** Id of a queue by developer name, or null if it does not exist. */
    public static Id queueId(String developerName) {
        if (queueIds == null) {
            queueIds = new Map<String, Id>();
            for (Group g : [SELECT Id, DeveloperName FROM Group WHERE Type = 'Queue'
                            AND DeveloperName IN ('Tier_1_Support', 'Tier_2_Support', 'Deal_Desk')]) {
                queueIds.put(g.DeveloperName, g.Id);
            }
        }
        return queueIds.get(developerName);
    }
}
