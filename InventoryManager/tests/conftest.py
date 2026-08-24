import os


os.environ["TESTING"] = "true"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_URL_HOST", None)


# Existing fast tests explicitly opt into bypassing the new request boundary.
# Security and isolation tests override this on their config classes.
from config import TestingConfig  # noqa: E402

TestingConfig.AUTH_BYPASS_FOR_TESTS = True
