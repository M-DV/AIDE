'''
    Helpers for geospatial operations.

    2023-24 Benjamin Kellenberger
'''

import os
from typing import Iterable, Tuple
import re
from psycopg2 import sql
import pyproj
import rasterio
from rasterio.enums import Resampling
from tqdm import tqdm

from modules.Database.app import Database
from util.drivers import GDALImageDriver



def get_postgis_version(db_connector: Database) -> str:
    '''
        Queries the database and returns the PostGIS version (or None if not available).
    '''
    version = db_connector.execute('SELECT PostGIS_full_version() AS version;', None, 1)
    if version is None or len(version) == 0:
        return None
    return version[0]['version']



def get_project_srid(db_connector: Database,
            project: str) -> int:
    '''
        Inputs:
        - "db_connector": Database, instance
        - "project": str, project shortname

        Returns:
        - EPSG code for SRID or None if not defined (e.g., if PostGIS is not available)
    '''
    #TODO: check if column actually exists
    srid = db_connector.execute('''
        SELECT Find_SRID(%s, 'image', 'extent') AS srid;
    ''', (project,), 1)
    return srid[0]['srid'] if srid is not None and len(srid) > 0 else None



def to_crs(srid: object) -> pyproj.CRS:
    '''
        Receives an "srid", one of:
        - int: EPSG code
        - str: WKT definition of CRS
        - CRS: rasterio CRS object
        Returns a pyproj.CRS object
    '''
    if isinstance(srid, int):
        return pyproj.CRS.from_epsg(srid)
    if isinstance(srid, str):
        if srid.lower().strip() == 'crs:84':
            return pyproj.CRS.from_epsg(4326)
        if srid.lower().startswith('+proj'):
            return pyproj.CRS.from_proj4(srid)
        return pyproj.CRS.from_string(srid)
    if isinstance(srid, rasterio.CRS):
        return pyproj.CRS.from_user_input(srid)
    if isinstance(srid, pyproj.CRS):
        return srid
    return None



def to_srid(crs: object) -> int:
    '''
        Receives a "crs", one of:
        - int: EPSG code
        - str: WKT definition of CRS
        - CRS: rasterio or pyproj CRS object
        Returns the CRS' EPSG code (int)
    '''
    if isinstance(crs, int):
        return crs
    if isinstance(crs, str):
        if crs.lower().strip() == 'crs:84':
            return 4326
        if crs.lower().startswith('+proj'):
            return pyproj.CRS.from_proj4(crs).to_epsg()
        return pyproj.CRS.from_string(crs).to_epsg()
    if isinstance(crs, rasterio.CRS):
        return pyproj.CRS.from_user_input(crs).to_epsg()
    if isinstance(crs, pyproj.CRS):
        return crs.to_epsg()
    return None



def crs_match(crs_a: object, crs_b: object, exact: bool=False) -> bool:
    '''
        Returns True if two given CRS (id, string, pyproj/rasterio CRS) are equal and False
        otherwise (also if either or both could not be parsed).
    '''
    if exact:
        return to_crs(crs_a).is_exact_same(to_crs(crs_b))
    return to_crs(crs_a).equals(to_crs(crs_b))



def is_xy(crs: object) -> bool:
    '''
        Attempts to parse a given "crs" object. Returns True if the CRS' coordinate order is x, y
        (or lon, lat; East, North; etc.), else False.
    '''
    axes = to_crs(crs).axis_info
    return axes[0].direction.lower() in ('east', 'west') \
            and axes[1].direction.lower() in ('north', 'south')



def convert(coords_x: Iterable[float],
            coords_y: Iterable[float],
            crs_source: object,
            crs_target: object,
            always_xy: bool=False) -> Tuple[Tuple[float]]:
    '''
        Receives an Iterable of x/y coordinates, a source and target CRS, and converts
        coordinates across reference systems accordingly.
    '''
    transformer = pyproj.Transformer.from_crs(to_crs(crs_source),
                                              to_crs(crs_target),
                                              always_xy=always_xy)
    return transformer.transform(xx=coords_x, yy=coords_y)



def get_geospatial_metadata(file_name: str,
                            srid: int=4326,
                            window: tuple=None,
                            transform_if_needed: bool=False) -> dict:
    '''
        Collects geospatial metadata for a given image (with optional window).
        Inputs:
        - "file_name": str, path of image to calculate extent for
        - "srid": int, spatial reference id for output polygon
        - "window" tuple, optional window as (x, y, width, height)
        - "transform_if_needed": bool, performs coordinate transformation for extent calculation if
                                 SRIDs don't match (else sets extent to None)

        Returns:
        - transform: rasterio Affine instance
        - extent: tuple, containing float values for (left, top, right, bottom) of extent
    '''
    try:
        meta = GDALImageDriver.metadata(file_name, window=window)
        if meta is None:
            meta = {}
        meta['extent'] = calc_extent(file_name, srid, window, transform_if_needed)
        return meta
    except Exception:
        return {}


def calc_extent(file_name: str,
                srid: int=4326,
                window: tuple=None,
                transform_if_needed: bool=True) -> tuple:
    '''
        Calculates the geospatial extent for an image (with optional window) and returns it as WKT
        string for insertion into PostGIS database.
        Inputs:
        - "file_name": str, path of image to calculate extent for
        - "srid": int, spatial reference id for output polygon
        - "window": tuple, optional window as (x, y, width, height)
        - "transform_if_needed": bool, performs coordinate transformation if SRIDs don't match (else
                                 returns None)

        Returns:
        tuple, containing float values for (left, top, right, bottom) of extent
    '''
    try:
        meta = GDALImageDriver.metadata(file_name, window=window)
        crs_source = to_crs(meta.get('crs', None))
        if crs_source is None:
            return None
        bounds = meta.get('bounds', None)
        if bounds is None:
            return None
        crs_target = to_crs(srid)
        if not crs_source.equals(crs_target):
            if not transform_if_needed:
                return None

            # transform bounds
            # pylint: disable=unpacking-non-sequence
            transformer = pyproj.Transformer.from_crs(crs_source,
                                                      crs_target,
                                                      always_xy=True)
            bounds_x, bounds_y = transformer.transform(xx=(bounds[0],bounds[2]),
                                                       yy=(bounds[1],bounds[3]))
            bounds = (bounds_x[0], bounds_y[0], bounds_x[1], bounds_y[1])
        return bounds
    except Exception:
        return None



def get_project_extent(db_connector: Database, project: str) -> tuple:
    '''
        Calculates and returns a tuple of (west, south, east, north) describing the coordinates of
        the full project's images' extent.
    '''
    extent = db_connector.execute(
        sql.SQL('''
            SELECT ST_Extent(extent) AS extent
            FROM {id_img};
        ''').format(
            id_img=sql.Identifier(project, 'image')
        ),
        None,
        1
    )
    if extent is not None and len(extent) > 0 and isinstance(extent[0]['extent'], str):
        extent = re.sub(
            r'(BOX\s*\(|,|\)\s*)',
            ' ',
            extent[0]['extent']
        ).strip().split(' ')
        return tuple(float(ext) for ext in extent)
    return None


def create_image_overviews(image_paths: Iterable,
                           scale_factors: tuple=(2,4,8,16),
                           method: Resampling=Resampling.nearest,
                           verbose: bool=False,
                           force_recreate: bool=False) -> None:
    '''
        Receives one or more images and calculates overviews (image pyramids) for them.
    '''
    #TODO: implement check for existing overviews
    if isinstance(method, str):
        method = getattr(Resampling, method.lower())
    else:
        assert method in Resampling, f'Invalid resampling method "{method}"'
    if isinstance(image_paths, str):
        image_paths = (image_paths,)
    iter_obj = tqdm(image_paths) if verbose else image_paths
    for image_path in iter_obj:
        if os.path.exists(image_path):
            with rasterio.open(image_path, 'r+') as f_img:
                f_img.build_overviews(scale_factors, method)
                f_img.update_tags(ns='rio_overview', resampling=method._name_)
