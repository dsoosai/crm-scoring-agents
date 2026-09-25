/**
 * Agent action: capture thumbs up or down with a comment on the latest action in the conversation.
 * Feeds the observability dashboard and the evaluation set.
 */
public with sharing class RecordAgentFeedback {

    public class Request {
        @InvocableVariable(label='Rating' description='Helpful or Not Helpful' required=true)
        public String rating;
        @InvocableVariable(label='Comment' description='What was good or wrong')
        public String comment;
        @InvocableVariable(label='Agent Name' description='Name of the calling agent')
        public String agentName;
    }

    public class Response {
        @InvocableVariable(label='Message' description='Confirmation for the user')
        public String message;
    }

    @InvocableMethod(label='Record Agent Feedback' description='Records whether the last answer was helpful, with an optional comment.' category='Agentic Enterprise')
    public static List<Response> record(List<Request> requests) {
        List<Response> out = new List<Response>();
        Datetime since = Datetime.now().addMinutes(-60);
        Id me = UserInfo.getUserId();
        for (Request req : requests) {
            String rating = (req.rating != null && req.rating.containsIgnoreCase('not')) ? 'Not Helpful' : 'Helpful';
            List<Agent_Audit_Log__c> recent = [
                SELECT Id FROM Agent_Audit_Log__c
                WHERE CreatedById = :me AND Agent__c = :req.agentName AND CreatedDate >= :since AND Feedback__c = null
                ORDER BY CreatedDate DESC LIMIT 1
            ];
            if (recent.isEmpty()) {
                AgentAuditLogger.start(req.agentName, 'Feedback').output(req.comment).done();
                AgentAuditLogger.flush();
                recent = [SELECT Id FROM Agent_Audit_Log__c WHERE CreatedById = :me ORDER BY CreatedDate DESC LIMIT 1];
            }
            if (!recent.isEmpty()) {
                update new Agent_Audit_Log__c(Id = recent[0].Id, Feedback__c = rating,
                    Feedback_Comment__c = AgentAuditLogger.clip(req.comment, 2000));
            }
            Response res = new Response();
            res.message = 'Thanks. I logged that as ' + rating.toLowerCase() + ' so the team can review it.';
            out.add(res);
        }
        return out;
    }
}
