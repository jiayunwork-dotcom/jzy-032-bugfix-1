"""Pytest bootstrap: point the app at a throwaway SQLite file and disable
the background scheduler loop *before* any app module is imported (settings
are read at import time). Scheduler behaviour is tested explicitly with
dedicated Scheduler instances and their own databases."""
import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "api_test.db")
os.environ["SCHEDULER_ENABLED"] = "0"
