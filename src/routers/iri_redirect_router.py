from contextlib import asynccontextmanager
from distutils.core import extension_keywords
from selectors import SelectSelector
from typing import List, Any, Optional, Tuple, Dict
from urllib.parse import parse_qsl

from starlette.datastructures import Headers
from starlette.routing import Router, Route, Mount
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from .._settings import settings

from logging import getLogger

from ..functions.iri_configs import load_all_defs
from ..functions.iri_redirect import make_redir

# The root logger, this is overridden by Azure Function App logger.
logger = getLogger()

def parse_forwarded_request(headers: Headers) -> Tuple[Optional[str], Optional[str]]:
    proto = None
    host = None
    forwarded_headers = headers.getlist("forwarded")
    if len(forwarded_headers) > 0:
        forwarded_str = forwarded_headers[0].split(",", 1)[0]
        components = [x.strip() for x in forwarded_str.split(";")]
        for c in components:
            if host is None and c.startswith("host="):
                host = c[5:]
            elif proto is None and c.startswith("proto="):
                proto = c[6:]
    else:
        forwarded_host_headers = headers.getlist("x-forwarded-host")
        if len(forwarded_host_headers) > 0:
            forwarded_host = forwarded_host_headers[0].split(",", 1)[0]
            if forwarded_host:
                forwarded_host = forwarded_host.split(":", 1)[0].strip().lower()
                logger.debug(f"[REDIRS] Found Proxy Forwarded host: {forwarded_host}")
                host = forwarded_host
        forwarded_proto_headers = headers.getlist("x-forwarded-proto")
        if len(forwarded_proto_headers) > 0:
            proto = forwarded_proto_headers[0].split(",", 1)[0]
            if proto:
                proto = proto.strip().lower()
        if proto is None:
            forwarded_ssl_headers = headers.getlist("x-forwarded-ssl")
            if len(forwarded_ssl_headers) > 0:
                ssh_header = forwarded_ssl_headers[0].split(",", 1)[0].strip().lower()
                if ssh_header in ("on", "true", "yes"):
                    proto = "https"
                elif ssh_header == ("off", "false", "no"):
                    proto = "http"
    return proto, host

async def redir_for_pid(request: Request) -> Response:
    app_domain_name = request.state.conf_server_name
    app_debug = request.state.conf_debug
    host_list = []
    mut_query_params: Dict[str, str] = {k: v for k, v in request.query_params.items()}
    if "_host" in mut_query_params:
        host_list.append(mut_query_params["_host"].strip().lower())
        del mut_query_params["_host"]
    if "_pid" in mut_query_params:
        iri = mut_query_params["_pid"].strip()
        del mut_query_params["_pid"]
    elif "iri" in mut_query_params:
        iri = mut_query_params["iri"].strip()
        # Don't remove iri from query params, it could be used for other purposes.
    else:
        return HTMLResponse(status_code=400, content="Missing iri parameter or _pid query parameter.")
    request_scheme = request.url.scheme
    proto_split = iri.split("://", 1)
    if len(proto_split) > 1:
        proto = proto_split[0]
        host_path = proto_split[1]
    else:
        proto = request_scheme
        host_path = proto_split[0]

    host_path_split = host_path.split("/", 1)
    if len(host_path_split) < 2:
        return HTMLResponse(status_code=400, content="Invalid PID URI given for redirect.")
    host_list.append(host_path_split[0])
    path = str(host_path_split[1]).lstrip("/")
    if "?" in path:
        path, query = path.split("?", 1)
        new_query_vals = dict(parse_qsl(query, keep_blank_values=True))
        mut_query_params.update(new_query_vals)
    forwarded_proto, forwarded_host = parse_forwarded_request(request.headers)
    if forwarded_host:
        host_list.append(forwarded_host)
    host_headers = request.headers.getlist("host")
    if len(host_headers) > 0:
        head_host = host_headers[0].split(",", 1)[0]
        head_host = head_host.split(":", 1)[0].strip().lower()
        if head_host in ("", "localhost", "127.0.0.1", "127.0.1.1"):
            logger.debug(f"[REDIRS] Detected possibly incorrect local Host header: {head_host}")
            # These are for local development purposes.
            # We'll substitute the configured server name to emulate a real server.
            if app_domain_name:
                logger.debug(f"[REDIRS] Substituting server name: {app_domain_name}")
                host_list.append(app_domain_name)
            else:
                logger.debug(f"[REDIRS] No localhost substitution found. Falling back to {head_host}.")
                host_list.append(head_host)
        else:
            host_list.append(head_host)

    # don't add fallback to `app_domain_name` or empty "" host in host_list
    # because the make_redir will do that for us
    return await make_redir(proto, host_list, path, mut_query_params, request)

async def index(request: Request) -> Response:
    app_domain_name = request.state.conf_server_name
    app_debug = request.state.conf_debug
    mut_query_params: Dict[str, str] = {k: v for k, v in request.query_params.items()}
    # Note, path does not include leading slash, but may have a trailing slash
    # /datasets/bdr => datasets/bdr
    # /hello/ => hello/
    # / => ""
    path: str = request.path_params.get("path", "")
    request_scheme: str = request.url.scheme
    host_list = []
    if "_host" in mut_query_params:
        host_list.append(mut_query_params["_host"].strip().lower())
        del mut_query_params["_host"]
    forwarded_host, forwarded_proto = parse_forwarded_request(request.headers)
    if forwarded_host:
        host_list.append(forwarded_host)
    proto = request_scheme if not forwarded_proto else forwarded_proto
    host_headers = request.headers.getlist("host")
    if len(host_headers) > 0:
        head_host = host_headers[0].split(",", 1)[0]
        head_host = head_host.split(":", 1)[0].strip().lower()
        if head_host in ("", "localhost", "127.0.0.1", "127.0.1.1"):
            logger.debug(f"[REDIRS] Detected possibly incorrect local Host header: {head_host}")
            # These are for local development purposes.
            # We'll substitute the configured server name to emulate a real server.
            if app_domain_name:
                logger.debug(f"[REDIRS] Substituting server name: {app_domain_name}")
                host_list.append(app_domain_name)
            else:
                logger.debug(f"[REDIRS] No localhost substitution found. Falling back to {head_host}.")
                host_list.append(head_host)
        else:
            host_list.append(head_host)
    # don't add fallback to `app_domain_name` or empty "" host in host_list
    # because the make_redir will do that for us
    return await make_redir(proto, host_list, path, mut_query_params, request)

@asynccontextmanager
async def lifespan(app: Optional[Any]):
    # ___ Before serving the first request, this section is run ___
    conf_server_name = settings.get("SERVER_NAME", None)
    if conf_server_name:
        conf_server_name = conf_server_name.split("//", 1)[-1].split("/", 1)[0]
        logger.info(f"[REDIRS] Using SERVER_NAME: {conf_server_name}")
    else:
        logger.info(f"[REDIRS] No SERVER_NAME given. Default server name used.")
    app_debug = None if app is None else getattr(app, "debug")
    is_debug =  app_debug or (settings['DEBUG_APP'] in ("true", "TRUE", 'T', True, "1", 1, "True"))
    logger.info(f"[REDIRS] DEBUG mode: {is_debug}.")
    state = {}
    state["conf_server_name"] = conf_server_name
    state["conf_debug"] = is_debug
    load_all_defs(state)
    try:
        # Now pass back to the request handler to serve requests
        yield state
    finally:
        # Server is shutting down, cleanup
        pass


def make_all_iri_redirect_routes() -> tuple[str,List[Route], Optional[Any]]:

    return "", [
        Route("/redir", redir_for_pid, methods=["GET", "OPTIONS", "HEAD"], name="redir", include_in_schema=False),
        Route("/{path:path}", index, methods=["GET", "OPTIONS", "HEAD"], name="handler", include_in_schema=False)
    ], lifespan
