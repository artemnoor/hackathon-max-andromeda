from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from andromeda.modules.auth.contracts.public import Account


def test_account_contract_is_strict_and_timezone_aware() -> None:
    account = Account(accountId="account:" + "a" * 32, email="student@example.com", createdAt=datetime.now(timezone.utc))
    assert account.account_id.startswith("account:")

    with pytest.raises(ValidationError):
        Account(accountId="not-an-account", email="student@example.com", createdAt=datetime.now(timezone.utc))
    with pytest.raises(ValidationError):
        Account(accountId="account:" + "a" * 32, email="student@example.com", createdAt=datetime.now())
    with pytest.raises(ValidationError):
        Account.model_validate({"accountId": "account:" + "a" * 32, "email": "student@example.com", "createdAt": datetime.now(timezone.utc), "password": "secret"})
