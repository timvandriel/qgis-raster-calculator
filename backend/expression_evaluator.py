import re
import traceback
from qgis.core import QgsMessageLog, Qgis
from .exceptions import InvalidExpressionError
from .raster_manager import RasterManager


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
        Checks if the expression is syntactically valid and contains at least one operand.

        Args:
            expression (str): The expression to validate.

        Returns:
            bool: True if valid, False otherwise.
        """
        if not expression:
            return False

        if expression.count("(") != expression.count(")"):
            return False

        # Replace quoted layer names with placeholder
        expr_cleaned = re.sub(r'"[^"]+"', "LAYER", expression)

        # Must contain at least one operand (LAYER)
        if "LAYER" not in expr_cleaned:
            return False

        # Check for invalid layer placement
        if "LAYERLAYER" in expr_cleaned or re.search(r"LAYER\s+LAYER", expr_cleaned):
            return False

        # Ensure only allowed characters remain
        if re.search(r"[^LAYER+\-*/()\s]", expr_cleaned):
            return False

        # Check for multiple consecutive operators
        if re.search(r"[\+\-\*/]{2,}", expr_cleaned):
            return False

        # Invalid start/end of group
        if re.search(r"\([+\*/]", expr_cleaned) or re.search(r"[+\*/]\)", expr_cleaned):
            return False

        # Check for invalid end of expression
        if expr_cleaned.strip()[-1] in "+-*/":
            return False

        # Check for empty parentheses
        if re.search(r"\(\s*\)", expr_cleaned):
            return False

        return True

    def reproject_if_needed(self, raster, target_crs):
        if raster.crs.to_string() == target_crs:
            return raster
        return raster.reproject(crs_or_geobox=target_crs)

    def evaluate(self, expression: str, target_crs_authid: str = None):
        """
        Evaluates a raster expression by:
        - Extracting layer names.
        - Validating their presence in the QGIS project.
        - Validating the expression syntax.
        - Replacing names with safe variable names.
        - Evaluating the expression using `eval()`.

        Args:
            expression (str): The raster math expression, with layer names in quotes.

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

        # Step 4.5: Reproject rasters if needed
        if target_crs_authid:
            raster_objects = {
                name: self.reproject_if_needed(raster, target_crs_authid)
                for name, raster in raster_objects.items()
            }

        # Step 5: Create a safe evaluation context
        context = {}
        name_map = {}

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
            # WARNING: `eval()` is used here and should ideally be replaced with a safer alternative
            result = eval(safe_expression, {"__builtins__": None}, context)
            return result
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error evaluating expression: {str(e)}\n{traceback.format_exc()}",
                "Lazy Raster Calculator",
                Qgis.Critical,
            )
            raise InvalidExpressionError(str(e))
