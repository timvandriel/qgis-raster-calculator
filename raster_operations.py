import os
import numpy as np
import sys
import traceback
from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsMapLayerType,
    QgsCoordinateReferenceSystem,
    QgsMessageLog,
    Qgis,
)
from qgis.utils import iface
import re
import raster_tools

# Check if raster_tools is available
if raster_tools is None:
    # Handle the case where raster_tools isn't available
    print("Warning: raster_tools is not available. Some features will be disabled.")


def extract_layer_names(expression: str) -> list[str]:
    """
    Extract layer names from the expression.

    Args:
        expression (str): The expression to extract layer names from.

    Returns:
        list[str]: A list of layer names.
    """
    pattern = r'"([^"]+)"'
    layer_names = re.findall(pattern, expression)
    return layer_names


def validate_raster_layer_names(layer_names: list[str]) -> list[str]:
    """Return list of raster layer names that are missing in the project."""
    missing_layers = []
    for name in layer_names:
        matches = QgsProject.instance().mapLayersByName(name)
        if not any(layer.type() == layer.RasterLayer for layer in matches):
            missing_layers.append(name)
    return missing_layers


def is_valid_expression(expression: str) -> bool:
    """
    Check if the expression is syntactically valid.
    Returns True if valid, False otherwise.
    """
    # check if expression is empty
    if not expression:
        return False

    # Check for balanced parentheses
    if expression.count("(") != expression.count(")"):
        return False

    # Remove valid quoted layer names so we can focus on operators
    expr_cleaned = re.sub(r'"[^"]+"', "LAYER", expression)

    # Check for invalid characters (anything that's not LAYER, operator, parens, or space)
    if re.search(r"[^LAYER+\-*/()\s]", expr_cleaned):
        return False

    # Check for consecutive operators (e.g., ++, **, etc.)
    if re.search(r"[\+\-\*/]{2,}", expr_cleaned):
        return False

    # Check for invalid sequences like operator after open paren or before close paren
    if re.search(r"\([+\*/]", expr_cleaned) or re.search(r"[+\*/]\)", expr_cleaned):
        return False

    return True


def get_raster_layer_by_name(name: str):
    """
    Returns the QgsRasterLayer with the given name, or None if not found.
    """
    for layer in QgsProject.instance().mapLayers().values():
        if isinstance(layer, QgsRasterLayer) and layer.name() == name:
            return layer
    return None


def get_raster_objects(layer_names):
    """Takes a list of layer names and returns a dictionary of raster objects."""
    raster_objects = {}
    for name in layer_names:
        layer = get_raster_layer_by_name(name)
        if layer is None:
            continue
        raster_objects[name] = raster_tools.Raster(layer.source())
    return raster_objects


def evaluate_expression(expression: str, raster_objects: dict):
    """
    Evaluate the expression using the raster objects.
    Replaces quoted layer names (e.g., "albedo_5") with safe variable names.
    """
    context = {}
    name_map = {}

    # Map each raster name to a safe variable name
    for i, (name, raster) in enumerate(raster_objects.items()):
        safe_name = f"r_{i}"
        context[safe_name] = raster
        name_map[name] = safe_name

    # Replace quoted layer names in the expression with variable names
    expression = re.sub(
        r'"([^"]+)"', lambda m: name_map.get(m.group(1), m.group(0)), expression
    )

    try:
        result = eval(expression, {"__builtins__": None}, context)
        return result
    except Exception as e:
        QgsMessageLog.logMessage(
            f"Error evaluating expression: {str(e)}\n{traceback.format_exc()}",
            "Lazy Raster Calculator",
            Qgis.Critical,
        )
        return None
