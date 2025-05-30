# This file is part of the Open Data Cube, see https://opendatacube.org for more information
#
# Copyright (c) 2015-2020 ODC Contributors
# SPDX-License-Identifier: Apache-2.0
"""
Add ``.odc.`` extension to :py:class:`xarray.Dataset` and :class:`xarray.DataArray`.
"""

from __future__ import annotations

import functools
import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    Hashable,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    TypeVar,
    Union,
)

import numpy
import xarray
from affine import Affine

from ._interop import have, is_dask_collection
from ._rgba import colorize, to_rgba
from .crs import CRS, CRSError, SomeCRS, norm_crs_or_error
from .gcp import GCPGeoBox, GCPMapping
from .geobox import Coordinate, GeoBox, GeoboxAnchor
from .geom import Geometry
from .math import (
    affine_from_axis,
    approx_equal_affine,
    is_affine_st,
    is_nodata_empty,
    maybe_int,
    resolution_from_affine,
    resolve_fill_value,
    resolve_nodata,
)
from .overlap import compute_output_geobox
from .roi import roi_is_empty
from .types import Nodata, Resolution, SomeNodata, SomeResolution, SomeShape, Unset, xy_

# pylint: disable=import-outside-toplevel
# pylint: disable=too-many-lines
if have.rasterio:
    from ._compress import compress
    from ._map import add_to, explore
    from .cog import to_cog, write_cog
    from .warp import rio_reproject

XarrayObject = Union[xarray.DataArray, xarray.Dataset]
XrT = TypeVar("XrT", xarray.DataArray, xarray.Dataset)
F = TypeVar("F", bound=Callable)
SomeGeoBox = Union[GeoBox, GCPGeoBox]

_DEFAULT_CRS_COORD_NAME = "spatial_ref"

# these attributes are pruned during reproject
SPATIAL_ATTRIBUTES = ("crs", "crs_wkt", "grid_mapping", "gcps", "epsg")
NODATA_ATTRIBUTES = ("nodata", "_FillValue")
REPROJECT_SKIP_ATTRS: set[str] = set(SPATIAL_ATTRIBUTES + NODATA_ATTRIBUTES)

# dimensions with these names are considered spatial
STANDARD_SPATIAL_DIMS = [
    ("y", "x"),
    ("yc", "xc"),
    ("latitude", "longitude"),
    ("lat", "lon"),
]

_NoValue = Unset()


@dataclass
class GeoState:
    """
    Geospatial information for xarray object.
    """

    spatial_dims: Optional[Tuple[str, str]] = None
    crs_coord: Optional[xarray.DataArray] = None
    transform: Optional[Affine] = None
    crs: Optional[CRS] = None
    geobox: Optional[SomeGeoBox] = None
    gcp: Optional[GCPMapping] = None


def _get_crs_from_attrs(obj: XarrayObject, sdims: Tuple[str, str]) -> Optional[CRS]:
    """
    Looks for attribute named ``crs`` containing CRS string.

    - Checks spatials coords attrs
    - Checks data variable attrs
    - Checks dataset attrs

    Returns
    =======
    Content for `.attrs[crs]` usually it's a string
    None if not present in any of the places listed above
    """
    crs_set: Set[CRS] = set()

    def _add_candidate(crs):
        if crs is None:
            return
        if isinstance(crs, str):
            try:
                crs_set.add(CRS(crs))
            except CRSError:
                warnings.warn(f"Failed to parse CRS: {crs}")
        elif isinstance(crs, CRS):
            # support current bad behaviour of injecting CRS directly into
            # attributes in example notebooks
            crs_set.add(crs)
        else:
            warnings.warn(f"Ignoring crs attribute of type: {type(crs)}")

    def process_attrs(attrs):
        _add_candidate(attrs.get("crs", None))
        _add_candidate(attrs.get("crs_wkt", None))

    def process_datavar(x):
        process_attrs(x.attrs)
        for dim in sdims:
            if dim in x.coords:
                process_attrs(x.coords[dim].attrs)

    if isinstance(obj, xarray.Dataset):
        process_attrs(obj.attrs)
        for dv in obj.data_vars.values():
            process_datavar(dv)
    else:
        process_datavar(obj)

    crs = None
    if len(crs_set) >= 1:
        crs = crs_set.pop()

    if len(crs_set) > 0:
        if any(other != crs for other in crs_set):
            warnings.warn("Have several candidates for a CRS")

    return crs


def spatial_dims(
    xx: Union[xarray.DataArray, xarray.Dataset], relaxed: bool = False
) -> Optional[Tuple[str, str]]:
    """
    Find spatial dimensions of ``xx``.

    Checks for presence of dimensions named:
    ``y, x | latitude, longitude | lat, lon``

    If ``relaxed=True`` and none of the above dimension names are found,
    assume that last two dimensions are spatial dimensions.

    :returns: ``None`` if no dimensions with expected names are found
    :returns: ``('y', 'x') | ('latitude', 'longitude') | ('lat', 'lon')``
    """

    def skip_dim(dim: str) -> bool:
        if dim in ("time", "band", "bands", "wavelength", "wavelengths"):
            return True

        # skip dimensions without coord of the same name
        if dim not in xx.coords:
            return True

        coord = xx.coords[dim]
        # Primary coordinate for spatial dimension must have floating point type
        if coord.dtype.kind != "f":
            return True

        return False

    _dims = [str(dim) for dim in xx.dims]
    dims = set(_dims)
    for guess in STANDARD_SPATIAL_DIMS:
        if dims.issuperset(guess):
            return guess

    _dims = [dim for dim in _dims if not skip_dim(str(dim))]

    if relaxed and len(_dims) >= 2:
        return _dims[-2], _dims[-1]

    return None


def _mk_crs_coord(
    crs: CRS,
    name: str = _DEFAULT_CRS_COORD_NAME,
    gcps=None,
    transform: Optional[Affine] = None,
) -> xarray.DataArray:
    # pylint: disable=protected-access

    cf = crs.proj.to_cf()
    epsg = 0 if crs.epsg is None else crs.epsg
    crs_wkt = cf.get("crs_wkt", None) or crs.wkt

    if gcps is not None:
        # Store as string
        cf["gcps"] = json.dumps(_gcps_to_json(gcps))

    if transform is not None:
        cf["GeoTransform"] = _render_geo_transform(transform, precision=24)

    return xarray.DataArray(
        numpy.asarray(epsg, "int32"),
        name=name,
        dims=(),
        attrs={"spatial_ref": crs_wkt, **cf},
    )


def _gcps_to_json(gcps):
    def _to_feature(p):
        coords = [p.x, p.y] if p.z is None else [p.x, p.y, p.z]

        return {
            "type": "Feature",
            "properties": {
                "id": str(p.id),
                "info": (p.info or ""),
                "row": p.row,
                "col": p.col,
            },
            "geometry": {"type": "Point", "coordinates": coords},
        }

    return {"type": "FeatureCollection", "features": list(map(_to_feature, gcps))}


def _coord_to_xr(name: str, c: Coordinate, **attrs) -> xarray.DataArray:
    """
    Construct xr.DataArray from named Coordinate object.

    This can then be used to define coordinates for ``xr.Dataset|xr.DataArray``
    """
    attrs = {"units": c.units, "resolution": c.resolution, **attrs}
    return xarray.DataArray(
        c.values, coords={name: c.values}, dims=(name,), attrs=attrs
    )


def assign_crs(
    xx: XrT,
    crs: SomeCRS,
    crs_coord_name: str = _DEFAULT_CRS_COORD_NAME,
) -> XrT:
    """
    Assign CRS for a non-georegistered array or dataset.

    Returns a new object with CRS information populated.

    .. code-block:: python

        xx = xr.open_rasterio("some-file.tif")
        print(xx.odc.crs)
        print(xx.astype("float32").crs)


    :param xx: :py:class:`~xarray.Dataset` or :py:class:`~xarray.DataArray`
    :param crs: CRS to assign
    :param crs_coord_name: how to name crs coordinate (defaults to ``spatial_ref``)
    """
    crs = norm_crs_or_error(crs)
    crs_coord = _mk_crs_coord(crs, name=crs_coord_name)
    xx = xx.assign_coords({crs_coord_name: crs_coord})

    if isinstance(xx, xarray.DataArray):
        xx.encoding.update(grid_mapping=crs_coord_name)
    elif isinstance(xx, xarray.Dataset):
        for band in xx.data_vars.values():
            band.encoding.update(grid_mapping=crs_coord_name)

    return xx


def mask(
    xx: XrT, poly: Geometry, invert: bool = False, all_touched: bool = True
) -> XrT:
    """
    Apply a polygon geometry as a mask, setting all
    :py:class:`xarray.Dataset` or :py:class:`xarray.DataArray` pixels
    outside the rasterized polygon to ``NaN``.

    :param xx:
       :py:class:`~xarray.Dataset` or :py:class:`~xarray.DataArray`.

    :param poly:
       A :py:class:`odc.geo.geom.Geometry` polygon used to mask ``xx``.

    :param invert:
        Whether to invert the mask before applying it to ``xx``. If
        ``True``, only pixels inside of ``poly`` will be masked.

    :param all_touched:
        If ``True``, the rasterize step will burn in all pixels touched
        by ``poly``. If ``False``, only pixels whose centers are within
        the polygon or that are selected by Bresenham's line algorithm
        will be burned in.

    :return:
        A :py:class:`~xarray.Dataset` or :py:class:`~xarray.DataArray`
        masked by ``poly``.

    .. seealso:: :py:meth:`odc.geo.xr.rasterize`
    """
    # Rasterise `poly` into geobox of `xx`
    rasterized = rasterize(
        poly=poly,
        how=xx.odc.geobox,
        all_touched=all_touched,
        value_inside=not invert,
    )

    # Mask data outside rasterized `poly`
    xx_masked = xx.where(rasterized.data)

    # Remove nodata attribute from arrays
    if isinstance(xx_masked, xarray.Dataset):
        for var in xx_masked.data_vars:
            xx_masked[var].attrs.pop("nodata", None)
    else:
        xx_masked.attrs.pop("nodata", None)

    return xx_masked


def crop(
    xx: XrT, poly: Geometry, apply_mask: bool = True, all_touched: bool = True
) -> XrT:
    """
    Crops and optionally mask an :py:class:`xarray.Dataset` or
    :py:class:`xarray.DataArray` to the spatial extent of a geometry.

    :param xx:
       :py:class:`~xarray.Dataset` or :py:class:`~xarray.DataArray`.

    :param poly:
       A :py:class:`odc.geo.geom.Geometry` polygon used to crop ``xx``.

    :param apply_mask:
       Whether to mask out pixels outside of the rasterized extent of
       ``poly`` by setting them to ``NaN``.

    :param all_touched:
        If ``True`` and ``apply_mask=True``, the rasterize step will
        burn in all pixels touched by ``poly``. If ``False``, only
        pixels whose centers are within the polygon or that are selected
        by Bresenham's line algorithm will be burned in.

    :return:
        A :py:class:`~xarray.Dataset` or :py:class:`~xarray.DataArray`
        cropped and optionally masked to the spatial extent of ``poly``.

    .. seealso:: :py:meth:`odc.geo.xr.mask`
    """
    meta: ODCExtension = xx.odc
    sdims = meta.spatial_dims
    gbox = meta.geobox

    if sdims is None or gbox is None:
        raise ValueError("Can't locate spatial dimensions")

    if not isinstance(gbox, GeoBox):
        raise ValueError("Can't crop GCPGeoBox")

    # Create new geobox with pixel grid of `xx` but enclosing `poly`.
    poly_geobox = gbox.enclosing(poly)

    # Calculate ROI slices into `xx` for intersection between both geoboxes.
    roi = gbox.overlap_roi(poly_geobox)

    # Verify that `poly` overlaps with `xx` by checking if the returned
    # ROI is empty
    if roi_is_empty(roi):
        raise ValueError(
            "The supplied `poly` must overlap spatially with the extent of `xx`."
        )

    # Crop spatial dims of `xx` using ROI
    xx_cropped = xx.isel({sdims[0]: roi[0], sdims[1]: roi[1]})

    # Optionally mask data outside rasterized `poly`
    if apply_mask:
        xx_cropped = mask(xx_cropped, poly, all_touched=all_touched)

    return xx_cropped


def xr_coords(
    gbox: SomeGeoBox,
    crs_coord_name: Optional[str] = _DEFAULT_CRS_COORD_NAME,
    always_yx: bool = False,
    dims: Optional[Tuple[str, str]] = None,
) -> Dict[Hashable, xarray.DataArray]:
    """
    Dictionary of Coordinates in xarray format.

    :param gbox:
      :py:class:`~odc.geo.geobox.GeoBox` or :py:class:`~odc.geo.gcp.GCPGeoBox`

    :param crs_coord_name:
       Use custom name for CRS coordinate, default is "spatial_ref". Set to
       ``None`` to not generate CRS coordinate at all.

    :param always_yx:
       If True, always use names ``y,x`` for spatial coordinates even for
       geographic geoboxes.

    :param dims:
       Use custom names for spatial dimensions, default is to use ``y,x`` or
       ``latitude, longitude`` based on projection used. Dimensions are supplied
       in "array" order, i.e. ``('y', 'x')``.

    :returns:
       Dictionary ``name:str -> xr.DataArray``. Where names are either as
       supplied by ``dims=`` or otherwise ``y,x`` for projected or
       ``latitude, longitude`` for geographic.

    """
    if dims is None:
        if always_yx:
            dims = ("y", "x")
        else:
            dims = gbox.dimensions

    attrs = {}
    crs = gbox.crs
    if crs is not None:
        attrs["crs"] = str(crs)

    gcps = None
    transform: Optional[Affine] = None

    if isinstance(gbox, GCPGeoBox):
        coords: Dict[Hashable, xarray.DataArray] = {
            name: _mk_pixel_coord(name, sz) for name, sz in zip(dims, gbox.shape)
        }
        gcps = gbox.gcps()
    else:
        transform = gbox.transform
        if gbox.axis_aligned:
            coords = {
                name: _coord_to_xr(name, coord, **attrs)
                for name, coord in zip(dims, gbox.coordinates.values())
            }
        else:
            coords = {
                name: _mk_pixel_coord(name, sz) for name, sz in zip(dims, gbox.shape)
            }

    if crs_coord_name is not None and crs is not None:
        coords[crs_coord_name] = _mk_crs_coord(
            crs, crs_coord_name, gcps=gcps, transform=transform
        )

    return coords


def _mk_pixel_coord(
    name: str,
    sz: int,
) -> xarray.DataArray:
    data = numpy.arange(0.5, sz, dtype="float32")
    xx = xarray.DataArray(
        data, coords={name: data}, dims=(name,), attrs={"units": "pixel"}
    )
    return xx


def _is_spatial_ref(coord) -> bool:
    return coord.ndim == 0 and (
        "spatial_ref" in coord.attrs or "crs_wkt" in coord.attrs
    )


def _locate_crs_coords(xx: XarrayObject) -> List[xarray.DataArray]:
    grid_mapping = xx.encoding.get("grid_mapping", None)
    if grid_mapping is None:
        grid_mapping = xx.attrs.get("grid_mapping")

    if grid_mapping is not None:
        # Specific mapping is defined via NetCDF/CF convention
        coord = xx.coords.get(grid_mapping, None)
        if coord is None:
            warnings.warn(
                f"grid_mapping={grid_mapping} is not pointing to valid coordinate"
            )
            return []
        return [coord]

    # Find all dimensionless coordinates with `spatial_ref|crs_wkt` attribute present
    return [coord for coord in xx.coords.values() if _is_spatial_ref(coord)]


def _extract_crs(crs_coord: xarray.DataArray) -> Optional[CRS]:
    _wkt = crs_coord.attrs.get("spatial_ref", None)  # GDAL convention?
    if _wkt is None:
        _wkt = crs_coord.attrs.get("crs_wkt", None)  # CF convention
    if _wkt is None:
        return None
    try:
        return CRS(_wkt)
    except CRSError:
        return None


def _extract_gcps(crs_coord: xarray.DataArray) -> Optional[GCPMapping]:
    gcps = crs_coord.attrs.get("gcps", None)
    if gcps is None:
        return None
    crs = _extract_crs(crs_coord)
    try:
        if isinstance(gcps, str):
            gcps = json.loads(gcps)
        wld = Geometry(gcps, crs=crs)
        pix = [
            xy_(f["properties"]["col"], f["properties"]["row"])
            for f in gcps["features"]
        ]
        return GCPMapping(pix, wld)
    except (IndexError, KeyError, ValueError, json.JSONDecodeError):
        return None


def _extract_geo_transform(crs_coord: xarray.DataArray) -> Optional[Affine]:
    geo_transform_parts = crs_coord.attrs.get("GeoTransform", "").split(" ")
    if len(geo_transform_parts) != 6:
        return None
    try:
        c, a, b, f, d, e = map(float, geo_transform_parts)
    except ValueError:
        return None

    return Affine.from_gdal(c, a, b, f, d, e)


def _render_geo_transform(transform: Affine, precision: int = 24) -> str:
    return " ".join(
        map(lambda x: f"{x:.{precision}f}".rstrip("0").rstrip("."), transform.to_gdal())
    )


def _extract_transform(
    src: XarrayObject,
    sdims: Tuple[str, str],
    crs_coord: Optional[xarray.DataArray],
    gcp: bool,
) -> Optional[Affine]:
    if any(dim not in src.coords for dim in sdims):
        # special case of no spatial dims at all
        # happens for GCP/rotated sources loaded by rioxarray
        if gcp or crs_coord is None:
            return None
        return _extract_geo_transform(crs_coord)

    _yy, _xx = (src[dim] for dim in sdims)
    original_transform: Affine | None = None
    if crs_coord is not None:
        original_transform = _extract_geo_transform(crs_coord)

    # First try to compute from 1-D X/Y coords
    try:
        transform = affine_from_axis(_xx.values, _yy.values)
    except ValueError:
        # This can fail when any dimension is shorter than 2 elements
        # Figure out fallback resolution if possible and try again
        if crs_coord is None or original_transform is None:
            return None
        try:
            transform = affine_from_axis(
                _xx.values,
                _yy.values,
                resolution_from_affine(original_transform),
            )
        except ValueError:
            return None

    if original_transform is not None:
        if not is_affine_st(original_transform):
            # non-axis aligned geobox detected
            # adjust transform
            #  world <- pix' <- pix
            transform = original_transform * transform

        if any(map(math.isnan, transform)):
            transform = original_transform

        if approx_equal_affine(transform, original_transform):
            transform = original_transform

    return transform


def _locate_geo_info(src: XarrayObject) -> GeoState:
    # pylint: disable=too-many-locals
    if len(src.dims) < 2:
        return GeoState()

    sdims = spatial_dims(src, relaxed=True)
    if sdims is None:
        return GeoState()

    crs_coord: Optional[xarray.DataArray] = None
    crs: Optional[CRS] = None
    geobox: Optional[SomeGeoBox] = None
    gcp: Optional[GCPMapping] = None

    ny, nx = (src.coords[dim].shape[0] for dim in sdims)

    _crs_coords = _locate_crs_coords(src)
    num_candidates = len(_crs_coords)
    if num_candidates > 0:
        if num_candidates > 1:
            warnings.warn("Multiple CRS coordinates are present")
        crs_coord = _crs_coords[0]
        crs = _extract_crs(crs_coord)
        gcp = _extract_gcps(crs_coord)
    else:
        # try looking in attributes
        crs = _get_crs_from_attrs(src, sdims)

    transform = _extract_transform(src, sdims, crs_coord, gcp is not None)

    if gcp is not None:
        geobox = GCPGeoBox((ny, nx), gcp, transform)
    elif transform is not None:
        geobox = GeoBox((ny, nx), transform, crs)

    return GeoState(
        spatial_dims=sdims,
        crs_coord=crs_coord,
        transform=transform,
        crs=crs,
        geobox=geobox,
        gcp=gcp,
    )


def _wrap_op(method: F) -> F:
    @functools.wraps(method, assigned=("__doc__",))
    def wrapped(*args, **kw):
        # pylint: disable=protected-access
        _self, *rest = args
        return method(_self._xx, *rest, **kw)

    return wrapped  # type: ignore


def xr_reproject(
    src: XrT,
    how: Union[SomeCRS, GeoBox],
    *,
    resampling: Union[str, int] = "nearest",
    dst_nodata: SomeNodata = "auto",
    dtype=None,
    resolution: Union[SomeResolution, Literal["auto", "fit", "same"]] = "auto",
    shape: Union[SomeShape, int, None] = None,
    tight: bool = False,
    anchor: GeoboxAnchor = "default",
    tol: float = 0.01,
    round_resolution: Union[None, bool, Callable[[float, str], float]] = None,
    **kw,
) -> XrT:
    """
    Reproject raster to different projection/resolution.

    :param src:
      :py:class:`~xarray.Dataset` or :py:class:`~xarray.DataArray` to reproject.

    :param how:
      How to reproject the raster. Can be a GeoBox or a CRS (e.g. CRS object or
      an "ESPG:XXXX" string/integer). If a CRS is provided, the output pixel
      grid can be customised further via ``resolution``, ``shape``, ``tight``,
      ``anchor``, ``tol``, ``round_resolution``.

    :param resampling:
      Resampling method to use when reprojecting the raster. Defaults to
      "nearest", also supports "average", "bilinear", "cubic", "cubic_spline",
      "lanczos", "mode", "gauss", "max", "min", "med", "q1", "q3".

    :param dst_nodata:
      Set a custom nodata value for the output resampled raster.

    :param resolution:

       * "same" use exactly the same resolution as src
       * "fit" use center pixel to determine scale change between the two
       * | "auto" is to use the same resolution on the output if CRS units are
         | the same between the source and destination and otherwise use "fit"
       * Ignored if ``shape=`` is supplied
       * Else resolution in the units of the output crs

    :param shape:
      Span that many pixels, if it's a single number then span that many pixels
      along the longest dimension, other dimension will be computed to maintain
      roughly square pixels. Takes precedence over ``resolution=`` parameter.

    :param tight:
      By default output pixel grid is adjusted to align pixel edges to X/Y axis,
      suppling ``tight=True`` produces unaligned geobox on the output.

    :param anchor:
      Control pixel snapping, default is to snap pixel edge to ``X=0,Y=0``.
      Ignored when ``tight=True`` is supplied.

    :param tol:
       Fraction of the output pixel that can be ignored, defaults to 1/100.
       Bounding box of the output geobox is allowed to be smaller by that amount
       than transformed footprint of the original.

    :param round_resolution:
      ``round_resolution(res: float, units: str) -> float``

    This method uses :py:mod:`rasterio`.

    .. seealso:: :py:meth:`odc.geo.overlap.compute_output_geobox`

    """
    kw = {
        "shape": shape,
        "resolution": resolution,
        "tight": tight,
        "anchor": anchor,
        "tol": tol,
        "round_resolution": round_resolution,
        **kw,
    }
    if isinstance(src, xarray.DataArray):
        return _xr_reproject_da(
            src, how, resampling=resampling, dst_nodata=dst_nodata, dtype=dtype, **kw
        )
    return _xr_reproject_ds(
        src, how, resampling=resampling, dst_nodata=dst_nodata, dtype=dtype, **kw
    )


def _extract_output_geobox_params(kw):
    # NOTE: modifies input, removes keys
    out = {}
    for k in ("tight", "anchor", "resolution", "shape", "tol", "round_resolution"):
        if k in kw:
            out[k] = kw.pop(k)
    return out


def _xr_reproject_ds(
    src: Any,
    how: Union[SomeCRS, GeoBox],
    *,
    resampling: Union[str, int] = "nearest",
    dst_nodata: SomeNodata = "auto",
    dtype=None,
    **kw,
) -> xarray.Dataset:
    assert isinstance(src, xarray.Dataset)

    if have.rasterio is False:  # pragma: nocover
        raise RuntimeError("Please install `rasterio` to use this method")

    assert isinstance(src.odc, ODCExtensionDs)
    if src.odc.geobox is None:
        raise ValueError("Can not reproject non-georegistered array.")

    kw_gbox = _extract_output_geobox_params(kw)

    if isinstance(how, GeoBox):
        dst_geobox = how
    else:
        dst_geobox = src.odc.output_geobox(how, **kw_gbox)

    def _maybe_reproject(dv: xarray.DataArray):
        if dv.odc.geobox is None:
            # pass-through data variables without a geobox
            strip_coords = [str(c.name) for c in _locate_crs_coords(dv)]
            if len(strip_coords) > 0:
                dv = dv.drop_vars(strip_coords)
            return dv
        return _xr_reproject_da(
            dv,
            how=dst_geobox,
            resampling=resampling,
            dst_nodata=dst_nodata,
            dtype=dtype,
            **kw,
        )

    return src.map(_maybe_reproject)


def _xr_reproject_da(
    src: Any,
    how: Union[SomeCRS, GeoBox],
    *,
    resampling: Union[str, int] = "nearest",
    dst_nodata: SomeNodata = "auto",
    dtype=None,
    **kw,
) -> xarray.DataArray:
    # pylint: disable=too-many-locals
    assert isinstance(src, xarray.DataArray)

    if have.rasterio is False:  # pragma: nocover
        raise RuntimeError("Please install `rasterio` to use this method")

    assert isinstance(src.odc, ODCExtensionDa)  # for mypy sake
    src_gbox = src.odc.geobox

    if src_gbox is None or src_gbox.crs is None:
        raise ValueError("Can not reproject non-georegistered array.")

    kw_gbox = _extract_output_geobox_params(kw)

    if isinstance(how, GeoBox):
        dst_geobox = how
    else:
        dst_geobox = src.odc.output_geobox(how, **kw_gbox)

    if dtype is None:
        dtype = src.dtype

    # compute destination shape by replacing spatial dimensions shape
    ydim = src.odc.ydim
    assert ydim + 1 == src.odc.xdim
    dst_shape = (*src.shape[:ydim], *dst_geobox.shape, *src.shape[ydim + 2 :])

    src_nodata = resolve_nodata(kw.pop("src_nodata", "auto"), src.dtype, src.odc.nodata)
    dst_nodata = resolve_nodata(dst_nodata, dtype, src_nodata)

    fill_value = resolve_fill_value(dst_nodata, src_nodata, dtype)

    if is_dask_collection(src):
        from ._dask import dask_rio_reproject

        dst: Any = dask_rio_reproject(
            src.data,
            src_gbox,
            dst_geobox,
            resampling=resampling,
            src_nodata=src_nodata,
            dst_nodata=fill_value,
            ydim=ydim,
            dtype=dtype,
            **kw,
        )
    else:
        dst = numpy.full(dst_shape, fill_value, dtype=dtype)

        # pylint: disable=possibly-used-before-assignment
        dst = rio_reproject(
            src.values,
            dst,
            src_gbox,
            dst_geobox,
            resampling=resampling,
            src_nodata=src_nodata,
            dst_nodata=fill_value,
            ydim=ydim,
            dtype=dtype,
            **kw,
        )

    attrs = {k: v for k, v in src.attrs.items() if k not in REPROJECT_SKIP_ATTRS}
    if not is_nodata_empty(dst_nodata):
        assert dst_nodata is not None
        attrs.update({k: maybe_int(float(dst_nodata), 1e-6) for k in NODATA_ATTRIBUTES})

    # new set of coords (replace x,y dims)
    # discard all coords that reference spatial dimensions
    sdims = src.odc.spatial_dims
    assert sdims is not None
    sdims = set(sdims)

    def should_keep(coord):
        if _is_spatial_ref(coord):
            return False
        return sdims.isdisjoint(coord.dims)

    coords = {k: coord for k, coord in src.coords.items() if should_keep(coord)}
    coords.update(xr_coords(dst_geobox))

    dims = (*src.dims[:ydim], *dst_geobox.dimensions, *src.dims[ydim + 2 :])

    out = xarray.DataArray(dst, coords=coords, dims=dims, attrs=attrs)
    out.encoding["grid_mapping"] = _DEFAULT_CRS_COORD_NAME
    return out


class ODCExtension:
    """
    ODC extension base class.

    Common accessors for both Array/Dataset.
    """

    def __init__(self, state: GeoState):
        self._state = state

    @property
    def spatial_dims(self) -> Optional[Tuple[str, str]]:
        """Return names of spatial dimensions, or ``None``."""
        return self._state.spatial_dims

    @property
    def transform(self) -> Optional[Affine]:
        return self._state.transform

    affine = transform

    @property
    def crs(self) -> Optional[CRS]:
        """Query :py:class:`~odc.geo.crs.CRS`."""
        return self._state.crs

    @property
    def geobox(self) -> Optional[SomeGeoBox]:
        """Query :py:class:`~odc.geo.geobox.GeoBox` or :py:class:`~odc.geo.gcp.GCPGeoBox`."""
        return self._state.geobox

    @property
    def aspect(self) -> float:
        gbox = self._state.geobox
        if gbox is None:
            return 1
        return gbox.aspect

    def output_geobox(self, crs: SomeCRS, **kw) -> GeoBox:
        """
        Compute geobox of this data in other projection.

        .. seealso:: :py:meth:`odc.geo.overlap.compute_output_geobox`
        """
        gbox = self.geobox
        if gbox is None:
            raise ValueError("Not geo registered")

        return compute_output_geobox(gbox, crs, **kw)

    def map_bounds(self) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """See :py:meth:`odc.geo.geobox.GeoBox.map_bounds`."""
        gbox = self.geobox
        if gbox is None:
            raise ValueError("Not geo registered")

        return gbox.map_bounds()

    @property
    def crs_coord(self) -> xarray.DataArray | None:
        """Return CRS coordinate DataArray."""
        return self._state.crs_coord

    @property
    def grid_mapping(self) -> str | None:
        """Return name of the grid mapping coordinate."""
        if c := self.crs_coord:
            return str(c.name)
        return None

    mask = _wrap_op(mask)
    crop = _wrap_op(crop)

    if have.rasterio:
        explore = _wrap_op(explore)
        reproject = _wrap_op(xr_reproject)


@xarray.register_dataarray_accessor("odc")
class ODCExtensionDa(ODCExtension):
    """
    ODC extension for :py:class:`xarray.DataArray`.
    """

    def __init__(self, xx: xarray.DataArray):
        ODCExtension.__init__(self, _locate_geo_info(xx))
        self._xx = xx

    @property
    def uncached(self) -> "ODCExtensionDa":
        return ODCExtensionDa(self._xx)

    def reload(self) -> xarray.DataArray:
        """Reload geospatial state info in-place."""
        self._state = _locate_geo_info(self._xx)
        return self._xx

    @property
    def ydim(self) -> int:
        """Index of the Y dimension."""
        if (sdims := self.spatial_dims) is not None:
            return self._xx.dims.index(sdims[0])
        raise ValueError("Can't locate spatial dimensions")

    @property
    def xdim(self) -> int:
        """Index of the X dimension."""
        if (sdims := self.spatial_dims) is not None:
            return self._xx.dims.index(sdims[1])
        raise ValueError("Can't locate spatial dimensions")

    def assign_crs(
        self, crs: SomeCRS, crs_coord_name: str = _DEFAULT_CRS_COORD_NAME
    ) -> xarray.DataArray:
        """See :py:meth:`odc.geo.xr.assign_crs`."""
        return assign_crs(self._xx, crs=crs, crs_coord_name=crs_coord_name)

    @property
    def nodata(self) -> Nodata:
        """Extract ``nodata/_FillValue`` attribute if set."""
        attrs = self._xx.attrs
        encoding = self._xx.encoding

        for k in ["nodata", "_FillValue"]:
            nodata = attrs.get(k, _NoValue)
            if nodata is _NoValue:
                nodata = encoding.get(k, _NoValue)

            if nodata is _NoValue:
                continue

            if nodata is None:
                return None

            return float(nodata)

        return None

    @nodata.setter
    def nodata(self, value: Nodata):
        nodata = resolve_nodata(value, self._xx.dtype)

        if nodata is None:
            for k in ["nodata", "_FillValue"]:
                self._xx.attrs.pop(k, None)
                self._xx.encoding.pop(k, None)
            return

        self._xx.attrs["nodata"] = nodata
        self._xx.encoding["_FillValue"] = nodata

    colorize = _wrap_op(colorize)

    if have.rasterio:
        write_cog = _wrap_op(write_cog)
        to_cog = _wrap_op(to_cog)
        compress = _wrap_op(compress)
        add_to = _wrap_op(add_to)


@xarray.register_dataset_accessor("odc")
class ODCExtensionDs(ODCExtension):
    """
    ODC extension for :py:class:`xarray.Dataset`.
    """

    def __init__(self, ds: xarray.Dataset):
        ODCExtension.__init__(self, _locate_geo_info(ds))
        self._xx = ds

    def reload(self) -> xarray.Dataset:
        """Reload geospatial state info in-place."""
        self._state = _locate_geo_info(self._xx)
        return self._xx

    @property
    def uncached(self) -> "ODCExtensionDs":
        return ODCExtensionDs(self._xx)

    def assign_crs(
        self, crs: SomeCRS, crs_coord_name: str = _DEFAULT_CRS_COORD_NAME
    ) -> xarray.Dataset:
        return assign_crs(self._xx, crs=crs, crs_coord_name=crs_coord_name)

    def to_rgba(
        self,
        bands: Optional[Tuple[str, str, str]] = None,
        *,
        vmin: Optional[float] = None,
        vmax: Optional[float] = None,
    ) -> xarray.DataArray:
        return to_rgba(self._xx, bands=bands, vmin=vmin, vmax=vmax)


ODCExtensionDs.to_rgba.__doc__ = to_rgba.__doc__


def _xarray_geobox(xx: XarrayObject) -> Optional[GeoBox]:
    if isinstance(xx, xarray.DataArray):
        return xx.odc.geobox
    for dv in xx.data_vars.values():
        geobox = dv.odc.geobox
        if geobox is not None:
            return geobox
    return None


def register_geobox():
    """
    Backwards compatiblity layer for datacube ``.geobox`` property.
    """
    xarray.Dataset.geobox = property(_xarray_geobox)  # type: ignore
    xarray.DataArray.geobox = property(_xarray_geobox)  # type: ignore


def wrap_xr(
    im: Any,
    gbox: SomeGeoBox,
    *,
    time=None,
    nodata: SomeNodata = "auto",
    crs_coord_name: Optional[str] = _DEFAULT_CRS_COORD_NAME,
    always_yx: bool = False,
    dims: Optional[Tuple[str, ...]] = None,
    axis: Optional[int] = None,
    **attrs,
) -> xarray.DataArray:
    """
    Wrap xarray around numpy array with CRS and x,y coords.

    :param im: numpy array to wrap, last two axes are Y,X
    :param gbox: Geobox, must same shape as last two axis of ``im``
    :param time: optional time axis value(s), defaults to None
    :param nodata: optional `nodata` value, defaults to None
    :param crs_coord_name: allows to change name of the crs coordinate variable
    :param always_yx: If True, always use names ``y,x`` for spatial coordinates
    :param dims: Custom names for spatial dimensions
    :param axis: Which axis of the input array corresponds to Y,X
    :param attrs: Any other attributes to set on the result
    :return: xarray DataArray
    """
    # pylint: disable=too-many-locals,too-many-arguments
    assert dims is None or len(dims) == im.ndim

    if axis is None:
        axis = 1 if time is not None else 0
    elif axis < 0:  # handle numpy style negative axis
        axis = int(im.ndim) + axis

    if im.ndim == 2 and axis == 1:
        im = im[numpy.newaxis, ...]

    assert axis >= 0
    assert im.ndim - axis - 2 >= 0
    assert im.shape[axis : axis + 2] == gbox.shape

    def _prefix_dims(n):
        if n == 0:
            return ()
        if n == 1:
            return ("time",)
        return ("time", *[f"dim_{i}" for i in range(n - 1)])

    def _postfix_dims(n):
        if n == 0:
            return ()
        if n == 1:
            return ("band",)
        return (f"b_{i}" for i in range(n))

    sdims: Optional[Tuple[str, str]] = None
    if dims is None:
        sdims = ("y", "x") if always_yx else gbox.dimensions
        dims = (*_prefix_dims(axis), *sdims, *_postfix_dims(im.ndim - axis - 2))
    else:
        sdims = dims[axis], dims[axis + 1]

    prefix_dims = dims[:axis]
    postfix_dims = dims[axis + 2 :]

    coords = xr_coords(
        gbox,
        crs_coord_name=crs_coord_name,
        always_yx=always_yx,
        dims=sdims,
    )

    if time is not None:
        if not isinstance(time, xarray.DataArray):
            if len(prefix_dims) > 0 and isinstance(time, (str, datetime)):
                time = [time]

            time = xarray.DataArray(time, dims=prefix_dims[:1]).astype("datetime64[ns]")

        coords["time"] = time

    if postfix_dims:
        for a, dim in enumerate(postfix_dims):
            nb = im.shape[axis + 2 + a]
            coords[dim] = xarray.DataArray(
                [f"b{i}" for i in range(nb)], dims=(dim,), name=dim
            )

    _nodata = resolve_nodata(nodata, im.dtype)
    if not is_nodata_empty(_nodata) or nodata != "auto":
        attrs = {"nodata": _nodata, **attrs}

    out = xarray.DataArray(im, coords=coords, dims=dims, attrs=attrs)
    if crs_coord_name is not None:
        out.encoding["grid_mapping"] = crs_coord_name
    return out


def xr_zeros(
    geobox: SomeGeoBox,
    dtype="float64",
    *,
    chunks: Optional[Union[Tuple[int, int], Tuple[int, int, int]]] = None,
    time=None,
    crs_coord_name: Optional[str] = _DEFAULT_CRS_COORD_NAME,
    **kw,
) -> xarray.DataArray:
    """
    Construct geo-registered xarray from a :py:class:`~odc.geo.geobox.GeoBox`.

    :param gbox: Desired footprint and resolution
    :param dtype: Pixel data type
    :param chunks: Create a dask array instead of numpy array
    :param time: When set adds time dimension
    :param crs_coord_name: allows to change name of the crs coordinate variable

    :return: :py:class:`xarray.DataArray` filled with zeros (numpy or dask)

    .. seealso:: :py:meth:`odc.geo.xr.wrap_xr`

    """
    if time is not None:
        _shape: Tuple[int, ...] = (len(time), *geobox.shape.yx)
    else:
        _shape = geobox.shape.yx

    if chunks is not None:
        from dask import array as da  # pylint: disable=import-outside-toplevel

        return wrap_xr(
            da.zeros(_shape, dtype=dtype, chunks=chunks),
            geobox,
            crs_coord_name=crs_coord_name,
            time=time,
            **kw,
        )

    return wrap_xr(
        numpy.zeros(_shape, dtype=dtype),
        geobox,
        crs_coord_name=crs_coord_name,
        time=time,
        **kw,
    )


def rasterize(
    poly: Geometry,
    how: Union[float, int, Resolution, GeoBox],
    *,
    value_inside: bool = True,
    all_touched: bool = False,
) -> xarray.DataArray:
    """
    Generate raster from geometry.

    This method is a wrapper for :py:meth:`rasterio.features.make_mask`.

    :param poly:
       Geometry shape to rasterize.

    :param how:
        This could be either just resolution or a GeoBox that fully defines output
        raster extent/resolution/projection.

    :param all_touched:
        If ``True``, all pixels touched by geometries will be burned in.  If
        ``False``, only pixels whose center is within the polygon or that
        are selected by Bresenham's line algorithm will be burned in.

    :param value_inside:
        By default pixels inside a polygon will have value of ``True`` and ``False``
        outside, but this can be flipped.

    :return: geo-registered data array
    """
    # pylint: disable=import-outside-toplevel

    if have.rasterio is False:  # pragma: nocover
        raise RuntimeError("Please install `rasterio` to use this method")

    from rasterio.features import geometry_mask

    if isinstance(how, GeoBox):
        geobox = how
    else:
        geobox = GeoBox.from_geopolygon(poly, resolution=how)

    if poly.crs != geobox.crs and geobox.crs is not None:
        poly = poly.to_crs(geobox.crs)

    pix = geometry_mask(
        [poly.geom],
        geobox.shape,
        geobox.transform,
        all_touched=all_touched,
        invert=value_inside,
    )
    return wrap_xr(pix, geobox)
