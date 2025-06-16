import re
import traceback
from qgis.core import QgsMessageLog, Qgis
from .exceptions import InvalidExpressionError
from .raster_manager import RasterManager
from .safe_evaluator import SafeEvaluator
import raster_tools
import ast
import numpy as np


class ExpressionEvaluator:
    """
    Responsible for parsing and evaluating raster expressions using layer names and Raster objects.
    """

    def __init__(self, raster_manager: RasterManager):
        """
        Initializes the ExpressionEvaluator with a reference to a RasterManager.

        Args:
            raster_manager (RasterManager): Manages loading raster layers as Raster objects.
        """
        self.raster_manager = raster_manager

    @staticmethod
    def extract_layer_names(expression: str) -> list[str]:
        """
        Extracts all raster layer names enclosed in double quotes from the expression.

        Args:
            expression (str): A mathematical expression with quoted raster layer names.

        Returns:
            list[str]: A list of layer names found in the expression.
        """
        pattern = r'"([^"]+)"'
        return re.findall(pattern, expression)

    @staticmethod
    def is_valid_expression(expression: str) -> bool:
        """
        Validates the expression syntax using Python's AST parser.
        Replaces quoted layer names with valid identifiers before parsing.
        Also checks for invalid syntax such as adjacent quoted layer names.
        """
        if not expression:
            return False

        # Check for adjacent quoted layer names with no operator between them
        adjacent_layer_pattern = r'"[^"]+"\s*"[^"]+"'
        if re.search(adjacent_layer_pattern, expression):
            return False  # Found two quoted names with no operator in between

        try:
            # Replace quoted layer names with dummy identifiers like r_0, r_1, etc.
            dummy_names = {}

            def replacer(match):
                name = match.group(1)
                if name not in dummy_names:
                    dummy_names[name] = f"r_{len(dummy_names)}"
                return dummy_names[name]

            expr_cleaned = re.sub(r'"([^"]+)"', replacer, expression)

            # Try parsing the cleaned expression
            ast.parse(expr_cleaned, mode="eval")
            return True

        except SyntaxError:
            return False

    def evaluate(
        self,
        expression: str,
        target_crs_authid: str = None,
        d_type: str = "<AUTO>",
    ):
        """
        Evaluates a raster expression by:
        - Extracting layer names.
        - Validating their presence in the QGIS project.
        - Validating the expression syntax.
        - Replacing names with safe variable names.
        - Evaluating the expression using `eval()`.

        Args:
            expression (str): The raster math expression, with layer names in quotes.
            target_crs_authid (str, optional): The target CRS authority ID for reprojection.
            d_type (str, optional): The data type to cast the resulting raster to. Defaults to "<AUTO>".

        Returns:
            raster_tools.Raster: The resulting lazily-evaluated raster object.

        Raises:
            LayerNotFoundError: If any raster layers are missing from the project.
            InvalidExpressionError: If the expression syntax is invalid or fails evaluation.
        """
        # Step 1: Extract layer names from the expression
        layer_names = self.extract_layer_names(expression)

        # Step 2: Validate that all layer names exist in the project
        self.raster_manager.layer_manager.validate_layer_names(layer_names)

        # Step 3: Validate the expression syntax
        if not self.is_valid_expression(expression):
            raise InvalidExpressionError("Expression syntax is invalid.")

        # Step 4: Retrieve Raster objects for all layers
        raster_objects = self.raster_manager.get_rasters(layer_names)

        # Step 4.5a: Reproject rasters if needed to target CRS
        if target_crs_authid:
            raster_objects = {
                name: self.raster_manager.reproject_if_needed(raster, target_crs_authid)
                for name, raster in raster_objects.items()
            }

        # Step 4.5b: Align rasters to the smallest extent
        ref_name, raster_objects = self.raster_manager._align_to_smallest_extent(
            raster_objects
        )
        # Step 4.5c: Cast to data type if specified
        d_type = self.raster_manager.get_dtype(d_type)
        if d_type != "<AUTO>":
            raster_objects = {
                name: raster.astype(d_type) for name, raster in raster_objects.items()
            }

        # Step 5: Create a safe evaluation context
        context = {}  # maps safe variable names to Raster objects
        name_map = {}  # maps original layer names to safe variable names

        for i, (name, raster) in enumerate(raster_objects.items()):
            safe_name = f"r_{i}"  # Create safe variable name
            context[safe_name] = raster
            name_map[name] = safe_name

        # Replace layer names in expression with safe variable names
        safe_expression = re.sub(
            r'"([^"]+)"', lambda m: name_map.get(m.group(1), m.group(0)), expression
        )

        try:
            # Step 6: Evaluate the expression
            evaluator = SafeEvaluator(
                context
            )  # Initialize the safe evaluator with context
            result = evaluator.evaluate(
                safe_expression
            )  # Evaluate the expression safely
            return result
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error evaluating expression: {str(e)}\n{traceback.format_exc()}",
                "Lazy Raster Calculator",
                Qgis.Critical,
            )
            raise InvalidExpressionError(str(e))
