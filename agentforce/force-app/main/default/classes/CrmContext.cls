/**
 * Plain-text CRM context for one account: profile, CRM score, people, pipeline, recent activity and
 * open cases. Used to ground prompt templates. Respects the running user's sharing.
 */
public with sharing class CrmContext {

    public static String forAccount(Id accountId) {
        List<Account> accounts = [
            SELECT Id, Name, Industry, Type, NumberOfEmployees, AnnualRevenue, BillingCity, BillingState, Description,
                   Owner.Name, Account_Score__c, Account_Tier__c, Score_Model_Version__c, Score_Reasons__c, Score_Updated__c
            FROM Account WHERE Id = :accountId LIMIT 1
        ];
        if (accounts.isEmpty()) {
            return 'Account not found or not visible to the running user.';
        }
        Account a = accounts[0];
        List<String> lines = new List<String>();
        lines.add('ACCOUNT: ' + a.Name + '. ' + nz(a.Type) + ', ' + nz(a.Industry) + ', '
            + (a.NumberOfEmployees == null ? 'n/a' : a.NumberOfEmployees.format()) + ' employees, annual revenue '
            + (a.AnnualRevenue == null ? 'n/a' : '$' + a.AnnualRevenue.format()) + ', ' + nz(a.BillingCity) + ' ' + nz(a.BillingState)
            + '. Account owner: ' + a.Owner.Name + '.');
        if (String.isNotBlank(a.Description)) {
            lines.add('ABOUT: ' + a.Description);
        }
        if (a.Account_Score__c != null) {
            lines.add('CRM SCORE: ' + a.Account_Score__c.setScale(1) + ' of 100, tier ' + a.Account_Tier__c + ', model ' + a.Score_Model_Version__c
                + '. Top reasons: ' + nz(a.Score_Reasons__c) + '.');
        }

        lines.add('CONTACTS:');
        for (Contact c : [SELECT Name, Title, Description FROM Contact WHERE AccountId = :accountId ORDER BY CreatedDate LIMIT 8]) {
            lines.add('- ' + c.Name + ', ' + nz(c.Title) + (String.isBlank(c.Description) ? '' : '. ' + c.Description));
        }

        lines.add('OPPORTUNITIES:');
        for (Opportunity o : [SELECT Name, StageName, Amount, CloseDate, Probability, IsClosed, Description FROM Opportunity
                              WHERE AccountId = :accountId ORDER BY IsClosed, CloseDate DESC LIMIT 8]) {
            lines.add('- ' + o.Name + ' | ' + o.StageName + ' | ' + (o.Amount == null ? 'n/a' : '$' + o.Amount.format())
                + ' | close ' + String.valueOf(o.CloseDate) + (o.IsClosed ? '' : ' | ' + o.Probability + '% probability')
                + (String.isBlank(o.Description) ? '' : ' | ' + o.Description));
        }

        lines.add('RECENT ACTIVITY:');
        for (Task t : [SELECT Subject, ActivityDate, Description, Who.Name FROM Task
                       WHERE WhatId = :accountId ORDER BY ActivityDate DESC NULLS LAST LIMIT 5]) {
            lines.add('- ' + String.valueOf(t.ActivityDate) + ' ' + t.Subject + (t.Who == null ? '' : ' (with ' + t.Who.Name + ')')
                + (String.isBlank(t.Description) ? '' : ': ' + t.Description));
        }

        lines.add('SUPPORT CASES:');
        for (Case c : [SELECT CaseNumber, Subject, Priority, Status, Product_Area__c, Description FROM Case
                       WHERE AccountId = :accountId ORDER BY IsClosed, CreatedDate DESC LIMIT 6]) {
            lines.add('- ' + c.CaseNumber + ' ' + c.Subject + ' | ' + c.Priority + ' | ' + c.Status + ' | ' + nz(c.Product_Area__c)
                + (String.isBlank(c.Description) ? '' : ' | ' + AgentAuditLogger.clip(c.Description, 240)));
        }
        return String.join(lines, '\n');
    }

    private static String nz(String s) {
        return String.isBlank(s) ? 'n/a' : s;
    }
}
