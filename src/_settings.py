# Note, this is not the same as configs.
# This file is for Starlette and Function App settings
# The configs for configuring redirects are in the /configs directory


# -*- coding: utf-8 -*-
#
import sys
from os import getenv
from .utils import do_load_dotenv


do_load_dotenv()

undef = object()

module = sys.modules[__name__]
defaults = module.defaults = {
    "SERVER_NAME": "localhost",
    "FUNCTION_APP_AUTH_LEVEL": "FUNCTION",
    "CONFIG_DEFS_DIRECTORY": "./configs",
    "APP_BASE_ROUTE": "/",
    "DEBUG_APP": "false",
    "WATCH_CONFIGS": "false",
    "WATCH_CONFIGS_INTERVAL": "300",
}
settings = module.settings = dict()

settings['SERVER_NAME'] = getenv("SERVER_NAME", None)
settings['FUNCTION_APP_AUTH_LEVEL'] = getenv("FUNCTION_APP_AUTH_LEVEL", None)
settings['CONFIG_DEFS_DIRECTORY'] = getenv("CONFIG_DEFS_DIRECTORY", None)
settings['APP_BASE_ROUTE'] = getenv("APP_BASE_ROUTE", None)
settings['DEBUG_APP'] = getenv("DEBUG_APP", None)
settings['WATCH_CONFIGS'] = getenv("WATCH_CONFIGS", None)
settings['WATCH_CONFIGS_INTERVAL'] = getenv("WATCH_CONFIGS_INTERVAL", None)

# Apply default values for options that are not defined in ENVs
for k, v in defaults.items():
    if k not in settings or settings[k] is None:
        if v is undef:
            raise RuntimeError(f"No default value available for config key \"{k}\"")
        settings[k] = v
