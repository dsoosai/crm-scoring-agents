/**
 * Audit trail for every agent action. Entries are buffered and written once at the end of the
 * action, after any callouts, because Apex does not allow a callout after uncommitted DML.
 */
public inherited sharing class AgentAuditLogger {

    private static List<Agent_Audit_Log__c> pending = new List<Agent_Audit_Log__c>();

    public class Entry {
        private final Agent_Audit_Log__c log;
        private final Long started;

        public Entry(String agent, String action) {
            log = new Agent_Audit_Log__c(
                Agent__c = clip(agent, 80),
                Action__c = clip(action, 80),
                Status__c = 'Success',
                Data_Source__c = 'Salesforce');
            started = System.currentTimeMillis();
        }

        public Entry account(Id accountId) { log.Account__c = accountId; return this; }
        public Entry recordId(String rid) { log.Record_Id__c = clip(rid, 18); return this; }
        public Entry inputs(Object value) { log.Inputs__c = clip(value instanceof String ? (String) value : JSON.serialize(value), 32000); return this; }
        public Entry output(String value) { log.Output_Summary__c = clip(value, 32000); return this; }
        public Entry source(String value) { log.Data_Source__c = clip(value, 80); return this; }
        public Entry queryId(String value) { log.Snowflake_Query_Id__c = clip(value, 100); return this; }
        public Entry model(String value) { log.Model__c = clip(value, 100); return this; }
        public Entry fallback(String reason) { log.Status__c = 'Fallback'; log.Guardrail__c = clip(reason, 255); return this; }
        public Entry blocked(String guardrail) { log.Status__c = 'Blocked'; log.Guardrail__c = clip(guardrail, 255); return this; }
        public Entry error(String message) { log.Status__c = 'Error'; log.Guardrail__c = clip(message, 255); return this; }
        public Entry guardrail(String note) { log.Guardrail__c = clip(note, 255); return this; }

        /** Stops the clock and queues the row. Call flush() once all callouts are done. */
        public Agent_Audit_Log__c done() {
            log.Latency_Ms__c = System.currentTimeMillis() - started;
            pending.add(log);
            return log;
        }
    }

    public static Entry start(String agent, String action) {
        return new Entry(String.isBlank(agent) ? 'Unknown agent' : agent, action);
    }

    public static void flush() {
        if (pending.isEmpty()) {
            return;
        }
        List<Agent_Audit_Log__c> rows = pending.clone();
        pending.clear();
        Database.insert(rows, false);
    }

    public static String clip(String value, Integer maxLength) {
        if (value == null) {
            return null;
        }
        return value.length() <= maxLength ? value : value.left(maxLength - 3) + '...';
    }
}
