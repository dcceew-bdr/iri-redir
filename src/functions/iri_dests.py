from typing import Optional

from .connegp import profile_extract, mediatype_extract


def apply_prez_curie(ns, localname, prefixes) -> Optional[str]:
    for prefix, ns2 in prefixes.items():
        if ns2 == ns:
            return f"{prefix}:{localname}"
    return None

def uri_to_curie(uri: str, prefixes: dict) -> Optional[str]:
    frag_parts = uri.split("#", 1)
    if len(frag_parts) > 1:
        ns, localname = frag_parts
        ns = ns + "#"
    else:
        path_parts = uri.rsplit("/", 1)
        if len(path_parts) > 1:
            ns, localname = path_parts
            ns = ns + "/"
        else:
            return None
    return apply_prez_curie(ns, localname, prefixes)

HTML_MEDIATYPES = ["text/html", "application/xhtml+xml"]
RDF_MEDIATYPES = ["text/turtle", "application/rdf+xml", "application/ld+json", "application/json"]

def prez_v3_dest(proto, host, path, fragment: Optional[str], request, *, dest_params, **kwargs) -> str:
    # In general, Prezv3 translation does not work with trailing slashes in the path
    # This is because the path splitting will split on the trailing slash
    # and curie generation will not work correctly.
    path = path.rstrip("/")
    if fragment:
        ns = f"{proto}://{host}/{path}#"
        localname = fragment
        uri = ns+localname
    else:
        uri = f"{proto}://{host}/{path}"
        ns, localname = uri.rsplit("/", 1)
        ns = ns+"/"
    query_params = kwargs.get("query_params", {})
    if "extension" in kwargs:
        extension = kwargs["extension"]
    else:
        path_parts = path.rsplit(".", 1)
        if len(path_parts) > 1:
            extension = path_parts[1]
        else:
            extension = None
    if "mediatype" in kwargs:
        mediatype = kwargs["mediatype"]
    else:
        mediatype = mediatype_extract(request.headers, query_params, extension)
    if "profile" in kwargs:
        profile = kwargs["profile"]
    else:
        profile = profile_extract(request.headers, query_params)
    curie: Optional[str] = None
    prefixes: Optional[dict] = kwargs.get("prefixes", dest_params.get("prefixes", None))
    if prefixes:
        curie = apply_prez_curie(ns, localname, prefixes)
    prez_kind = kwargs.get("prez_kind", dest_params.get("prez_kind", None))
    prez_parent = kwargs.get("prez_parent", dest_params.get("prez_parent", None))
    parent_curie: Optional[str] = None
    if prez_parent:
        if prez_parent.startswith("http://") or prez_parent.startswith("https://") or prez_parent.startswith("urn:"):
            parent_curie = uri_to_curie(prez_parent, prefixes)
        elif ":" in prez_parent:
            parent_curie = prez_parent
    if mediatype is None or len(mediatype) < 1:
        prez_end = "backend"
    else:
        # this should already be ordered by highest preference first
        for (q, m) in mediatype:
            if m in HTML_MEDIATYPES:
                prez_end = "frontend"
            elif m in RDF_MEDIATYPES:
                prez_end = "backend"
            else:
                continue
            break
        else:
            prez_end = "backend"
    web_endpoint = kwargs.get("web_endpoint", dest_params.get("web_endpoint", None))
    api_endpoint = kwargs.get("api_endpoint", dest_params.get("api_endpoint", None))
    if web_endpoint is None or api_endpoint is None:
        raise RuntimeError("Web and API endpoints for Prez dest must be specified")

    endpoint_base = web_endpoint if prez_end == "frontend" else api_endpoint
    made_uri: Optional[str] = None
    if curie is not None:
        if prez_kind == "catalog":
            made_uri = f"{endpoint_base}c/catalogs/{curie}"
        elif prez_kind == "resource" and parent_curie is not None:
            made_uri = f"{endpoint_base}c/catalogs/{parent_curie}/resources/{curie}"
        elif prez_kind == "vocab":
            made_uri = f"{endpoint_base}v/vocab/{curie}"
        elif prez_kind == "concept" and parent_curie is not None:
            made_uri = f"{endpoint_base}v/vocab/{parent_curie}/{curie}"
    if not made_uri:
        made_uri = f"{endpoint_base}object?uri={uri}"
    return made_uri

def prez_v4_dest(proto, host, path, fragment: Optional[str], query_args, headers, request, *, dest_params) -> str:
    if fragment:
        ns = f"{proto}://{host}/{path}#"
        localname = fragment
        uri = ns+localname
    else:
        uri = f"{proto}://{host}/{path}"
        ns, localname = uri.rsplit("/", 1)
        ns = ns+"/"
    redir_to = uri
    return redir_to

dest_kind_map = {
    "prez_v3": prez_v3_dest,
    "prez_v4": prez_v4_dest
}