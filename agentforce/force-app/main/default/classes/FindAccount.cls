/**
 * Agent action: find an account by name (or Id) so later actions can work on it.
 */
public with sharing class FindAccount {

    public class Request {
        @InvocableVariable(label='Account Name or Id' description='Full or partial account name, or a Salesforce account Id' required=true)
        public String accountName;
        @InvocableVariable(label='Agent Name' description='Name of the calling agent, for the audit log')
        public String agentName;
    }

    public class Response {
        @InvocableVariable(label='Found' description='True when exactly one account matched')
        public Boolean found;
        @InvocableVariable(label='Account Id' description='Salesforce Id of the matched account')
        public String accountId;
        @InvocableVariable(label='Account Name' description='Name of the matched account')
        public String accountName;
        @InvocableVariable(label='Summary' description='Owner, industry, tier and score, or the list of candidates when several match')
        public String summary;
    }

    @InvocableMethod(label='Find Account' description='Finds an account by name or Id and returns its Id, owner, industry, CRM tier and score.' category='Agentic Enterprise')
    public static List<Response> find(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            out.add(findOne(req));
        }
        AgentAuditLogger.flush();
        return out;
    }

    private static Response findOne(Request req) {
        AgentAuditLogger.Entry audit = AgentAuditLogger.start(req.agentName, 'Find Account').inputs(req.accountName);
        Response res = new Response();
        res.found = false;
        res.accountId = '';
        res.accountName = '';
        String term = req.accountName == null ? '' : req.accountName.trim();
        List<Account> matches = new List<Account>();
        if (Pattern.matches('^001[a-zA-Z0-9]{12}([a-zA-Z0-9]{3})?$', term)) {
            matches = [SELECT Id, Name, Industry, Type, Owner.Name, Account_Tier__c, Account_Score__c
                       FROM Account WHERE Id = :term WITH USER_MODE LIMIT 1];
        } else if (term.length() >= 2) {
            String likeTerm = '%' + term + '%';
            matches = [SELECT Id, Name, Industry, Type, Owner.Name, Account_Tier__c, Account_Score__c
                       FROM Account WHERE Name LIKE :likeTerm WITH USER_MODE
                       ORDER BY Account_Score__c DESC NULLS LAST LIMIT 6];
        }
        Account pick = null;
        if (matches.size() == 1) {
            pick = matches[0];
        } else {
            for (Account a : matches) {
                if (a.Name.equalsIgnoreCase(term) || a.Name.equalsIgnoreCase(term + ' Inc.') || a.Name.equalsIgnoreCase(term + ' Inc')) {
                    pick = a;
                }
            }
        }
        if (pick != null) {
            res.found = true;
            res.accountId = pick.Id;
            res.accountName = pick.Name;
            res.summary = pick.Name + ': ' + (pick.Type == null ? 'account' : pick.Type) + ' in ' + (pick.Industry == null ? 'an unknown industry' : pick.Industry)
                + ', owned by ' + pick.Owner.Name + '. CRM score ' + (pick.Account_Score__c == null ? 'not scored' : pick.Account_Score__c.setScale(1) + ' (tier ' + pick.Account_Tier__c + ')') + '.';
            audit.account(pick.Id).recordId(pick.Id);
        } else if (matches.isEmpty()) {
            res.summary = 'No account matches "' + term + '". Ask for the exact name.';
        } else {
            List<String> names = new List<String>();
            for (Account a : matches) {
                names.add(a.Name + ' (' + (a.Industry == null ? 'n/a' : a.Industry) + ')');
            }
            res.summary = 'Several accounts match: ' + String.join(names, '; ') + '. Ask which one.';
        }
        audit.output(res.summary).done();
        return res;
    }
}
