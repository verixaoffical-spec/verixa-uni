# The tests use their own database, never the one in .env. Set TEST_DATABASE_URL to run them on PostgreSQL.
import os
import tempfile

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or (
    "sqlite:///" + os.path.join(tempfile.gettempdir(), "verixa-tests.db").replace("\\", "/"))
os.environ["PUBLIC_URL"] = "http://testserver"
for name in ("SECRET_KEY", "WEBHOOK_SECRET", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET",
             "ATLASSIAN_CLIENT_ID", "ATLASSIAN_CLIENT_SECRET"):
    os.environ.setdefault(name, "test-" + name.lower())
