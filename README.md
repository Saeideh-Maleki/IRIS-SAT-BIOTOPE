# IRIS Task 119 — Sentinel-2 Biotope Disturbance Detector

## 1\. Purpose

This Python project **screens for potential vegetation disturbance** in multi-year Sentinel-2 Level-2A imagery. It compares each observed month with the **same calendar month in earlier years** and produces pixel-level change maps, site-level alerts, and a quality report. **The user does not specify a disturbance year.**

The demonstration uses **La Teste-de-Buch, France**, near the July 2022 wildfire. The two polygons in `data/sites.geojson` are **illustrative monitoring sites**, not official protected-biotope boundaries or an official fire perimeter.

## 2\. What you need

* Python 3.11 or newer, with the packages in `requirements.txt`.
* A `config.json` settings file and `data/sites.geojson` site polygons.
* Sentinel-2 **Level-2A** input, from one of three supported sources:

|`source` in `config.json`|Input|Internet needed for processing?|
|-|-|-|
|`"tif"`|Local four-band GeoTIFFs (including suitable GEE exports)|No|
|`"safe"`|Local, extracted Sentinel-2 L2A `.SAFE` product folders|No|
|`"copernicus"`|Automatically searches/downloads L2A SAFE from Copernicus Data Space|Yes, for download|

Google Earth Engine is **not required to run this software**. If using GEE-exported imagery, retain the export settings and acquisition-date information to make the input provenance reproducible.

### Project files

|File or folder|Purpose|
|-|-|
|`main.py`|Reads imagery, calculates NDVI/NBR, produces alerts and maps|
|`download.py`|Copernicus catalogue search and authenticated SAFE download|
|`config.json`|User-selectable source, paths and thresholds|
|`data/images/`|Local satellite input files|
|`data/sites.geojson`|Monitoring-site polygons|
|`outputs/`|Generated maps, CSV/GeoJSON alerts, quality report|
|`tests/`|Automated checks|
|`requirements.txt`|Python packages|
|`Dockerfile`, `docker-compose.yml`|Container configuration|
|`make\_example.py` (optional)|Creates **synthetic** teaching images; do not run in a real-data folder because it writes to `data/images/` and `data/sites.geojson`|

## 3\. First run — local GeoTIFFs (simplest option)

1. TIFFs are downloaded from GEE and stored  in `data/images/` .
2. Set these fields in `config.json` (leave the other existing settings as they are):

```json
"source": "tif",
"images": "data/images",
"sites": "data/sites.geojson",
"output": "outputs"
```

3. Open the project folder (the one containing `main.py`) in Windows File Explorer. Click its address bar, type `powershell`, and press Enter.
4. Install dependencies (once), then run:

```powershell
py -3.11 -m pip install -r requirements.txt
py -3.11 main.py
```

If `py` is not available, use the installed Python executable instead. Example for a standard Windows user installation:

```powershell
\& "$env:LOCALAPPDATA\\Programs\\Python\\Python311\\python.exe" -m pip install -r requirements.txt
\& "$env:LOCALAPPDATA\\Programs\\Python\\Python311\\python.exe" main.py
```

**TIFF requirements:** Four bands in this exact order: **B04 (red), B08 (NIR), B12 (SWIR), SCL (scene classification)**. Images must be spatially compatible. Examples of supported names: `S2\_202006.tif` for a **monthly label**, or `S2\_20200615.tif` for a date. A monthly filename does **not** establish the actual acquisition day. Record the original scene IDs/dates separately when using exported TIFFs. Sentinel-2 L2A bands can be stored as scaled reflectance integers; the ratios NDVI/NBR are unchanged by a common multiplicative scale.

## 4\. Use local SAFE products

1. Download **Sentinel-2 Level-2A**, not L1C, from [Copernicus Browser](https://browser.dataspace.copernicus.eu/).
2. Extract the **complete** `.SAFE` folders into `data/images/` .
3. Set `"source": "safe"` in `config.json`.
4. Run `main.py` using the same PowerShell command in Section 3.

The SAFE reader locates B04, B08, B12 and SCL from the product's JPEG2000 files. SAFE scenes are typically full tiles and can use substantial disk space.

## 5\. Automatically download SAFE products from Copernicus

1. Create a free Copernicus Data Space account at [https://dataspace.copernicus.eu/](https://dataspace.copernicus.eu/).
2. In `config.json`, set the following **inside the existing JSON object** (adjust as needed):

```json
"source": "copernicus",
"start\_year": 2020,
"end\_year": 2023,
"months": \[6, 8],
"max\_scene\_cloud\_percent": 25
```

3. Keep the existing `bbox\_lonlat` setting for the study area, or replace it with your area's bounding box (`\[west, south, east, north]`, longitude/latitude).
4. Run `main.py` as shown in Section 3. Enter your **Copernicus** email and password when prompted; the password is hidden as you type. 

The downloader searches for L2A imagery and downloads **up to one least-cloudy whole-tile product per selected month**. Downloaded SAFE files are processed by the same analysis code. The catalogue cloud percentage describes the tile, **not necessarily your small study area**. The SCL mask is applied during processing. Some months can still have inadequate coverage; this is recorded rather than filled with invented observations. Products can exceed 1 GB. The official interface is documented at [https://documentation.dataspace.copernicus.eu/APIs/OData.html](https://documentation.dataspace.copernicus.eu/APIs/OData.html).



## 6\. How the detector works

1. Read the bands B04, B08, B12 and SCL. Retain SCL classes **4 (vegetation), 5 (non-vegetated), 6 (water)** and reject other classes (clouds, cloud shadows and uncertain pixels). Water inclusion is a current screening choice and may need adjustment for particular terrestrial habitats.
2. Calculate:

   * **NDVI** = `(B08 - B04) / (B08 + B04)`
   * **NBR** = `(B08 - B12) / (B08 + B12)`
3. For an observation in a given month, find available observations from the **same calendar month in earlier years**. Each pixel needs **at least two valid prior-year NDVI observations** to form its historical median.
4. Calculate **NDVI change = current NDVI − historical same-month median NDVI**.
5. Mark pixels with change below the configurable default threshold **−0.20** as **potential vegetation decline**.
6. Make site alerts from the comparable pixels, subject to the minimum clear/comparable coverage (default **60%**) and affected fraction (default **15%**). Report `INSUFFICIENT\_DATA` rather than assume missing pixels are stable.

**Automatic baseline:** No specific fire/disturbance year or fixed baseline year is entered. For example, with June/August imagery spanning **2020–2023**, **2020–2021** contribute to the historical references, while **2022–2023** can produce maps once two earlier same-month observations exist. With a different starting year, the same rule applies automatically. Earlier periods are still used as inputs. NBR is a supporting indicator and does **not** independently trigger the current alert.

## 7\. Outputs and interpretation

The program writes to `outputs/`:

|Output|Meaning|
|-|-|
|`ndvi\_change\_YYYYMM.tif`|Per-pixel NDVI minus same-month historical median; **negative** values represent decline; nodata = `-9999`|
|`disturbance\_YYYYMM.tif`|Per-pixel class **1** = potential decline; **0** = no decline beyond threshold; **255** = no valid comparison|
|`alerts.csv`|One record per eligible site/month: disturbance status and supporting indicators|
|`alerts.geojson`|Monitoring-site polygons with dates and alert attributes. **Not pixel-level disturbance outlines**; records for different dates overlap|
|`quality\_report.json`|Input coverage, quality notes and methodological gaps|

**Site alert labels:** `POTENTIAL\_DISTURBANCE` means the configured rule was triggered; `STABLE` means it was not triggered for adequately observed data; `INSUFFICIENT\_DATA` means the observation cannot be assessed reliably. These are **screening categories, not independently verified ground truth**.

**Example interpretation:** In an earlier La Teste-de-Buch TIFF run, the illustrative `FOREST\_WEST` site had August 2021 NDVI around **0.794** and August 2022 NDVI around **0.418**, an observed difference around **−0.376**. Approximately **78%** of comparable pixels were flagged in that run. The values must be recalculated if imagery, sites or settings change. They do **not** prove that the fire caused the decline. In August 2022 `FOREST\_EAST` had about **59%** usable coverage, below the 60% site minimum, and was flagged as insufficient data.

### View results in QGIS

1. Add `outputs/disturbance\_202208.tif` as a raster layer.
2. Right-click layer → **Properties → Symbology → Paletted/Unique values**.
3. Color **1 red**, **0 green**, and make **255 transparent** (missing comparison).
4. Add `outputs/ndvi\_change\_202208.tif` to inspect the magnitude of decline. For site alerts, load `alerts.geojson` and filter its **date/month attribute** so overlapping site polygons are not mistaken for independent areas.

Some maps can look incomplete: cloud-masked or otherwise incomparable pixels are deliberately shown as missing rather than classified. A monthly single-scene image is **not** the same as a cloud-free monthly composite.

## 8\. Run automated tests

From PowerShell in the project folder:

```powershell
py -3.11 -m pytest -q
```

Or use the full Python executable path from Section 3. Five local automated tests passed in the checked project version. **Passing tests checks selected code behaviors, not scientific validation of every real-world alert.**

## 9\. Run with Docker

Install and start Docker Desktop. In the project folder, set `"source": "tif"` (the easiest offline test), then run:

```powershell
docker compose up --build
```

The supplied Compose configuration makes local `data/` available and writes output to local `outputs/`. Building an image requires access to the Python base image and dependencies. 

## 10\. Reproducibility, assumptions and limitations

* **Provenance:** Sentinel-2 L2A data. Record exact product IDs/acquisition dates, image source, preprocessing/export settings and applicable Copernicus data terms when publishing the real-data demonstration. A monthly filename such as `S2\_202208.tif` is a period label, **not** proof of acquisition on August 1.
* **Scope:** The sample monitors two **illustrative** polygons; they are **not** official protected or compensation biotope boundaries. For an operational protected-biotope service, substitute authoritative site boundaries and independently validate alerts.
* **Interpretation:** NDVI decline may be associated with fire, vegetation clearance, drought or natural seasonal changes. Same-month comparison reduces but does not eliminate phenology effects. The −0.20 threshold is an example, not a universally validated ecological threshold.
* **Missing data:** The current SCL filter and a single selected scene per month can leave large gaps. The detector flags insufficient observations rather than fill them artificially. No automatic monthly multi-scene compositing is claimed.
* **Geographic reference:** Example raster processing uses **EPSG:32630** (appropriate UTM zone for La Teste-de-Buch); GeoJSON site geometries are in **EPSG:4326**. Check/adapt projected CRS for other locations.
* **Integration:** Output files demonstrate a local, staging-style interface. The assignment's `iris\_staging` service interface was not supplied, so **no live staging/production database write is implemented**. Nothing writes to `iris\_core` or production systems.

## The example GeoTIFF images were exported from Google Earth Engine using Sentinel-2 Level-2A data. The original GEE export script is not included. For independent data acquisition and processing, the project provides an automated Copernicus Data Space download option.

