@IsTest
private class ScoreExplainActionTest {

    @IsTest
    static void explainsScoredAccount() {
        Account a = new Account(
            Name = 'Summit Retail 0001',
            Account_Score__c = 82.5,
            Account_Tier__c = 'A',
            Score_Model_Version__c = 'account-v12',
            Score_Reasons__c = 'Product usage % 91 (+18); Open opportunities 2 (+6)',
            Score_Updated__c = Datetime.newInstanceGmt(2026, 9, 30, 12, 0, 0)
        );
        insert a;
        List<ScoreExplainAction.Response> res = ScoreExplainAction.explain(requests(a.Id));
        System.assertEquals(1, res.size());
        System.assert(res[0].explanation.contains('tier A'), res[0].explanation);
        System.assert(res[0].explanation.contains('account-v12'), res[0].explanation);
        System.assert(res[0].explanation.contains('2026-09-30'), res[0].explanation);
    }

    @IsTest
    static void explainsUnscoredLead() {
        Lead l = new Lead(LastName = 'Contact 24011', Company = 'Harbor Labs 0042');
        insert l;
        List<ScoreExplainAction.Response> res = ScoreExplainAction.explain(requests(l.Id));
        System.assert(res[0].explanation.contains('has not been scored yet'), res[0].explanation);
    }

    @IsTest
    static void handlesMissingRecord() {
        Account a = new Account(Name = 'Temp');
        insert a;
        Id gone = a.Id;
        delete a;
        List<ScoreExplainAction.Response> res = ScoreExplainAction.explain(requests(gone));
        System.assert(res[0].explanation.startsWith('No Account or Lead'), res[0].explanation);
    }

    private static List<ScoreExplainAction.Request> requests(Id recordId) {
        ScoreExplainAction.Request r = new ScoreExplainAction.Request();
        r.recordId = recordId;
        return new List<ScoreExplainAction.Request>{ r };
    }
}
