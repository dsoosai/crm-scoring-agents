/**
 * Agent action and guardrail: pricing, discounts and contract terms are never answered by the agent.
 * They go to the Deal Desk queue as a case, and the audit log records that the guardrail fired.
 */
public with sharing class RequestDealDeskReview {

    public class Request {
        @InvocableVariable(label='Account Id' description='Salesforce Id of the account' required=true)
        public String accountId;
        @InvocableVariable(label='Request Summary' description='What the rep or customer asked for: discount, price, terms, credits, ramp' required=true)
        public String requestSummary;
        @InvocableVariable(label='Opportunity Name' description='Opportunity the request relates to, if known')
        public String opportunityName;
        @InvocableVariable(label='Agent Name' description='Name of the calling agent, for the audit log')
        public String agentName;
    }

    public class Response {
        @InvocableVariable(label='Case Number' description='Deal Desk case number')
        public String caseNumber;
        @InvocableVariable(label='Message' description='Confirmation for the user')
        public String message;
    }

    @InvocableMethod(label='Request Deal Desk Review' description='Routes any pricing, discount or contract-terms request to the Deal Desk queue. The agent must not answer these itself.' category='Agentic Enterprise')
    public static List<Response> request(List<Request> requests) {
        List<Response> out = new List<Response>();
        Id queue = AgenticDemoConfig.queueId('Deal_Desk');
        for (Request req : requests) {
            Account acct = ConsumptionService.loadAccount(ConsumptionService.toId(req.accountId));
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(req.agentName, 'Request Deal Desk Review')
                .account(acct == null ? null : acct.Id).inputs(req.requestSummary)
                .blocked('Pricing, discounts and contract terms go to Deal Desk');
            Response res = new Response();
            Case c = new Case(
                AccountId = acct == null ? null : acct.Id,
                Subject = AgentAuditLogger.clip('Deal Desk review: ' + (acct == null ? '' : acct.Name + ' - ') + req.requestSummary, 255),
                Description = 'Requested through ' + req.agentName + ' by ' + UserInfo.getName() + '.\n\nRequest: ' + req.requestSummary
                    + (String.isBlank(req.opportunityName) ? '' : '\nOpportunity: ' + req.opportunityName),
                Priority = 'Medium',
                Status = 'New',
                Origin = 'Web',
                Agent_Created__c = true,
                Product_Area__c = 'Billing and Contracts');
            if (queue != null) {
                c.OwnerId = queue;
            }
            insert c;
            res.caseNumber = [SELECT CaseNumber FROM Case WHERE Id = :c.Id].CaseNumber;
            res.message = 'Deal Desk case ' + res.caseNumber + ' is open. Pricing, discounts and contract terms need Deal Desk approval, so I do not quote them. '
                + 'They usually reply within one business day.';
            audit.recordId(c.Id).output(res.message).done();
            out.add(res);
        }
        AgentAuditLogger.flush();
        return out;
    }
}
