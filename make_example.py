"""Make small synthetic teaching TIFFs; not real satellite observations."""
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

root = Path('data'); (root/'images').mkdir(parents=True, exist_ok=True)
west, south, east, north = -1.23, 44.51, -1.16, 44.56
x1, y1, x2, y2 = transform_bounds('EPSG:4326', 'EPSG:32630', west,south,east,north)
size = 20
width, height = int((x2-x1)/size)+2, int((y2-y1)/size)+2
transform = from_origin(x1,y2,size,size)
# Two representative sites inside the rectangle, not official protected habitat boundaries.
sites = [{'type':'Feature','properties':{'site_id':name},'geometry':{'type':'Polygon','coordinates':[[[a,44.52],[b,44.52],[b,44.55],[a,44.55],[a,44.52]]]}}
         for name,a,b in [('FOREST_WEST',-1.224,-1.194),('FOREST_EAST',-1.19,-1.164)]]
(root/'sites.geojson').write_text(json.dumps({'type':'FeatureCollection','features':sites},indent=2))
# Simple synthetic reflectances in scaled Sentinel-2 style; after August 2022 west is disturbed.
for year in [2020,2021,2022]:
    for month in [6,8]:
        red = np.full((height,width), 2000, dtype='int16')
        nir = np.full((height,width), 7000, dtype='int16')
        swir = np.full((height,width), 2200, dtype='int16')
        scl = np.full((height,width), 4, dtype='int16')
        if year == 2022 and month == 8:
            red[:,:width//2] = 3700
            nir[:,:width//2] = 4200
            swir[:,:width//2] = 4500
        # Put a small cloud patch in all scenes; in August 2022 slightly larger.
        scl[0:20, 0:20 if month == 6 else 40] = 9
        path = root/'images'/f'S2_{year}{month:02d}15.tif'
        with rasterio.open(path,'w',driver='GTiff',height=height,width=width,
                           count=4,dtype='int16',crs='EPSG:32630',transform=transform,
                           compress='deflate') as ds:
            for i,arr in enumerate((red,nir,swir,scl),1): ds.write(arr,i)
            ds.descriptions = ('B04','B08','B12','SCL')
print('Created six SYNTHETIC 4-band TIFFs and two test-site polygons.')
