/**
 * Support agent action: open a case with everything the engineer needs, and route it.
 *
 *   Resolved in the conversation   -> closed case, Resolved by Agent (deflection is still recorded)
 *   Critical, or asks for a person -> Tier 2 Support queue
 *   High severity on a tier A account (CRM score from the scoring agents) -> Tier 2 Support queue
 *   Everything else                -> Tier 1 Support queue
 *
 * Runs without sharing for the same reason as VerifySupportContact; it only writes a case for the
 * verified contact.
 */
public without sharing class CreateSupportCase {

    public class Request {
        @InvocableVariable(label='Contact Id' description='Id of the verified contact' required=true)
        public String contactId;
        @InvocableVariable(label='Subject' description='One-line summary of the issue' required=true)
        public String subject;
        @InvocableVariable(label='Description' description='The issue in the customer words, with error messages and impact' required=true)
        public String description;
        @InvocableVariable(label='Product Area' description='Performance, Data Loading, Security and Access, Cost Management, AI and ML, Data Sharing, Billing and Contracts or Other')
        public String productArea;
        @InvocableVariable(label='Severity' description='Critical (production down), High (major impact), Medium or Low')
        public String severity;
        @InvocableVariable(label='KB Article Id' description='Article the agent suggested, if any')
        public String kbArticleId;
        @InvocableVariable(label='Resolved By Agent' description='True when the customer confirmed the article fixed it')
        public Boolean resolvedByAgent;
        @InvocableVariable(label='Wants a Person' description='True when the customer asked for a human')
        public Boolean wantsPerson;
        @InvocableVariable(label='Agent Summary' description='What was tried in the conversation and why it is handed off')
        public String agentSummary;
    }

    public class Response {
        @InvocableVariable(label='Case Number' description='Case number to give the customer')
        public String caseNumber;
        @InvocableVariable(label='Routed To' description='Queue or status the case went to')
        public String routedTo;
        @InvocableVariable(label='Message' description='What to tell the customer')
        public String message;
    }

    @InvocableMethod(label='Create Support Case' description='Opens a support case for the verified contact and routes it by severity, account tier and whether the agent solved it.' category='Agentic Enterprise')
    public static List<Response> create(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            out.add(createOne(req));
        }
        AgentAuditLogger.flush();
        return out;
    }

    private static Response createOne(Request req) {
        AgentAuditLogger.Entry audit = AgentAuditLogger.start(AgenticDemoConfig.SUPPORT_AGENT, 'Create Support Case').inputs(req);
        Response res = new Response();
        Id contactId = ConsumptionService.toId(req.contactId);
        List<Contact> cs = [SELECT Id, AccountId, Account.Account_Tier__c FROM Contact WHERE Id = :contactId LIMIT 1];
        if (cs.isEmpty()) {
            res.message = 'I need to verify your email before I can open a case.';
            audit.error('Unverified contact').output(res.message).done();
            return res;
        }
        Contact c = cs[0];
        audit.account(c.AccountId);

        // Guardrail: the same issue submitted twice in five minutes returns the first case.
        Datetime recent = Datetime.now().addMinutes(-5);
        String subject = AgentAuditLogger.clip(req.subject, 255);
        List<Case> dupes = [SELECT Id, CaseNumber, Status FROM Case WHERE ContactId = :c.Id AND Subject = :subject
                            AND Agent_Created__c = true AND CreatedDate >= :recent LIMIT 1];
        if (!dupes.isEmpty()) {
            res.caseNumber = dupes[0].CaseNumber;
            res.routedTo = 'Existing case';
            res.message = 'You already have case ' + res.caseNumber + ' for this. I added nothing new.';
            audit.recordId(dupes[0].Id).guardrail('Duplicate case suppressed').output(res.message).done();
            return res;
        }

        String severity = String.isBlank(req.severity) ? 'Medium' : req.severity.trim();
        Boolean resolved = req.resolvedByAgent == true;
        Boolean tierA = c.Account.Account_Tier__c == 'A';
        String priority = severity.equalsIgnoreCase('Critical') || severity.equalsIgnoreCase('High') ? 'High'
            : (severity.equalsIgnoreCase('Low') ? 'Low' : 'Medium');

        String queueName;
        String reason;
        if (resolved) {
            queueName = null;
            reason = 'Resolved in the conversation with ' + req.kbArticleId;
        } else if (severity.equalsIgnoreCase('Critical') || req.wantsPerson == true) {
            queueName = 'Tier_2_Support';
            reason = severity.equalsIgnoreCase('Critical') ? 'Critical severity' : 'Customer asked for a person';
        } else if (tierA && priority == 'High') {
            queueName = 'Tier_2_Support';
            reason = 'High severity on a tier A account (CRM score)';
        } else {
            queueName = 'Tier_1_Support';
            reason = 'Standard routing';
        }

        Case k = new Case(
            ContactId = c.Id,
            AccountId = c.AccountId,
            Subject = subject,
            Description = req.description,
            Priority = priority,
            Origin = 'Web',
            Status = resolved ? 'Closed' : 'New',
            Product_Area__c = SearchSupportKnowledge.PRODUCT_AREAS.contains(req.productArea) ? req.productArea : 'Other',
            KB_Article__c = AgentAuditLogger.clip(req.kbArticleId, 20),
            Agent_Created__c = true,
            Agent_Resolved__c = resolved,
            Agent_Summary__c = AgentAuditLogger.clip('Routing: ' + reason + '.\n' + (req.agentSummary == null ? '' : req.agentSummary), 32000));
        Id queue = queueName == null ? null : AgenticDemoConfig.queueId(queueName);
        if (queue != null) {
            k.OwnerId = queue;
        }
        insert k;
        res.caseNumber = [SELECT CaseNumber FROM Case WHERE Id = :k.Id].CaseNumber;
        res.routedTo = resolved ? 'Closed, resolved by agent' : queueName.replace('_', ' ');
        if (resolved) {
            res.message = 'Glad that fixed it. I logged it as case ' + res.caseNumber + ' and closed it, so you have a record.';
        } else if (queueName == 'Tier_2_Support') {
            res.message = 'I opened case ' + res.caseNumber + ' and sent it straight to our Tier 2 engineers with a summary of what we tried, so you will not need to repeat yourself.';
        } else {
            res.message = 'I opened case ' + res.caseNumber + ' with a summary of what we tried. A support engineer will pick it up.';
        }
        audit.recordId(k.Id).guardrail(reason).output(res.message).done();
        return res;
    }
}
