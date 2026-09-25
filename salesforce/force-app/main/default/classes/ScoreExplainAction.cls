/**
 * Agentforce action: explain the current CRM score on an Account or Lead.
 *
 * Deterministic on purpose. The agent's LLM decides when to call it and how to
 * phrase the answer; this class only reads what the scoring agents wrote.
 * Runs with sharing, so the agent sees only records its running user can see.
 */
public with sharing class ScoreExplainAction {

    public class Request {
        @InvocableVariable(label='Record Id' description='Id of the Account or Lead to explain' required=true)
        public Id recordId;
    }

    public class Response {
        @InvocableVariable(label='Explanation' description='Score, tier, model version, top reasons and when it was scored')
        public String explanation;
    }

    @InvocableMethod(
        label='Explain CRM Score'
        description='Returns the current score, tier, model version and top reasons for an Account or Lead.'
        category='CRM Scoring')
    public static List<Response> explain(List<Request> requests) {
        Set<Id> accountIds = new Set<Id>();
        Set<Id> leadIds = new Set<Id>();
        for (Request r : requests) {
            if (r == null || r.recordId == null) {
                continue;
            }
            if (r.recordId.getSObjectType() == Account.SObjectType) {
                accountIds.add(r.recordId);
            } else if (r.recordId.getSObjectType() == Lead.SObjectType) {
                leadIds.add(r.recordId);
            }
        }

        Map<Id, Account> accounts = new Map<Id, Account>([
            SELECT Id, Name, Account_Score__c, Account_Tier__c, Score_Model_Version__c,
                   Score_Reasons__c, Score_Updated__c
            FROM Account WHERE Id IN :accountIds
        ]);
        Map<Id, Lead> leads = new Map<Id, Lead>([
            SELECT Id, Name, Company, Lead_Score__c, Lead_Grade__c, Score_Model_Version__c,
                   Score_Reasons__c, Score_Updated__c
            FROM Lead WHERE Id IN :leadIds
        ]);

        List<Response> out = new List<Response>();
        for (Request r : requests) {
            Response res = new Response();
            Id rid = (r == null) ? null : r.recordId;
            if (rid != null && accounts.containsKey(rid)) {
                Account a = accounts.get(rid);
                res.explanation = describe(a.Name, 'tier', a.Account_Score__c, a.Account_Tier__c,
                    a.Score_Model_Version__c, a.Score_Reasons__c, a.Score_Updated__c);
            } else if (rid != null && leads.containsKey(rid)) {
                Lead l = leads.get(rid);
                res.explanation = describe(l.Name + ' (' + l.Company + ')', 'grade', l.Lead_Score__c, l.Lead_Grade__c,
                    l.Score_Model_Version__c, l.Score_Reasons__c, l.Score_Updated__c);
            } else {
                res.explanation = 'No Account or Lead found for that Id, or you do not have access to it.';
            }
            out.add(res);
        }
        return out;
    }

    @TestVisible
    private static String describe(String name, String tierWord, Decimal score, String tier,
                                   String version, String reasons, Datetime updated) {
        if (score == null) {
            return name + ' has not been scored yet.';
        }
        String s = name + ' scores ' + score.setScale(1) + ' out of 100 (' + tierWord + ' ' + tier + ') on model ' + version + '.';
        if (String.isNotBlank(reasons)) {
            s += ' What lifted it most: ' + reasons + '.';
        }
        if (updated != null) {
            s += ' Last scored ' + updated.formatGmt('yyyy-MM-dd') + '.';
        }
        return s;
    }
}
