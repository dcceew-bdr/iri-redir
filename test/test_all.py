from pathlib import Path
from tomli import load as load_toml
try:
    import pytest
except ImportError:
    raise RuntimeError("pytest must be installed in the python environment for tests to run")
try:
    import pytest_asyncio
except ImportError:
    raise RuntimeError("pytest-asyncio must be installed in the python environment for tests to run")
try:
    import httpx
except ImportError:
    raise RuntimeError("httpx must be installed in the python environment for tests to run")
from starlette.testclient import TestClient

tests_dir = Path(__file__).parent

from src.factory import create_app
from src import settings
settings["CONFIG_DEFS_DIRECTORY"] = str(tests_dir / "configs")

test_files_dir = tests_dir / "test_files"
all_files = list(test_files_dir.glob("*.toml"))


test_data = []
for test_file in all_files:
    with open(test_file, "rb") as f:
        test_def = load_toml(f)
        _host = test_def['host']
        _host_aliases = test_def.get('host_aliases', [])
        _test_redirects = test_def.get('test_redirect', [])
        _default_redirect_code = test_def.get('default_redirect_code', 307)
        _default_scheme = test_def.get('default_scheme', "http")
        _kwargs = {"host_aliases": _host_aliases, "default_redirect_code": _default_redirect_code}
        test_data.append((_host, _test_redirects, _kwargs))

@pytest.mark.asyncio
@pytest.mark.parametrize("host, test_redirects, kwargs", test_data)
async def test_redirects(host, test_redirects, kwargs):
    settings["SERVER_NAME"] = host
    host_aliases = kwargs.get("host_aliases", [])
    default_redirect_code = kwargs.get("default_redirect_code", 307)
    default_scheme = kwargs.get("default_scheme", "http")
    app = create_app()
    with TestClient(app=app, root_path="") as client:
        for t_def in test_redirects:
            from_ = t_def['from']
            to_ = t_def['to']
            code_ = t_def.get('code', default_redirect_code)
            scheme = t_def.get('scheme', default_scheme)
            if not from_.startswith("https://") and not from_.startswith("http://"):
                from_ = f"{scheme}://{host.rstrip('/')}/{from_.lstrip('/')}"
            headers = t_def.get('headers', {})
            resp = client.get(from_, headers=headers, follow_redirects=False)
            assert resp.status_code == code_
            location = resp.headers.get_list("location")
            assert len(location) == 1
            loc_parts = location[0].split(",", 1)
            assert len(loc_parts) == 1
            assert loc_parts[0].lower() == to_.lower()


