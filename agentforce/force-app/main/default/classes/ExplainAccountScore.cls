/**
 * Agent action: explain the account's CRM score. The score comes from the champion model
 * managed by the CRM scoring agents (trained and registered on Hugging Face).
 */
public with sharing class ExplainAccountScore {

    public class Request {
        @InvocableVariable(label='Account Id' description='Salesforce Id of the account' required=true)
        public String accountId;
        @InvocableVariable(label='Agent Name' description='Name of the calling agent, for the audit log')
        public String agentName;
    }

    public class Response {
        @InvocableVariable(label='Explanation' description='Score, tier, model version, top reasons and when it was scored')
        public String explanation;
    }

    @InvocableMethod(label='Explain Account Score' description='Explains the account CRM score: tier, model version and the top reasons.' category='Agentic Enterprise')
    public static List<Response> explain(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(req.agentName, 'Explain Account Score').inputs(req.accountId);
            Response res = new Response();
            ScoreExplainAction.Request scoreRequest = new ScoreExplainAction.Request();
            try {
                scoreRequest.recordId = Id.valueOf(req.accountId);
                res.explanation = ScoreExplainAction.explain(new List<ScoreExplainAction.Request>{ scoreRequest })[0].explanation;
                res.explanation += ' Scores come from the champion model promoted by the CRM scoring agents after drift checks and gated retraining.';
                audit.account(scoreRequest.recordId.getSObjectType() == Account.SObjectType ? scoreRequest.recordId : null).model('CRM scoring champion (Hugging Face)');
            } catch (Exception e) {
                res.explanation = 'That is not a valid account Id.';
                audit.error(e.getMessage());
            }
            audit.output(res.explanation).done();
            out.add(res);
        }
        AgentAuditLogger.flush();
        return out;
    }
}
