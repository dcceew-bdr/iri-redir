import sys
import logging
import os
from pathlib import Path

#------- Fix up Logging to Application Logger -------
CONSOLE_LOG_PREFIX = "LanguageWorkerConsoleLog"
root_logger = logging.getLogger()

h = logging.StreamHandler(sys.stderr)
root_logger.addHandler(h)
#if os.getenv("PYTHON_ENABLE_DEBUG_LOGGING", "").lower() in ("true", "1", "t", "yes"):
root_logger.setLevel(logging.DEBUG)
for ha in root_logger.handlers:
    ha.setLevel(logging.DEBUG)

def print_console_error(msg: str):
    print(f"{CONSOLE_LOG_PREFIX} ERROR: {msg}", file=sys.stderr, flush=True)
#---------------------------------------------------

#------- Fix up Python Path for site-packages and local dir -------
# The cwd is probably /tmp/functions\\standby\\wwwroot because
# the /home/site/wwwroot directory is read-only.
existing_sys_path = ','.join(sys.path)
root_logger.info(f"Current sys.path: {existing_sys_path}")
print_console_error(f"Current sys.path: {existing_sys_path}")
h.flush()
base_dir = Path("/home/site/wwwroot").resolve()
if "/home/site/wwwroot/.python_packages/lib/site-packages" in sys.path:
    dest = base_dir / ".python_packages" / "lib" / "site-packages"
    if not dest.exists():
        root_logger.debug("Cannot find .python_packages/lib/site-packages, adding real site-packages")
        h.flush()
        print_console_error("Cannot find .python_packages/lib/site-packages, adding real site-packages")
        # Find the python version equivalent
        python_dirs = (base_dir / ".python_packages" / "lib").glob("python*")
        for p in python_dirs:
            if p.is_dir():
                root_logger.debug(f"Adding {p} to sys.path")
                h.flush()
                print_console_error(f"Adding {p} to sys.path")
                sys.path.insert(0, str(p))
                break
        else:
            raise RuntimeError("Cannot find python site-packages in .python_packages/lib/*")
if str(base_dir) not in sys.path:
    # Add the base dir here to the path, so it can find "src" package
    root_logger.info(f"Adding {base_dir} to sys.path")
    h.flush()
    print_console_error(f"Adding {base_dir} to sys.path")
    sys.path.insert(0, str(base_dir))
#---------------------------------------------------

import azure.functions as func
from azure.functions import HttpRequest
try:
    from src.factory import create_app
except ImportError as e:
    import traceback
    formatted_exc = traceback.format_exc(e).replace("\n", "|")
    print_console_error(f"ImportError: {e}, {formatted_exc}")
    root_logger.exception("Importing src.factory")
    create_app = None


if create_app is None:
    root_logger.error(
      "Cannot import src in the Azure function app. Check requirements.py and deployment logs."
    )
    raise RuntimeError(
        "Cannot import src in the Azure function app. Check requirements.py and deployment logs."
    )

from patched_azure_function_app import AsgiFunctionApp
from src import settings

fn_auth_level: str = settings["FUNCTION_APP_AUTH_LEVEL"]
fn_auth_level = fn_auth_level.strip().upper()
if fn_auth_level == "ADMIN":
    auth_level: func.AuthLevel = func.AuthLevel.ADMIN
elif fn_auth_level == "ANONYMOUS":
    auth_level = func.AuthLevel.ANONYMOUS
else:
    auth_level = func.AuthLevel.FUNCTION

ROOT_PATH: str = settings["APP_BASE_ROUTE"]
if ROOT_PATH == "/": # non-prefix route should be empty string
    # Not a single slash, that doesn't work with the Starlette router
    ROOT_PATH = ""
else:
    # Strip off the trailing slash, if present
    ROOT_PATH = ROOT_PATH.rstrip("/")

starlette_app = create_app(root_path=ROOT_PATH, router_only=True)

app = AsgiFunctionApp(app=starlette_app, http_auth_level=auth_level)

if __name__ == "__main__":
    import asyncio

    req = HttpRequest("GET", "/v", headers={}, body=b"")
    context = dict()
    loop = asyncio.get_event_loop()
    fns = app.get_functions()
    assert len(fns) == 1
    fn_def = fns[0]
    fn = fn_def.get_user_function()
    task = fn(req, context)
    resp = loop.run_until_complete(task)
    print(resp)
