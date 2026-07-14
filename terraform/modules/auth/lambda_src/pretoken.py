"""Cognito pre-token-generation (v2) trigger.

Normalises Entra App Roles into Cognito groups and a clean ``custom:role`` claim
so the application has a trustworthy claim set with no directory lookups. Entra
emits App Roles as a (possibly multi-valued) attribute mapped to ``custom:role``;
here we split it and stamp the groups onto the access token.
"""

VALID_ROLES = {"QCApprover", "QCLead", "QCManager", "Director"}


def handler(event, _context):
    attributes = event.get("request", {}).get("userAttributes", {}) or {}
    raw_role = attributes.get("custom:role", "") or ""

    roles = [r.strip() for r in raw_role.replace(";", ",").split(",") if r.strip()]
    groups = [r for r in roles if r in VALID_ROLES]

    event["response"] = {
        "claimsAndScopeOverrideDetails": {
            "groupOverrideDetails": {
                "groupsToOverride": groups,
            },
            "accessTokenGeneration": {
                "claimsToAddOrOverride": {
                    "custom:role": ",".join(groups),
                },
            },
        }
    }
    return event
