"""Search and download Sentinel-2 L2A SAFE products from Copernicus Data Space.
Run: python download.py (config.json selects years/months). No passwords saved.
"""
import getpass
import json
import os
import zipfile
from datetime import date
from pathlib import Path

import requests

CATALOG = 'https://catalogue.dataspace.copernicus.eu/odata/v1/Products'
DOWNLOAD = 'https://download.dataspace.copernicus.eu/odata/v1/Products'
TOKEN = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'


def month_products(session, bbox, year, month, max_cloud):
    west, south, east, north = bbox
    polygon = f'POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))'
    start = date(year, month, 1).isoformat()
    end = date(year + 1, 1, 1).isoformat() if month == 12 else date(year, month + 1, 1).isoformat()
    query = (
        "Collection/Name eq 'SENTINEL-2' and "
        "Attributes/OData.CSC.StringAttribute/any(a:a/Name eq 'productType' "
        "and a/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
        f"ContentDate/Start ge {start}T00:00:00.000Z and "
        f"ContentDate/Start lt {end}T00:00:00.000Z and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{polygon}')"
    )
    response = session.get(CATALOG, params={'$filter': query, '$top': 100,
                                            '$orderby': 'ContentDate/Start asc', '$expand': 'Attributes'}, timeout=90)
    response.raise_for_status()
    items = [p for p in response.json().get('value', []) if 'MSIL2A' in p['Name']]
    # Some catalogue records omit cloudCover. Keep only records with a trusted value.
    def cloud(p):
        for a in p.get('Attributes', []):
            if a.get('Name') == 'cloudCover':
                return float(a['Value'])
        return 101.0
    eligible = sorted((p for p in items if cloud(p) <= max_cloud), key=cloud)
    if items and not eligible:
        print(f'Found {len(items)} L2A products, but none with cloud coverage <= {max_cloud}%')
    return eligible


def obtain_token(session):
    username = os.environ.get('CDSE_USER') or input('Copernicus account email: ')
    password = os.environ.get('CDSE_PASSWORD') or getpass.getpass('Copernicus password: ')
    response = session.post(TOKEN, data={'client_id': 'cdse-public', 'grant_type': 'password',
                                         'username': username, 'password': password}, timeout=60)
    response.raise_for_status()
    return response.json()['access_token']


def unpack_safe(archive, destination):
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            path = Path(member.filename)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe path in downloaded ZIP')
        z.extractall(destination)


def run(config='config.json'):
    settings = json.loads(Path(config).read_text())
    destination = Path(settings['images'])
    destination.mkdir(parents=True, exist_ok=True)
    months = settings['months']
    if any(m not in range(1, 13) for m in months):
        raise ValueError('months must be between 1 and 12')
    with requests.Session() as session:
        token = None
        for year in range(settings['start_year'], settings['end_year'] + 1):
            for month in months:
                items = month_products(session, settings['bbox_lonlat'], year, month,
                                       settings.get('max_scene_cloud_percent', 25))
                if not items:
                    print(f'{year}-{month:02d}: no matching L2A product')
                    continue
                # One least-cloudy whole-tile product per month, not an AOI-based cloud minimum.
                product = items[0]
                name = product['Name'].removesuffix('.SAFE')
                safe = destination / (name + '.SAFE')
                archive = destination / (name + '.zip')
                if safe.is_dir():
                    print('Already available:', safe.name)
                    continue
                if token is None:
                    token = obtain_token(session)
                print('Downloading (full SAFE tile; may be >1 GB):', name)
                try:
                    url = f"{DOWNLOAD}({product['Id']})/$value"
                    with session.get(url, headers={'Authorization': f'Bearer {token}'},
                                     stream=True, timeout=(30, 180)) as result:
                        if result.status_code == 401:
                            token = obtain_token(session)
                            result.close()
                            result = session.get(url, headers={'Authorization': f'Bearer {token}'},
                                                 stream=True, timeout=(30, 180))
                        result.raise_for_status()
                        with archive.open('wb') as file:
                            for block in result.iter_content(chunk_size=1024 * 1024):
                                if block:
                                    file.write(block)
                    unpack_safe(archive, destination)
                except Exception:
                    archive.unlink(missing_ok=True)  # never retain a partial ZIP
                    raise
                archive.unlink(missing_ok=True)
                if not safe.is_dir():
                    raise RuntimeError(f'Archive extracted but {safe.name} not found; inspect ZIP layout')
                print('Ready:', safe.name)
    print('Copernicus download stage finished.')


if __name__ == '__main__':
    import sys
    run(sys.argv[1] if len(sys.argv) > 1 else 'config.json')
