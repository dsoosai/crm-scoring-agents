/**
 * Agent action: recommend the next use cases for an account. Peers in the same industry that run a
 * use case live (Snowflake SQL) plus a matching case study found with Cortex Search.
 */
public with sharing class RecommendUseCases {

    public class Request {
        @InvocableVariable(label='Account Id' description='Salesforce Id of the account' required=true)
        public String accountId;
        @InvocableVariable(label='Agent Name' description='Name of the calling agent, for the audit log')
        public String agentName;
    }

    public class Response {
        @InvocableVariable(label='Recommendations' description='Top three use cases with peer adoption, outcomes, footprint, prerequisites and a case study')
        public String recommendations;
        @InvocableVariable(label='Top Use Case' description='Name of the top recommended use case')
        public String topUseCase;
        @InvocableVariable(label='Source' description='Where the recommendations and evidence came from')
        public String source;
    }

    @InvocableMethod(label='Recommend Use Cases' description='Recommends the next three use cases for an account from peer adoption in Snowflake, with a case study for each from Cortex Search.' category='Agentic Enterprise' callout=true)
    public static List<Response> recommend(List<Request> requests) {
        List<Response> out = new List<Response>();
        List<ConsumptionService.Result> toPersist = new List<ConsumptionService.Result>();
        for (Request req : requests) {
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(req.agentName, 'Recommend Use Cases').inputs(req.accountId);
            Response res = new Response();
            ConsumptionService.Result r = ConsumptionService.getSummary(ConsumptionService.toId(req.accountId));
            ConsumptionService.addRecommendations(r, true);
            res.recommendations = String.isBlank(r.useCasesText) ? 'No recommendations available.' : r.useCasesText;
            res.topUseCase = r.useCases.isEmpty() ? '' : r.useCases[0].name;
            res.source = r.live ? 'Snowflake SQL API; evidence from ' + r.evidenceSource : r.source;
            audit.account(r.account == null ? null : r.account.Id)
                .source(r.live ? (r.evidenceSource == 'Snowflake Cortex Search' ? 'Snowflake Cortex Search' : 'Snowflake SQL API') : r.source)
                .queryId(r.queryId).output(res.recommendations);
            if (!r.live) {
                audit.fallback('Served cached recommendations: ' + r.fallbackReason);
            }
            audit.done();
            toPersist.add(r);
            out.add(res);
        }
        for (ConsumptionService.Result r : toPersist) {
            ConsumptionService.persist(r);
        }
        AgentAuditLogger.flush();
        return out;
    }
}
