/**
 * Prompt Builder grounding for Account_Executive_Summary: CRM context plus live Snowflake telemetry
 * and peer-based use cases. Read only; the cached snapshot is used if Snowflake is unreachable.
 */
public with sharing class AccountBriefContext {

    public class Request {
        @InvocableVariable(label='Account Id' description='Salesforce Id of the account' required=true)
        public String accountId;
    }

    public class Response {
        @InvocableVariable
        public String Prompt;
    }

    @InvocableMethod(label='Account Brief Context' description='CRM context plus live Snowflake telemetry and use cases for the executive summary prompt.' callout=true)
    public static List<Response> build(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            Id accountId = ConsumptionService.toId(req.accountId);
            Response res = new Response();
            ConsumptionService.Result r = ConsumptionService.getSummary(accountId);
            ConsumptionService.addRecommendations(r, false);
            res.Prompt = 'CRM DATA (Salesforce):\n' + CrmContext.forAccount(accountId)
                + '\n\nPRODUCT TELEMETRY (' + r.source + '):\n' + ConsumptionService.describeSummary(r)
                + '\n\nSIGNALS:\n' + GetConsumptionTelemetry.signals(r)
                + '\n\nRECOMMENDED NEXT USE CASES (peer adoption in Snowflake):\n' + (r.useCasesText == null ? 'n/a' : r.useCasesText);
            out.add(res);
        }
        return out;
    }
}
