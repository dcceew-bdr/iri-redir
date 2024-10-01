from functools import partial
from pathlib import Path
from logging import getLogger
from tomli import load as load_toml
import regex

from .. import settings
from .iri_dests import dest_kind_map

logger = getLogger()  # Root logger

TRUTH_VALUES = (True, "true", 1, "1", "t", "yes")

def find_regex_startsmatch(re_string: str):
    if re_string.startswith('^'):
        re_string = re_string[1:]
    startsmatch_string = ""
    for c in re_string:
        if c in "^$.[](){}|*+?\\":
            continue
        startsmatch_string += c
    return startsmatch_string.lower()

def load_all_defs(state: dict, force: bool = False):
    try:
        defs_ctx = state["defs"]
    except LookupError:
        state["defs"] = defs_ctx = {}
    try:
        dests_ctx = state["dests"]
    except LookupError:
        state["dests"] = dests_ctx = {}
    logger.info("[REDIRS] Loading definition files.")
    if len(defs_ctx) < 1:
        defs_ctx[""] = {"redirects": {}, "rewrites": {}, "conditional_rewrites": {}, "conditional_redirects":{}, "_default_redir_code": 307}
        defs_ctx["_file_mtimes"] = {}
    defs_dir = Path(settings["CONFIG_DEFS_DIRECTORY"]).absolute()
    logger.info("[REDIRS] Using definition directory: "+str(defs_dir))
    if not defs_dir.exists():
        raise RuntimeError(f"Directory {defs_dir} does not exist!")
    if not defs_dir.is_dir():
        raise RuntimeError(f"Directory {defs_dir} is not a directory!")
    for conf_filename in defs_dir.glob("*.toml"):
        conf_file = conf_filename.absolute()
        try:
            stats = conf_file.stat()
            mtime = stats.st_mtime
        except Exception:
            logger.info("Cannot get file modification date. Ignoring.")
            mtime = 1
        try:
            old_mtime = defs_ctx['_file_mtimes'][conf_file]
        except LookupError:
            old_mtime = 0
        if not force and (mtime <= old_mtime):
            logger.debug(f"[REDIRS] File not modified. {conf_file}")
            continue
        else:
            defs_ctx['_file_mtimes'][conf_file] = mtime

        try:
            f = open(conf_file, "rb")
        except Exception:
            logger.error(f"[REDIRS] Cannot open {conf_file}!")
            raise

        try:
            this_def = load_toml(f)
            logger.info(f"[REDIRS] Reading {conf_file}")
        except Exception as e:
            logger.error(f"[REDIRS] Cannot read or load {conf_file}.")
            logger.exception(f"Error reading or loading {conf_file}:")
            continue
        finally:
            f.close()

        default_redir_code = 307
        default_route_prefix = '/'
        default_allow_slash = False
        virtualhost = None
        host_aliases = []
        default_qsa = False
        if 'default' in this_def:
            if 'code' in this_def['default']:
                default_redir_code = int(this_def['default']['code'])
            if 'virtualhost' in this_def['default']:
                virtualhost = this_def['default']['virtualhost']
            if 'route_prefix' in this_def['default']:
                default_route_prefix = this_def['default']['route_prefix']
            if 'host_aliases' in this_def['default']:
                host_aliases = this_def['default']['host_aliases']
            if 'allow_slash' in this_def['default']:
                default_allow_slash_lit = this_def['default']['allow_slash']
                default_allow_slash = default_allow_slash_lit in TRUTH_VALUES
            if 'qsa' in this_def['default']:
                default_qsa_lit = this_def['default']['qsa']
                default_qsa = default_qsa_lit in TRUTH_VALUES
        if virtualhost is None or virtualhost == "@" or virtualhost == "":
            logger.info("[REDIRS] Loading definitions for Default host")
            virtualhost = ""
        else:
            logger.info(f"[REDIRS] Loading definitions for virtualhost: {virtualhost}")
        if virtualhost in defs_ctx:
            logger.info("[REDIRS] Appending redirect rules to existing host rules.")
            host_def = defs_ctx[virtualhost]
        else:
            defs_ctx[virtualhost] = host_def = {"redirects": {}, "rewrites": {}, "conditional_redirects": {}, "conditional_rewrites": {}}

        for alias in host_aliases:
            if alias in defs_ctx:
                if not defs_ctx[alias] is host_def:
                    logger.error(f"[REDIRS] Host alias {alias} already exists for a different virtualhost!")
                continue
            defs_ctx[alias] = host_def
        host_def['_default_redir_code'] = default_redir_code
        host_def['_default_qsa'] = default_qsa

        if 'redirects' in this_def:
            has_regex = []
            has_conditional_regex = []
            for k, v in this_def['redirects'].items():
                is_conditional = False
                # redirect is just a string
                if isinstance(v, (bytes, str)):
                    new_entry = {"to": v}
                    pfx = default_route_prefix
                elif isinstance(v, dict):
                    new_entry = v
                    if "to" not in v:
                        raise RuntimeError(f"Value for redirect {k} does not have 'to' value.")
                    pfx = v.get('route_prefix', default_route_prefix)
                    if "condition" in v:
                        is_conditional = True
                    if "from" in v:
                        k = v['from']
                        if not is_conditional and k in host_def['redirects']:
                            raise RuntimeError(f"Non-Conditional redirect rule: {k} already exists.")
                else:
                    raise RuntimeError(f"Bad redirect value for {k}")
                kind = new_entry.get("kind", "simple")

                if str(kind).lower() == "regex":
                    try:
                        new_entry['_regex'] = regex.compile(k, flags=regex.IGNORECASE)
                    except regex.error as e:
                        logger.warning(f"Cannot compile regex. Error:\n{str(e)}")
                        continue
                    startsmatch_string = find_regex_startsmatch(k)
                    new_entry['_startsmatch'] = startsmatch_string
                    if is_conditional:
                        has_conditional_regex.append(k)
                    else:
                        has_regex.append(k)
                    allow_slash = False
                else:
                    allow_slash = new_entry.get("allow_slash", default_allow_slash)
                match_route = '/'.join((pfx.rstrip('/'), k)).lstrip('/')
                if allow_slash:
                    # Remove the trailing slash, so we can a second one
                    # with the trailing slash added
                    match_route = match_route.rstrip('/')
                    match_routes = [match_route, match_route+'/']
                else:
                    match_routes = [match_route]

                if is_conditional:
                    for match_route in match_routes:
                        if match_route not in host_def['conditional_redirects']:
                            host_def['conditional_redirects'][match_route] = []
                        host_def['conditional_redirects'][match_route].append(new_entry)
                        logger.debug(
                            f"[REDIRS] Assigned conditional redirect: \"{match_route}\" -> \"{new_entry['to']}\""
                        )
                else:
                    for match_route in match_routes:
                        host_def['redirects'][match_route] = new_entry
                        logger.debug(f"[REDIRS] Assigned redirect: \"{match_route}\" -> \"{new_entry['to']}\"")
            host_def['redirects']["_has_regex"] = has_regex
            host_def['conditional_redirects']["_has_regex"] = has_conditional_regex
        if 'rewrites' in this_def:
            has_regex = []
            has_conditional_regex = []
            for k, v in this_def['rewrites'].items():
                is_conditional = False
                # rewrite is just a string
                if isinstance(v, (bytes, str)):
                    new_entry = {"to": v}
                elif isinstance(v, dict):
                    new_entry = v
                    if "to" not in v:
                        raise RuntimeError(f"Value for rewrite {k} does not have 'to' value.")
                    if "condition" in v:
                        is_conditional = True
                    if "from" in v:
                        k = v['from']
                        if not is_conditional and k in host_def['rewrites']:
                            raise RuntimeError(f"Non-Conditional rewrite rule: {k} already exists.")
                else:
                    raise RuntimeError(f"Bad rewrite value for {k}")
                kind = new_entry.get("kind", "simple")
                if str(kind).lower() == "regex":
                    try:
                        new_entry['_regex'] = regex.compile(k, flags=regex.IGNORECASE)
                    except regex.error as e:
                        logger.warning(f"Cannot compile regex. Error:\n{str(e)}")
                        continue
                    startsmatch_string = find_regex_startsmatch(k)
                    new_entry['_startsmatch'] = startsmatch_string
                    if is_conditional:
                        has_conditional_regex.append(k)
                    else:
                        has_regex.append(k)
                if is_conditional:
                    if k not in host_def['conditional_rewrites']:
                        host_def['conditional_rewrites'][k] = []
                    host_def['conditional_rewrites'][k].append(new_entry)
                    logger.debug(f"[REDIRS] Assigned conditional rewrite: \"{k}\" -> \"{new_entry['to']}\"")
                else:
                    host_def['rewrites'][k] = new_entry
                    logger.debug(f"[REDIRS] Assigned rewrite: \"{k}\" -> \"{new_entry['to']}\"")
            host_def['rewrites']["_has_regex"] = has_regex
            host_def['conditional_rewrites']["_has_regex"] = has_regex
        if 'dests' in this_def:
            for name, desc in this_def['dests'].items():
                if 'name' in dests_ctx:
                    raise RuntimeError(f"Destination name {name} already defined!")
                if 'kind' not in desc:
                    raise RuntimeError(f"Destination {name} does not have a 'kind' value.")
                kind = desc['kind']
                if kind not in dest_kind_map:
                    raise RuntimeError(f"Destination {name} has an unknown 'kind' value: {kind}")
                dest_fn = dest_kind_map[kind]
                parameterized_dest_fn = partial(dest_fn, dest_params=desc)
                dests_ctx[name] = parameterized_dest_fn
