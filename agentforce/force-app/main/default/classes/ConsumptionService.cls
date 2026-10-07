/**
 * Reads product telemetry and use-case evidence from Snowflake for one Salesforce account.
 *
 * Zero copy: the numbers stay in Snowflake and are read at the moment an agent or prompt needs them.
 * The last good answer is kept in Consumption_Snapshot__c so agents still work, clearly labelled as
 * cached, when Snowflake cannot be reached.
 */
public with sharing class ConsumptionService {

    public class UseCase {
        public Integer rank;
        public String useCaseId;
        public String name;
        public String businessUnit;
        public String description;
        public Integer peersLive;
        public String peerNames;
        public String peerOutcomes;
        public Decimal estAnnualCredits;
        public Decimal indicativeValueUsd;
        public String typicalOutcome;
        public Decimal timeToValueWeeks;
        public String prerequisites;
        public String caseStudyId;
        public String caseStudyTitle;
        public String caseStudyExcerpt;
    }

    public class Result {
        public Account account;
        public Boolean found = false;
        public Boolean live = false;
        public String source = 'Snowflake SQL API';
        public String fallbackReason;
        public String queryId;
        public Long latencyMs = 0;
        public Consumption_Snapshot__c snapshot;
        public List<UseCase> useCases = new List<UseCase>();
        public String useCasesText;
        public String evidenceSource;
        public List<String> monthlyTrend = new List<String>();
    }

    private static final String SUMMARY_SQL =
        'SELECT ACCOUNT_NAME, TO_VARCHAR(AS_OF_DATE, \'YYYY-MM-DD\') AS AS_OF_DATE, TRAILING_12M_CREDITS, YOY_GROWTH_PCT, '
        + 'LAST_90D_GROWTH_PCT, CONSUMPTION_TREND, ANNUALIZED_RUN_RATE_CREDITS, AVG_DAILY_ACTIVE_USERS, CONTRACT_ANNUAL_CREDITS, '
        + 'TO_VARCHAR(TERM_END, \'YYYY-MM-DD\') AS TERM_END, CONSUMED_IN_TERM_CREDITS, CONTRACT_UTILIZATION_PCT, '
        + 'PROJECTED_TERM_END_UTILIZATION_PCT, TO_VARCHAR(PROJECTED_EXHAUSTION_DATE, \'YYYY-MM-DD\') AS PROJECTED_EXHAUSTION_DATE, '
        + 'TOP_WORKLOAD, TOP_WORKLOAD_SHARE_PCT, FASTEST_GROWING_WORKLOAD, FASTEST_GROWTH_PCT, DECLINING_WORKLOAD, DECLINE_PCT '
        + 'FROM V_ACCOUNT_CONSUMPTION_SUMMARY WHERE SF_EXT_ID = ?';

    private static final String RECS_SQL =
        'SELECT RANK, USE_CASE_ID, USE_CASE, BUSINESS_UNIT, DESCRIPTION, PEERS_LIVE, PEER_NAMES, PEER_OUTCOMES, '
        + 'EST_ANNUAL_CREDITS, INDICATIVE_ANNUAL_VALUE_USD, TYPICAL_OUTCOME, TIME_TO_VALUE_WEEKS, PREREQUISITES '
        + 'FROM V_USE_CASE_RECOMMENDATIONS WHERE SF_EXT_ID = ? ORDER BY RANK LIMIT 3';

    private static final String MONTHLY_SQL =
        'SELECT TO_VARCHAR(USAGE_MONTH, \'YYYY-MM\') AS MONTH, WORKLOAD, CREDITS FROM V_WORKLOAD_MONTHLY '
        + 'WHERE SF_EXT_ID = ? AND USAGE_MONTH >= DATEADD(month, -6, DATE_TRUNC(\'month\', '
        + '(SELECT MAX(USAGE_DATE) FROM DAILY_CONSUMPTION))) ORDER BY MONTH, WORKLOAD';

    private static final String CASE_STUDY_SQL =
        'SELECT STUDY_ID, TITLE, CUSTOMER, USE_CASE_ID, LEFT(BODY, 700) AS BODY FROM CASE_STUDIES '
        + 'WHERE USE_CASE_ID = ? ORDER BY STUDY_ID LIMIT 1';

    /** Returns null instead of throwing when the agent passes something that is not an Id. */
    public static Id toId(String value) {
        try {
            return String.isBlank(value) ? null : Id.valueOf(value.trim());
        } catch (Exception e) {
            return null;
        }
    }

    public static Account loadAccount(Id accountId) {
        if (accountId == null) {
            return null;
        }
        List<Account> rows = [
            SELECT Id, Name, Industry, CRM_Score_Ext_Id__c, Account_Score__c, Account_Tier__c, OwnerId
            FROM Account WHERE Id = :accountId LIMIT 1
        ];
        return rows.isEmpty() ? null : rows[0];
    }

    /** Consumption summary: live from Snowflake, else the cached snapshot. */
    public static Result getSummary(Id accountId) {
        Result r = new Result();
        r.account = loadAccount(accountId);
        if (r.account == null) {
            r.fallbackReason = 'Account not found or not visible to you.';
            return r;
        }
        if (String.isBlank(r.account.CRM_Score_Ext_Id__c)) {
            r.fallbackReason = r.account.Name + ' has no platform account key, so there is no telemetry to read.';
            return r;
        }
        try {
            SnowflakeClient.QueryResult qr = SnowflakeClient.query(SUMMARY_SQL, new List<String>{ r.account.CRM_Score_Ext_Id__c });
            r.queryId = qr.queryId;
            r.latencyMs += qr.latencyMs;
            Map<String, String> row = qr.first();
            if (row == null) {
                r.fallbackReason = 'Snowflake has no telemetry for ' + r.account.Name + '.';
                return r;
            }
            r.snapshot = toSnapshot(r.account.Id, row, qr.queryId);
            r.found = true;
            r.live = true;
        } catch (Exception e) {
            useCache(r, e);
        }
        return r;
    }

    /** Peer-based use-case recommendations, optionally with a case study for each (Cortex Search). */
    public static void addRecommendations(Result r, Boolean withCaseStudies) {
        if (r.account == null || String.isBlank(r.account.CRM_Score_Ext_Id__c)) {
            return;
        }
        if (!r.live && r.snapshot != null) {
            r.useCasesText = r.snapshot.Recommended_Use_Cases__c;
            return;
        }
        try {
            SnowflakeClient.QueryResult qr = SnowflakeClient.query(RECS_SQL, new List<String>{ r.account.CRM_Score_Ext_Id__c });
            r.latencyMs += qr.latencyMs;
            for (Map<String, String> row : qr.rows) {
                UseCase uc = new UseCase();
                Decimal rank = SnowflakeClient.num(row, 'RANK');
                uc.rank = rank == null ? r.useCases.size() + 1 : rank.intValue();
                uc.useCaseId = row.get('USE_CASE_ID');
                uc.name = row.get('USE_CASE');
                uc.businessUnit = row.get('BUSINESS_UNIT');
                uc.description = row.get('DESCRIPTION');
                Decimal peers = SnowflakeClient.num(row, 'PEERS_LIVE');
                uc.peersLive = peers == null ? 0 : peers.intValue();
                uc.peerNames = row.get('PEER_NAMES');
                uc.peerOutcomes = row.get('PEER_OUTCOMES');
                uc.estAnnualCredits = SnowflakeClient.num(row, 'EST_ANNUAL_CREDITS');
                uc.indicativeValueUsd = SnowflakeClient.num(row, 'INDICATIVE_ANNUAL_VALUE_USD');
                uc.typicalOutcome = row.get('TYPICAL_OUTCOME');
                uc.timeToValueWeeks = SnowflakeClient.num(row, 'TIME_TO_VALUE_WEEKS');
                uc.prerequisites = row.get('PREREQUISITES');
                r.useCases.add(uc);
            }
            if (withCaseStudies) {
                addCaseStudies(r);
            }
            // Prices stay out of everything the agents and prompts read. Deal Desk owns pricing.
            r.useCasesText = describeUseCases(r.useCases, false);
            if (r.snapshot != null) {
                r.snapshot.Recommended_Use_Cases__c = AgentAuditLogger.clip(r.useCasesText, 32000);
            }
        } catch (Exception e) {
            if (r.snapshot == null || String.isBlank(r.snapshot.Recommended_Use_Cases__c)) {
                Consumption_Snapshot__c cached = latestSnapshot(r.account.Id);
                r.useCasesText = cached == null ? null : cached.Recommended_Use_Cases__c;
            }
            r.fallbackReason = 'Recommendations: ' + e.getMessage();
        }
    }

    // One Cortex Search call per use case, filtered to that use case. Falls back to plain SQL
    // when Cortex Search is not available on the account.
    private static void addCaseStudies(Result r) {
        for (UseCase uc : r.useCases) {
            try {
                SnowflakeClient.SearchResult sr = SnowflakeClient.search(
                    AgenticDemoConfig.CASE_STUDY_SEARCH,
                    uc.name + ' outcomes for a ' + (r.account.Industry == null ? '' : r.account.Industry) + ' company',
                    new List<String>{ 'STUDY_ID', 'TITLE', 'CUSTOMER', 'BODY' },
                    new Map<String, Object>{ '@eq' => new Map<String, Object>{ 'USE_CASE_ID' => uc.useCaseId } },
                    1);
                r.latencyMs += sr.latencyMs;
                if (!sr.results.isEmpty()) {
                    Map<String, Object> hit = sr.results[0];
                    uc.caseStudyId = SnowflakeClient.str(hit, 'STUDY_ID');
                    uc.caseStudyTitle = SnowflakeClient.str(hit, 'TITLE');
                    uc.caseStudyExcerpt = AgentAuditLogger.clip(SnowflakeClient.str(hit, 'BODY'), 700);
                }
                r.evidenceSource = 'Snowflake Cortex Search';
            } catch (Exception e) {
                SnowflakeClient.QueryResult qr = SnowflakeClient.query(CASE_STUDY_SQL, new List<String>{ uc.useCaseId });
                Map<String, String> row = qr.first();
                if (row != null) {
                    uc.caseStudyId = row.get('STUDY_ID');
                    uc.caseStudyTitle = row.get('TITLE');
                    uc.caseStudyExcerpt = row.get('BODY');
                }
                r.evidenceSource = 'Snowflake SQL API (Cortex Search unavailable)';
            }
        }
    }

    /** Six months of credits by workload, for the account plan. */
    public static void addMonthlyTrend(Result r) {
        if (!r.live) {
            return;
        }
        try {
            SnowflakeClient.QueryResult qr = SnowflakeClient.query(MONTHLY_SQL, new List<String>{ r.account.CRM_Score_Ext_Id__c });
            r.latencyMs += qr.latencyMs;
            for (Map<String, String> row : qr.rows) {
                r.monthlyTrend.add(row.get('MONTH') + ' | ' + row.get('WORKLOAD') + ' | ' + row.get('CREDITS'));
            }
        } catch (Exception e) {
            r.monthlyTrend.add('Monthly trend unavailable: ' + e.getMessage());
        }
    }

    /** Writes the snapshot so later calls can fall back to it. Call after all callouts. */
    public static void persist(Result r) {
        if (r == null || !r.live || r.snapshot == null) {
            return;
        }
        Consumption_Snapshot__c existing = latestSnapshot(r.account.Id);
        if (existing != null) {
            r.snapshot.Id = existing.Id;
            if (String.isBlank(r.snapshot.Recommended_Use_Cases__c)) {
                r.snapshot.Recommended_Use_Cases__c = existing.Recommended_Use_Cases__c;
            }
        }
        Database.upsert(r.snapshot, false);
    }

    public static Consumption_Snapshot__c latestSnapshot(Id accountId) {
        List<Consumption_Snapshot__c> rows = [
            SELECT Id, Account__c, As_Of_Date__c, Trailing_12M_Credits__c, YoY_Growth_Pct__c, Last_90D_Growth_Pct__c,
                   Consumption_Trend__c, Annualized_Run_Rate__c, Contract_Annual_Credits__c, Term_End__c,
                   Consumed_In_Term__c, Contract_Utilization_Pct__c, Projected_Term_End_Utilization_Pct__c,
                   Projected_Exhaustion_Date__c, Top_Workload__c, Top_Workload_Share_Pct__c,
                   Fastest_Growing_Workload__c, Fastest_Growth_Pct__c, Declining_Workload__c, Decline_Pct__c,
                   Avg_Daily_Active_Users__c, Recommended_Use_Cases__c, Source__c, Retrieved_At__c, Snowflake_Query_Id__c
            FROM Consumption_Snapshot__c
            WHERE Account__c = :accountId
            ORDER BY Retrieved_At__c DESC NULLS LAST
            LIMIT 1
        ];
        return rows.isEmpty() ? null : rows[0];
    }

    private static void useCache(Result r, Exception e) {
        r.fallbackReason = e.getMessage();
        Consumption_Snapshot__c cached = latestSnapshot(r.account.Id);
        if (cached != null) {
            r.snapshot = cached;
            r.found = true;
            r.source = 'Snowflake (cached ' + (cached.Retrieved_At__c == null ? 'earlier' : cached.Retrieved_At__c.format('yyyy-MM-dd HH:mm')) + ')';
        } else {
            r.source = 'Unavailable';
        }
    }

    @TestVisible
    private static Consumption_Snapshot__c toSnapshot(Id accountId, Map<String, String> row, String queryId) {
        return new Consumption_Snapshot__c(
            Account__c = accountId,
            As_Of_Date__c = SnowflakeClient.day(row, 'AS_OF_DATE'),
            Trailing_12M_Credits__c = SnowflakeClient.num(row, 'TRAILING_12M_CREDITS'),
            YoY_Growth_Pct__c = SnowflakeClient.num(row, 'YOY_GROWTH_PCT'),
            Last_90D_Growth_Pct__c = SnowflakeClient.num(row, 'LAST_90D_GROWTH_PCT'),
            Consumption_Trend__c = row.get('CONSUMPTION_TREND'),
            Annualized_Run_Rate__c = SnowflakeClient.num(row, 'ANNUALIZED_RUN_RATE_CREDITS'),
            Avg_Daily_Active_Users__c = SnowflakeClient.num(row, 'AVG_DAILY_ACTIVE_USERS'),
            Contract_Annual_Credits__c = SnowflakeClient.num(row, 'CONTRACT_ANNUAL_CREDITS'),
            Term_End__c = SnowflakeClient.day(row, 'TERM_END'),
            Consumed_In_Term__c = SnowflakeClient.num(row, 'CONSUMED_IN_TERM_CREDITS'),
            Contract_Utilization_Pct__c = SnowflakeClient.num(row, 'CONTRACT_UTILIZATION_PCT'),
            Projected_Term_End_Utilization_Pct__c = SnowflakeClient.num(row, 'PROJECTED_TERM_END_UTILIZATION_PCT'),
            Projected_Exhaustion_Date__c = SnowflakeClient.day(row, 'PROJECTED_EXHAUSTION_DATE'),
            Top_Workload__c = row.get('TOP_WORKLOAD'),
            Top_Workload_Share_Pct__c = SnowflakeClient.num(row, 'TOP_WORKLOAD_SHARE_PCT'),
            Fastest_Growing_Workload__c = row.get('FASTEST_GROWING_WORKLOAD'),
            Fastest_Growth_Pct__c = SnowflakeClient.num(row, 'FASTEST_GROWTH_PCT'),
            Declining_Workload__c = row.get('DECLINING_WORKLOAD'),
            Decline_Pct__c = SnowflakeClient.num(row, 'DECLINE_PCT'),
            Source__c = 'Snowflake SQL API',
            Retrieved_At__c = Datetime.now(),
            Snowflake_Query_Id__c = queryId
        );
    }

    // ---- text for agents and prompts ----

    public static String describeSummary(Result r) {
        if (!r.found || r.snapshot == null) {
            // The raw reason goes to the audit log; the prompt gets a clean statement.
            return r.account != null && String.isBlank(r.account.CRM_Score_Ext_Id__c)
                ? 'No product telemetry: this account has no platform account key.'
                : 'Product telemetry is unavailable right now: Snowflake could not be reached and there is no cached snapshot yet.';
        }
        Consumption_Snapshot__c s = r.snapshot;
        List<String> lines = new List<String>();
        lines.add('Source: ' + r.source + (s.As_Of_Date__c == null ? '' : '; telemetry as of ' + fmt(s.As_Of_Date__c)) + '.');
        lines.add('Trailing 12 months: ' + n(s.Trailing_12M_Credits__c) + ' credits, ' + signed(s.YoY_Growth_Pct__c)
            + ' year over year. Last 90 days vs prior 90: ' + signed(s.Last_90D_Growth_Pct__c) + ' (' + s.Consumption_Trend__c + ').');
        lines.add('Contract: ' + n(s.Contract_Annual_Credits__c) + ' credits a year, term ends ' + fmt(s.Term_End__c)
            + '. Used ' + n(s.Consumed_In_Term__c) + ' so far (' + pct(s.Contract_Utilization_Pct__c) + ').');
        lines.add('Run rate: ' + n(s.Annualized_Run_Rate__c) + ' credits annualized. Projected use by term end: '
            + pct(s.Projected_Term_End_Utilization_Pct__c) + ' of contract.'
            + exhaustionText(s));
        lines.add('Largest workload: ' + s.Top_Workload__c + ' (' + pct(s.Top_Workload_Share_Pct__c) + ' of the last 90 days).');
        if (s.Fastest_Growing_Workload__c != null) {
            lines.add('Fastest growing: ' + s.Fastest_Growing_Workload__c + ' (' + signed(s.Fastest_Growth_Pct__c) + ' over the prior 90 days).');
        }
        if (s.Declining_Workload__c != null) {
            lines.add('Declining: ' + s.Declining_Workload__c + ' (' + signed(s.Decline_Pct__c) + '). Treat as a risk signal.');
        }
        lines.add('Average daily active users: ' + n(s.Avg_Daily_Active_Users__c) + '.');
        return String.join(lines, '\n');
    }

    private static String exhaustionText(Consumption_Snapshot__c s) {
        if (s.Projected_Exhaustion_Date__c == null || s.Term_End__c == null || s.Projected_Exhaustion_Date__c > s.Term_End__c) {
            return ' Capacity lasts through the term.';
        }
        return ' Capacity runs out around ' + fmt(s.Projected_Exhaustion_Date__c) + ', '
            + s.Projected_Exhaustion_Date__c.daysBetween(s.Term_End__c) + ' days before the term ends.';
    }

    public static String describeUseCases(List<UseCase> useCases, Boolean includeValue) {
        if (useCases == null || useCases.isEmpty()) {
            return 'No peer-based use-case recommendations.';
        }
        List<String> lines = new List<String>();
        for (UseCase uc : useCases) {
            String line = uc.rank + '. ' + uc.name + ' (' + uc.useCaseId + ', ' + uc.businessUnit + '). '
                + uc.peersLive + ' industry peers run it live: ' + uc.peerNames + '. '
                + 'Typical outcome: ' + uc.typicalOutcome + '. Time to value about ' + n(uc.timeToValueWeeks) + ' weeks. '
                + 'Estimated footprint ' + n(uc.estAnnualCredits) + ' credits a year';
            if (includeValue && uc.indicativeValueUsd != null) {
                line += ' (indicative list value ' + usd(uc.indicativeValueUsd) + ', internal only, not a quote)';
            }
            line += '. Prerequisites: ' + uc.prerequisites + '.';
            if (String.isNotBlank(uc.peerOutcomes)) {
                line += ' Peer results: ' + uc.peerOutcomes + '.';
            }
            if (String.isNotBlank(uc.caseStudyTitle)) {
                line += '\n   Case study ' + uc.caseStudyId + ', "' + uc.caseStudyTitle + '": ' + uc.caseStudyExcerpt;
            }
            lines.add(line);
        }
        return String.join(lines, '\n');
    }

    public static String n(Decimal d) {
        return d == null ? 'n/a' : d.setScale(0).format();
    }

    public static String pct(Decimal d) {
        return d == null ? 'n/a' : d.setScale(1).format() + '%';
    }

    public static String signed(Decimal d) {
        if (d == null) {
            return 'n/a';
        }
        return (d >= 0 ? '+' : '') + d.setScale(1).format() + '%';
    }

    public static String usd(Decimal d) {
        return d == null ? 'n/a' : '$' + d.setScale(0).format();
    }

    public static String fmt(Date d) {
        return d == null ? 'n/a' : Datetime.newInstance(d, Time.newInstance(12, 0, 0, 0)).format('MMM d, yyyy');
    }
}
