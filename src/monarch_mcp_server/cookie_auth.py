"""Cookie-based authentication for Monarch's new session-cookie API.

In May 2026 Monarch's web app stopped sending `Authorization: Token <...>`
on GraphQL requests and switched to session-cookie auth: a `session_id`
cookie (HttpOnly), a `csrftoken` cookie, and an `x-csrftoken` request header
matching the csrftoken cookie. The upstream monarchmoneycommunity library
still ships the old Token-header flow, so we subclass MonarchMoney and
override the GraphQL transport to send cookies instead.

Known limitation: the upload paths in the upstream library
(`_upload_form_data`, account balance history upload, attachment upload)
build their own aiohttp ClientSession with the legacy headers and will not
work with cookie auth until upstream patches the library. The hardened
build refuses those mutations by default anyway.
"""

from __future__ import annotations

from typing import Dict

from gql import Client
from gql.transport.aiohttp import AIOHTTPTransport
from monarchmoney import MonarchMoney
from monarchmoney.monarchmoney import MonarchMoneyEndpoints

WEB_ORIGIN = "https://app.monarch.com"


class MonarchMoneyCookieAuth(MonarchMoney):
    """MonarchMoney variant authenticating via session_id + csrftoken cookies."""

    def __init__(
        self,
        session_id: str,
        csrftoken: str,
        timeout: int = 10,
    ) -> None:
        super().__init__(timeout=timeout)
        self._session_id = session_id
        self._csrftoken = csrftoken
        self._headers.pop("Authorization", None)
        self._headers["x-csrftoken"] = csrftoken
        self._headers["Origin"] = WEB_ORIGIN
        self._headers["Referer"] = WEB_ORIGIN + "/"

    def _cookies(self) -> Dict[str, str]:
        return {"session_id": self._session_id, "csrftoken": self._csrftoken}

    def _get_graphql_client(self) -> Client:
        transport = AIOHTTPTransport(
            url=MonarchMoneyEndpoints.getGraphQL(),
            headers=self._headers,
            cookies=self._cookies(),
            timeout=self._timeout,
            ssl=True,
        )
        return Client(
            transport=transport,
            fetch_schema_from_transport=False,
            execute_timeout=self._timeout,
        )
