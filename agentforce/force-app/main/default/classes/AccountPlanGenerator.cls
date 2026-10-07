/**
 * Drafts an account plan in four chained background jobs, called by the Account_Plan_Autofill flow.
 *
 *   1. Ground:  read telemetry, monthly workload trend, peer use cases and case studies from
 *               Snowflake (SQL API and Cortex Search) and save them on the plan.
 *   2. Draft:   consumption trends and recommended use cases.
 *   3. Draft:   customer landscape and SWOT.
 *   4. Draft:   account vision, mark Ready for Review and notify the owner.
 *
 * Each draft calls a Prompt Builder template that runs on Claude through the Einstein Trust Layer.
 * Jobs are split so no transaction mixes callouts after DML, and so the record fills in visibly.
 * Four jobs also stays inside the Developer Edition limit of five chained queueables.
 */
public with sharing class AccountPlanGenerator implements Queueable, Database.AllowsCallouts {

    public class GenerationException extends Exception {}

    public class Request {
        @InvocableVariable(label='Plan Id' description='Id of the account plan to draft' required=true)
        public Id planId;
    }

    private final Id planId;
    private final Integer stage;

    public AccountPlanGenerator(Id planId, Integer stage) {
        this.planId = planId;
        this.stage = stage;
    }

    @InvocableMethod(label='Generate Account Plan' description='Grounds an account plan in Snowflake data and drafts its sections with Prompt Builder.' category='Agentic Enterprise')
    public static void start(List<Request> requests) {
        List<Account_Plan__c> updates = new List<Account_Plan__c>();
        for (Request r : requests) {
            if (r == null || r.planId == null) {
                continue;
            }
            updates.add(new Account_Plan__c(
                Id = r.planId,
                Status__c = 'Grounding',
                Sections_Completed__c = 0,
                Generation_Error__c = null,
                Consumption_Trends__c = null,
                Recommended_Use_Cases__c = null,
                Customer_Landscape__c = null,
                SWOT_Analysis__c = null,
                Account_Vision__c = null));
        }
        update updates;
        for (Account_Plan__c p : updates) {
            System.enqueueJob(new AccountPlanGenerator(p.Id, 1));
        }
    }

    public void execute(QueueableContext ctx) {
        Account_Plan__c plan = loadPlan(planId);
        if (plan == null) {
            return;
        }
        try {
            if (stage == 1) {
                ground(plan);
            } else if (stage == 2) {
                draft(plan, 'Plan_Consumption_Trends', 'Consumption_Trends__c');
                draft(plan, 'Plan_Use_Cases', 'Recommended_Use_Cases__c');
                plan.Sections_Completed__c = 2;
            } else if (stage == 3) {
                draft(plan, 'Plan_Customer_Landscape', 'Customer_Landscape__c');
                draft(plan, 'Plan_SWOT', 'SWOT_Analysis__c');
                plan.Sections_Completed__c = 4;
            } else {
                draft(plan, 'Plan_Vision', 'Account_Vision__c');
                plan.Sections_Completed__c = 5;
                plan.Status__c = 'Ready for Review';
                plan.Generated_At__c = Datetime.now();
                plan.Generation_Model__c = AgenticDemoConfig.PROMPT_MODEL;
            }
            update plan;
            AgentAuditLogger.flush();
            if (stage < 4) {
                if (!Test.isRunningTest()) {
                    System.enqueueJob(new AccountPlanGenerator(planId, stage + 1));
                }
            } else {
                notifyOwner(plan);
            }
        } catch (Exception e) {
            fail(plan, e);
        }
    }

    // Stage 1: all Snowflake reads happen here, before any DML in this transaction.
    private void ground(Account_Plan__c plan) {
        AgentAuditLogger.Entry audit = AgentAuditLogger.start(AgenticDemoConfig.PLAN_GENERATOR, 'Ground Account Plan')
            .account(plan.Account__c).recordId(plan.Id).inputs(plan.Name);
        ConsumptionService.Result r = ConsumptionService.getSummary(plan.Account__c);
        ConsumptionService.addMonthlyTrend(r);
        ConsumptionService.addRecommendations(r, true);

        List<String> g = new List<String>();
        g.add('TELEMETRY:');
        g.add(ConsumptionService.describeSummary(r));
        g.add('');
        g.add('SIGNALS:');
        g.add(GetConsumptionTelemetry.signals(r));
        if (!r.monthlyTrend.isEmpty()) {
            g.add('');
            g.add('MONTHLY CREDITS BY WORKLOAD (month | workload | credits):');
            g.addAll(r.monthlyTrend);
        }
        g.add('');
        g.add('RECOMMENDED USE CASES (peers in the same industry that run them live):');
        g.add(r.useCasesText == null ? 'n/a' : r.useCasesText);

        plan.Grounding_Snapshot__c = AgentAuditLogger.clip(String.join(g, '\n'), 131000);
        plan.Grounding_Source__c = AgentAuditLogger.clip(r.live
            ? 'Snowflake SQL API, live (query ' + r.queryId + ')'
                + (r.evidenceSource == null || r.evidenceSource == 'Snowflake SQL API' ? '' : '. Case studies: ' + r.evidenceSource.replace('Snowflake SQL API (Cortex Search unavailable)', 'keyword search, Cortex Search off'))
            : r.source, 255);
        plan.Status__c = 'Drafting';
        audit.source(r.live ? 'Snowflake SQL API' : r.source).queryId(r.queryId).output(plan.Grounding_Snapshot__c);
        if (!r.live) {
            audit.fallback('Snowflake unreachable, grounded on cached snapshot: ' + r.fallbackReason);
        }
        audit.done();
        ConsumptionService.persist(r);
    }

    private void draft(Account_Plan__c plan, String templateName, String fieldName) {
        AgentAuditLogger.Entry audit = AgentAuditLogger.start(AgenticDemoConfig.PLAN_GENERATOR, 'Draft ' + templateName)
            .account(plan.Account__c).recordId(plan.Id).inputs(templateName).source('Prompt Builder').model(AgenticDemoConfig.PROMPT_MODEL);
        String html = RichText.toHtml(generate(templateName, new Map<String, String>{ 'planId' => plan.Id }));
        plan.put(fieldName, html);
        audit.output(RichText.toPlain(html)).done();
    }

    /** Runs a Prompt Builder template through the Einstein Trust Layer and returns the text. */
    @TestVisible
    private static String generate(String templateName, Map<String, String> inputs) {
        if (Test.isRunningTest()) {
            return '<p>Draft from ' + templateName + '</p>';
        }
        ConnectApi.EinsteinPromptTemplateGenerationsInput input = new ConnectApi.EinsteinPromptTemplateGenerationsInput();
        input.isPreview = false;
        input.additionalConfig = new ConnectApi.EinsteinLlmAdditionalConfigInput();
        input.additionalConfig.applicationName = 'PromptTemplateGenerationsInvocable';
        Map<String, ConnectApi.WrappedValue> params = new Map<String, ConnectApi.WrappedValue>();
        for (String key : inputs.keySet()) {
            ConnectApi.WrappedValue v = new ConnectApi.WrappedValue();
            v.value = inputs.get(key);
            params.put('Input:' + key, v);
        }
        input.inputParams = params;
        ConnectApi.EinsteinPromptTemplateGenerationsRepresentation result =
            ConnectApi.EinsteinLLM.generateMessagesForPromptTemplate(templateName, input);
        if (result == null || result.generations == null || result.generations.isEmpty()) {
            throw new GenerationException('No text came back from ' + templateName + '.');
        }
        return result.generations[0].text;
    }

    private void fail(Account_Plan__c plan, Exception e) {
        Account_Plan__c upd = new Account_Plan__c(
            Id = plan.Id,
            Status__c = 'Failed',
            Generation_Error__c = AgentAuditLogger.clip('Stage ' + stage + ': ' + e.getTypeName() + ': ' + e.getMessage(), 4000));
        Database.update(upd, false);
        AgentAuditLogger.start(AgenticDemoConfig.PLAN_GENERATOR, 'Account Plan Stage ' + stage)
            .account(plan.Account__c).recordId(plan.Id).error(e.getMessage()).output(e.getStackTraceString()).done();
        AgentAuditLogger.flush();
    }

    private static void notifyOwner(Account_Plan__c plan) {
        try {
            List<CustomNotificationType> types = [SELECT Id FROM CustomNotificationType WHERE DeveloperName = 'Account_Plan_Ready' LIMIT 1];
            if (types.isEmpty()) {
                return;
            }
            Messaging.CustomNotification n = new Messaging.CustomNotification();
            n.setNotificationTypeId(types[0].Id);
            n.setTitle(plan.Name + ' is ready for review');
            n.setBody('Five sections drafted by Claude, grounded in Salesforce and live Snowflake data. Review and approve.');
            n.setTargetId(plan.Id);
            n.send(new Set<String>{ plan.CreatedById });
        } catch (Exception e) {
            System.debug(LoggingLevel.WARN, 'Notification failed: ' + e.getMessage());
        }
    }

    private static Account_Plan__c loadPlan(Id planId) {
        List<Account_Plan__c> rows = [
            SELECT Id, Name, Account__c, Fiscal_Year__c, Status__c, Sections_Completed__c, CreatedById,
                   Grounding_Snapshot__c, Grounding_Source__c
            FROM Account_Plan__c WHERE Id = :planId LIMIT 1
        ];
        return rows.isEmpty() ? null : rows[0];
    }
}
