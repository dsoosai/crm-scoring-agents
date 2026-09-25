# agentforce/

Salesforce side of the Agentic Enterprise demo. The story, demo script and runbook are in [../docs/AGENTFORCE_DEMO.md](../docs/AGENTFORCE_DEMO.md).

```
force-app/main/default/
  aiAuthoringBundles/     Sales_Strategy_Assistant (employee agent), Support_Intake_Agent (service agent), Agent Script
  classes/                Apex actions, Snowflake client, grounding for prompt templates, plan generator, tests
  genAiPromptTemplates/   seven Prompt Builder templates on Claude
  flows/                  Account_Plan_Autofill (record-triggered)
  objects/                Account_Plan__c, Consumption_Snapshot__c, Agent_Audit_Log__c, Case and User fields
  namedCredentials/       Snowflake_API
  externalCredentials/    Snowflake_PAT (the token is added in Setup, never in source)
  permissionsets/         Agentic_Demo_User, Support_Intake_Agent_Access
  queues/ tabs/ layouts/ applications/ notificationtypes/
data/
  generate_demo_data.py   seeded generator for the Snowflake tables and the Omega seed script
  score_omega.py          scores Omega with the champion account model
  build_space_page.py     builds space/agentic.html for the Hugging Face Space
  out/                    the CSVs loaded into Snowflake
  hf_dataset/README.md    card for the Hugging Face dataset
scripts/
  post_deploy_setup.apex  permission sets, queues, scheduling link, Einstein Agent User
  seed_omega.apex         Omega Inc. account, contacts, opportunities, cases and meeting notes
```

Validate the agents locally with the Agent Script compiler, then deploy in three steps: everything except templates and agents, then `genAiPromptTemplates`, then `aiAuthoringBundles`.
