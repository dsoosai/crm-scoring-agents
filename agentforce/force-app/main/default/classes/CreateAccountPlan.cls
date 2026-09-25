/**
 * Agent action: create an account plan. Inserting the record with status Queued starts the
 * Account_Plan_Autofill flow, which grounds and drafts every section in the background.
 */
public with sharing class CreateAccountPlan {

    public class Request {
        @InvocableVariable(label='Account Id' description='Salesforce Id of the account' required=true)
        public String accountId;
        @InvocableVariable(label='Fiscal Year' description='Plan year such as FY27. Defaults to FY27.')
        public String fiscalYear;
        @InvocableVariable(label='Agent Name' description='Name of the calling agent, for the audit log')
        public String agentName;
    }

    public class Response {
        @InvocableVariable(label='Plan Id' description='Id of the account plan record')
        public String planId;
        @InvocableVariable(label='Plan Name' description='Name of the account plan')
        public String planName;
        @InvocableVariable(label='Message' description='What happens next and where to open the plan')
        public String message;
    }

    @InvocableMethod(label='Create Account Plan' description='Creates an account plan and starts drafting it in the background from CRM data and live Snowflake telemetry.' category='Agentic Enterprise')
    public static List<Response> create(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            out.add(createOne(req));
        }
        AgentAuditLogger.flush();
        return out;
    }

    private static Response createOne(Request req) {
        AgentAuditLogger.Entry audit = AgentAuditLogger.start(req.agentName, 'Create Account Plan').inputs(req);
        Response res = new Response();
        Account acct = ConsumptionService.loadAccount(ConsumptionService.toId(req.accountId));
        if (acct == null) {
            res.message = 'I could not find that account.';
            audit.error('Account not found').output(res.message).done();
            return res;
        }
        audit.account(acct.Id);
        String fy = String.isBlank(req.fiscalYear) ? AgenticDemoConfig.DEFAULT_FISCAL_YEAR : req.fiscalYear.trim().toUpperCase();

        // Guardrail: one plan in flight per account. A second request returns the running one.
        Datetime recent = Datetime.now().addMinutes(-30);
        List<Account_Plan__c> inFlight = [
            SELECT Id, Name, Status__c FROM Account_Plan__c
            WHERE Account__c = :acct.Id AND Status__c IN ('Queued', 'Grounding', 'Drafting') AND CreatedDate >= :recent
            ORDER BY CreatedDate DESC LIMIT 1
        ];
        if (!inFlight.isEmpty()) {
            res.planId = inFlight[0].Id;
            res.planName = inFlight[0].Name;
            res.message = res.planName + ' is already being drafted (status ' + inFlight[0].Status__c + '). Open it at /lightning/r/Account_Plan__c/' + res.planId + '/view';
            audit.recordId(res.planId).guardrail('Duplicate request: returned the plan already in progress').output(res.message).done();
            return res;
        }

        Account_Plan__c plan = new Account_Plan__c(
            Name = AgentAuditLogger.clip(acct.Name + ' ' + fy + ' Account Plan', 80),
            Account__c = acct.Id,
            Fiscal_Year__c = fy,
            Status__c = 'Queued');
        insert plan;
        res.planId = plan.Id;
        res.planName = plan.Name;
        res.message = 'Created ' + plan.Name + '. The Account Plan Autofill flow is pulling live telemetry from Snowflake and drafting five sections with Claude: '
            + 'consumption trends, recommended use cases, customer landscape, SWOT and account vision. It takes about a minute; you get a notification when it is ready for review. '
            + 'Open it at /lightning/r/Account_Plan__c/' + plan.Id + '/view';
        audit.recordId(plan.Id).output(res.message).done();
        return res;
    }
}
