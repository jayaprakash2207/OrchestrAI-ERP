from __future__ import annotations

from decimal import Decimal


def validate_positive_decimal(value: Decimal, field_name: str) -> None:
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")


def validate_alphanumeric_code(value: str, field_name: str, max_length: int) -> None:
    if not value or len(value) > max_length or not value.replace("-", "").isalnum():
        raise ValueError(f"{field_name} must be alphanumeric and <= {max_length} characters.")
