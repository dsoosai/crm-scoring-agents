"""Plain-English cycle summaries for RevOps.

Deterministic template by default, so a demo never depends on a network call.
Set ANTHROPIC_API_KEY or HF_TOKEN to have an LLM write the summary instead.
The LLM only narrates; it never decides a promotion.
"""
from __future__ import annotations

import json
import os


def template_summary(rec: dict) -> str:
    obj, period = rec["object"], rec["period"]
    mon, dec = rec["monitor"], rec["decision"]
    lines = [f"{obj.title()} cycle {period}: monitor status {mon['status']}."]
    if mon["status"] != "healthy":
        lines.append("Findings: " + "; ".join(mon["findings"][:3]) + ".")
    lines.append(f"Builder tried {', '.join(rec['methods'])}.")
    if dec["action"] == "promote":
        lines.append(f"Promoted {dec['champion']} over {dec.get('previous')}. {dec['reason']}")
    elif dec["action"] == "pending_approval":
        lines.append(f"{dec['candidate']} passed the gates and is waiting for RevOps approval.")
    else:
        lines.append(f"Held {dec['champion']}. {dec['reason']}")
    lines = [ln if ln.endswith(".") else ln + "." for ln in lines]
    lines.append(f"Scored {rec['scoring']['scored']} records with {rec['scoring']['model_version']} "
                 f"and updated the CRM.")
    return " ".join(lines)


def _prompt(rec: dict) -> str:
    slim = {k: rec[k] for k in ("object", "period", "methods")}
    slim["monitor"] = {k: rec["monitor"][k] for k in ("status", "findings")}
    slim["decision"] = rec["decision"]
    slim["scoring"] = {k: rec["scoring"][k] for k in ("scored", "model_version", "tiers")}
    return ("You are writing a three-sentence update for a RevOps leader about a scoring model cycle. "
            "Plain words, no hype, name the model versions and the reason for the decision. "
            "Do not invent numbers.\n\n" + json.dumps(slim, default=str))


def summarize(rec: dict) -> tuple[str, str]:
    """Return (summary, source)."""
    try:
        if os.getenv("ANTHROPIC_API_KEY"):
            import anthropic
            client = anthropic.Anthropic()
            msg = client.messages.create(model=os.getenv("CRM_AGENT_LLM_MODEL", "claude-sonnet-4-5"),
                                         max_tokens=300, messages=[{"role": "user", "content": _prompt(rec)}])
            return msg.content[0].text.strip(), "anthropic"
        if os.getenv("HF_TOKEN"):
            from huggingface_hub import InferenceClient
            client = InferenceClient(token=os.environ["HF_TOKEN"])
            out = client.chat_completion(model=os.getenv("CRM_AGENT_HF_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
                                         messages=[{"role": "user", "content": _prompt(rec)}], max_tokens=300)
            return out.choices[0].message.content.strip(), "huggingface"
    except Exception as exc:  # fall back, never fail a cycle over a summary
        return template_summary(rec) + f" (LLM summary unavailable: {type(exc).__name__})", "template"
    return template_summary(rec), "template"
