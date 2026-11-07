# The tests use their own database, never the one in .env. Set TEST_DATABASE_URL to run them on PostgreSQL.
import os
import tempfile

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or (
    "sqlite:///" + os.path.join(tempfile.gettempdir(), "verixa-tests.db").replace("\\", "/"))
os.environ["PUBLIC_URL"] = "http://testserver"
# The agents' trace stays out of the real log and out of the test output.
os.environ["AGENT_TRACE_FILE"] = os.path.join(tempfile.gettempdir(), "verixa-tests-trace.jsonl")
os.environ["AGENT_TRACE_CONSOLE"] = "0"
# The agent's CI read calls GitHub, so it is off unless a test turns it on and fakes GitHub.
os.environ["AGENT_CI_CHECK"] = "0"
for name in ("SECRET_KEY", "WEBHOOK_SECRET", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET",
             "ATLASSIAN_CLIENT_ID", "ATLASSIAN_CLIENT_SECRET"):
    os.environ.setdefault(name, "test-value-for-" + name.lower())
