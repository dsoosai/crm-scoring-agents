/**
 * Prompt Builder grounding for Sales_Outreach_Email: sender, recipient, latest meeting notes and the
 * use cases with peer case studies (Snowflake SQL API plus Cortex Search).
 */
public with sharing class OutreachContext {

    public class Request {
        @InvocableVariable(label='Account Id' description='Salesforce Id of the account' required=true)
        public String accountId;
        @InvocableVariable(label='Contact Name' description='Name of the person the email is for' required=true)
        public String contactName;
        @InvocableVariable(label='Focus' description='Optional use case or topic to lead with')
        public String focus;
    }

    public class Response {
        @InvocableVariable
        public String Prompt;
    }

    @InvocableMethod(label='Outreach Context' description='Sender, recipient, meeting notes and use cases with case studies for the outreach email prompt.' callout=true)
    public static List<Response> build(List<Request> requests) {
        List<Response> out = new List<Response>();
        User me = [SELECT Name, Title, Email, Scheduling_Link__c FROM User WHERE Id = :UserInfo.getUserId()];
        for (Request req : requests) {
            Id accountId = ConsumptionService.toId(req.accountId);
            List<String> lines = new List<String>();
            lines.add('SENDER: ' + me.Name + (String.isBlank(me.Title) ? ', Account Executive' : ', ' + me.Title) + ', ' + me.Email
                + '. Scheduling link: ' + (String.isBlank(me.Scheduling_Link__c) ? 'none, ask for times instead' : me.Scheduling_Link__c) + '.');
            lines.add('RECIPIENT: ' + describeContact(accountId, req.contactName));
            lines.add('FOCUS REQUESTED BY THE ACCOUNT EXECUTIVE: ' + (String.isBlank(req.focus) ? 'none; lead with the top use case' : req.focus));
            lines.add('');
            lines.add(CrmContext.forAccount(accountId));
            ConsumptionService.Result r = ConsumptionService.getSummary(accountId);
            ConsumptionService.addRecommendations(r, true);
            lines.add('');
            lines.add('USE CASES PEERS RUN (Snowflake; case studies via ' + (r.evidenceSource == null ? r.source : r.evidenceSource) + '):');
            lines.add(r.useCasesText == null ? 'n/a' : r.useCasesText);
            Response res = new Response();
            res.Prompt = String.join(lines, '\n');
            out.add(res);
        }
        return out;
    }

    private static String describeContact(Id accountId, String contactName) {
        String term = '%' + (contactName == null ? '' : contactName.trim()) + '%';
        List<Contact> cs = [SELECT Name, FirstName, Title, Description FROM Contact
                            WHERE AccountId = :accountId AND Name LIKE :term LIMIT 1];
        if (cs.isEmpty()) {
            return contactName + ' (not found in CRM; keep the greeting generic)';
        }
        Contact c = cs[0];
        return c.Name + ' (first name ' + c.FirstName + '), ' + c.Title + (String.isBlank(c.Description) ? '' : '. Notes: ' + c.Description);
    }
}
