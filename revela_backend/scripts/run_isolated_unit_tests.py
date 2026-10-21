"""Run mocked/in-memory tests with application DB connections and HTTP disabled."""
from contextlib import ExitStack
from pathlib import Path
import sys
import importlib
import subprocess
import linecache
from unittest.mock import patch


def forbidden(*_args, **_kwargs):
    raise AssertionError("Isolated tests forbid application DB connections and external HTTP")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with ExitStack() as guards:
        guards.enter_context(patch("dotenv.load_dotenv", return_value=False))
        guards.enter_context(patch("MySQLdb.connect", forbidden))
        guards.enter_context(patch("MySQLdb._mysql.connect", forbidden))
        guards.enter_context(patch("requests.sessions.Session.request", forbidden))
        guards.enter_context(patch("apscheduler.schedulers.background.BackgroundScheduler.start", forbidden))
        if "--baseline" in sys.argv:
            sys.argv.remove("--baseline")
            for name, relative in (
                ("api.registry.service", "api/registry/service.py"),
                ("api.registry.places_resolver", "api/registry/places_resolver.py"),
                ("api.flags.service", "api/flags/service.py"),
                ("api.inspections.service", "api/inspections/service.py"),
                ("api.inspections.routes", "api/inspections/routes.py"),
            ):
                module = importlib.import_module(name)
                source = subprocess.run(
                    ["git", "show", f"HEAD:revela_backend/{relative}"],
                    cwd=Path(__file__).resolve().parents[1], capture_output=True,
                    text=True, encoding="utf-8", check=True,
                ).stdout
                filename = f"<baseline:{relative}>"
                linecache.cache[filename] = (len(source), None, source.splitlines(keepends=True), filename)
                exec(compile(source, filename, "exec"), module.__dict__)
        import pytest
        raise SystemExit(pytest.main(sys.argv[1:]))
