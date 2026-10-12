"""Account identity and subscription tools."""

import logging
from typing import Any, Dict, List

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import json_success, json_error

logger = logging.getLogger(__name__)

# Monarch disables GraphQL introspection for non-admin users and masks unknown
# field errors as a generic "Something went wrong", so this selection set was
# established field-by-field against the live API. Fields confirmed absent:
# me.household, me.attributionData, subscription.currentPlan,
# subscription.isEligibleForTrial, subscription.activePromoCode.
#
# Deliberately not selected: me.birthday and me.profilePictureUrl. They are
# personal data an agent has no use for, and this tool's output tends to end up
# in transcripts.
#
# The remaining `me` fields are broader than check_auth_status (which only
# echoes the MONARCH_EMAIL env var and whether a session exists), and that is
# deliberate rather than an oversight: this tool's whole purpose is answering
# "who is signed in", so name/email are the substance of the answer, not
# incidental exposure. `has_password` and `external_auth_providers` are
# non-financial account metadata with a real diagnostic use -- distinguishing
# an SSO-only account from one that also has a password, which matters when
# choosing a login path in login_setup.py. `id` is Monarch's internal user id,
# not a secret and not derivable from anything sensitive; nothing downstream in
# this codebase consumes it today, so it is included only in case a caller
# needs a stable identifier, not because a feature requires it.
WHOAMI_QUERY = gql("""
query GetWhoAmI {
  me {
    id
    name
    email
    timezone
    hasPassword
    externalAuthProviderNames
    __typename
  }
  subscription {
    id
    entitlements
    hasPremiumEntitlement
    isOnFreeTrial
    billingPeriod
    currentPeriodEndsAt
    trialEndsAt
    willCancelAtPeriodEnd
    paymentSource
    nextPaymentAmount
    __typename
  }
}
""")


# Plan-gated features, probed rather than inferred.
#
# Deriving availability from entitlement names would be guesswork: the names
# are not documented and the mapping is not visible from a single account. So
# each capability is a cheap query that either succeeds or does not, which is
# the same signal the caller would get by trying to use the feature.
#
# To gate another feature, add an entry: the operation name, a probe query, and
# the root field to read the result from. Keep the probe minimal -- it runs on
# every whoami call. The operation name is stored rather than read off the
# parsed query, because gql returns different objects across versions.
CAPABILITY_PROBES = {
    "business_entities": (
        "ProbeBusinessEntities",
        gql("query ProbeBusinessEntities { businessEntities { id name color } }"),
        "businessEntities",
    ),
}


def _trial_entitlements(entitlements: List[str]) -> List[str]:
    """Entitlements granted by a trial, which will lapse."""
    return [e for e in entitlements if e.endswith("_trial")]


async def _probe_capabilities(client) -> Dict[str, Any]:
    """Run each capability probe, treating any failure as 'not available'.

    A gated feature is usually absent from the schema entirely rather than
    returning an empty list, and Monarch masks that as a generic error, so the
    exception IS the answer here. A probe must never fail the whole tool.
    """
    capabilities: Dict[str, Any] = {}
    for name, (operation, query, root) in CAPABILITY_PROBES.items():
        try:
            result = await client.gql_call(
                operation=operation, graphql_query=query, variables={},
            )
            items = result.get(root) or []
            capabilities[name] = {"available": True, "items": items}
        except Exception:
            logger.info("Capability %s unavailable on this account", name)
            capabilities[name] = {"available": False, "items": []}
    return capabilities


@mcp.tool()
async def monarch_whoami() -> str:
    """
    Report who is signed in and what the account's plan entitles it to.

    Use this before assuming a feature exists. Parts of Monarch's schema are
    plan-gated: business entities in particular are absent entirely on lower
    tiers, so a transaction rule's business-entity fields simply will not be
    there. Their absence is normal, not an error.

    `capabilities` answers that directly. Each entry is probed against the live
    schema rather than inferred from the plan name, and carries the objects the
    feature needs -- so `capabilities.business_entities.items` is also where a
    business-entity id comes from when setting one on a rule.

    `timezone` is worth reading before doing any date arithmetic, since
    Monarch's dates are rendered in the account's zone.

    Returns:
        JSON with the signed-in user, the subscription, and an `entitlements`
        list. Entitlements ending in `_trial` are temporary -- a feature
        available today may disappear when the trial ends.
    """
    try:
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="GetWhoAmI", graphql_query=WHOAMI_QUERY, variables={}
        )

        capabilities = await _probe_capabilities(client)

        me: Dict[str, Any] = result.get("me") or {}
        sub: Dict[str, Any] = result.get("subscription") or {}
        entitlements = sub.get("entitlements") or []
        trial_only = _trial_entitlements(entitlements)

        return json_success({
            "user": {
                "id": me.get("id"),
                "name": me.get("name"),
                "email": me.get("email"),
                "timezone": me.get("timezone"),
                "has_password": me.get("hasPassword"),
                "external_auth_providers": me.get("externalAuthProviderNames") or [],
            },
            "subscription": {
                "entitlements": entitlements,
                "has_premium": sub.get("hasPremiumEntitlement"),
                "on_free_trial": sub.get("isOnFreeTrial"),
                "billing_period": sub.get("billingPeriod"),
                "current_period_ends_at": sub.get("currentPeriodEndsAt"),
                "trial_ends_at": sub.get("trialEndsAt"),
                "will_cancel_at_period_end": sub.get("willCancelAtPeriodEnd"),
                "payment_source": sub.get("paymentSource"),
                "next_payment_amount": sub.get("nextPaymentAmount"),
            },
            "trial_entitlements": trial_only,
            "capabilities": capabilities,
            "note": (
                "Monarch's schema is plan-gated. Treat a missing field -- "
                "business entities especially -- as this account not having "
                "that feature, not as a failure."
                + (
                    f" Entitlements {trial_only} come from a trial and will "
                    "lapse, taking their fields with them."
                    if trial_only else ""
                )
            ),
        })
    except Exception as e:
        return json_error("monarch_whoami", e)


@mcp.tool()
async def get_household_members() -> str:
    """
    Get household member IDs, names, display names, and roles.

    Returns JSON with members in myHousehold.users. Use a member's id as
    owner_user_id in update_transaction(). Pending invitations are not included.
    """
    try:
        client = await get_monarch_client()
        result = await client.get_household_members()
        return json_success(result)
    except Exception as e:
        return json_error("get_household_members", e)
