// Agentic Enterprise demo: one-time setup after the metadata deploy.
// Run as the demo admin in Workbench (Utilities > Apex Execute) or the Developer Console.
// Setup objects only (users, permission sets, queue members), so there is no mixed-DML error.
// Safe to re-run.

String schedulingLink = 'https://meet.example.com/daniel-soosai/30min'; // replace with your own link

Id me = UserInfo.getUserId();

// 1. Permission sets for the demo admin: the app and actions, plus Prompt Builder.
Set<String> mine = new Set<String>{ 'Agentic_Demo_User', 'EinsteinGPTPromptTemplateManager', 'EinsteinGPTPromptTemplateUser' };
Set<Id> already = new Set<Id>();
for (PermissionSetAssignment a : [SELECT PermissionSetId FROM PermissionSetAssignment WHERE AssigneeId = :me]) {
    already.add(a.PermissionSetId);
}
List<PermissionSetAssignment> psas = new List<PermissionSetAssignment>();
for (PermissionSet ps : [SELECT Id, Name FROM PermissionSet WHERE Name IN :mine]) {
    if (!already.contains(ps.Id)) {
        psas.add(new PermissionSetAssignment(AssigneeId = me, PermissionSetId = ps.Id));
    }
}
Database.insert(psas, false);

// 2. Scheduling link used by the outreach email template. Set dynamically: anonymous Apex compiles
//    with your field permissions, and the field is visible only once the permission set above applies.
User meRecord = new User(Id = me);
meRecord.put('Scheduling_Link__c', schedulingLink);
update meRecord;

// 3. Put the admin in the demo queues so queue list views show the routed cases.
List<GroupMember> members = new List<GroupMember>();
for (Group g : [SELECT Id FROM Group WHERE Type = 'Queue' AND DeveloperName IN ('Tier_1_Support', 'Tier_2_Support', 'Deal_Desk')]) {
    members.add(new GroupMember(GroupId = g.Id, UserOrGroupId = me));
}
Database.insert(members, false);

// 4. Einstein Agent User that runs the Support Intake Agent (a service agent).
String agentUsername = 'support.intake.agent.' + UserInfo.getOrganizationId().left(15).toLowerCase() + '@agentforce.demo';
List<User> existing = [SELECT Id FROM User WHERE Username = :agentUsername LIMIT 1];
Id agentUserId;
if (existing.isEmpty()) {
    Profile p = [SELECT Id FROM Profile WHERE Name = 'Einstein Agent User' LIMIT 1];
    User u = new User(
        Username = agentUsername,
        LastName = 'Support Intake Agent',
        Email = UserInfo.getUserEmail(),
        Alias = 'sia',
        TimeZoneSidKey = 'America/Los_Angeles',
        LocaleSidKey = 'en_US',
        EmailEncodingKey = 'UTF-8',
        LanguageLocaleKey = 'en_US',
        ProfileId = p.Id);
    insert u;
    agentUserId = u.Id;
} else {
    agentUserId = existing[0].Id;
}
List<PermissionSetAssignment> agentPsas = new List<PermissionSetAssignment>();
for (PermissionSet ps : [SELECT Id FROM PermissionSet WHERE Name IN ('AgentforceServiceAgentUser', 'Support_Intake_Agent_Access')]) {
    agentPsas.add(new PermissionSetAssignment(AssigneeId = agentUserId, PermissionSetId = ps.Id));
}
Database.insert(agentPsas, false);

System.debug('AGENT_USER=' + agentUsername);
System.debug('Put this username in access.default_agent_user of Support_Intake_Agent.agent before deploying the agent.');
