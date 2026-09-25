# Demo talk track

Seven minutes. The dashboard carries the story; the live run proves it is real. Read numbers off your own dashboard on the day. The ones below come from the pinned libraries.

## Before you walk in

- [ ] `make demo-live` on the laptop you will present from. Then `make a2a` in one terminal.
- [ ] `space/index.html` open in a browser tab. The Hugging Face Space as a backup: https://huggingface.co/spaces/dsoosai/crm-scoring-agents
- [ ] Second terminal ready at the repo root.
- [ ] If live mode is set up: the Salesforce org open on a seeded Account.
- [ ] Wi-Fi off test: everything above runs offline.

## 1. The problem (30 seconds)

> A scoring model starts rotting the day it ships. Marketing changes a campaign, a new segment lands, what drives expansion shifts. Most teams find out when sales stops trusting the score. This is how I run a score as an agent with a lifecycle instead.

## 2. The v0 finding (30 seconds)

> I started from my own notebooks. Hand-set weights, no outcomes. And a bug: every category got the same weight, so industry and role never moved a score. The lead score was really just site visits. That is the baseline in green on every chart.

## 3. Leads: monthly rebuild (90 seconds)

Point at the lead chart and the drift grid.

> Blue is the agent-managed champion. Orange is the first model, frozen. Green is v0.
>
> July to October: four monthly rebuilds, none beat the champion, so nothing changed. The agent does not churn models for the sake of it.
>
> November: a paid campaign floods site visits. The monitor flags it the day the leads land, PSI 0.26, a month before outcomes can confirm it.
>
> December: outcomes confirm it. AUC down nine points, scores five points too hot. Every challenger was trained before the campaign, so every one fails the gates. The agent holds and says exactly why.
>
> January: a retrain with campaign data wins, 0.76 against 0.70, and promotes itself. Lead promotions need no human.
>
> March: a new keyword, AI Agents, shows up. The monitor names it. The builder says no update path can learn it until outcomes land. In May a retrain learns it and goes live.
>
> Net: by August the managed model is five points of AUC ahead of the frozen one and eleven ahead of v0.

## 4. Accounts: quarterly rescore (90 seconds)

> Accounts are different. Tiers drive territories and coverage, so stability matters and RevOps signs off.
>
> Q4 2025: calibration drifted. A recalibration and a full retrain ranked equally well. The agent chose the recalibration: 4 percent of accounts change tier instead of 23. Same accuracy, far less disruption for reps.
>
> Q1 2026: expansion starts following product adoption instead of margin. The monitor sees AUC fall seven points. Nothing can beat the champion yet because the new pattern has no outcomes. It holds and flags it.
>
> Q2: a warm-start fine-tune adapts faster than a full retrain and is promoted after approval. That is the fine-tuning path: keep what the model knows, add trees on the newest outcomes.
>
> Q3: Public Sector reaches 8 percent of the book. Fine-tune and retrain tie on accuracy, but only the retrain knows the new segment. The agent picks the retrain.

## 5. Live: the last cycle over A2A (60 seconds)

In the second terminal:

```bash
curl -s http://127.0.0.1:9100/agents | python3 -m json.tool
.venv/bin/crm-agent cycle account 2026Q3 --transport a2a
.venv/bin/crm-agent approve account-v12 --approver "Daniel, RevOps" --a2a-url http://127.0.0.1:9100
```

Use the version the cycle prints as pending. It is account-v12 with the pinned libraries. After approving, stop the A2A server and show the card with `.venv/bin/crm-agent card account-v12`.

> Three agents, each with an A2A card. The monitor finds the drift, the builder builds, governance gates. It stops at pending approval. I approve as RevOps, and the model card records who approved it and why.

## 6. Where it meets Salesforce (60 seconds)

If live mode is set up, open a seeded Account.

> The governance agent writes score, tier, model version and reasons to the record. In Agentforce, a rep asks why this account is tier A. The action reads those fields. The agent explains. It will not change a score.

If not, show `salesforce/` and the Apex action, and say the same.

> The same tools are on MCP, so Claude Desktop or an Agentforce agent can drive the lifecycle in conversation.

## 7. Tie it to the job (30 seconds)

> Deployment Strategists own Identify, Commit, Deploy and Consume. This is Consume. Go-live is where the work starts: the score has to stay right, stay trusted and stay explainable. The gates, the approval step and the audit trail are what keep a customer out of pilot purgatory after launch.

Stop. Count to three.

## Questions to expect

**Why not just retrain every month and ship it?**
Because a retrain that does not beat the champion only adds churn. For accounts, about one in five would change tier for nothing. The builder always tries a retrain; governance only ships one that earns it.

**Why PSI?**
It needs no labels, so it sees trouble a full period early. It is a trigger to look, not a verdict. Outcomes decide.

**What does "fine-tuning" mean for a tree model?**
Warm start. Keep the champion's trees and add trees fitted on the newest outcomes. It adapts fast but cannot learn a category it has never seen. That is why the agent escalates to a full retrain for new segments.

**What is the LLM doing?**
Writing the summary for RevOps, if you turn it on. It does not decide promotions. Gates do. That is deliberate.

**How would this run at a real customer?**
Features from Data 360 or the customer's warehouse. Scores written back or read zero-copy. Gates and the approval step agreed with RevOps in the Commit stage, before anything ships.

**What would you change for production?**
A proper feature store, the official A2A SDK with streaming, shadow scoring before promotion, and fairness checks on protected attributes where the use case needs them.

**The data is synthetic. Does that matter?**
The drift is scripted so every path gets exercised in seven minutes. The mechanics are the same on real data. That is the point of a demo.

## If something breaks

- A2A server will not start: run the cycle in-process, `crm-agent cycle account 2026Q3`. Same agents, same messages.
- No laptop: the Hugging Face Space has the full timeline.
