"""Carrier-mod generator framework (P0-DATATOOLS). Entry point: ``gen/run.py``.

See ``gen/framework/README.md`` for the plugin interface.
"""
from .core import (RESOURCE_DLL, Context, GenError, Generator, build, deploy, discover,
                   run_validate, undeploy)
from .strings import StringsError, StringsRegistry

__all__ = ["Context", "Generator", "GenError", "RESOURCE_DLL", "StringsError",
           "StringsRegistry", "build", "deploy", "discover", "run_validate", "undeploy"]
