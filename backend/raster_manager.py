import raster_tools
import xarray as xr
from .layer_manager import LayerManager
from typing import Optional
from .exceptions import RasterToolsUnavailableError, LayerNotFoundError


class RasterManager:
    """
    Manages conversion of QGIS raster layers into `raster_tools.Raster` objects.
    Uses a cache to avoid redundant conversions and improves performance.
    """

    def __init__(self, layer_manager: LayerManager):
        """
        Initializes the RasterManager with a reference to the LayerManager.

        Args:
            layer_manager (LayerManager): The manager used to retrieve QGIS raster layers.
        """
        self.layer_manager = layer_manager
        self._raster_cache = {}  # Cache of Raster objects keyed by layer name

    def get_raster(self, name: str) -> Optional[raster_tools.Raster]:
        """
        Retrieves a lazy `raster_tools.Raster` object for a given raster layer name.

        Args:
            name (str): The name of the raster layer to retrieve.

        Returns:
            raster_tools.Raster or None: A `Raster` object if the layer exists; otherwise, None.
        """
        if name in self._raster_cache:
            return self._raster_cache[name]

        # Attempt to retrieve the corresponding QGIS raster layer
        qgis_layer = self.layer_manager.get_raster_layer(name)
        # If the layer is not found, raise an exception
        if not qgis_layer:
            raise LayerNotFoundError(f"Layer '{name}' not found in QGIS project.")

        try:
            raster = raster_tools.Raster(qgis_layer.source()).astype("float32")
        except Exception as e:
            # Wrap and raise a more informative error if Raster creation fails
            raise RasterToolsUnavailableError(
                f"Failed to create Raster from layer '{name}': {str(e)}"
            )

        self._raster_cache[name] = raster
        return raster

    def get_rasters(self, names: list[str]) -> dict[str, raster_tools.Raster]:
        """
        Retrieves a dictionary of `raster_tools.Raster` objects for a list of layer names.

        Args:
            names (list[str]): List of raster layer names to retrieve.

        Returns:
            dict[str, raster_tools.Raster]: Dictionary mapping names to `Raster` objects.
        """
        rasters = {}
        for name in names:
            raster = self.get_raster(name)
            if raster:
                rasters[name] = raster
            else:
                raise LayerNotFoundError(f"Layer '{name}' not found in QGIS project.")
        return rasters

    def reproject_if_needed(self, raster, target_crs):
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

    def _approx_geobox_area(self, geobox):
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
