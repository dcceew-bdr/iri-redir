"""
Implements the factory pattern for creating the Starlette app
"""
from contextlib import asynccontextmanager
from functools import partial
from typing import Optional, List

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route, Mount, Router
from starlette.applications import Starlette
from ._settings import settings
from .routers import make_all_iri_redirect_routes

async def multi_lifespan(lifespan_contexts: List, app):
    state = {}
    try:
        for lifespan_context in lifespan_contexts:
            async with lifespan_context(app) as maybe_state:
                if maybe_state is not None:
                    state.update(maybe_state)
        yield state
    finally:
        # cleanup
        pass

def create_app(
    *,  # All parameters are keyword-only
    root_path: str = "",
    # if True, we don't return a Starlette app, only an ASGI Router
    router_only: bool = False,
    **kwargs
):
    route_makers = [make_all_iri_redirect_routes]

    routes = []
    lifespan_contexts = []

    for route_maker in route_makers:
        prefix, this_routes, lifespan_context = route_maker()
        if prefix is not None and not (prefix is "" or prefix is "/"):
            this_routes = [Mount(prefix, None, this_routes)]
        routes.extend(this_routes)
        if lifespan_context is not None:
            lifespan_contexts.append(lifespan_context)
    if len(lifespan_contexts) > 0:
        lifespan_fn = partial(multi_lifespan, lifespan_contexts)
        lifespan = asynccontextmanager(lifespan_fn)
    else:
        lifespan = None
    middlewares = [Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )]

    if root_path is not None and not (root_path is "" or root_path is "/"):
        routes = [Mount(root_path, None, routes, "root")]
    if router_only:
        return Router(routes=routes, lifespan=lifespan, middleware=middlewares, **kwargs)

    app = Starlette(
        debug=settings["DEBUG_APP"],
        routes=routes,
        middleware=middlewares,
        lifespan=lifespan,
        **kwargs
    )
    return app