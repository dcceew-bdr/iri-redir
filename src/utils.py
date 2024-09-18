# -*- coding: utf-8 -*-
#
"""utils.py"""
import functools
from datetime import datetime, date, timedelta
from asyncio.locks import Lock
from cachetools.keys import hashkey


def do_load_dotenv():
    if do_load_dotenv.completed:
        return True
    from dotenv import load_dotenv
    load_dotenv()
    do_load_dotenv.completed = True
    return True
do_load_dotenv.completed = False


def aiocached(cache, key=hashkey, lock=None):
    """
    Decorator to wrap a function or a coroutine with a memoizing callable
    that saves results in a cache.
    When ``lock`` is provided for a standard function, it's expected to
    implement ``__enter__`` and ``__exit__`` that will be used to lock
    the cache when gets updated. If it wraps a coroutine, ``lock``
    must implement ``__aenter__`` and ``__aexit__``.
    """
    lock = lock or Lock()

    def decorator(func):
        async def wrapper(*args, **kwargs):
            k = key(*args, **kwargs)
            try:
                async with lock:
                    return cache[k]

            except KeyError:
                pass  # key not found

            val = await func(*args, **kwargs)

            try:
                async with lock:
                    cache[k] = val

            except ValueError:
                pass  # val too large

            return val
        new_fn = functools.wraps(func)(wrapper)
        async def update(val, *args, **kwargs):
            k = key(*args, **kwargs)
            try:
                async with lock:
                    cache[k] = val
            except ValueError:
                pass  # val too large
        async def uncache(*args, **kwargs):
            k = key(*args, **kwargs)
            try:
                async with lock:
                    del cache[k]
            except LookupError:
                pass
        setattr(new_fn, "update", update)
        setattr(new_fn, "uncache", uncache)
        setattr(new_fn, "orig_fn", func)
        return new_fn
    return decorator
