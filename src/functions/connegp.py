from typing import Optional, List, Tuple, Mapping

from starlette.datastructures import Headers


def profile_extract(r_headers: Headers, r_query: Mapping[str, str]) -> List[Tuple[float, str]]:
    # QSA takes precedence over Accept-Profile header
    if "_profile" in r_query:
        return [(1.0,r_query['_profile'])]
    ret_list = []
    # Accept-profile disables lookup of "Link" and "Prefer"
    accept_profiles_list = r_headers.getlist("accept-profile")
    if len(accept_profiles_list) > 0:
        all_accept_profile = []
        _ = [all_accept_profile.extend((a.strip() for a in ap.split(','))) for ap in accept_profiles_list]
        for ap in all_accept_profile:
            q = 1.0
            parts = [x.strip() for x in ap.split(';')]
            profile = parts.pop(0)
            for p in parts:
                if p.startswith("q="):
                    try:
                        q = float(p[2:])
                    except ValueError:
                        q = 0.0
                    break
            ret_list.append((q, profile))
    if len(ret_list) < 1:
        link_list = r_headers.getlist("link")
        if len(link_list) > 1:
            all_link_list = []
            _ = [all_link_list.extend((l.strip() for l in ll.split(','))) for ll in link_list]
            for lp in all_link_list:
                is_rel_profile = False
                parts = [x.strip() for x in lp.split(';')]
                href = parts.pop(0)
                for p in parts:
                    p_lower = p.lower()
                    if p_lower in ("rel=\"profile\"", "rel='profile'", "rel=profile"):
                        is_rel_profile = True
                        break
                if is_rel_profile:
                    ret_list.append((1.0, href.strip("<>\"'")))
    if len(ret_list) < 1:
        prefer_list = r_headers.getlist("prefer")
        if len(prefer_list) > 0:
            all_prefer_list = []
            _ = [all_prefer_list.extend((p.strip() for p in pl.split(','))) for pl in prefer_list]
            for p in all_prefer_list:
                parts = [x.strip() for x in p.split(';')]
                for p in parts:
                    p_lower = p.lower()
                    if p_lower.startswith("profile="):
                        try:
                            found_profile = str(p[8:])
                            ret_list.append((1.0, found_profile.strip("<>\"'")))
                        except (LookupError, ValueError):
                            pass
                        else:
                            break
    if len(ret_list) < 1 and "_view" in r_query:
        # View is an old LDAPI form of "_profile"
        return [(1.0,r_query['_view'])]
    return sorted(ret_list, reverse=True)

EXT_TO_MEDIATYPE = {
    "ttl": "text/turtle",
    "jsonld": "application/json-ld",
    "json": "application/json",
    "xml": "application/xml",
    "n3": "text/n3",
}


def mediatype_extract(r_headers: Headers, r_query: Mapping[str, str], f_ext: Optional[str]) -> List[Tuple[float, str]]:
    # QSA takes precedence over Accept header
    if "_mediatype" in r_query:
        return [(1.0,r_query['_mediatype'])]
    ret_list = []
    # Accept header disables lookup of "Prefer"
    accept_content_list = r_headers.getlist("accept")
    has_wildcard: Optional[str] = None
    if len(accept_content_list) > 0:
        all_accept_content = []
        _ = [all_accept_content.extend((a.strip() for a in ac.split(','))) for ac in accept_content_list]

        for ap in all_accept_content:
            q = 1.0
            parts = [x.strip() for x in ap.split(';')]
            profile = parts.pop(0)
            for p in parts:
                if p.startswith("q="):
                    try:
                        q = float(p[2:])
                    except ValueError:
                        q = 0.0
                    break
            if profile == "*/*" or profile == "*" and q == 1.0:
                has_wildcard = profile
            else:
                ret_list.append((q, profile))
    if len(ret_list) < 1:
        prefer_list = r_headers.getlist("prefer")
        if len(prefer_list) > 0:
            all_prefer_list = []
            _ = [all_prefer_list.extend((p.strip() for p in pl.split(','))) for pl in prefer_list]
            for p in all_prefer_list:
                parts = [x.strip() for x in p.split(';')]
                for p in parts:
                    p_lower = p.lower()
                    if p_lower.startswith("mediatype="):
                        try:
                            found_profile = str(p[8:])
                            ret_list.append((1.0, found_profile.strip("<>\"'")))
                        except (LookupError, ValueError):
                            pass
                        else:
                            break
    if len(ret_list) < 1 and "_format" in r_query:
        # _format is an old version of "_mediatype"
        return [(1.0,r_query['_format'])]
    elif len(ret_list) < 1 and f_ext is not None:
        if f_ext in EXT_TO_MEDIATYPE:
            return [(1.0, EXT_TO_MEDIATYPE[f_ext])]
    elif len(ret_list) < 1 and has_wildcard is not None:
        return [(1.0, has_wildcard)]
    return sorted(ret_list, reverse=True)