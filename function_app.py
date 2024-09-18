import sys
import logging
import os
from pathlib import Path

#------- Fix up Logging to Application Logger -------
root_logger = logging.getLogger()
h = logging.StreamHandler(sys.stderr)
root_logger.addHandler(h)
if os.getenv("PYTHON_ENABLE_DEBUG_LOGGING", "").lower() in ("true", "1", "t", "yes"):
    root_logger.setLevel(logging.DEBUG)
    for h in root_logger.handlers:
        h.setLevel(logging.DEBUG)
#---------------------------------------------------

#------- Fix up Python Path for site-packages and local dir -------
base_dir = Path(__file__).resolve().parent
if "/home/site/wwwroot/.python_packages/lib/site-packages" in sys.path or \
        ".python_packages/lib/site-packages" in sys.path:
    dest = base_dir / ".python_packages" / "lib" / "site-packages"
    if not dest.exists():
        root_logger.debug("Cannot find .python_packages/lib/site-packages, creating symlink")
        # Find the python version equivalent
        python_dirs = (base_dir / ".python_packages" / "lib").glob("python*")
        for p in python_dirs:
            if p.is_dir():
                root_logger.debug(f"Symlinking {p} to {dest}")
                new_path = Path(p) / "site-packages"
                dest.symlink_to(new_path, target_is_directory=True)
                break
        else:
            raise RuntimeError("Cannot find python site-packages in .python_packages/lib/*")
if "." not in sys.path or str(base_dir) not in sys.path:
    # Add the base dir here to the path, so it can find "src" package
    sys.path.insert(0, str(base_dir))
#---------------------------------------------------

import azure.functions as func
from azure.functions import HttpRequest
try:
    from src.factory import create_app
except ImportError as e:
    logging.exception("Importing src.factory")
    create_app = None


if create_app is None:
    logging.error(
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
