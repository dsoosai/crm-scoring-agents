/**
 * Agent action: ask the Snowflake Cortex agent (Claude on Cortex, with Cortex Analyst over the
 * semantic view and Cortex Search over case studies) an ad hoc question. Agent to agent.
 */
public with sharing class AskSnowflakeAnalyst {

    public class Request {
        @InvocableVariable(label='Question' description='Question about consumption, workloads, warehouses, contracts or peer adoption' required=true)
        public String question;
        @InvocableVariable(label='Account Name' description='Account the question is about, if any')
        public String accountName;
        @InvocableVariable(label='Agent Name' description='Name of the calling agent, for the audit log')
        public String agentName;
    }

    public class Response {
        @InvocableVariable(label='Answer' description='Answer from the Snowflake Cortex agent')
        public String answer;
        @InvocableVariable(label='Generated SQL' description='SQL that Cortex Analyst generated, when it used one')
        public String generatedSql;
        @InvocableVariable(label='Source' description='Where the answer came from')
        public String source;
    }

    @InvocableMethod(label='Ask Snowflake Analyst' description='Sends an ad hoc analytics question to the Snowflake Cortex agent, which writes SQL over the governed semantic view and searches case studies.' category='Agentic Enterprise' callout=true)
    public static List<Response> ask(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            String question = req.question;
            if (String.isNotBlank(req.accountName) && !question.containsIgnoreCase(req.accountName)) {
                question = 'About ' + req.accountName + ': ' + question;
            }
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(req.agentName, 'Ask Snowflake Analyst')
                .inputs(question).model(AgenticDemoConfig.CORTEX_MODEL);
            Response res = new Response();
            try {
                SnowflakeClient.AgentAnswer a = SnowflakeClient.askAgent(question);
                res.answer = String.isBlank(a.text) ? 'The Snowflake agent returned no answer.' : a.text;
                res.generatedSql = a.sqlText;
                res.source = 'Snowflake Cortex Agent (CONSUMPTION_ANALYST)';
                audit.source('Snowflake Cortex Agent').queryId(a.queryId);
            } catch (Exception e) {
                res.answer = 'The Snowflake analyst is not reachable right now (' + e.getMessage() + '). Use the consumption telemetry action instead.';
                res.source = 'Unavailable';
                audit.source('Snowflake Cortex Agent').error(e.getMessage());
            }
            audit.output(res.answer + (res.generatedSql == null ? '' : '\nSQL: ' + res.generatedSql)).done();
            out.add(res);
        }
        AgentAuditLogger.flush();
        return out;
    }
}
