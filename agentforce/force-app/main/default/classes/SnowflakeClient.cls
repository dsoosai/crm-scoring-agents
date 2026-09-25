/**
 * Thin client for Snowflake: SQL API v2, Cortex Search REST and Cortex Agents (DATA_AGENT_RUN).
 *
 * Authentication is a programmatic access token held in the Snowflake_PAT external credential.
 * The token never appears in code or logs. Every call runs as the AGENTFORCE_SVC service user
 * under the read-only AGENTFORCE_READER role, so Snowflake query history shows each agent read.
 */
public with sharing class SnowflakeClient {

    public class SnowflakeException extends Exception {}

    public class QueryResult {
        public List<String> columns = new List<String>();
        public List<Map<String, String>> rows = new List<Map<String, String>>();
        public String queryId;
        public Long latencyMs;

        public Map<String, String> first() {
            return rows.isEmpty() ? null : rows[0];
        }
    }

    public class SearchResult {
        public List<Map<String, Object>> results = new List<Map<String, Object>>();
        public String requestId;
        public Long latencyMs;
    }

    public class AgentAnswer {
        public String text = '';
        public String sqlText;
        public String queryId;
        public Long latencyMs;
    }

    @TestVisible
    private static Integer maxPolls = 3;

    /** Runs one SQL statement. Bindings are positional (?) and passed as TEXT. */
    public static QueryResult query(String sqlText, List<String> textBindings) {
        Long started = System.currentTimeMillis();
        Map<String, Object> body = new Map<String, Object>{
            'statement' => sqlText,
            'timeout' => 50,
            'database' => AgenticDemoConfig.DATABASE_NAME,
            'schema' => AgenticDemoConfig.SCHEMA_NAME,
            'warehouse' => AgenticDemoConfig.WAREHOUSE_NAME,
            'role' => AgenticDemoConfig.ROLE_NAME
        };
        if (textBindings != null && !textBindings.isEmpty()) {
            Map<String, Object> bindings = new Map<String, Object>();
            for (Integer i = 0; i < textBindings.size(); i++) {
                bindings.put(String.valueOf(i + 1), new Map<String, Object>{
                    'type' => 'TEXT',
                    'value' => textBindings[i]
                });
            }
            body.put('bindings', bindings);
        }

        HttpResponse res = send('POST', '/api/v2/statements', JSON.serialize(body));
        Integer polls = 0;
        // 202 means the statement is still running. The status URL returns the result when done.
        while (res.getStatusCode() == 202 && polls < maxPolls) {
            Map<String, Object> pending = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
            String statusUrl = (String) pending.get('statementStatusUrl');
            if (String.isBlank(statusUrl)) {
                break;
            }
            res = send('GET', statusUrl, null);
            polls++;
        }
        if (res.getStatusCode() != 200) {
            throw new SnowflakeException(describeError(res));
        }
        QueryResult qr = parseStatement(res.getBody());
        qr.latencyMs = System.currentTimeMillis() - started;
        return qr;
    }

    /** Queries a Cortex Search service (hybrid vector and keyword search). */
    public static SearchResult search(String serviceName, String queryText, List<String> columns,
                                      Map<String, Object> filter, Integer limitCount) {
        Long started = System.currentTimeMillis();
        Map<String, Object> body = new Map<String, Object>{
            'query' => queryText,
            'columns' => columns,
            'limit' => limitCount
        };
        if (filter != null && !filter.isEmpty()) {
            body.put('filter', filter);
        }
        String path = '/api/v2/databases/' + AgenticDemoConfig.DATABASE_NAME
            + '/schemas/' + AgenticDemoConfig.SCHEMA_NAME
            + '/cortex-search-services/' + serviceName + ':query';
        HttpResponse res = send('POST', path, JSON.serialize(body));
        if (res.getStatusCode() != 200) {
            throw new SnowflakeException(describeError(res));
        }
        SearchResult sr = new SearchResult();
        Map<String, Object> root = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
        sr.requestId = (String) root.get('request_id');
        List<Object> results = (List<Object>) root.get('results');
        if (results != null) {
            for (Object o : results) {
                sr.results.add((Map<String, Object>) o);
            }
        }
        sr.latencyMs = System.currentTimeMillis() - started;
        return sr;
    }

    /** Asks the Cortex agent a question. The agent picks Cortex Analyst (SQL) or Cortex Search. */
    public static AgentAnswer askAgent(String question) {
        Map<String, Object> request = new Map<String, Object>{
            'messages' => new List<Object>{
                new Map<String, Object>{
                    'role' => 'user',
                    'content' => new List<Object>{
                        new Map<String, Object>{ 'type' => 'text', 'text' => question }
                    }
                }
            }
        };
        QueryResult qr = query('SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?) AS RESPONSE',
            new List<String>{ AgenticDemoConfig.CORTEX_AGENT, JSON.serialize(request) });
        AgentAnswer answer = parseAgentResponse(qr.first() == null ? null : qr.first().get('RESPONSE'));
        answer.queryId = qr.queryId;
        answer.latencyMs = qr.latencyMs;
        return answer;
    }

    @TestVisible
    private static AgentAnswer parseAgentResponse(String raw) {
        AgentAnswer answer = new AgentAnswer();
        if (String.isBlank(raw)) {
            return answer;
        }
        Object root = JSON.deserializeUntyped(raw);
        List<String> texts = new List<String>();
        collect(root, texts, answer, 0);
        answer.text = String.join(texts, '\n').trim();
        return answer;
    }

    // Walks the agent response: keeps top-level text blocks and the first SQL statement it finds.
    private static void collect(Object node, List<String> texts, AgentAnswer answer, Integer depth) {
        if (depth > 12 || node == null) {
            return;
        }
        if (node instanceof Map<String, Object>) {
            Map<String, Object> m = (Map<String, Object>) node;
            if ('text'.equals(m.get('type')) && m.get('text') instanceof String) {
                texts.add((String) m.get('text'));
            }
            if (answer.sqlText == null && m.get('sql') instanceof String) {
                answer.sqlText = (String) m.get('sql');
            }
            for (String key : m.keySet()) {
                if (!'text'.equals(key)) {
                    collect(m.get(key), texts, answer, depth + 1);
                }
            }
        } else if (node instanceof List<Object>) {
            for (Object child : (List<Object>) node) {
                collect(child, texts, answer, depth + 1);
            }
        }
    }

    @TestVisible
    private static QueryResult parseStatement(String responseBody) {
        QueryResult qr = new QueryResult();
        Map<String, Object> root = (Map<String, Object>) JSON.deserializeUntyped(responseBody);
        qr.queryId = (String) root.get('statementHandle');
        Map<String, Object> meta = (Map<String, Object>) root.get('resultSetMetaData');
        if (meta != null && meta.get('rowType') != null) {
            for (Object o : (List<Object>) meta.get('rowType')) {
                qr.columns.add(String.valueOf(((Map<String, Object>) o).get('name')).toUpperCase());
            }
        }
        List<Object> data = (List<Object>) root.get('data');
        if (data != null) {
            for (Object rowObj : data) {
                List<Object> row = (List<Object>) rowObj;
                Map<String, String> values = new Map<String, String>();
                for (Integer i = 0; i < qr.columns.size() && i < row.size(); i++) {
                    values.put(qr.columns[i], row[i] == null ? null : String.valueOf(row[i]));
                }
                qr.rows.add(values);
            }
        }
        return qr;
    }

    private static HttpResponse send(String method, String path, String body) {
        HttpRequest req = new HttpRequest();
        req.setEndpoint('callout:' + AgenticDemoConfig.NAMED_CREDENTIAL + path);
        req.setMethod(method);
        req.setTimeout(AgenticDemoConfig.HTTP_TIMEOUT_MS);
        req.setHeader('Content-Type', 'application/json');
        req.setHeader('Accept', 'application/json');
        req.setHeader('User-Agent', 'AgentforceAgenticDemo/1.0');
        req.setHeader('X-Snowflake-Authorization-Token-Type', 'PROGRAMMATIC_ACCESS_TOKEN');
        if (body != null) {
            req.setBody(body);
        }
        return new Http().send(req);
    }

    @TestVisible
    private static String describeError(HttpResponse res) {
        String detail = res.getBody();
        try {
            Map<String, Object> err = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
            detail = String.valueOf(err.get('code')) + ': ' + String.valueOf(err.get('message'));
        } catch (Exception e) {
            detail = String.isBlank(detail) ? res.getStatus() : detail.left(300);
        }
        return 'Snowflake returned HTTP ' + res.getStatusCode() + ' (' + detail + ')';
    }

    // ---- small helpers for callers ----

    public static Decimal num(Map<String, String> row, String key) {
        String v = row == null ? null : row.get(key);
        if (String.isBlank(v)) {
            return null;
        }
        try {
            return Decimal.valueOf(v);
        } catch (Exception e) {
            return null;
        }
    }

    public static Date day(Map<String, String> row, String key) {
        String v = row == null ? null : row.get(key);
        if (String.isBlank(v)) {
            return null;
        }
        try {
            return Date.valueOf(v.left(10));
        } catch (Exception e) {
            return null;
        }
    }

    public static String str(Map<String, Object> m, String key) {
        Object v = m == null ? null : m.get(key);
        return v == null ? null : String.valueOf(v);
    }
}
