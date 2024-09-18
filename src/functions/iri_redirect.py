from contextlib import asynccontextmanager
from distutils.core import extension_keywords
from selectors import SelectSelector
from typing import List, Any, Optional, Tuple, Dict
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit

from starlette.datastructures import Headers
from starlette.routing import Router, Route, Mount
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from .._settings import settings
from .iri_configs import load_all_defs
from .connegp import profile_extract, mediatype_extract

from logging import getLogger


undef = object()
# The root logger, this is overridden by Azure Function App logger.
logger = getLogger()

mediatype_expands = {
    "html": "text/html",
    "xhtml": "application/xhtml+xml",
    "xml": "application/xml",
    "rdf": "application/rdf+xml",
    "ttl": "text/turtle",
    "turtle": "text/turtle",
    "n3": "text/n3",
    "nt": "text/n3",
    "jsonld": "application/ld+json",
    "json-ld": "application/ld+json",
    "json": "application/json",
}

def match_mediatype(mediatypes: List[Tuple[float, str]], mt: str) -> bool:
    mt = mediatype_expands.get(mt, mt)
    # The mediatype list should already be sorted by qval
    return any(mt == mt_str for (q, mt_str) in mediatypes)

def match_profile(profiles: List[Tuple[float, str]], profile: str) -> bool:
    # The profile list should already be sorted by qval
    return any(profile == profile_str for (q, profile_str) in profiles)

def _evaluate_conditional(cond: dict, profiles: List[Tuple[float, str]], mediatypes: List[Tuple[float, str]], request: Request) -> bool:
    resps = {}
    for k, v in cond.items():
        if k == "not":
            if len(v) < 1:
                resps[k] = False
            else:
                resps[k] = not _evaluate_conditional(v, profiles, mediatypes, request)
        elif k == "mediatype":
            resps[k] = match_mediatype(mediatypes, v)
        elif k == "profile":
            resps[k] = match_profile(profiles, v)

    # AND all conditions together to get the final result
    return len(resps) < 1 or all(bool(v) for k, v in resps.items())

async def make_redir(proto, host_list: List[str], path: str, query_params: Dict[str, str], request: Request) -> Response:
    # STEP 0: Set up local constants, get path from request
    app_domain_name = request.state.conf_server_name
    app_debug = request.state.conf_debug
    # Note, path does not include leading slash
    orig_path = str(path)
    localname: Optional[str]
    extension: Optional[str]
    if not orig_path.endswith("/"):
        localname = orig_path.rsplit("/", 1)[-1]
        if "." in localname:
            extension = localname.rsplit(".", 1)[-1].lower()
        else:
            extension = None
    else:
        localname = None
        extension = None
    request.state.client_requested_path = orig_path
    logger.debug(f"[REDIRS] Client requested path: {orig_path}")

    mediatype: Optional[List[Tuple[float, str]]] = None
    profile: Optional[List[Tuple[float, str]]] = None

    # STEP 1: Find the correct "redirect host" file to use based on
    # Host header, x-forwarded-host header, and configured server name
    redir_rules = undef
    host = "(None)"
    redir_host_defs = request.state.defs
    redir_dests = request.state.dests
    m_path = orig_path.lower()  # match-path for matching redirs is always lowercase

    for possible_host in host_list:
        if possible_host in redir_host_defs:
            host = str(possible_host)
            redir_rules = redir_host_defs[possible_host]
            break

    if redir_rules is undef:
        if app_domain_name and (app_domain_name in redir_host_defs):
            redir_rules = redir_host_defs[app_domain_name]
        else:
            redir_rules = redir_host_defs[""]


    use_default_redir_code = redir_rules.get("_default_redir_code", 307)
    use_default_qsa = redir_rules.get("_default_qsa", False)

    # STEP 2: Check and apply relevant rewrite rules
    did_rewrite = False
    if m_path in redir_rules['rewrites']:
        new_path = str(redir_rules['rewrites'][m_path]['to']).lower().lstrip('/')
        logger.debug(f"[REDIR] Match rewrite rule. Rewriting path to \"{new_path}\"")
        m_path = new_path
        did_rewrite = True
    else:
        # No static-rewrite for this path
        pass
    do_regex = (not did_rewrite) and len(redir_rules['rewrites'].get("_has_regex", [])) > 0
    if do_regex:
        # Sort by length, longest first
        for k in sorted(redir_rules['rewrites']["_has_regex"], key=lambda x: len(x), reverse=True):
            this_regex_c_rewrite = redir_rules['rewrites'][k]
            compiled_regex = this_regex_c_rewrite['_regex']  # type: regex.Pattern
            startsmatch_string = this_regex_c_rewrite['_startsmatch']
            if len(startsmatch_string) > 0 and not m_path.startswith(startsmatch_string):
                continue
            (new_path, n) = compiled_regex.subfn(this_regex_c_rewrite['to'], m_path, concurrent=True)
            if n > 0:
                logger.debug(f"[REDIR] Match regex rewrite rule. Substituting path to \"{new_path}\"")
                m_path = new_path
                m_path = m_path.lstrip('/')
                did_rewrite = True
                break
    if not did_rewrite and m_path in redir_rules['conditional_rewrites']:
        # Now check for conditional rewrites, these are applied only after
        # the static rewrites and static regex rewrites
        this_rewrites = redir_rules['conditional_rewrites'][m_path]
        for this_rewrite in this_rewrites:
            cond = this_rewrite['condition']
            applies = False
            if len(cond) > 0:
                if mediatype is None:
                    mediatype = mediatype_extract(request.headers, query_params, extension)
                if profile is None:
                    profile = profile_extract(request.headers, query_params)
                applies = _evaluate_conditional(cond, profile, mediatype, request)
            if applies:
                new_path = this_rewrite['to']
                logger.debug(f"[REDIR] Match conditional rewrite rule. Rewriting path to \"{new_path}\"")
                m_path = new_path.lstrip('/')
                did_rewrite = True
                break
    do_cond_regex = (not did_rewrite) and len(redir_rules['conditional_rewrites'].get("_has_regex", [])) > 0
    if do_cond_regex:
        # Sort by length, longest first
        for k in sorted(redir_rules['conditional_rewrites']["_has_regex"], key=lambda x: len(x), reverse=True):
            this_regex_cond_rewrites = redir_rules['conditional_rewrites'][k]
            for this_regex_c_rewrite in this_regex_cond_rewrites:
                startsmatch_string = this_regex_c_rewrite['_startsmatch']
                if len(startsmatch_string) > 0 and not m_path.startswith(startsmatch_string):
                    continue
                cond = this_regex_c_rewrite['condition']
                applies = False
                if len(cond) > 0:
                    if mediatype is None:
                        mediatype = mediatype_extract(request.headers, query_params, extension)
                    if profile is None:
                        profile = profile_extract(request.headers, query_params)
                    applies = _evaluate_conditional(cond, profile, mediatype, request)
                if applies:
                    compiled_regex = this_regex_c_rewrite['_regex']  # type: regex.Pattern
                    (new_path, n) = compiled_regex.subfn(this_regex_c_rewrite['to'], m_path, concurrent=True)
                    if n > 0:
                        logger.debug(f"[REDIR] Match conditioanl regex rewrite rule. Substituting path to \"{new_path}\"")
                        m_path = new_path
                        m_path = m_path.lstrip('/')
                        did_rewrite = True
                        break
            if did_rewrite:
                break
    # Step 3: Do the actual redirects
    redir_to: Optional[str] = None
    used_record: Optional[dict] = None
    if m_path in redir_rules['redirects']:
        # Static redirects
        record = redir_rules['redirects'][m_path]
        redir_to = record['to']
        used_record = record.copy()
    do_regex = (redir_to is None) and len(redir_rules['redirects'].get("_has_regex", [])) > 0
    if do_regex:
        # Sort by length, longest first
        for k in sorted(redir_rules['redirects']["_has_regex"], key=lambda x: len(x), reverse=True):
            this_regex_c_redir = redir_rules['redirects'][k]
            startsmatch_string = this_regex_c_redir['_startsmatch']
            if len(startsmatch_string) > 0 and not m_path.startswith(startsmatch_string):
                continue
            compiled_regex = this_regex_c_redir['_regex']  # type: regex.Pattern
            (new_path, n) = compiled_regex.subfn(this_regex_c_redir['to'], m_path, concurrent=True)
            if n > 0:
                logger.debug(f"[REDIR] Match regex redirect rule. Substituting redirect to \"{new_path}\"")
                redir_to = new_path
                used_record = this_regex_c_redir.copy()
                break
    if redir_to is None and m_path in redir_rules['conditional_redirects']:
        # Now check for conditional redirects, these are applied only after
        # the static redirects and static regex redirects
        this_records = redir_rules['conditional_redirects'][m_path]
        for this_record in this_records:
            cond = this_record['condition']
            applies = False
            if len(cond) > 0:
                if mediatype is None:
                    mediatype = mediatype_extract(request.headers, query_params, extension)
                if profile is None:
                    profile = profile_extract(request.headers, query_params)
                applies = _evaluate_conditional(cond, profile, mediatype, request)
            if applies:
                redir_to = this_record['to']
                used_record = this_record.copy()
                break
    do_cond_regex = (redir_to is None) and len(redir_rules['conditional_redirects'].get("_has_regex", [])) > 0
    if do_cond_regex:
        # Sort by length, longest first
        for k in sorted(redir_rules['conditional_redirects']["_has_regex"], key=lambda x: len(x), reverse=True):
            this_regex_cond_records = redir_rules['conditional_redirects'][k]
            for this_regex_c_record in this_regex_cond_records:
                startsmatch_string = this_regex_c_record['_startsmatch']
                if len(startsmatch_string) > 0 and not m_path.startswith(startsmatch_string):
                    continue
                cond = this_regex_c_record['condition']
                applies = False
                if len(cond) > 0:
                    if mediatype is None:
                        mediatype = mediatype_extract(request.headers, query_params, extension)
                    if profile is None:
                        profile = profile_extract(request.headers, query_params)
                    applies = _evaluate_conditional(cond, profile, mediatype, request)
                if applies:
                    compiled_regex = this_regex_c_record['_regex']  # type: regex.Pattern
                    (new_path, n) = compiled_regex.subfn(this_regex_c_record['to'], m_path, concurrent=True)
                    if n > 0:
                        redir_to = new_path
                        used_record = this_regex_c_record.copy()
                        break
            if redir_to is not None:
                break
    if redir_to is None or used_record is None:
        return HTMLResponse(f"Not Found; host={host}; path={m_path}", status_code=404)
    elif redir_to.startswith("!"):
        redir_to_dest = redir_to[1:]
        if not redir_to_dest in redir_dests:
            return HTMLResponse(f"Not Found; host={host}; path={m_path}", status_code=404)
        kwargs = {"query_params": query_params}
        if mediatype is not None:
            kwargs["mediatype"] = mediatype
        if profile is not None:
            kwargs["profile"] = profile
        if extension is not None:
            kwargs["extension"] = extension
        kwargs.update(used_record)
        dest_fn = redir_dests[redir_to_dest]
        redir_to = dest_fn(proto, host, path, None, request, **kwargs)
    append_route = used_record.get("append_route", False)
    redir_code = used_record.get("code", use_default_redir_code)
    qsa = used_record.get("qsa", use_default_qsa)
    if append_route:
        redir_to = "/".join((redir_to.rstrip("/"), orig_path))
    if qsa:
        # Append query args to redirect
        _scheme, _netloc, _path, _query, _fragment = urlsplit(redir_to)
        _new_query_params = dict(parse_qsl(_query, keep_blank_values=True))
        query_params.update(_new_query_params)
        _new_query_string = urlencode(query_params, doseq=True)
        redir_to = urlunsplit((_scheme, _netloc, _path, _new_query_string, _fragment))
    logger.debug(f"[REDIRS] Match redirect rule. Redirecting with code {redir_code} to {redir_to}")
    request.state.target_path = redir_to
    return Response(None, status_code=redir_code, headers={"Location": redir_to})
