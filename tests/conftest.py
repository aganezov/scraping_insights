import os
import pytest


@pytest.fixture(autouse=True, scope="session")
def disable_paid_transcripts_for_tests():
    """
    Ensure test runs never trigger paid transcript API calls.
    Can be overridden by explicitly setting YTTI_ALLOW_PAID_TESTS=1.
    """
    if os.getenv("YTTI_ALLOW_PAID_TESTS") == "1":
        return
    os.environ["YTTI_SKIP_PAID"] = "1"
