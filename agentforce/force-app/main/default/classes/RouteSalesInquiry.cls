/**
 * Support agent action and guardrail: the support agent does not discuss pricing, discounts,
 * renewals or contract terms. It hands the question to the account owner as a task.
 */
public without sharing class RouteSalesInquiry {

    public class Request {
        @InvocableVariable(label='Contact Id' description='Id of the verified contact' required=true)
        public String contactId;
        @InvocableVariable(label='Inquiry' description='What the customer asked about pricing, renewal, credits or contract terms' required=true)
        public String inquiry;
    }

    public class Response {
        @InvocableVariable(label='Message' description='What to tell the customer')
        public String message;
    }

    @InvocableMethod(label='Route Sales Inquiry' description='Sends a pricing, renewal or contract question to the customer account executive instead of answering it.' category='Agentic Enterprise')
    public static List<Response> route(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            Id contactId = ConsumptionService.toId(req.contactId);
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(AgenticDemoConfig.SUPPORT_AGENT, 'Route Sales Inquiry')
                .inputs(req.inquiry).blocked('Support agent does not discuss pricing or contract terms');
            Response res = new Response();
            List<Contact> cs = [SELECT Id, Name, AccountId, Account.OwnerId, Account.Owner.FirstName FROM Contact WHERE Id = :contactId LIMIT 1];
            if (cs.isEmpty()) {
                res.message = 'Your account team can help with pricing and contract questions. Please verify your email first so I can reach them.';
            } else {
                Contact c = cs[0];
                Task t = new Task(
                    OwnerId = c.Account.OwnerId,
                    WhatId = c.AccountId,
                    WhoId = c.Id,
                    Subject = AgentAuditLogger.clip('Customer question for the account team: ' + req.inquiry, 255),
                    Description = c.Name + ' asked the support agent: ' + req.inquiry,
                    Priority = 'High',
                    Status = 'Not Started',
                    ActivityDate = Date.today().addDays(1));
                insert t;
                audit.account(c.AccountId).recordId(t.Id);
                res.message = 'Pricing and contract questions go to your account team, so I passed this to ' + c.Account.Owner.FirstName
                    + '. Expect a reply within one business day.';
            }
            audit.output(res.message).done();
            out.add(res);
        }
        AgentAuditLogger.flush();
        return out;
    }
}
