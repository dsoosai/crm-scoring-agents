/**
 * Agent action: ask the Snowflake Cortex agent (Claude on Cortex, with Cortex Analyst over the
 * semantic view and Cortex Search over case studies) an ad hoc question. Agent to agent.
 *
 * When the Cortex agent is unavailable (AI features off, or the agent not created), the action
 * answers the most common ad hoc question, credits by warehouse and month, with one governed SQL
 * statement through the SQL API, and says so. The agent never guesses.
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
        @InvocableVariable(label='Answer' description='Answer from the Snowflake Cortex agent, or from the governed SQL fallback')
        public String answer;
        @InvocableVariable(label='Generated SQL' description='SQL that answered the question')
        public String generatedSql;
        @InvocableVariable(label='Source' description='Where the answer came from')
        public String source;
    }

    /** Keeps the Cortex answer readable in a chat panel: no charts, and a partial month is not a decline. */
    @TestVisible
    private static final String ANSWER_STYLE = ' Answer in plain text without charts, tables or markdown, and list monthly figures inline.'
        + ' The most recent month is month to date, so do not describe it as a decline.';

    @TestVisible
    private static final String FALLBACK_SQL =
        'SELECT TO_VARCHAR(DATE_TRUNC(\'month\', d.USAGE_DATE), \'YYYY-MM\') AS MONTH, d.WAREHOUSE_NAME, d.WORKLOAD, '
        + 'ROUND(SUM(d.CREDITS), 1) AS CREDITS, TO_VARCHAR(MAX(d.USAGE_DATE), \'YYYY-MM-DD\') AS LAST_DAY '
        + 'FROM DAILY_CONSUMPTION d JOIN ACCOUNTS a ON a.ACCOUNT_KEY = d.ACCOUNT_KEY '
        + 'WHERE a.SF_EXT_ID = ? AND (? = \'ALL\' OR d.WORKLOAD = ?) '
        + 'AND d.USAGE_DATE >= DATEADD(month, -6, DATE_TRUNC(\'month\', (SELECT MAX(USAGE_DATE) FROM DAILY_CONSUMPTION))) '
        + 'GROUP BY 1, 2, 3 ORDER BY 1, 2';

    @InvocableMethod(label='Ask Snowflake Analyst' description='Sends an ad hoc analytics question to the Snowflake Cortex agent, which writes SQL over the governed semantic view and searches case studies. Falls back to governed SQL by warehouse and month.' category='Agentic Enterprise' callout=true)
    public static List<Response> ask(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            String question = req.question == null ? '' : req.question;
            if (String.isNotBlank(req.accountName) && !question.containsIgnoreCase(req.accountName)) {
                question = 'About ' + req.accountName + ': ' + question;
            }
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(req.agentName, 'Ask Snowflake Analyst')
                .inputs(question).model(AgenticDemoConfig.CORTEX_MODEL);
            Response res = new Response();
            try {
                SnowflakeClient.AgentAnswer a = SnowflakeClient.askAgent(question + ANSWER_STYLE);
                if (String.isBlank(a.text)) {
                    throw new SnowflakeClient.SnowflakeException('The Cortex agent returned no answer.');
                }
                res.answer = a.text;
                res.generatedSql = a.sqlText;
                res.source = 'Snowflake Cortex Agent (CONSUMPTION_ANALYST)';
                audit.source('Snowflake Cortex Agent').queryId(a.queryId);
            } catch (Exception e) {
                fallback(req, question, e.getMessage(), res, audit);
            }
            audit.output(res.answer + (res.generatedSql == null ? '' : '\nSQL: ' + res.generatedSql)).done();
            out.add(res);
        }
        AgentAuditLogger.flush();
        return out;
    }

    private static void fallback(Request req, String question, String cortexError, Response res, AgentAuditLogger.Entry audit) {
        Account acct = findAccount(req.accountName, question);
        if (acct == null || String.isBlank(acct.CRM_Score_Ext_Id__c)) {
            res.answer = 'The Snowflake Cortex agent is not available right now, and the governed fallback needs an account with a platform account key. '
                + 'Use the consumption telemetry action for the account summary.';
            res.source = 'Unavailable';
            audit.source('Snowflake Cortex Agent').error(cortexError);
            return;
        }
        String workload = workloadIn(question);
        try {
            SnowflakeClient.QueryResult qr = SnowflakeClient.query(FALLBACK_SQL,
                new List<String>{ acct.CRM_Score_Ext_Id__c, workload, workload });
            res.answer = 'The Snowflake Cortex agent is not available on this account right now, so this answer comes from one governed SQL statement '
                + 'over the same telemetry, through the SQL API.\n' + describe(acct.Name, workload, qr);
            res.generatedSql = FALLBACK_SQL.replaceFirst('\\?', '\'' + acct.CRM_Score_Ext_Id__c + '\'')
                .replaceFirst('\\?', '\'' + workload + '\'').replaceFirst('\\?', '\'' + workload + '\'');
            res.source = 'Snowflake SQL API (governed fallback, Cortex agent unavailable)';
            audit.account(acct.Id).source('Snowflake SQL API').queryId(qr.queryId)
                .fallback('Cortex agent unavailable, answered with governed SQL: ' + cortexError);
        } catch (Exception e) {
            res.answer = 'Snowflake is not reachable right now (' + e.getMessage() + '). Use the consumption telemetry action, which falls back to the cached snapshot.';
            res.source = 'Unavailable';
            audit.account(acct.Id).source('Snowflake SQL API').error(e.getMessage());
        }
    }

    private static Account findAccount(String accountName, String question) {
        if (String.isNotBlank(accountName)) {
            List<Account> exact = [SELECT Id, Name, CRM_Score_Ext_Id__c FROM Account WHERE Name = :accountName.trim() LIMIT 1];
            if (!exact.isEmpty()) {
                return exact[0];
            }
            String term = '%' + accountName.trim() + '%';
            List<Account> partial = [SELECT Id, Name, CRM_Score_Ext_Id__c FROM Account WHERE Name LIKE :term ORDER BY Name LIMIT 1];
            if (!partial.isEmpty()) {
                return partial[0];
            }
        }
        for (Account a : [SELECT Id, Name, CRM_Score_Ext_Id__c FROM Account WHERE CRM_Score_Ext_Id__c != null ORDER BY Name LIMIT 200]) {
            if (question.containsIgnoreCase(a.Name) || question.containsIgnoreCase(a.Name.removeEnd('.').removeEnd(' Inc'))) {
                return a;
            }
        }
        return null;
    }

    /** Maps words in the question to one workload, or ALL. */
    @TestVisible
    private static String workloadIn(String question) {
        String q = ' ' + question.toLowerCase().replaceAll('[^a-z0-9 ]', ' ') + ' ';
        if (q.contains(' ai ') || q.contains(' cortex ') || q.contains(' llm ') || q.contains(' copilot ') || q.contains(' genai ')) {
            return 'AI (Cortex)';
        }
        if (q.contains(' ml ') || q.contains(' machine learning ') || q.contains(' data science ') || q.contains(' training ')) {
            return 'Data Science & ML';
        }
        if (q.contains(' bi ') || q.contains(' dashboard') || q.contains(' reporting ')) {
            return 'BI & Analytics';
        }
        if (q.contains(' engineering ') || q.contains(' elt ') || q.contains(' etl ') || q.contains(' pipeline')) {
            return 'Data Engineering';
        }
        if (q.contains(' sharing ') || q.contains(' apps ')) {
            return 'Data Sharing & Apps';
        }
        return 'ALL';
    }

    /** Turns month x warehouse rows into a short table and a one-line finding. */
    @TestVisible
    private static String describe(String accountName, String workload, SnowflakeClient.QueryResult qr) {
        Map<String, Map<String, Decimal>> byWarehouse = new Map<String, Map<String, Decimal>>();
        Map<String, String> workloadOf = new Map<String, String>();
        Set<String> monthSet = new Set<String>();
        String lastDay;
        for (Map<String, String> row : qr.rows) {
            String wh = row.get('WAREHOUSE_NAME');
            String month = row.get('MONTH');
            monthSet.add(month);
            if (!byWarehouse.containsKey(wh)) {
                byWarehouse.put(wh, new Map<String, Decimal>());
            }
            Map<String, Decimal> m = byWarehouse.get(wh);
            m.put(month, (m.containsKey(month) ? m.get(month) : 0) + SnowflakeClient.num(row, 'CREDITS'));
            workloadOf.put(wh, row.get('WORKLOAD'));
            String d = row.get('LAST_DAY');
            if (d != null && (lastDay == null || d > lastDay)) {
                lastDay = d;
            }
        }
        if (byWarehouse.isEmpty()) {
            return 'No telemetry rows for ' + accountName + (workload == 'ALL' ? '' : ' in ' + workload) + ' in the last six months.';
        }
        List<String> months = new List<String>(monthSet);
        months.sort();
        String latest = months[months.size() - 1];
        Boolean partial = lastDay != null && !lastDay.endsWith('-28') && !lastDay.endsWith('-29') && !lastDay.endsWith('-30') && !lastDay.endsWith('-31');
        String lastFull = partial && months.size() > 1 ? months[months.size() - 2] : latest;

        List<String> lines = new List<String>();
        lines.add(accountName + ', ' + (workload == 'ALL' ? 'all workloads' : workload) + ', credits by warehouse and month'
            + (partial ? ' (' + latest + ' is month to date through ' + lastDay + ')' : '') + ':');
        String driver;
        Decimal driverGain;
        for (String wh : byWarehouse.keySet()) {
            Map<String, Decimal> m = byWarehouse.get(wh);
            List<String> cells = new List<String>();
            for (String month : months) {
                cells.add(month + ' ' + (m.containsKey(month) ? String.valueOf(m.get(month).setScale(1)) : '0'));
            }
            lines.add('- ' + wh + ' (' + workloadOf.get(wh) + '): ' + String.join(cells, ' | '));
            Decimal first = m.containsKey(months[0]) ? m.get(months[0]) : 0;
            Decimal last = m.containsKey(lastFull) ? m.get(lastFull) : 0;
            if (driver == null || (last - first) > driverGain) {
                driver = wh;
                driverGain = last - first;
            }
        }
        Map<String, Decimal> dm = byWarehouse.get(driver);
        Decimal first = dm.containsKey(months[0]) ? dm.get(months[0]) : 0;
        Decimal last = dm.containsKey(lastFull) ? dm.get(lastFull) : 0;
        String growth = first > 0 ? ' (' + (((last - first) / first) * 100).setScale(0) + ' percent)' : '';
        lines.add('Finding: ' + driver + ' drives the growth, from ' + first.setScale(1) + ' credits in ' + months[0]
            + ' to ' + last.setScale(1) + ' in ' + lastFull + growth + '.');
        return String.join(lines, '\n');
    }
}
