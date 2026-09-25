/**
 * Prompt Builder grounding for the five account plan section templates. Reads the plan, the CRM
 * context, the Snowflake grounding snapshot saved on the plan and the sections drafted so far.
 * No callouts: the generator fetched the telemetry once and stored it on the plan.
 */
public with sharing class AccountPlanContext {

    public class Request {
        @InvocableVariable(label='Plan Id' description='Salesforce Id of the account plan' required=true)
        public String planId;
    }

    public class Response {
        @InvocableVariable
        public String Prompt;
    }

    @InvocableMethod(label='Account Plan Context' description='CRM context, Snowflake grounding and drafted sections for an account plan.')
    public static List<Response> build(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            Response res = new Response();
            Id planId = ConsumptionService.toId(req.planId);
            List<Account_Plan__c> plans = [
                SELECT Id, Name, Account__c, Account__r.Name, Fiscal_Year__c, Grounding_Snapshot__c, Grounding_Source__c,
                       Consumption_Trends__c, Recommended_Use_Cases__c, Customer_Landscape__c, SWOT_Analysis__c
                FROM Account_Plan__c WHERE Id = :planId LIMIT 1
            ];
            if (plans.isEmpty()) {
                res.Prompt = 'Plan not found.';
                out.add(res);
                continue;
            }
            Account_Plan__c p = plans[0];
            List<String> lines = new List<String>();
            lines.add('PLAN: ' + p.Name + ' for ' + p.Account__r.Name + ', fiscal year ' + p.Fiscal_Year__c + '.');
            lines.add('');
            lines.add(CrmContext.forAccount(p.Account__c));
            lines.add('');
            lines.add('SNOWFLAKE GROUNDING (' + p.Grounding_Source__c + '):');
            lines.add(String.isBlank(p.Grounding_Snapshot__c) ? 'n/a' : p.Grounding_Snapshot__c);
            addSection(lines, 'CONSUMPTION TRENDS', p.Consumption_Trends__c);
            addSection(lines, 'RECOMMENDED USE CASES', p.Recommended_Use_Cases__c);
            addSection(lines, 'CUSTOMER LANDSCAPE', p.Customer_Landscape__c);
            addSection(lines, 'SWOT', p.SWOT_Analysis__c);
            res.Prompt = String.join(lines, '\n');
            out.add(res);
        }
        return out;
    }

    private static void addSection(List<String> lines, String title, String html) {
        if (String.isNotBlank(html)) {
            lines.add('');
            lines.add('DRAFTED SECTION, ' + title + ':');
            lines.add(RichText.toPlain(html));
        }
    }
}
