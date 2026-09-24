"""Business entity tools (Monarch's paid "businesses" feature).

A business entity is Monarch's per-transaction "which business is this for"
label. The underlying field is ``businessEntityId`` on the transaction update
input, confirmed against the live API on 2026-09-24 (single and bulk).
"""

import logging
from typing import Optional

from gql import gql

from monarch_mcp_server.app import mcp
from monarch_mcp_server.client import get_monarch_client
from monarch_mcp_server.helpers import (
    json_error,
    json_rejected,
    json_success,
    payload_errors,
)

logger = logging.getLogger(__name__)

GET_BUSINESS_ENTITIES_QUERY = gql("""
query Common_GetBusinessEntities {
  businessEntities {
    id
    name
  }
}
""")

SET_BUSINESS_ENTITY_MUTATION = gql("""
mutation Common_SetTransactionBusinessEntity($input: UpdateTransactionMutationInput!) {
  updateTransaction(input: $input) {
    transaction {
      id
      businessEntity {
        id
        name
      }
    }
    errors {
      message
      fieldErrors {
        field
        messages
      }
    }
  }
}
""")


@mcp.tool()
async def get_business_entities() -> str:
    """
    List the business entities on the Monarch account (id and name).

    Use the id with set_business_entity or bulk_update_transactions.
    """
    try:
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="Common_GetBusinessEntities",
            graphql_query=GET_BUSINESS_ENTITIES_QUERY,
            variables={},
        )
        return json_success(result.get("businessEntities") or [])
    except Exception as e:
        return json_error("get_business_entities", e)


@mcp.tool()
async def set_business_entity(
    transaction_id: str,
    business_entity_id: Optional[str] = None,
) -> str:
    """
    Set (or clear) the business entity on one transaction.

    Args:
        transaction_id: The transaction to update
        business_entity_id: Business id from get_business_entities, or
            omit / pass "none" to clear it (mark as personal)

    Returns:
        The transaction id and its business entity after the write, read
        back from the mutation response.
    """
    try:
        value = None
        if business_entity_id and business_entity_id.strip().lower() != "none":
            value = business_entity_id
        client = await get_monarch_client()
        result = await client.gql_call(
            operation="Common_SetTransactionBusinessEntity",
            graphql_query=SET_BUSINESS_ENTITY_MUTATION,
            variables={"input": {"id": transaction_id, "businessEntityId": value}},
        )
        errors = payload_errors(result, "updateTransaction")
        if errors:
            return json_rejected("set_business_entity", errors)
        return json_success((result.get("updateTransaction") or {}).get("transaction"))
    except Exception as e:
        return json_error("set_business_entity", e)
