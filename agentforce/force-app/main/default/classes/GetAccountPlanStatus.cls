/**
 * Agent action: where the latest account plan for an account stands.
 */
public with sharing class GetAccountPlanStatus {

    public class Request {
        @InvocableVariable(label='Account Id' description='Salesforce Id of the account' required=true)
        public String accountId;
    }

    public class Response {
        @InvocableVariable(label='Status' description='Plan status, or None when the account has no plan')
        public String status;
        @InvocableVariable(label='Sections Completed' description='How many of the five sections are drafted')
        public Decimal sectionsCompleted;
        @InvocableVariable(label='Plan Id' description='Id of the latest plan')
        public String planId;
        @InvocableVariable(label='Message' description='Summary with a link and the account vision once ready')
        public String message;
    }

    @InvocableMethod(label='Get Account Plan Status' description='Returns the status of the latest account plan for an account, with its vision once drafted.' category='Agentic Enterprise')
    public static List<Response> getStatus(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            Id accountId = ConsumptionService.toId(req.accountId);
            Response res = new Response();
            List<Account_Plan__c> plans = [
                SELECT Id, Name, Status__c, Sections_Completed__c, Generated_At__c, Account_Vision__c, Generation_Error__c
                FROM Account_Plan__c WHERE Account__c = :accountId ORDER BY CreatedDate DESC LIMIT 1
            ];
            if (plans.isEmpty()) {
                res.status = 'None';
                res.sectionsCompleted = 0;
                res.message = 'This account has no account plan yet.';
            } else {
                Account_Plan__c p = plans[0];
                res.status = p.Status__c;
                res.sectionsCompleted = p.Sections_Completed__c;
                res.planId = p.Id;
                res.message = p.Name + ': ' + p.Status__c + ', ' + (p.Sections_Completed__c == null ? 0 : p.Sections_Completed__c.intValue())
                    + ' of 5 sections drafted. Open it at /lightning/r/Account_Plan__c/' + p.Id + '/view';
                if (p.Status__c == 'Failed') {
                    res.message += '. Error: ' + p.Generation_Error__c;
                } else if (String.isNotBlank(p.Account_Vision__c)) {
                    res.message += '\nAccount vision: ' + AgentAuditLogger.clip(RichText.toPlain(p.Account_Vision__c), 900);
                }
            }
            out.add(res);
        }
        return out;
    }
}
