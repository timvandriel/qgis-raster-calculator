import re
import traceback
from qgis.core import QgsMessageLog, Qgis
from .exceptions import LayerNotFoundError, InvalidExpressionError
from .raster_manager import RasterManager


class ExpressionEvaluator:
    def __init__(self, raster_manager: RasterManager):
        self.raster_manager = raster_manager

    @staticmethod
    def extract_layer_names(expression: str) -> list[str]:
        pattern = r'"([^"]+)"'
        return re.findall(pattern, expression)

    @staticmethod
    def is_valid_expression(expression: str) -> bool:
        if not expression:
            return False
        if expression.count("(") != expression.count(")"):
            return False

        expr_cleaned = re.sub(r'"[^"]+"', "LAYER", expression)

        if "LAYERLAYER" in expr_cleaned or re.search(r"LAYER\s+LAYER", expr_cleaned):
            return False

        if re.search(r"[^LAYER+\-*/()\s]", expr_cleaned):
            return False

        if re.search(r"[\+\-\*/]{2,}", expr_cleaned):
            return False

        if re.search(r"\([+\*/]", expr_cleaned) or re.search(r"[+\*/]\)", expr_cleaned):
            return False

        return True

    def evaluate(self, expression: str):
        layer_names = self.extract_layer_names(expression)
        missing = self.raster_manager.layer_manager.validate_layer_names(layer_names)
        if missing:
            raise LayerNotFoundError(missing)

        if not self.is_valid_expression(expression):
            raise InvalidExpressionError("Expression syntax is invalid")

        raster_objects = self.raster_manager.get_rasters(layer_names)
        context = {}
        name_map = {}

        for i, (name, raster) in enumerate(raster_objects.items()):
            safe_name = f"r_{i}"
            context[safe_name] = raster
            name_map[name] = safe_name

        safe_expression = re.sub(
            r'"([^"]+)"', lambda m: name_map.get(m.group(1), m.group(0)), expression
        )

        try:
            # Potential improvement: Replace eval with a sandboxed evaluator
            result = eval(safe_expression, {"__builtins__": None}, context)
            return result
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error evaluating expression: {str(e)}\n{traceback.format_exc()}",
                "Lazy Raster Calculator",
                Qgis.Critical,
            )
            raise InvalidExpressionError(str(e))
