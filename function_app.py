import os
from typing import Union, TYPE_CHECKING

import azure.functions as func
from azure.functions import HttpRequest
try:
    from src.factory import create_app
except ImportError as e:
    raise
    create_app = None


if create_app is None:
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
