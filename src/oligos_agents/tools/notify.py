"""Notification tool: publish to SNS.

On approval, stakeholders (synthesis lead, QC lead, order owner) are alerted via
an SNS topic. Message attributes allow subscribers to filter by severity or
batch. Recipients are configured on the topic subscriptions, not in code.
"""

from __future__ import annotations

from oligos_agents.deps import AgentDeps


class NotificationsNotConfigured(RuntimeError):
    pass


def send_notifications(
    deps: AgentDeps,
    subject: str,
    message: str,
    *,
    severity: str | None = None,
    batch_id: str | None = None,
) -> str:
    """Publish a notification to the configured SNS topic; returns the message id."""
    topic_arn = deps.settings.notifications_topic_arn
    if not topic_arn:
        raise NotificationsNotConfigured(
            "NOTIFICATIONS_TOPIC_ARN is not set; cannot send notifications."
        )

    attributes: dict = {}
    if severity:
        attributes["severity"] = {"DataType": "String", "StringValue": severity}
    if batch_id:
        attributes["batch_id"] = {"DataType": "String", "StringValue": batch_id}

    response = deps.clients.sns.publish(
        TopicArn=topic_arn,
        Subject=subject[:100],
        Message=message,
        MessageAttributes=attributes,
    )
    return response["MessageId"]
