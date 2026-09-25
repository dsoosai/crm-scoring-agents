/**
 * Agent action: live consumption telemetry for an account, read from Snowflake through the SQL API.
 * Falls back to the last snapshot, and says so, when Snowflake is unreachable.
 */
public with sharing class GetConsumptionTelemetry {

    public class Request {
        @InvocableVariable(label='Account Id' description='Salesforce Id of the account' required=true)
        public String accountId;
        @InvocableVariable(label='Agent Name' description='Name of the calling agent, for the audit log')
        public String agentName;
    }

    public class Response {
        @InvocableVariable(label='Summary' description='Credits, growth, contract utilization, projected exhaustion and workload trends')
        public String summary;
        @InvocableVariable(label='Source' description='Snowflake SQL API when live, or the cached snapshot time')
        public String source;
        @InvocableVariable(label='Is Live' description='True when read live from Snowflake')
        public Boolean isLive;
        @InvocableVariable(label='Contract Utilization Percent' description='Share of this term capacity already consumed')
        public Decimal utilizationPct;
        @InvocableVariable(label='Projected Exhaustion Date' description='When capacity runs out at the current run rate, blank if it lasts the term')
        public String projectedExhaustionDate;
        @InvocableVariable(label='Signals' description='Expansion and risk signals derived from the telemetry')
        public String signals;
    }

    @InvocableMethod(label='Get Consumption Telemetry' description='Reads live product consumption for an account from Snowflake: credits, growth, contract utilization, projected exhaustion date and workload trends.' category='Agentic Enterprise' callout=true)
    public static List<Response> getTelemetry(List<Request> requests) {
        List<Response> out = new List<Response>();
        List<ConsumptionService.Result> toPersist = new List<ConsumptionService.Result>();
        for (Request req : requests) {
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(req.agentName, 'Get Consumption Telemetry').inputs(req.accountId);
            Response res = new Response();
            ConsumptionService.Result r = ConsumptionService.getSummary(ConsumptionService.toId(req.accountId));
            res.summary = ConsumptionService.describeSummary(r);
            res.source = r.source;
            res.isLive = r.live;
            res.signals = signals(r);
            if (r.snapshot != null) {
                res.utilizationPct = r.snapshot.Contract_Utilization_Pct__c;
                res.projectedExhaustionDate = r.snapshot.Projected_Exhaustion_Date__c == null ? '' : String.valueOf(r.snapshot.Projected_Exhaustion_Date__c);
            }
            audit.account(r.account == null ? null : r.account.Id).source(r.live ? 'Snowflake SQL API' : r.source)
                .queryId(r.queryId).output(res.summary + '\n' + res.signals);
            if (!r.live) {
                audit.fallback('Snowflake unreachable, served cached snapshot: ' + r.fallbackReason);
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

    public static String signals(ConsumptionService.Result r) {
        if (r.snapshot == null) {
            return 'No signals without telemetry.';
        }
        Consumption_Snapshot__c s = r.snapshot;
        List<String> out = new List<String>();
        if (s.Projected_Exhaustion_Date__c != null && s.Term_End__c != null && s.Projected_Exhaustion_Date__c < s.Term_End__c) {
            Integer days = s.Projected_Exhaustion_Date__c.daysBetween(s.Term_End__c);
            out.add('Expansion signal: capacity runs out about ' + days + ' days before the term ends. Open the renewal and expansion conversation now.');
        }
        if (s.Fastest_Growing_Workload__c != null && s.Fastest_Growth_Pct__c != null && s.Fastest_Growth_Pct__c >= 50) {
            out.add('Adoption signal: ' + s.Fastest_Growing_Workload__c + ' grew ' + ConsumptionService.signed(s.Fastest_Growth_Pct__c) + ' in 90 days.');
        }
        if (s.Declining_Workload__c != null && s.Decline_Pct__c != null && s.Decline_Pct__c <= -15) {
            out.add('Risk signal: ' + s.Declining_Workload__c + ' fell ' + ConsumptionService.signed(s.Decline_Pct__c) + '. Check for a competing platform.');
        }
        return out.isEmpty() ? 'No strong signals.' : String.join(out, '\n');
    }
}
