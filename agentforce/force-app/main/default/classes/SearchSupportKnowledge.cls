/**
 * Support agent action: search the support knowledge base in Snowflake with Cortex Search.
 * Falls back to Snowflake keyword search when Cortex Search is not available.
 */
public with sharing class SearchSupportKnowledge {

    public static final Set<String> PRODUCT_AREAS = new Set<String>{
        'Performance', 'Data Loading', 'Security and Access', 'Cost Management', 'AI and ML', 'Data Sharing', 'Billing and Contracts', 'Other'
    };

    private static final Set<String> STOP_WORDS = new Set<String>{
        'about', 'after', 'again', 'being', 'could', 'every', 'having', 'there', 'their', 'these', 'those',
        'which', 'while', 'where', 'would', 'should', 'since', 'still', 'today', 'think', 'really', 'getting'
    };

    public class Request {
        @InvocableVariable(label='Issue' description='The customer problem in their words' required=true)
        public String issue;
        @InvocableVariable(label='Product Area' description='Performance, Data Loading, Security and Access, Cost Management, AI and ML, Data Sharing, Billing and Contracts or Other')
        public String productArea;
    }

    public class Response {
        @InvocableVariable(label='Found' description='True when at least one article matched')
        public Boolean found;
        @InvocableVariable(label='Articles' description='Up to three matching articles with their steps')
        public String articles;
        @InvocableVariable(label='Top Article Id' description='Id of the best article, for example KB-1001')
        public String topArticleId;
        @InvocableVariable(label='Source' description='Cortex Search or keyword fallback')
        public String source;
    }

    @InvocableMethod(label='Search Support Knowledge' description='Searches the support knowledge base in Snowflake (Cortex Search) for articles that fix the customer issue.' category='Agentic Enterprise' callout=true)
    public static List<Response> search(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            String area = (req.productArea != null && PRODUCT_AREAS.contains(req.productArea)) ? req.productArea : null;
            AgentAuditLogger.Entry audit = AgentAuditLogger.start(AgenticDemoConfig.SUPPORT_AGENT, 'Search Support Knowledge')
                .inputs(new Map<String, String>{ 'issue' => req.issue, 'productArea' => area });
            Response res = new Response();
            res.found = false;
            List<Map<String, Object>> hits = new List<Map<String, Object>>();
            try {
                Map<String, Object> filter = area == null || area == 'Other' ? null
                    : new Map<String, Object>{ '@eq' => new Map<String, Object>{ 'PRODUCT_AREA' => area } };
                SnowflakeClient.SearchResult sr = SnowflakeClient.search(AgenticDemoConfig.SUPPORT_KB_SEARCH, req.issue,
                    new List<String>{ 'ARTICLE_ID', 'TITLE', 'PRODUCT_AREA', 'BODY' }, filter, 3);
                hits = sr.results;
                res.source = 'Snowflake Cortex Search';
                audit.source('Snowflake Cortex Search').queryId(sr.requestId);
            } catch (Exception e) {
                try {
                    List<String> binds = new List<String>();
                    String sqlText = keywordSql(req.issue, area, binds);
                    SnowflakeClient.QueryResult qr = SnowflakeClient.query(sqlText, binds);
                    for (Map<String, String> row : qr.rows) {
                        Map<String, Object> hit = new Map<String, Object>();
                        for (String key : row.keySet()) {
                            hit.put(key, row.get(key));
                        }
                        hits.add(hit);
                    }
                    res.source = 'Snowflake keyword search (Cortex Search unavailable)';
                    audit.source('Snowflake SQL API').queryId(qr.queryId).fallback('Cortex Search unavailable: ' + e.getMessage());
                } catch (Exception e2) {
                    res.source = 'Unavailable';
                    audit.source('Snowflake SQL API').error(e2.getMessage());
                }
            }
            List<String> lines = new List<String>();
            for (Map<String, Object> h : hits) {
                lines.add(SnowflakeClient.str(h, 'ARTICLE_ID') + ' | ' + SnowflakeClient.str(h, 'TITLE') + ' | '
                    + SnowflakeClient.str(h, 'PRODUCT_AREA') + '\n' + AgentAuditLogger.clip(SnowflakeClient.str(h, 'BODY'), 900));
            }
            res.found = !hits.isEmpty();
            res.topArticleId = hits.isEmpty() ? '' : SnowflakeClient.str(hits[0], 'ARTICLE_ID');
            res.articles = hits.isEmpty() ? 'No matching article.' : String.join(lines, '\n\n');
            audit.output(res.articles).done();
            out.add(res);
        }
        AgentAuditLogger.flush();
        return out;
    }

    // Keyword fallback: scores articles by how many issue keywords they contain, plus the product area.
    @TestVisible
    private static String keywordSql(String issue, String area, List<String> binds) {
        List<String> terms = new List<String>();
        for (String word : (issue == null ? '' : issue.toLowerCase()).split('[^a-z0-9]+')) {
            if (word.length() >= 5 && !STOP_WORDS.contains(word) && !terms.contains(word) && terms.size() < 6) {
                terms.add(word);
            }
        }
        List<String> parts = new List<String>{ 'IFF(PRODUCT_AREA = ?, 2, 0)' };
        binds.add(area == null ? '' : area);
        for (String t : terms) {
            parts.add('IFF((TITLE || \' \' || BODY) ILIKE ?, 1, 0)');
            binds.add('%' + t + '%');
        }
        return 'SELECT ARTICLE_ID, TITLE, PRODUCT_AREA, BODY FROM (SELECT ARTICLE_ID, TITLE, PRODUCT_AREA, LEFT(BODY, 900) AS BODY, '
            + String.join(parts, ' + ') + ' AS HITS FROM SUPPORT_KB) WHERE HITS > 0 ORDER BY HITS DESC, ARTICLE_ID LIMIT 3';
    }
}
