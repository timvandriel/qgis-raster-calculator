import raster_tools
import xarray as xr
from .layer_manager import LayerManager
from typing import Optional
from .exceptions import RasterToolsUnavailableError, LayerNotFoundError
from .lazy_manager import get_lazy_layer_registry


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
        self.lazy_registry = get_lazy_layer_registry()
        self._raster_cache = {}  # Cache of Raster objects keyed by layer name

    def get_raster(self, name: str) -> Optional[raster_tools.Raster]:
        print(f"get_raster called with name: {name}")
        print(f"Current lazy registry: {self.lazy_registry.all_layers()}")

        if name in self._raster_cache:
            print(f"Returning cached raster for {name}")
            return self._raster_cache[name]

        base_name = name
        if name.endswith(" (Lazy)"):
            base_name = name[:-7]
        print(f"Base name for lazy lookup: {base_name}")

        print(f"Checking lazy registry for base_name: {base_name}")
        has_lazy = self.lazy_registry.has(base_name)
        print(f"lazy_registry.has({base_name}) returned: {has_lazy}")
        if has_lazy:
            print(f"Found lazy layer for base name: {base_name}")
            lazy_layer = self.lazy_registry.get(base_name)
            self._raster_cache[name] = lazy_layer.raster
            return lazy_layer.raster

        # Only fetch QGIS layer if lazy layer not found
        qgis_layer = self.layer_manager.get_raster_layer(name)
        if not qgis_layer:
            raise LayerNotFoundError(f"Layer '{name}' not found in QGIS project.")
        print(f"Found QGIS layer: {name}, source: {qgis_layer.source()}")

        try:
            raster = raster_tools.Raster(qgis_layer.source())
        except Exception as e:
            print(f"Error creating raster_tools.Raster: {e}")
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

    def add_lazy_layer(self, name: str, raster: raster_tools.Raster):
        """
        Adds a raster as a lazy layer to the lazy registry.
        Args:
            name (str): The name of the lazy layer.
            raster (raster_tools.Raster): The raster object to register.
        """
        lazy_layer = self.lazy_registry.register(name, raster)
        return lazy_layer

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
