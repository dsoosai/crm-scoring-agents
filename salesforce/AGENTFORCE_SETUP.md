# Agentforce: "Score Advisor"

A small agent that lets a rep ask why an account or lead scored what it did. It reads the fields the scoring agents write. It never changes a score.

## What gets deployed

`make sf-deploy` from the repo root deploys:

| Metadata | Purpose |
| --- | --- |
| 6 fields on Account | `CRM_Score_Ext_Id__c`, `Account_Score__c`, `Account_Tier__c`, `Score_Model_Version__c`, `Score_Reasons__c`, `Score_Updated__c` |
| 6 fields on Lead | Same, with `Lead_Score__c` and `Lead_Grade__c` |
| Permission set `CRM_Score_Agent` | Field access and the Apex action. Assign to the integration user and the agent user. |
| Apex `ScoreExplainAction` | Invocable action "Explain CRM Score". Runs with sharing. |
| Apex `ScoreExplainActionTest` | Three tests, run on deploy |

## Build the agent

Menu names shift between releases. These are the steps in a current Developer Edition org.

1. Setup, search for Agentforce Agents, create a new agent from the employee agent template. Name it Score Advisor.
2. Add a topic named **CRM Score Questions**.
   - Classification description: Questions about an account's score or tier, or a lead's score or grade, and why it has that value.
   - Scope: Explain existing CRM scores. Do not change scores, tiers or grades. Do not predict outcomes beyond what the score says.
   - Instructions:
     1. If the user is on an Account or Lead record, use that record. Otherwise find the record by name first.
     2. Call Explain CRM Score with the record Id.
     3. Answer in two or three sentences: the score, the tier or grade, and the top reasons in plain words.
     4. Say which model version produced it and when it was scored.
     5. If the record has not been scored, say so. Do not guess.
     6. If asked to change a score, explain that scores come from the scoring model and suggest raising it with RevOps.
3. Add actions to the topic:
   - **Explain CRM Score** (Apex, from `ScoreExplainAction`).
   - The standard action that identifies a record by name, so users can ask about an account without opening it.
4. Assign the `CRM_Score_Agent` permission set to the agent's running user.
5. Activate, then test in the builder's conversation preview:
   - Open a seeded account and ask "Why is this account tier A?"
   - "What is driving this lead's grade?"
   - "Can you bump this account to tier A?" (the agent should decline and point to RevOps)

## Why the action is Apex, not a prompt

The action is deterministic. It reads fields and formats them. The agent's reasoning decides when to call it and how to phrase the answer. That split keeps the factual part testable, which is the same line the scoring agents draw: gates decide, the LLM narrates.

## Talking points

- Sharing is enforced. The agent sees only records its running user can see.
- The scores are written by an external lifecycle. Salesforce shows the model version on every record, so a rep's question can be traced to a model card.
- With Salesforce Hosted MCP Servers in the same org, an MCP client can hold both the org's data and the scoring lifecycle's tools in one conversation.
