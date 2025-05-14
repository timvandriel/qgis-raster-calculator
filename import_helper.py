"""
Import helper for raster tools and its dependencies
Place this file in your plugin's root directory
"""

import os
import sys
import importlib.util


def get_bundled_module(module_name):
    """
    Import a module from bundled lib directory
    Falls back to system module if bundled one isn't available
    """
    # Try to import from bundled lib directory first
    lib_path = os.path.join(os.path.dirname(__file__), "lib")

    # Check if the module exists in the lib directory
    potential_paths = [
        os.path.join(lib_path, module_name),
        os.path.join(lib_path, module_name.replace("-", "_")),
        os.path.join(lib_path, module_name.replace("_", "-")),
    ]

    module_spec = None
    module_path = None

    for path in potential_paths:
        if os.path.exists(path):
            init_path = os.path.join(path, "__init__.py")
            if os.path.exists(init_path):
                module_spec = importlib.util.spec_from_file_location(
                    module_name, init_path
                )
                module_path = init_path
                break

        # Check for direct .py file
        py_path = f"{path}.py"
        if os.path.exists(py_path):
            module_spec = importlib.util.spec_from_file_location(module_name, py_path)
            module_path = py_path
            break

    if module_spec and module_path:
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        return module

    # Fall back to system module
    try:
        return importlib.import_module(module_name)
    except ImportError:
        raise ImportError(
            f"Could not import {module_name} from either bundled packages or system"
        )


# Only the modules that need to be bundled
raster_tools = get_bundled_module("raster_tools")
dask_geopandas = get_bundled_module(
    "dask_geopandas"
)  # Note the underscore instead of hyphen
dask_image = get_bundled_module("dask_image")  # Note the underscore instead of hyphen
netcdf4 = get_bundled_module("netcdf4")
odc = get_bundled_module("odc")  # Note the underscore instead of hyphen
