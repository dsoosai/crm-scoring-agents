# Live setup

Local mode needs nothing. This guide adds the real systems one at a time. Each step works on its own, so stop wherever you like.

Order: GitHub, Hugging Face Space, Salesforce, Snowflake, then GitHub Actions.

Snowflake is optional. Without it, DuckDB stays the warehouse and every other step works.

## 1. GitHub

```bash
cd crm-scoring-agents
git add -A && git commit -m "CRM scoring agents: lifecycle, MCP, A2A"
gh repo create dsoosai/crm-scoring-agents --public --source . --push
```

CI runs the tests and a full replay on every push, and uploads the dashboard as a build artifact.

## 2. Hugging Face Space (the shareable dashboard)

1. Create a write token at huggingface.co, Settings, Access Tokens.
2. Log in and publish:

```bash
.venv/bin/pip install -U huggingface_hub
.venv/bin/hf auth login
make demo && make space
```

The Space is static, so it costs nothing and never sleeps. To publish from GitHub instead, add the token as the `HF_TOKEN` repository secret and set the `HF_SPACE` variable to `dsoosai/crm-scoring-agents`. The `space` workflow publishes whenever `space/` changes on `main`.

## 3. Salesforce Developer Edition

A free Developer Edition org now includes Agentforce, Data 360 and Salesforce Hosted MCP Servers.

1. Sign up at developer.salesforce.com/signup.
2. Install the Salesforce CLI and log in:

```bash
npm install -g @salesforce/cli
sf org login web --alias crm-dev
```

   Run this on your own machine. The login opens a browser and needs a direct connection to salesforce.com, so it fails in sandboxes and cloud shells.

3. Deploy the fields, permission set and Apex action, and assign the permission set to yourself:

```bash
make sf-deploy
```

4. Pick an auth method for the agents.

   Quick start: username, password and security token. Reset the token from your personal settings; it arrives by email.

   ```bash
   export SF_USERNAME=you@example.com SF_PASSWORD='...' SF_SECURITY_TOKEN='...'
   ```

   Preferred: JWT bearer through an External Client App with a certificate. Set `SF_USERNAME`, `SF_CONSUMER_KEY` and `SF_PRIVATE_KEY_FILE`. Salesforce is retiring the SOAP login used by the quick start, so move to JWT before relying on this.

   No CLI? Use Workbench instead. Log in at workbench.developerforce.com with your org, open Migration, Deploy, choose `salesforce/deploy/metadata.zip`, tick "Single Package" and "Rollback On Error", set the test level to "RunSpecifiedTests" with `ScoreExplainActionTest`, and deploy. Then assign the `CRM_Score_Agent` permission set to yourself in Setup.

   On the Workbench login page, pick the newest API version your org supports (`/services/data/` on your org lists them). A version the org does not support fails the login and signs you out of Salesforce.

5. Seed a small sample (Developer Edition storage is small) and run a cycle that writes to the org:

```bash
make demo-live
.venv/bin/crm-agent sf-seed --accounts 300 --leads 500
CRM_TARGET=salesforce .venv/bin/crm-agent cycle lead 2026-09
CRM_TARGET=salesforce .venv/bin/crm-agent cycle account 2026Q3 --approve --approver "Your name, RevOps"
```

The agents only update records that carry `CRM_Score_Ext_Id__c`. They never create records in the org.

6. Build the Agentforce action: [salesforce/AGENTFORCE_SETUP.md](../salesforce/AGENTFORCE_SETUP.md).

## 4. Snowflake trial (optional, the partner warehouse)

1. Start a trial at signup.snowflake.com. Any cloud and region.
2. Make a key pair on your Mac:

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out ~/.ssh/crm_agent_rsa.p8 -nocrypt
openssl rsa -in ~/.ssh/crm_agent_rsa.p8 -pubout -out ~/.ssh/crm_agent_rsa.pub
```

3. In a Snowsight worksheet, run `snowflake/setup.sql`. Then paste the public key body (without the BEGIN and END lines) into the `ALTER USER ... SET RSA_PUBLIC_KEY` line and run it.
4. Point the agents at Snowflake and replay:

```bash
.venv/bin/pip install -e ".[snowflake]"
export CRM_WAREHOUSE=snowflake
export SNOWFLAKE_ACCOUNT=<your account identifier, for example abc12345.us-east-1>
export SNOWFLAKE_USER=CRM_AGENT_SVC
export SNOWFLAKE_PRIVATE_KEY_FILE=~/.ssh/crm_agent_rsa.p8
.venv/bin/crm-agent simulate
```

5. Run `snowflake/views.sql` for `SCORES_LATEST`, `CHAMPION_HISTORY` and `AGENT_ACTIONS`.

In Snowflake mode the registry, drift reports, scores and audit log all live in `CRM_SCORING.LIFECYCLE`. Model artifacts are stored in the registry table, so any machine can load the champion. The MCP server and the A2A agents can run at the same time.

## 5. Linking Salesforce and Snowflake

What is built: the agents read features from Snowflake and write scores to both Snowflake (`SCORES`) and Salesforce (Account and Lead fields).

What to discuss, not built: Data 360 zero-copy federation could read `SCORES_LATEST` straight from Snowflake, so Salesforce sees scores without a write-back job. Check that the Snowflake connector is enabled in your Developer Edition org before promising it.

## 6. GitHub Actions for live cycles

Add repository secrets: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_PRIVATE_KEY` (the `.p8` contents), `SF_USERNAME`, plus either `SF_CONSUMER_KEY` and `SF_PRIVATE_KEY` or `SF_PASSWORD` and `SF_SECURITY_TOKEN`. Create an environment called `live`.

Then run the `lifecycle` workflow from the Actions tab. Tick "approve" for an account cycle and your GitHub name becomes the approver in the audit log. The monthly and quarterly schedules are in the workflow, commented out until new periods land in Snowflake on their own.

## 7. Optional: an LLM writes the cycle summary

Set `ANTHROPIC_API_KEY` or `HF_TOKEN`. The summary changes; the decisions do not.
