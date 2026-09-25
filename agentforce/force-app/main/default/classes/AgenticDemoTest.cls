@IsTest
private class AgenticDemoTest {

    private static final String AGENT = 'Sales_Strategy_Assistant';

    @TestSetup
    static void setup() {
        Account a = new Account(Name = 'Omega Inc.', Industry = 'Technology', CRM_Score_Ext_Id__c = 'A-OMEGA',
            Account_Score__c = 94.3, Account_Tier__c = 'A', Score_Model_Version__c = 'account-v12',
            Score_Reasons__c = 'Product usage % 92 (+17)', Score_Updated__c = Datetime.now());
        insert a;
        insert new Contact(AccountId = a.Id, FirstName = 'Marcus', LastName = 'Lee', Title = 'Director, Data Engineering',
            Email = 'marcus.lee@omega-inc.example');
        insert new Contact(AccountId = a.Id, FirstName = 'Chris', LastName = 'Post', Title = 'VP, Revenue Operations',
            Email = 'chris.post@omega-inc.example');
        insert new Opportunity(AccountId = a.Id, Name = 'Omega - FY27 Renewal', StageName = 'Negotiation/Review',
            Amount = 540000, CloseDate = Date.today().addDays(60));
    }

    static Account omega() {
        return [SELECT Id FROM Account WHERE CRM_Score_Ext_Id__c = 'A-OMEGA' LIMIT 1];
    }

    static Contact marcus() {
        return [SELECT Id FROM Contact WHERE Email = 'marcus.lee@omega-inc.example' LIMIT 1];
    }

    @IsTest
    static void findAccountByName() {
        FindAccount.Request req = new FindAccount.Request();
        req.accountName = 'Omega';
        req.agentName = AGENT;
        FindAccount.Response res = FindAccount.find(new List<FindAccount.Request>{ req })[0];
        System.assertEquals(true, res.found);
        System.assertEquals(omega().Id, res.accountId);
        System.assert(res.summary.contains('tier A'), res.summary);
    }

    @IsTest
    static void telemetryLiveWritesSnapshotAndAudit() {
        Test.setMock(HttpCalloutMock.class, new SnowflakeMock('ok'));
        GetConsumptionTelemetry.Request req = new GetConsumptionTelemetry.Request();
        req.accountId = omega().Id;
        req.agentName = AGENT;
        Test.startTest();
        GetConsumptionTelemetry.Response res = GetConsumptionTelemetry.getTelemetry(new List<GetConsumptionTelemetry.Request>{ req })[0];
        Test.stopTest();
        System.assertEquals(true, res.isLive);
        System.assert(res.summary.contains('63,570'), res.summary);
        System.assert(res.signals.contains('Expansion signal'), res.signals);
        System.assertEquals('2026-11-13', res.projectedExhaustionDate);
        System.assertEquals(1, [SELECT COUNT() FROM Consumption_Snapshot__c]);
        Agent_Audit_Log__c log = [SELECT Status__c, Data_Source__c, Snowflake_Query_Id__c FROM Agent_Audit_Log__c LIMIT 1];
        System.assertEquals('Success', log.Status__c);
        System.assertEquals('01b7-test-handle', log.Snowflake_Query_Id__c);
    }

    @IsTest
    static void telemetryFallsBackToCache() {
        insert new Consumption_Snapshot__c(Account__c = omega().Id, Trailing_12M_Credits__c = 60000, Contract_Utilization_Pct__c = 80,
            Retrieved_At__c = Datetime.now().addHours(-2), Consumption_Trend__c = 'Growing', Top_Workload__c = 'Data Engineering');
        Test.setMock(HttpCalloutMock.class, new SnowflakeMock('down'));
        GetConsumptionTelemetry.Request req = new GetConsumptionTelemetry.Request();
        req.accountId = omega().Id;
        req.agentName = AGENT;
        Test.startTest();
        GetConsumptionTelemetry.Response res = GetConsumptionTelemetry.getTelemetry(new List<GetConsumptionTelemetry.Request>{ req })[0];
        Test.stopTest();
        System.assertEquals(false, res.isLive);
        System.assert(res.source.startsWith('Snowflake (cached'), res.source);
        System.assertEquals('Fallback', [SELECT Status__c FROM Agent_Audit_Log__c LIMIT 1].Status__c);
    }

    @IsTest
    static void recommendUseCasesWithCaseStudy() {
        Test.setMock(HttpCalloutMock.class, new SnowflakeMock('ok'));
        RecommendUseCases.Request req = new RecommendUseCases.Request();
        req.accountId = omega().Id;
        req.agentName = AGENT;
        Test.startTest();
        RecommendUseCases.Response res = RecommendUseCases.recommend(new List<RecommendUseCases.Request>{ req })[0];
        Test.stopTest();
        System.assertEquals('Predictive Lead and Account Scoring', res.topUseCase);
        System.assert(res.recommendations.contains('CS-01'), res.recommendations);
        System.assert(res.source.contains('Cortex Search'), res.source);
    }

    @IsTest
    static void recommendUseCasesWithoutCortexSearch() {
        Test.setMock(HttpCalloutMock.class, new SnowflakeMock('noSearch'));
        RecommendUseCases.Request req = new RecommendUseCases.Request();
        req.accountId = omega().Id;
        Test.startTest();
        RecommendUseCases.Response res = RecommendUseCases.recommend(new List<RecommendUseCases.Request>{ req })[0];
        Test.stopTest();
        System.assert(res.recommendations.contains('Northwind lead scoring'), res.recommendations);
    }

    @IsTest
    static void askSnowflakeAnalyst() {
        Test.setMock(HttpCalloutMock.class, new SnowflakeMock('ok'));
        AskSnowflakeAnalyst.Request req = new AskSnowflakeAnalyst.Request();
        req.question = 'Which workload grew fastest?';
        req.accountName = 'Omega Inc.';
        req.agentName = AGENT;
        Test.startTest();
        AskSnowflakeAnalyst.Response res = AskSnowflakeAnalyst.ask(new List<AskSnowflakeAnalyst.Request>{ req })[0];
        Test.stopTest();
        System.assert(res.answer.contains('282'), res.answer);
        System.assertEquals('SELECT 1', res.generatedSql);
    }

    @IsTest
    static void createAccountPlanRunsGrounding() {
        Test.setMock(HttpCalloutMock.class, new SnowflakeMock('ok'));
        CreateAccountPlan.Request req = new CreateAccountPlan.Request();
        req.accountId = omega().Id;
        req.agentName = AGENT;
        Test.startTest();
        CreateAccountPlan.Response res = CreateAccountPlan.create(new List<CreateAccountPlan.Request>{ req })[0];
        AccountPlanGenerator.Request start = new AccountPlanGenerator.Request();
        start.planId = res.planId;
        AccountPlanGenerator.start(new List<AccountPlanGenerator.Request>{ start });
        Test.stopTest();
        Account_Plan__c plan = [SELECT Status__c, Grounding_Snapshot__c, Grounding_Source__c FROM Account_Plan__c WHERE Id = :res.planId];
        System.assertEquals('Drafting', plan.Status__c);
        System.assert(plan.Grounding_Snapshot__c.contains('RECOMMENDED USE CASES'), plan.Grounding_Snapshot__c);

        CreateAccountPlan.Response again = CreateAccountPlan.create(new List<CreateAccountPlan.Request>{ req })[0];
        System.assertEquals(res.planId, again.planId, 'Second request returns the plan in flight');
    }

    @IsTest
    static void finalStageMarksPlanReady() {
        Account_Plan__c plan = new Account_Plan__c(Name = 'Omega FY27', Account__c = omega().Id, Fiscal_Year__c = 'FY27', Status__c = 'Drafting',
            Grounding_Snapshot__c = 'TELEMETRY: test', Grounding_Source__c = 'test');
        insert plan;
        Test.startTest();
        System.enqueueJob(new AccountPlanGenerator(plan.Id, 4));
        Test.stopTest();
        plan = [SELECT Status__c, Sections_Completed__c, Account_Vision__c FROM Account_Plan__c WHERE Id = :plan.Id];
        System.assertEquals('Ready for Review', plan.Status__c);
        System.assertEquals(5, plan.Sections_Completed__c);
        System.assert(plan.Account_Vision__c.contains('Plan_Vision'));

        AccountPlanContext.Request ctx = new AccountPlanContext.Request();
        ctx.planId = plan.Id;
        String prompt = AccountPlanContext.build(new List<AccountPlanContext.Request>{ ctx })[0].Prompt;
        System.assert(prompt.contains('SNOWFLAKE GROUNDING'), prompt);

        GetAccountPlanStatus.Request st = new GetAccountPlanStatus.Request();
        st.accountId = omega().Id;
        System.assertEquals('Ready for Review', GetAccountPlanStatus.getStatus(new List<GetAccountPlanStatus.Request>{ st })[0].status);
    }

    @IsTest
    static void groundingProvidersBuildPrompts() {
        Test.setMock(HttpCalloutMock.class, new SnowflakeMock('ok'));
        Test.startTest();
        AccountBriefContext.Request b = new AccountBriefContext.Request();
        b.accountId = omega().Id;
        String brief = AccountBriefContext.build(new List<AccountBriefContext.Request>{ b })[0].Prompt;
        OutreachContext.Request o = new OutreachContext.Request();
        o.accountId = omega().Id;
        o.contactName = 'Chris Post';
        String outreach = OutreachContext.build(new List<OutreachContext.Request>{ o })[0].Prompt;
        Test.stopTest();
        System.assert(brief.contains('PRODUCT TELEMETRY'), brief);
        System.assert(outreach.contains('first name Chris'), outreach);
    }

    @IsTest
    static void salesGuardrailsAndDrafts() {
        Id accountId = omega().Id;
        RequestDealDeskReview.Request dd = new RequestDealDeskReview.Request();
        dd.accountId = accountId;
        dd.requestSummary = '15 percent discount on the FY27 renewal';
        dd.agentName = AGENT;
        RequestDealDeskReview.Response ddr = RequestDealDeskReview.request(new List<RequestDealDeskReview.Request>{ dd })[0];
        System.assertNotEquals(null, ddr.caseNumber);
        System.assertEquals('Blocked', [SELECT Status__c FROM Agent_Audit_Log__c WHERE Action__c = 'Request Deal Desk Review'].Status__c);

        SaveOutreachDraft.Request sd = new SaveOutreachDraft.Request();
        sd.accountId = accountId;
        sd.contactName = 'Chris Post';
        sd.emailDraft = 'Subject: Scoring ideas\nHi Chris,';
        sd.agentName = AGENT;
        SaveOutreachDraft.save(new List<SaveOutreachDraft.Request>{ sd });
        System.assertEquals('Review and send: Scoring ideas', [SELECT Subject FROM Task LIMIT 1].Subject);

        RecordAgentFeedback.Request fb = new RecordAgentFeedback.Request();
        fb.rating = 'Helpful';
        fb.comment = 'Great brief';
        fb.agentName = AGENT;
        RecordAgentFeedback.record(new List<RecordAgentFeedback.Request>{ fb });
        System.assertEquals(1, [SELECT COUNT() FROM Agent_Audit_Log__c WHERE Feedback__c = 'Helpful']);

        ExplainAccountScore.Request ex = new ExplainAccountScore.Request();
        ex.accountId = accountId;
        System.assert(ExplainAccountScore.explain(new List<ExplainAccountScore.Request>{ ex })[0].explanation.contains('94.3'));
    }

    @IsTest
    static void supportIntakeEndToEnd() {
        Test.setMock(HttpCalloutMock.class, new SnowflakeMock('ok'));
        // Callouts first: Apex does not allow a callout after uncommitted DML in the same transaction.
        Test.startTest();
        SearchSupportKnowledge.Request s = new SearchSupportKnowledge.Request();
        s.issue = 'Dashboards queue for 20 minutes at month-end close';
        s.productArea = 'Performance';
        SearchSupportKnowledge.Response sr = SearchSupportKnowledge.search(new List<SearchSupportKnowledge.Request>{ s })[0];
        Test.stopTest();
        System.assertEquals('KB-1001', sr.topArticleId);

        VerifySupportContact.Request v = new VerifySupportContact.Request();
        v.email = 'Marcus.Lee@omega-inc.example ';
        VerifySupportContact.Response vr = VerifySupportContact.verify(new List<VerifySupportContact.Request>{ v })[0];
        System.assertEquals(true, vr.found);
        System.assertEquals('Priority', vr.supportTier);

        CreateSupportCase.Request c = new CreateSupportCase.Request();
        c.contactId = vr.contactId;
        c.subject = 'Month-end queuing on BI_WH';
        c.description = 'Dashboards queue for 20 minutes.';
        c.productArea = 'Performance';
        c.severity = 'High';
        c.kbArticleId = 'KB-1001';
        c.resolvedByAgent = false;
        CreateSupportCase.Response cr = CreateSupportCase.create(new List<CreateSupportCase.Request>{ c })[0];
        System.assertEquals('Tier 2 Support', cr.routedTo, 'High severity on a tier A account goes to Tier 2');
        CreateSupportCase.Response dup = CreateSupportCase.create(new List<CreateSupportCase.Request>{ c })[0];
        System.assertEquals('Existing case', dup.routedTo);

        GetCaseStatus.Request g = new GetCaseStatus.Request();
        g.caseNumber = cr.caseNumber;
        g.contactId = vr.contactId;
        System.assert(GetCaseStatus.getStatus(new List<GetCaseStatus.Request>{ g })[0].status.contains(cr.caseNumber));

        CreateSupportCase.Request solved = new CreateSupportCase.Request();
        solved.contactId = vr.contactId;
        solved.subject = 'SSO group sync';
        solved.description = 'Fixed by the article.';
        solved.severity = 'Low';
        solved.resolvedByAgent = true;
        solved.kbArticleId = 'KB-1005';
        System.assertEquals('Closed, resolved by agent', CreateSupportCase.create(new List<CreateSupportCase.Request>{ solved })[0].routedTo);

        RouteSalesInquiry.Request r = new RouteSalesInquiry.Request();
        r.contactId = vr.contactId;
        r.inquiry = 'Can we get a discount on renewal?';
        System.assert(RouteSalesInquiry.route(new List<RouteSalesInquiry.Request>{ r })[0].message.contains('account team'));
    }

    @IsTest
    static void knowledgeFallsBackToKeywordSearch() {
        Test.setMock(HttpCalloutMock.class, new SnowflakeMock('noSearch'));
        SearchSupportKnowledge.Request s = new SearchSupportKnowledge.Request();
        s.issue = 'Warehouse queuing during month-end close';
        Test.startTest();
        SearchSupportKnowledge.Response sr = SearchSupportKnowledge.search(new List<SearchSupportKnowledge.Request>{ s })[0];
        Test.stopTest();
        System.assertEquals(true, sr.found);
        System.assert(sr.source.contains('keyword'), sr.source);
    }

    @IsTest
    static void richTextConversions() {
        String html = RichText.toHtml('```html\n<p>Hi</p>\n```');
        System.assertEquals('<p>Hi</p>', html);
        String md = RichText.toHtml('## Title\n- **One**\n- Two\nDone');
        System.assert(md.contains('<ul><li><b>One</b></li><li>Two</li></ul>'), md);
        System.assertEquals('- One', RichText.toPlain('<ul><li>One</li></ul>'));
    }
}
