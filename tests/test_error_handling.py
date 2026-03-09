"""Tests for error handling and sanitization."""

from concurrent.futures import TimeoutError as FuturesTimeoutError

import pytest

from monarch_mcp_server.server import (
    ValidationError,
    _sanitize_error,
)


class TestSanitizeError:
    """Tests for _sanitize_error function."""

    def test_authentication_needed_error_preserved(self) -> None:
        """Test that authentication needed message is passed through."""
        error = RuntimeError("Authentication needed! Run: python login_setup.py")
        result = _sanitize_error("getting accounts", error)
        assert "Authentication needed" in result

    def test_validation_error_message_preserved(self) -> None:
        """Test that validation error messages are preserved."""
        error = ValidationError("limit must be at least 1")
        result = _sanitize_error("getting transactions", error)
        assert "Validation error" in result
        assert "limit must be at least 1" in result

    def test_timeout_error_sanitized(self) -> None:
        """Test that timeout errors get user-friendly message."""
        error = FuturesTimeoutError()
        result = _sanitize_error("getting accounts", error)
        assert "timed out" in result
        assert "getting accounts" in result

    def test_generic_error_sanitized(self) -> None:
        """Test that generic errors are sanitized and don't expose details."""
        error = Exception("Connection refused: api.monarch.com:443")
        result = _sanitize_error("getting accounts", error)
        assert "getting accounts" in result
        assert "unexpected error" in result
        assert "Connection refused" not in result
        assert "api.monarch.com" not in result

    def test_api_error_details_not_exposed(self) -> None:
        """Test that API error details are not exposed to user."""
        error = Exception("GraphQL error: Invalid token at position 42")
        result = _sanitize_error("getting transactions", error)
        assert "GraphQL" not in result
        assert "token" not in result
        assert "position" not in result

    def test_operation_name_in_error(self) -> None:
        """Test that operation name is included in sanitized error."""
        error = Exception("Some internal error")
        result = _sanitize_error("refreshing accounts", error)
        assert "refreshing accounts" in result
