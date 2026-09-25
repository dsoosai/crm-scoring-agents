/**
 * Support agent action: status of a case, only if it belongs to the verified contact.
 */
public without sharing class GetCaseStatus {

    public class Request {
        @InvocableVariable(label='Case Number' description='Case number the customer gives' required=true)
        public String caseNumber;
        @InvocableVariable(label='Contact Id' description='Id of the verified contact' required=true)
        public String contactId;
    }

    public class Response {
        @InvocableVariable(label='Status' description='Case status and last update, or why it cannot be shown')
        public String status;
    }

    @InvocableMethod(label='Get Case Status' description='Returns the status of one of the verified contact cases.' category='Agentic Enterprise')
    public static List<Response> getStatus(List<Request> requests) {
        List<Response> out = new List<Response>();
        for (Request req : requests) {
            Response res = new Response();
            String num = req.caseNumber == null ? '' : req.caseNumber.trim().leftPad(8, '0');
            Id contactId = ConsumptionService.toId(req.contactId);
            List<Case> cs = [SELECT CaseNumber, Subject, Status, Priority, LastModifiedDate, Owner.Name
                             FROM Case WHERE CaseNumber = :num AND ContactId = :contactId LIMIT 1];
            res.status = cs.isEmpty()
                ? 'I cannot find case ' + req.caseNumber + ' on your account.'
                : 'Case ' + cs[0].CaseNumber + ' (' + cs[0].Subject + ') is ' + cs[0].Status + ', priority ' + cs[0].Priority
                    + ', with ' + cs[0].Owner.Name + '. Last updated ' + cs[0].LastModifiedDate.format('MMM d, h:mm a') + '.';
            out.add(res);
        }
        return out;
    }
}
