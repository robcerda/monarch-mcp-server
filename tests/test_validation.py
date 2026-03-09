"""Tests for input validation functions."""

import pytest

from monarch_mcp_server.server import (
    MAX_DESCRIPTION_LENGTH,
    MAX_LIMIT,
    MIN_LIMIT,
    ValidationError,
    _validate_date,
    _validate_description,
    _validate_limit,
    _validate_offset,
)


class TestValidateLimit:
    """Tests for _validate_limit function."""

    def test_valid_limit_default(self) -> None:
        """Test that default limit value is valid."""
        assert _validate_limit(100) == 100

    def test_valid_limit_minimum(self) -> None:
        """Test minimum valid limit."""
        assert _validate_limit(MIN_LIMIT) == MIN_LIMIT

    def test_valid_limit_maximum(self) -> None:
        """Test maximum valid limit."""
        assert _validate_limit(MAX_LIMIT) == MAX_LIMIT

    def test_limit_below_minimum(self) -> None:
        """Test that limit below minimum raises ValidationError."""
        with pytest.raises(ValidationError, match="must be at least"):
            _validate_limit(0)

    def test_limit_negative(self) -> None:
        """Test that negative limit raises ValidationError."""
        with pytest.raises(ValidationError, match="must be at least"):
            _validate_limit(-1)

    def test_limit_above_maximum(self) -> None:
        """Test that limit above maximum raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot exceed"):
            _validate_limit(MAX_LIMIT + 1)


class TestValidateOffset:
    """Tests for _validate_offset function."""

    def test_valid_offset_zero(self) -> None:
        """Test that zero offset is valid."""
        assert _validate_offset(0) == 0

    def test_valid_offset_positive(self) -> None:
        """Test that positive offset is valid."""
        assert _validate_offset(100) == 100

    def test_offset_negative(self) -> None:
        """Test that negative offset raises ValidationError."""
        with pytest.raises(ValidationError, match="must be non-negative"):
            _validate_offset(-1)


class TestValidateDate:
    """Tests for _validate_date function."""

    def test_valid_date_format(self) -> None:
        """Test valid YYYY-MM-DD date format."""
        assert _validate_date("2024-01-15", "test_date") == "2024-01-15"

    def test_none_date(self) -> None:
        """Test that None date returns None."""
        assert _validate_date(None, "test_date") is None

    def test_invalid_date_format_wrong_separator(self) -> None:
        """Test that wrong separator raises ValidationError."""
        with pytest.raises(ValidationError, match="must be in YYYY-MM-DD format"):
            _validate_date("2024/01/15", "test_date")

    def test_invalid_date_format_wrong_order(self) -> None:
        """Test that wrong order raises ValidationError."""
        with pytest.raises(ValidationError, match="must be in YYYY-MM-DD format"):
            _validate_date("15-01-2024", "test_date")

    def test_invalid_date_format_incomplete(self) -> None:
        """Test that incomplete date raises ValidationError."""
        with pytest.raises(ValidationError, match="must be in YYYY-MM-DD format"):
            _validate_date("2024-01", "test_date")

    def test_invalid_date_format_with_time(self) -> None:
        """Test that date with time raises ValidationError."""
        with pytest.raises(ValidationError, match="must be in YYYY-MM-DD format"):
            _validate_date("2024-01-15T10:30:00", "test_date")

    def test_error_message_includes_field_name(self) -> None:
        """Test that error message includes the field name."""
        with pytest.raises(ValidationError, match="start_date"):
            _validate_date("invalid", "start_date")


class TestValidateDescription:
    """Tests for _validate_description function."""

    def test_valid_short_description(self) -> None:
        """Test that short description is valid."""
        desc = "Coffee at Starbucks"
        assert _validate_description(desc) == desc

    def test_valid_max_length_description(self) -> None:
        """Test that max length description is valid."""
        desc = "a" * MAX_DESCRIPTION_LENGTH
        assert _validate_description(desc) == desc

    def test_empty_description(self) -> None:
        """Test that empty description is valid."""
        assert _validate_description("") == ""

    def test_description_too_long(self) -> None:
        """Test that overly long description raises ValidationError."""
        desc = "a" * (MAX_DESCRIPTION_LENGTH + 1)
        with pytest.raises(ValidationError, match="cannot exceed"):
            _validate_description(desc)
