from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _cfg() -> dict[str, str]:
    return {
        "tenant_id": os.environ.get("GRAPH_TENANT_ID", "").strip(),
        "client_id": os.environ.get("GRAPH_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("GRAPH_CLIENT_SECRET", "").strip(),
        "user_id": os.environ.get("GRAPH_USER_ID", "me").strip(),
        "api_base": os.environ.get("GRAPH_API_BASE", "https://graph.microsoft.com/v1.0").strip(),
    }


def _fetch_access_token(cfg: dict[str, str]) -> str:
    token_url = f"https://login.microsoftonline.com/{cfg['tenant_id']}/oauth2/v2.0/token"
    form = urllib.parse.urlencode(
        {
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        token_url,
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    token = str(payload.get("access_token", "")).strip()
    if not token:
        raise RuntimeError("Graph token response missing access_token")
    return token


def _graph_get_json(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "TapdashEmailSwarm/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _message_to_compact(message: dict[str, Any]) -> dict[str, Any]:
    sender = ((message.get("from") or {}).get("emailAddress") or {}).get("address")
    to_recipients = [
        ((r.get("emailAddress") or {}).get("address"))
        for r in (message.get("toRecipients") or [])
        if isinstance(r, dict)
    ]
    return {
        "id": message.get("id"),
        "conversationId": message.get("conversationId"),
        "subject": message.get("subject"),
        "receivedDateTime": message.get("receivedDateTime"),
        "from": sender,
        "to": [x for x in to_recipients if x],
        "bodyPreview": message.get("bodyPreview"),
        "webLink": message.get("webLink"),
    }


def _fetch_thread_messages(work_order: dict[str, Any], cfg: dict[str, str], token: str) -> list[dict[str, Any]]:
    message_id = str(work_order.get("message_id") or "").strip()
    conversation_id = str(work_order.get("conversation_id") or "").strip()
    user_id = urllib.parse.quote(cfg["user_id"], safe="")
    api_base = cfg["api_base"]
    messages: list[dict[str, Any]] = []

    if message_id:
        encoded_message_id = urllib.parse.quote(message_id, safe="")
        url = (
            f"{api_base}/users/{user_id}/messages/{encoded_message_id}"
            "?$select=id,conversationId,subject,from,toRecipients,bodyPreview,receivedDateTime,webLink"
        )
        payload = _graph_get_json(url, token=token)
        if isinstance(payload, dict) and payload.get("id"):
            messages.append(_message_to_compact(payload))
            if not conversation_id:
                conversation_id = str(payload.get("conversationId") or "").strip()

    if conversation_id:
        filt = urllib.parse.quote(f"conversationId eq '{conversation_id}'", safe=" =%'")
        url = (
            f"{api_base}/users/{user_id}/messages"
            f"?$filter={filt}&$top=10&$orderby=receivedDateTime desc"
            "&$select=id,conversationId,subject,from,toRecipients,bodyPreview,receivedDateTime,webLink"
        )
        payload = _graph_get_json(url, token=token)
        values = payload.get("value") if isinstance(payload, dict) else None
        if isinstance(values, list):
            for message in values:
                if isinstance(message, dict):
                    compact = _message_to_compact(message)
                    if compact.get("id") and all(existing.get("id") != compact["id"] for existing in messages):
                        messages.append(compact)

    return messages


def graph_coordinator_agent(work_order: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg()
    enabled = bool(cfg["tenant_id"] and cfg["client_id"] and cfg["client_secret"])
    response: dict[str, Any] = {
        "enabled": enabled,
        "source": "microsoft_graph",
        "requested_at": _now_iso(),
        "errors": [],
        "thread_context": {},
    }
    if not enabled:
        response["errors"].append("graph_not_configured")
        return response

    if not (work_order.get("message_id") or work_order.get("conversation_id")):
        response["errors"].append("graph_missing_message_or_conversation_id")
        return response

    try:
        token = _fetch_access_token(cfg)
        messages = _fetch_thread_messages(work_order=work_order, cfg=cfg, token=token)
        participants = sorted(
            {
                participant
                for message in messages
                for participant in ([message.get("from")] + list(message.get("to") or []))
                if participant
            }
        )
        response["thread_context"] = {
            "message_count": len(messages),
            "messages": messages[:10],
            "participants": participants,
            "latest_message": messages[0] if messages else None,
        }
        response["match_confidence"] = "high" if messages else "low"
        return response
    except Exception as exc:
        response["errors"].append(str(exc))
        response["match_confidence"] = "none"
        return response
