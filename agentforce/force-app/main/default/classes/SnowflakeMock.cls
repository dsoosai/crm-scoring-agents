/**
 * Test double for the Snowflake SQL API and Cortex Search REST API.
 * mode: 'ok' (everything works), 'noSearch' (Cortex Search fails, SQL works), 'down' (all calls fail).
 */
@IsTest
public class SnowflakeMock implements HttpCalloutMock {

    public String mode = 'ok';

    public SnowflakeMock(String mode) {
        this.mode = mode;
    }

    public HttpResponse respond(HttpRequest req) {
        HttpResponse res = new HttpResponse();
        res.setHeader('Content-Type', 'application/json');
        String url = req.getEndpoint();
        String body = req.getBody() == null ? '' : req.getBody();
        if (mode == 'down' || (mode == 'noSearch' && url.contains(':query'))) {
            res.setStatusCode(401);
            res.setBody('{"code":"390303","message":"Invalid OAuth access token."}');
            return res;
        }
        res.setStatusCode(200);
        if (url.contains('SUPPORT_KB_SEARCH')) {
            res.setBody('{"results":[{"ARTICLE_ID":"KB-1001","TITLE":"Queries queue during peak hours or month-end close",'
                + '"PRODUCT_AREA":"Performance","BODY":"Fix: make the warehouse multi-cluster."}],"request_id":"req-kb"}');
        } else if (url.contains('CASE_STUDY_SEARCH')) {
            res.setBody('{"results":[{"STUDY_ID":"CS-01","TITLE":"Northwind Analytics turns lead scoring into a managed agent",'
                + '"CUSTOMER":"Northwind Analytics","BODY":"Pipeline conversion rose 18 percent."}],"request_id":"req-cs"}');
        } else if (body.contains('V_ACCOUNT_CONSUMPTION_SUMMARY')) {
            res.setBody(statement(
                new List<String>{ 'ACCOUNT_NAME', 'AS_OF_DATE', 'TRAILING_12M_CREDITS', 'YOY_GROWTH_PCT', 'LAST_90D_GROWTH_PCT',
                    'CONSUMPTION_TREND', 'ANNUALIZED_RUN_RATE_CREDITS', 'AVG_DAILY_ACTIVE_USERS', 'CONTRACT_ANNUAL_CREDITS', 'TERM_END',
                    'CONSUMED_IN_TERM_CREDITS', 'CONTRACT_UTILIZATION_PCT', 'PROJECTED_TERM_END_UTILIZATION_PCT', 'PROJECTED_EXHAUSTION_DATE',
                    'TOP_WORKLOAD', 'TOP_WORKLOAD_SHARE_PCT', 'FASTEST_GROWING_WORKLOAD', 'FASTEST_GROWTH_PCT', 'DECLINING_WORKLOAD', 'DECLINE_PCT' },
                new List<List<String>>{ new List<String>{ 'Omega Inc.', '2026-09-24', '63570', '18.2', '9.5', 'Growing', '73607', '61',
                    '60000', '2026-12-19', '49913', '83.2', '122.7', '2026-11-13', 'Data Engineering', '41', 'AI (Cortex)', '282',
                    'Data Science & ML', '-28' } }));
        } else if (body.contains('V_USE_CASE_RECOMMENDATIONS')) {
            res.setBody(statement(
                new List<String>{ 'RANK', 'USE_CASE_ID', 'USE_CASE', 'BUSINESS_UNIT', 'DESCRIPTION', 'PEERS_LIVE', 'PEER_NAMES', 'PEER_OUTCOMES',
                    'EST_ANNUAL_CREDITS', 'INDICATIVE_ANNUAL_VALUE_USD', 'TYPICAL_OUTCOME', 'TIME_TO_VALUE_WEEKS', 'PREREQUISITES' },
                new List<List<String>>{ new List<String>{ '1', 'UC01', 'Predictive Lead and Account Scoring', 'Revenue Operations',
                    'Score every lead.', '4', 'Helix Software, Northwind Analytics', 'Northwind Analytics: conversion up 18 percent', '9100',
                    '27000', 'Pipeline conversion up 12 to 20 percent', '6', 'CRM history with outcomes' } }));
        } else if (body.contains('V_WORKLOAD_MONTHLY')) {
            res.setBody(statement(new List<String>{ 'MONTH', 'WORKLOAD', 'CREDITS' },
                new List<List<String>>{ new List<String>{ '2026-08', 'AI (Cortex)', '1210.5' } }));
        } else if (body.contains('DATA_AGENT_RUN')) {
            String agentJson = '{"role":"assistant","content":[{"type":"tool_use","tool_use":{"name":"Consumption"}},'
                + '{"type":"tool_result","tool_result":{"content":[{"json":{"sql":"SELECT 1"}}]}},'
                + '{"type":"text","text":"AI (Cortex) grew fastest, up 282 percent."}]}';
            res.setBody(statement(new List<String>{ 'RESPONSE' }, new List<List<String>>{ new List<String>{ agentJson } }));
        } else if (body.contains('SUPPORT_KB')) {
            res.setBody(statement(new List<String>{ 'ARTICLE_ID', 'TITLE', 'PRODUCT_AREA', 'BODY' },
                new List<List<String>>{ new List<String>{ 'KB-1001', 'Queries queue', 'Performance', 'Use multi-cluster.' } }));
        } else if (body.contains('CASE_STUDIES')) {
            res.setBody(statement(new List<String>{ 'STUDY_ID', 'TITLE', 'CUSTOMER', 'USE_CASE_ID', 'BODY' },
                new List<List<String>>{ new List<String>{ 'CS-01', 'Northwind lead scoring', 'Northwind Analytics', 'UC01', 'Up 18 percent.' } }));
        } else {
            res.setBody(statement(new List<String>{ 'X' }, new List<List<String>>()));
        }
        return res;
    }

    private static String statement(List<String> cols, List<List<String>> rows) {
        List<Object> rowType = new List<Object>();
        for (String c : cols) {
            rowType.add(new Map<String, Object>{ 'name' => c, 'type' => 'text' });
        }
        return JSON.serialize(new Map<String, Object>{
            'code' => '090001',
            'statementHandle' => '01b7-test-handle',
            'resultSetMetaData' => new Map<String, Object>{ 'numRows' => rows.size(), 'rowType' => rowType },
            'data' => rows
        });
    }
}
