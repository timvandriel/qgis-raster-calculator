#!/usr/bin/env python3
"""
Script to bundle raster tools and its dependencies into a QGIS plugin
Run this script from your plugin's root directory
"""

import os
import sys
import shutil
import subprocess
import tempfile
import importlib
import pkgutil

# Configuration - adjust as needed
PACKAGE_NAME = "raster-tools"  # Note: Package name uses hyphen, not underscore
MODULE_NAME = "raster_tools"  # But the module imported uses underscore

# Dependencies directly from defaults.txt
DEPENDENCIES = [
    "affine",
    "cfgrib",
    "dask",
    "dask-geopandas",
    "dask-image",
    "fiona",
    "geopandas",
    "netcdf4",
    "numba",
    "numpy>=1.22",
    "odc-geo",
    "pandas",
    "pyogrio",
    "pyproj",
    "rioxarray",
    "rasterio",
    "scipy",
    "shapely>=2.0",
    "xarray",
]


# Set up directory structure
def setup_directories():
    """Create the necessary directory structure for bundled packages"""
    lib_dir = os.path.join(os.getcwd(), "lib")
    if not os.path.exists(lib_dir):
        os.makedirs(lib_dir)

    # Create __init__.py to make it a package
    init_file = os.path.join(lib_dir, "__init__.py")
    if not os.path.exists(init_file):
        with open(init_file, "w") as f:
            f.write("# This file makes the lib directory a Python package\n")

    return lib_dir


def check_qgis_packages():
    """Check which packages are already available in QGIS Python environment"""
    available_packages = {}

    for dep in DEPENDENCIES + [PACKAGE_NAME]:
        # Handle version requirements by stripping them for the import check
        dep_name = dep.split(">=")[0].split("==")[0].split("<")[0].strip()
        try:
            # Try to import the module
            module = importlib.__import__(dep_name)
            version = getattr(module, "__version__", "unknown")
            available_packages[dep_name] = version
            print(f"✓ {dep_name} {version} is already available in QGIS")
        except ImportError:
            print(f"✗ {dep_name} is not available in QGIS and will be bundled")

    return available_packages


def download_package(package_name, target_dir):
    """Download a package and its dependencies to the target directory"""
    temp_dir = tempfile.mkdtemp()
    print(f"Downloading {package_name} to {target_dir}...")

    try:
        # Use pip to download the package and dependencies
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                target_dir,
                "--no-deps",  # We'll handle dependencies separately
                package_name,
            ],
            check=True,
        )
        print(f"Successfully installed {package_name}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to install {package_name}: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def update_plugin_init():
    """Update the plugin's __init__.py to include the lib directory in sys.path"""
    init_file = os.path.join(os.getcwd(), "__init__.py")

    if not os.path.exists(init_file):
        print("Warning: __init__.py not found in plugin directory")
        return

    with open(init_file, "r") as f:
        content = f.read()

    # Check if the path insertion code is already there
    if "lib_path = os.path.join(os.path.dirname(__file__), 'lib')" in content:
        print("__init__.py already has lib path insertion code")
        return

    # Add the code to include lib directory in sys.path
    with open(init_file, "w") as f:
        # Add imports if they don't already exist
        if "import os" not in content:
            content = "import os\n" + content
        if "import sys" not in content:
            content = "import sys\n" + content

        # Add path insertion code before any other code
        path_code = """
# Add bundled packages to Python path
lib_path = os.path.join(os.path.dirname(__file__), 'lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)
"""
        insertion_point = max(
            content.find("\n\n"),  # After initial imports
            content.find("def "),  # Before first function
            0,  # Fallback to start of file
        )

        new_content = content[:insertion_point] + path_code + content[insertion_point:]
        f.write(new_content)

    print("Updated __init__.py to include lib directory in Python path")


def create_import_helper():
    """Create an import helper file to easily access bundled modules"""
    helper_file = os.path.join(os.getcwd(), "import_helper.py")

    with open(helper_file, "w") as f:
        f.write(
            """\"\"\"
Import helper for raster tools and its dependencies
Place this file in your plugin's root directory
\"\"\"

import os
import sys
import importlib.util
import importlib.metadata

def get_bundled_module(module_name):
    \"\"\"
    Import a module from bundled lib directory
    Falls back to system module if bundled one isn't available
    
    Args:
        module_name: Name of the module to import
        
    Returns:
        The imported module
    \"\"\"
    # Try to import from bundled lib directory first
    lib_path = os.path.join(os.path.dirname(__file__), 'lib')
    
    # Check if the module exists in the lib directory
    potential_paths = [
        os.path.join(lib_path, module_name),
        os.path.join(lib_path, module_name.replace('-', '_')),
        os.path.join(lib_path, module_name.replace('_', '-'))
    ]
    
    module_spec = None
    module_path = None
    
    for path in potential_paths:
        if os.path.exists(path):
            init_path = os.path.join(path, '__init__.py')
            if os.path.exists(init_path):
                module_spec = importlib.util.spec_from_file_location(module_name, init_path)
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
        raise ImportError(f"Could not import {module_name} from either bundled packages or system")

# Main raster tools module and commonly used dependencies
raster_tools = get_bundled_module('raster_tools')
numpy = get_bundled_module('numpy')
xarray = get_bundled_module('xarray')
pandas = get_bundled_module('pandas')
shapely = get_bundled_module('shapely')
"""
        )

    print(f"Created import helper at {helper_file}")


def optimize_dependencies():
    """
    Check for dependencies that might be already included in QGIS
    and filter out any redundant or unnecessary ones
    """
    # QGIS often includes these packages
    qgis_included = ["numpy", "pandas", "scipy", "shapely", "gdal"]

    # Ask user which dependencies to skip if they're already in QGIS
    print("\nQGIS typically includes several Python packages.")
    print("You may choose to skip bundling packages that are likely included in QGIS.")
    print("This can reduce the size of your plugin significantly.")

    skip_common = (
        input(
            "Would you like to skip bundling common packages already in QGIS? (y/n): "
        ).lower()
        == "y"
    )

    if skip_common:
        return [
            dep
            for dep in DEPENDENCIES
            if dep.split(">=")[0].split("==")[0].split("<")[0].strip()
            not in qgis_included
        ]
    else:
        return DEPENDENCIES


def main():
    """Main function to bundle raster tools and its dependencies"""
    print("Starting dependency bundling for QGIS plugin...")

    # Set up directory structure
    lib_dir = setup_directories()

    # Check what packages are already available in QGIS
    available_packages = check_qgis_packages()

    # Ask about optimizing dependencies
    optimized_deps = optimize_dependencies()

    # Download raster tools package
    if MODULE_NAME not in available_packages:
        download_package(PACKAGE_NAME, lib_dir)

    # Download dependencies
    deps_to_install = []
    for dep in optimized_deps:
        # Extract the base package name without version specifiers
        dep_name = dep.split(">=")[0].split("==")[0].split("<")[0].strip()
        if dep_name not in available_packages:
            deps_to_install.append(dep)

    # Show summary before proceeding
    print(f"\nWill install {len(deps_to_install)} packages:")
    for dep in deps_to_install:
        print(f"  - {dep}")

    proceed = input("\nProceed with installation? (y/n): ").lower() == "y"
    if not proceed:
        print("Installation cancelled.")
        return

    # Install dependencies
    for dep in deps_to_install:
        download_package(dep, lib_dir)

    # Update plugin's __init__.py
    update_plugin_init()

    # Create import helper
    create_import_helper()

    print("\nCompleted bundling dependencies.")
    print("Your plugin now includes raster tools and its dependencies.")
    print("\nTo use raster tools in your code:")
    print("from .import_helper import raster_tools, numpy, xarray")
    print("\nMake sure to test the plugin thoroughly before distribution.")


if __name__ == "__main__":
    main()
