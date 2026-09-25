/**
 * Support agent action: identify the customer by the email they give.
 *
 * Runs without sharing because the service agent's user owns no records. It returns only the
 * contact matched by exact email and that contact's own account and open cases.
 */
public without sharing class VerifySupportContact {

    public class Request {
        @InvocableVariable(label='Email' description='Email address the customer gives' required=true)
        public String email;
    }

    public class Response {
        @InvocableVariable(label='Found' description='True when exactly one contact has this email')
        public Boolean found;
        @InvocableVariable(label='Contact Id' description='Salesforce Id of the contact')
        public String contactId;
        @InvocableVariable(label='Contact Name' description='First name to greet the customer with')
        public String firstName;
        @InvocableVariable(label='Account Name' description='Company of the contact')
        public String accountName;
        @InvocableVariable(label='Support Tier' description='Priority when the CRM tier is A, else Standard')
        public String supportTier;
        @InvocableVariable(label='Open Cases' description='The contact open cases, if any')
        public String openCases;
    }

    @InvocableMethod(label='Verify Support Contact' description='Looks up the customer by email and returns their name, company, support tier and open cases.' category='Agentic Enterprise')
    public static List<Response> verify(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            String email = req.email == null ? '' : req.email.trim().toLowerCase();
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(AgenticDemoConfig.SUPPORT_AGENT, 'Verify Support Contact').inputs(email);
            Response res = new Response();
            res.found = false;
            res.contactId = '';
            res.firstName = '';
            res.accountName = '';
            res.supportTier = '';
            res.openCases = 'None';
            List<Contact> cs = [SELECT Id, FirstName, AccountId, Account.Name, Account.Account_Tier__c
                                FROM Contact WHERE Email = :email LIMIT 2];
            if (cs.size() == 1) {
                Contact c = cs[0];
                res.found = true;
                res.contactId = c.Id;
                res.firstName = c.FirstName;
                res.accountName = c.Account.Name;
                res.supportTier = c.Account.Account_Tier__c == 'A' ? 'Priority' : 'Standard';
                List<String> open = new List<String>();
                for (Case k : [SELECT CaseNumber, Subject, Status FROM Case WHERE ContactId = :c.Id AND IsClosed = false
                               ORDER BY CreatedDate DESC LIMIT 5]) {
                    open.add(k.CaseNumber + ' ' + k.Subject + ' (' + k.Status + ')');
                }
                res.openCases = open.isEmpty() ? 'None' : String.join(open, '; ');
                audit.account(c.AccountId).recordId(c.Id);
            }
            audit.output(res.found ? 'Verified ' + res.firstName + ' at ' + res.accountName + ', ' + res.supportTier + ' support' : 'No unique match').done();
            out.add(res);
        }
        AgentAuditLogger.flush();
        return out;
    }
}
