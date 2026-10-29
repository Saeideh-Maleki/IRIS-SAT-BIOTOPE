"""IRIS Task 119: simple monthly Sentinel-2 vegetation disturbance detector.

Run: python main.py. Change input format and thresholds in config.json.
"""
import csv
import json
import re
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds, transform_geom


def read_settings(path='config.json'):
    return json.loads(Path(path).read_text())


def find_images(folder, source):
    """For TIFF: four bands B04,B08,B12,SCL. For SAFE: native L2A band files."""
    folder = Path(folder)
    if source == 'tif':
        paths = sorted(folder.glob('*.tif'))
    else:
        paths = sorted(p for p in folder.iterdir() if p.is_dir() and p.name.endswith('.SAFE'))
    result = []
    for path in paths:
        # Accept YYYYMM (monthly TIFF) or YYYYMMDD (dated scene / SAFE).
        match = re.search(r'(20\d{2})(0[1-9]|1[0-2])([0-3]\d)?', path.name)
        if not match:
            raise ValueError(f'Filename needs YYYYMM or YYYYMMDD: {path.name}')
        date_text = ''.join(part or '' for part in match.groups())
        day = datetime.strptime(date_text, '%Y%m%d' if len(date_text) == 8 else '%Y%m')
        result.append((day, path))
    if not result:
        raise ValueError(f'No {source} images found in {folder}')
    return result


def band_files(safe):
    """Locate Level-2A bands. Red/NIR may be 10 m or 20 m."""
    files = {}
    for band in ('B04', 'B08', 'B12', 'SCL'):
        candidates = [p for p in safe.rglob('*.jp2')
                      if re.search(rf'_{band}_(10|20)m\.jp2$', p.name)]
        if band in ('B04', 'B08'):
            candidates.sort(key=lambda p: 0 if '_20m.' in p.name else 1)
        if not candidates:
            raise ValueError(f'{band} missing in {safe.name} (Level-2A required)')
        files[band] = candidates[0]
    return files


def read_scene(path, source, crs, transform, shape):
    """Read four aligned bands into a small AOI grid, using nearest for SCL."""
    values = []
    if source == 'tif':
        with rasterio.open(path) as src:
            if src.count < 4:
                raise ValueError(f'{path.name}: TIFF requires B04,B08,B12,SCL as bands 1–4')
            for i in range(1, 5):
                with WarpedVRT(src, crs=crs, transform=transform,
                               width=shape[1], height=shape[0],
                               resampling=Resampling.nearest if i == 4 else Resampling.bilinear) as vrt:
                    arr = vrt.read(i, masked=True).astype('float32').filled(np.nan)
                    values.append(arr)
    else:
        files = band_files(path)
        for band in ('B04', 'B08', 'B12', 'SCL'):
            with rasterio.open(files[band]) as src:
                with WarpedVRT(src, crs=crs, transform=transform,
                               width=shape[1], height=shape[0],
                               resampling=Resampling.nearest if band == 'SCL' else Resampling.bilinear) as vrt:
                    values.append(vrt.read(1, masked=True).astype('float32').filled(np.nan))
    red, nir, swir, scl = values
    # SCL 4=vegetation, 5=bare, 6=water; exclude clouds, shadow, snow and uncertain classes.
    clear = np.isin(scl, [4, 5, 6]) & np.isfinite(red + nir + swir)
    clear &= (red >= 0) & (nir >= 0) & (swir >= 0)
    ndvi = np.divide(nir-red, nir+red, out=np.full(shape, np.nan), where=(nir+red)>0)
    nbr = np.divide(nir-swir, nir+swir, out=np.full(shape, np.nan), where=(nir+swir)>0)
    return np.where(clear, ndvi, np.nan), np.where(clear, nbr, np.nan)


def median_stack(arrays):
    """Pixel-by-pixel median; leave pixels with no clear image as missing."""
    # nanmedian warns about cloudy pixels with no valid values; these remain NaN.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='All-NaN slice encountered', category=RuntimeWarning)
        return np.nanmedian(np.stack(arrays), axis=0)


def process(config='config.json'):
    c = read_settings(config)
    source = c['source']
    if source == 'copernicus':
        from download import run
        run(config)
        source = 'safe'
    if source not in ('tif', 'safe'):
        raise ValueError('source must be tif or safe (use download.py first for copernicus)')
    sites = json.loads(Path(c['sites']).read_text())['features']
    # Site polygons in GeoJSON are longitude/latitude (EPSG:4326).
    if not sites or any(f['geometry']['type'] not in ('Polygon', 'MultiPolygon') for f in sites):
        raise ValueError('sites GeoJSON must contain polygon features')
    crs = c.get('crs', 'EPSG:32630')  # Correct for La Teste-de-Buch
    projected = [(f['properties']['site_id'], transform_geom('EPSG:4326', crs, f['geometry'])) for f in sites]
    coords = []
    def collect(x):
        if isinstance(x[0], (int, float)):
            coords.append(x)
        else:
            for item in x: collect(item)
    for _, geom in projected: collect(geom['coordinates'])
    resolution = int(c.get('resolution_m', 20))
    minx, miny = min(p[0] for p in coords), min(p[1] for p in coords)
    maxx, maxy = max(p[0] for p in coords), max(p[1] for p in coords)
    width = int(np.ceil((maxx-minx)/resolution))
    height = int(np.ceil((maxy-miny)/resolution))
    transform = from_origin(minx, maxy, resolution, resolution)
    shape = (height, width)
    masks = [(site, geometry_mask([geom], out_shape=shape, transform=transform, invert=True))
             for site, geom in projected]
    grouped = defaultdict(list)
    provenance = []
    for day, file in find_images(c['images'], source):
        ndvi, nbr = read_scene(file, source, crs, transform, shape)
        grouped[(day.year, day.month)].append((ndvi, nbr))
        provenance.append({'file': file.name, 'date': day.strftime('%Y-%m-%d'),
                           'clear_aoi_fraction': round(float(np.isfinite(ndvi).mean()), 3)})
    monthly = {}
    for key, scenes in sorted(grouped.items()):
        monthly[key] = (median_stack([x[0] for x in scenes]), median_stack([x[1] for x in scenes]))
    out = Path(c['output']); out.mkdir(parents=True, exist_ok=True)
    records = []
    map_summary = []
    # Clean old maps from earlier runs (otherwise reference-only years remain in outputs).
    for pattern in ('ndvi_change_*.tif', 'disturbance_*.tif'):
        for old_map in out.glob(pattern):
            old_map.unlink()
    for (year, month), (ndvi, nbr) in sorted(monthly.items()):
        earlier = [monthly[(y, month)][0] for y, m in monthly if m == month and y < year]
        # No chosen disturbance year: start comparisons when the same month exists
        # in at least two earlier years. Earlier images are still baseline inputs.
        if len(earlier) < 2:
            continue
        baseline = median_stack(earlier)
        valid_baseline = np.sum(np.isfinite(np.stack(earlier)), axis=0) >= 2
        baseline[~valid_baseline] = np.nan
        # Spatial map: 1=NDVI decline, 0=stable, 255=no comparison/baseline.
        # Keep missing or cloudy pixels separate from unchanged vegetation.
        valid_pixel = np.isfinite(ndvi) & np.isfinite(baseline)
        diff = np.where(valid_pixel, ndvi - baseline, np.nan).astype('float32')
        disturbance = np.full(shape, 255, dtype='uint8')
        disturbance[valid_pixel] = 0
        disturbance[valid_pixel & (diff < c['ndvi_drop'])] = 1
        profile = dict(driver='GTiff', height=height, width=width, count=1,
                       crs=crs, transform=transform, compress='deflate')
        with rasterio.open(out / f'ndvi_change_{year}{month:02d}.tif', 'w',
                           dtype='float32', nodata=-9999, **profile) as dst:
            dst.write(np.where(np.isfinite(diff), diff, -9999).astype('float32'), 1)
        with rasterio.open(out / f'disturbance_{year}{month:02d}.tif', 'w',
                           dtype='uint8', nodata=255, **profile) as dst:
            dst.write(disturbance, 1)
        map_summary.append({'month': f'{year}-{month:02d}', 'comparable_pixels': int((disturbance != 255).sum()),
                            'disturbed_pixels': int((disturbance == 1).sum())})
        for site_id, mask in masks:
            total = int(mask.sum())
            valid = mask & np.isfinite(ndvi)
            coverage = valid.sum() / total if total else 0
            comparable = valid & np.isfinite(baseline)
            affected = comparable & ((ndvi-baseline) < c['ndvi_drop'])
            fraction = float(affected.sum()/comparable.sum()) if comparable.any() else 0.
            # At least two previous years for a meaningful seasonal baseline.
            if coverage < c['min_clear_fraction'] or comparable.sum()/max(total, 1) < c['min_clear_fraction']:
                status = 'INSUFFICIENT_DATA'
            elif fraction >= c['min_affected_fraction']:
                status = 'POTENTIAL_DISTURBANCE'
            else:
                status = 'STABLE'
            records.append({'site_id': site_id, 'year': year, 'month': month,
                            'status': status, 'clear_fraction': round(float(coverage), 3),
                            'affected_fraction': round(fraction, 3),
                            'mean_ndvi': round(float(np.nanmean(ndvi[valid])), 3) if valid.any() else '',
                            'mean_nbr': round(float(np.nanmean(nbr[valid])), 3) if valid.any() else '',
                            'baseline_years': len(earlier), 'input_scenes': len(grouped[(year, month)])})
    with (out/'alerts.csv').open('w', newline='') as fh:
        if records:
            writer = csv.DictWriter(fh, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
        else:
            fh.write('site_id,year,month,status\n')
    features = []
    for row in records:
        geom = next(f['geometry'] for f in sites if f['properties']['site_id'] == row['site_id'])
        features.append({'type': 'Feature', 'geometry': geom, 'properties': row})
    (out/'alerts.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features}, indent=2))
    report = {'source': source, 'synthetic_data': bool(c.get('synthetic_data', False)),
              'crs': crs, 'resolution_m': resolution, 'dates_and_clear_coverage': provenance, 'raster_maps': map_summary,
              'notes': ['SCL classes 4/5/6 used as clear; thin clouds may remain.',
                        'Monthly median from available scenes; missing months remain missing.',
                        'No predefined disturbance year; compare with at least two preceding same-month years.',
                        'Reference-only months produce no alert rows or disturbance maps.',
                        'Each comparable pixel requires at least two valid earlier same-month values.',
                        'Potential vegetation disturbance is not proof of biotope damage.',
                        'Site polygons are test sites, not official protected biotope boundaries.',
                        'Baseline confidence limited when prior years or clear pixels are few.',
                        'NBR reported as complementary indicator, not a separate alert rule.',
                        'No direct iris_staging integration; local GeoJSON/CSV are proposed staging outputs.',
                        'Maps: 1=potential disturbance, 0=no significant decline, 255=no valid comparison.',
                        'YYYYMM GeoTIFF filenames are monthly labels, not exact acquisition dates.']}
    (out/'quality_report.json').write_text(json.dumps(report, indent=2))
    print(f'Read {len(grouped)} months; analyzed {len(map_summary)} months, {len(sites)} sites: {out}/alerts.csv')
    return records


if __name__ == '__main__':
    import sys
    process(sys.argv[1] if len(sys.argv)>1 else 'config.json')
