/**
 * Agent action: save an outreach email draft as a task on the contact. The agent never sends email;
 * the account executive reviews and sends.
 */
public with sharing class SaveOutreachDraft {

    /** The prompt writes this placeholder. The link is inserted here, so it never passes through the LLM. */
    public static final String LINK_PLACEHOLDER = '[scheduling link]';

    public class Request {
        @InvocableVariable(label='Account Id' description='Salesforce Id of the account' required=true)
        public String accountId;
        @InvocableVariable(label='Contact Name' description='Name of the recipient' required=true)
        public String contactName;
        @InvocableVariable(label='Email Draft' description='Full draft including the subject line' required=true)
        public String emailDraft;
        @InvocableVariable(label='Agent Name' description='Name of the calling agent, for the audit log')
        public String agentName;
    }

    public class Response {
        @InvocableVariable(label='Task Id' description='Id of the task that holds the draft')
        public String taskId;
        @InvocableVariable(label='Message' description='Confirmation for the user')
        public String message;
    }

    @InvocableMethod(label='Save Outreach Draft' description='Saves an email draft as an open task on the contact for the account executive to review and send.' category='Agentic Enterprise')
    public static List<Response> save(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            Id accountId = ConsumptionService.toId(req.accountId);
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(req.agentName, 'Save Outreach Draft').account(accountId).inputs(req.contactName);
            Response res = new Response();
            String term = '%' + (req.contactName == null ? '' : req.contactName.trim()) + '%';
            List<Contact> cs = [SELECT Id, Name FROM Contact WHERE AccountId = :accountId AND Name LIKE :term LIMIT 1];
            String subject = 'Email draft';
            String body = fillLink(req.emailDraft == null ? '' : req.emailDraft.trim());
            if (body.startsWithIgnoreCase('Subject:')) {
                subject = body.substringBefore('\n').substringAfter(':').trim();
            }
            Task t = new Task(
                WhatId = accountId,
                WhoId = cs.isEmpty() ? null : cs[0].Id,
                Subject = AgentAuditLogger.clip('Review and send: ' + subject, 255),
                Description = AgentAuditLogger.clip(body, 32000),
                Status = 'Not Started',
                Priority = 'Normal',
                ActivityDate = Date.today(),
                OwnerId = UserInfo.getUserId());
            insert t;
            res.taskId = t.Id;
            res.message = 'Saved the draft as a task for you to review and send' + (cs.isEmpty() ? '' : ' to ' + cs[0].Name) + '. Nothing was sent.';
            audit.recordId(t.Id).output(res.message).done();
            out.add(res);
        }
        AgentAuditLogger.flush();
        return out;
    }

    /** Replaces the placeholder with the account executive's scheduling link, or drops the phrase if there is none. */
    @TestVisible
    private static String fillLink(String body) {
        if (!body.contains(LINK_PLACEHOLDER)) {
            return body;
        }
        String link = [SELECT Scheduling_Link__c FROM User WHERE Id = :UserInfo.getUserId()].Scheduling_Link__c;
        if (String.isNotBlank(link)) {
            return body.replace(LINK_PLACEHOLDER, link);
        }
        return body.replace(': ' + LINK_PLACEHOLDER, '').replace(' ' + LINK_PLACEHOLDER, '').replace(LINK_PLACEHOLDER, '');
    }
}
