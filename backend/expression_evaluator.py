import re
import traceback
from qgis.core import QgsMessageLog, Qgis
from .exceptions import InvalidExpressionError
from .raster_manager import RasterManager
from .safe_evaluator import SafeEvaluator
import raster_tools
import xarray as xr
import ast


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
        """
        if not expression:
            return False

        try:
            # Replace quoted layer names with dummy identifiers like r_0, r_1, etc.
            # This makes it syntactically valid Python code
            dummy_names = {}

            def replacer(match):
                name = match.group(1)
                if name not in dummy_names:
                    dummy_names[name] = f"r_{len(dummy_names)}"
                return dummy_names[name]

            expr_cleaned = re.sub(r'"([^"]+)"', replacer, expression)

            # Try parsing the expression
            ast.parse(expr_cleaned, mode="eval")
            return True

        except SyntaxError:
            return False

    @staticmethod
    def reproject_if_needed(raster, target_crs):
        """Check if the raster's CRS matches the target CRS and reproject if necessary.
        Args:
            raster (raster_tools.Raster): The raster object to check.
            target_crs (str): The target CRS in AUTHID format (e.g., "EPSG:4326").
        Returns:
            raster_tools.Raster: The raster object, reprojected if necessary.
        """
        if raster.crs.to_string() == target_crs:
            return raster
        return raster.reproject(crs_or_geobox=target_crs)

    @staticmethod
    def _approx_geobox_area(geobox):
        """
        Estimates the area of a geobox by mulitplying its rows, columns, and pixel size.
        Args:
            geobox (raster_tools.Geobox): The geobox to estimate the area for.
        Returns:
            float: The estimated area of the geobox.
        """
        rows, cols = geobox.shape[0], geobox.shape[1]  # Get number of rows and columns
        px_w, px_h = geobox.affine.a, abs(geobox.affine.e)  # Get pixel width and height
        return rows * cols * px_w * px_h

    def _align_to_smallest_extent(self, rasters: dict):
        """Aligns multiple rasters to the smallest extent by reprojecting them to a common geobox.
        Args:
            rasters (dict): A dictionary of raster names and their corresponding raster objects.
        Returns:
            tuple: A tuple containing the reference raster name and a dictionary of aligned rasters.
        """
        # If only one raster, return it as the reference
        if len(rasters) <= 1:
            return next(iter(rasters)), rasters

        # Find the raster with the smallest geobox area to use as reference
        ref_name, ref_raster = min(
            rasters.items(),
            key=lambda item: self._approx_geobox_area(item[1].geobox),
        )
        # Use the reference raster's geobox for alignment
        ref_grid = ref_raster.geobox
        aligned_rasters = {}

        # Align all rasters to the reference geobox
        for name, raster in rasters.items():
            if ref_grid == raster.geobox:
                aligned_rasters[name] = raster
            else:
                # Reproject
                reprojected = raster.reproject(crs_or_geobox=ref_grid)

                # Wrap dask array in xarray DataArray with coords/dims from reference
                xr_da = xr.DataArray(
                    reprojected.data,
                    coords={
                        "x": ref_raster.xdata.coords["x"],
                        "y": ref_raster.xdata.coords["y"],
                        # Add other coords if necessary
                    },
                    dims=ref_raster.xdata.dims,
                )

                aligned_rasters[name] = raster_tools.Raster(
                    xr_da
                )  # Wrap in Raster object

        return ref_name, aligned_rasters

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

        # Step 4.5a: Reproject rasters if needed to target CRS
        if target_crs_authid:
            raster_objects = {
                name: self.reproject_if_needed(raster, target_crs_authid)
                for name, raster in raster_objects.items()
            }

        # Step 4.5b: Align rasters to the smallest extent
        ref_name, raster_objects = self._align_to_smallest_extent(raster_objects)

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
            parsed = ast.parse(safe_expression, mode="eval")
            evaluator = SafeEvaluator(context)
            result = evaluator.visit(parsed.body)
            return result
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error evaluating expression: {str(e)}\n{traceback.format_exc()}",
                "Lazy Raster Calculator",
                Qgis.Critical,
            )
            raise InvalidExpressionError(str(e))
