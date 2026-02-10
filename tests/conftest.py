"""Shared test configuration: mock monarchmoney before any tool imports."""

import sys
from unittest.mock import MagicMock

# Mock the monarchmoney module before any monarch_mcp_server imports
mm_mock = MagicMock()
mm_mock.MonarchMoney = MagicMock
mm_mock.RequireMFAException = Exception
sys.modules["monarchmoney"] = mm_mock
sys.modules["monarchmoney.monarchmoney"] = MagicMock()
