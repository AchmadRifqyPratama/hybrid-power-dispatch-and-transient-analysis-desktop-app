"""Klien data angin ERA5 (reanalisis ECMWF / Copernicus C3S) untuk WTG.

ERA5 menyediakan angin per-jam pada 10 m dan 100 m (grid 0,25°) sejak 1940.
Untuk turbin angin dipakai angin **100 m** — dekat ketinggian hub, sehingga
ekstrapolasi hukum pangkat (IEC 61400-1) hanya menempuh jarak pendek.

Dua jalur unduhan (dipilih di halaman Data):

* ``open-meteo``  — Open-Meteo Historical Weather API (``models=era5``).
  Tanpa akun; data berlisensi CC BY 4.0. Pemakaian KOMERSIAL memerlukan API
  key Open-Meteo (server ``customer-archive-api``) — isikan pada kolom API key.
* ``cds``         — Copernicus Climate Data Store (sumber resmi), dataset
  ``reanalysis-era5-single-levels-timeseries`` (deret titik, CSV). Memerlukan
  akun CDS gratis + personal access token, dan paket Python ``cdsapi``.

Keduanya mengembalikan struktur yang sama. Waktu ERA5 adalah UTC; deret
digeser ke waktu lokal (≈ bujur/15°) agar sejajar profil beban — sama seperti
klien PVGIS. Modul MURNI-data (tanpa GUI).

Atribusi yang wajib dicantumkan pada laporan: "Contains modified Copernicus
Climate Change Service information" (+ Open-Meteo bila jalur itu dipakai).
"""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import zipfile
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import numpy as np

from .pvgis import _utc_offset_hours

_UA = 'HPPStudio/1.0 (Akartha Energi Baru)'
OPEN_METEO_FREE = 'https://archive-api.open-meteo.com/v1/archive'
OPEN_METEO_PAID = 'https://customer-archive-api.open-meteo.com/v1/archive'
CDS_URL = 'https://cds.climate.copernicus.eu/api'
CDS_DATASET = 'reanalysis-era5-single-levels-timeseries'
ERA5_HEIGHT_M = 100.0
ATTRIBUTION = ('Contains modified Copernicus Climate Change Service '
               'information (ERA5).')


class ERA5Error(Exception):
    pass


def _finish(ws100, ws10, t2m, lat, lon, year, provider, grid=None) -> dict:
    """Validasi, geser UTC -> waktu lokal, rangkum."""
    ws100 = np.asarray(ws100, float)
    n = int(ws100.size)
    if n not in (8760, 8784):
        raise ERA5Error(f'ERA5 returned {n} hourly values '
                        '(expected 8760 or 8784 for a full year).')
    if not np.isfinite(ws100).all():
        bad = int((~np.isfinite(ws100)).sum())
        if bad > 0.02 * n:
            raise ERA5Error(f'ERA5 wind series has {bad} missing values.')
        idx = np.arange(n)
        ok = np.isfinite(ws100)
        ws100 = np.interp(idx, idx[ok], ws100[ok])
    ws100 = np.clip(ws100, 0.0, None)
    off = _utc_offset_hours(lon)
    out = dict(provider=provider, lat=float(lat), lon=float(lon),
               year=int(year), height_m=ERA5_HEIGHT_M, utc_offset_h=off,
               attribution=ATTRIBUTION)
    if grid:
        out['grid_lat'], out['grid_lon'] = grid

    def loc(a):
        if a is None:
            return None
        a = np.nan_to_num(np.asarray(a, float))
        return np.roll(a, off) if (off and a.size == n) else a
    out['ws100'] = loc(ws100)
    out['ws10'] = loc(ws10) if ws10 is not None and np.size(ws10) == n else None
    t = loc(t2m) if t2m is not None and np.size(t2m) == n else None
    out['t2m'] = t
    out['mean_ws100'] = float(np.mean(out['ws100']))
    out['max_ws100'] = float(np.max(out['ws100']))
    out['mean_ws10'] = (float(np.mean(out['ws10']))
                        if out['ws10'] is not None else None)
    out['mean_t2m'] = float(np.mean(t)) if t is not None else None
    # eksponen geser efektif 10 m -> 100 m (informasi: bandingkan dgn 0,2 IEC)
    if out['mean_ws10'] and out['mean_ws10'] > 0.1:
        out['shear_10_100'] = float(np.log(out['mean_ws100'] / out['mean_ws10'])
                                    / np.log(10.0))
    return out


# ---------------------------------------------------------------- Open-Meteo
def parse_open_meteo(doc: dict, lat, lon, year) -> dict:
    if not isinstance(doc, dict):
        raise ERA5Error('Open-Meteo response is not valid JSON.')
    if doc.get('error'):
        raise ERA5Error('Open-Meteo: ' + str(doc.get('reason', 'request rejected')))
    h = doc.get('hourly') or {}
    if 'wind_speed_100m' not in h:
        raise ERA5Error('Open-Meteo response has no 100 m wind speed.')
    unit = str((doc.get('hourly_units') or {}).get('wind_speed_100m', 'm/s')).lower()
    k = 1.0 / 3.6 if 'km' in unit else 1.0

    def arr(key):
        v = h.get(key)
        if v is None:
            return None
        return np.asarray([np.nan if x is None else float(x) for x in v], float)
    ws100 = arr('wind_speed_100m') * k
    ws10 = arr('wind_speed_10m')
    ws10 = ws10 * k if ws10 is not None else None
    return _finish(ws100, ws10, arr('temperature_2m'), lat, lon, year,
                   'Open-Meteo (ERA5)',
                   grid=(doc.get('latitude'), doc.get('longitude')))


def fetch_open_meteo(lat, lon, year: int, api_key: str = '',
                     timeout: float = 90.0) -> dict:
    params = {
        'latitude': f'{float(lat):.5f}', 'longitude': f'{float(lon):.5f}',
        'start_date': f'{int(year)}-01-01', 'end_date': f'{int(year)}-12-31',
        'hourly': 'wind_speed_10m,wind_speed_100m,temperature_2m',
        'models': 'era5', 'wind_speed_unit': 'ms', 'timezone': 'GMT',
    }
    base = OPEN_METEO_FREE
    if api_key and api_key.strip():
        params['apikey'] = api_key.strip()
        base = OPEN_METEO_PAID
    req = Request(base + '?' + urlencode(params), headers={'User-Agent': _UA})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', 'replace')
    except HTTPError as e:
        detail = ''
        try:
            detail = json.loads(e.read().decode('utf-8', 'replace')).get('reason', '')
        except Exception:
            pass
        raise ERA5Error(f'Open-Meteo rejected the request (HTTP {e.code}). '
                        f'{detail}'.strip())
    except (URLError, TimeoutError) as e:
        raise ERA5Error('Cannot reach the Open-Meteo server — check the '
                        f'internet connection. ({e})')
    try:
        doc = json.loads(raw)
    except Exception:
        raise ERA5Error('Open-Meteo response is not valid JSON.')
    return parse_open_meteo(doc, lat, lon, year)


# ---------------------------------------------------------------- Copernicus CDS
def parse_cds_csv(text: str, lat, lon, year) -> dict:
    """CSV deret-titik CDS: kolom waktu + komponen angin u/v (10 m & 100 m).
    Nama kolom dikenali longgar (u100/v100/u10/v10/t2m atau nama panjangnya)."""
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if r and not str(r[0]).lstrip().startswith('#')]
    if len(rows) < 2:
        raise ERA5Error('CDS CSV is empty.')
    head = [str(c).strip().lower() for c in rows[0]]

    def col(*keys):
        for k in keys:
            for i, name in enumerate(head):
                if name == k or name.replace(' ', '_') == k:
                    return i
        for k in keys:
            for i, name in enumerate(head):
                if k in name:
                    return i
        return None
    iu100 = col('u100', '100m_u_component_of_wind', '100m_u')
    iv100 = col('v100', '100m_v_component_of_wind', '100m_v')
    iu10 = col('u10', '10m_u_component_of_wind', '10m_u')
    iv10 = col('v10', '10m_v_component_of_wind', '10m_v')
    it2 = col('t2m', '2m_temperature')
    if iu100 is None or iv100 is None:
        raise ERA5Error('CDS CSV has no 100 m wind components '
                        f'(columns: {", ".join(rows[0])}).')

    def num(i):
        if i is None:
            return None
        out = []
        for r in rows[1:]:
            try:
                out.append(float(r[i]))
            except (ValueError, IndexError):
                out.append(np.nan)
        return np.asarray(out, float)
    ws100 = np.hypot(num(iu100), num(iv100))
    ws10 = (np.hypot(num(iu10), num(iv10))
            if iu10 is not None and iv10 is not None else None)
    t2 = num(it2)
    if t2 is not None and np.nanmean(t2) > 150:          # Kelvin -> °C
        t2 = t2 - 273.15
    return _finish(ws100, ws10, t2, lat, lon, year, 'Copernicus CDS (ERA5)')


def fetch_cds(lat, lon, year: int, token: str, url: str = CDS_URL) -> dict:
    try:
        import cdsapi
    except Exception:
        raise ERA5Error('Python package "cdsapi" is not installed. Install it '
                        '(pip install cdsapi) or use the Open-Meteo source.')
    if not token or not token.strip():
        raise ERA5Error('A Copernicus CDS personal access token is required '
                        '(cds.climate.copernicus.eu → your profile).')
    req = {
        'variable': ['10m_u_component_of_wind', '10m_v_component_of_wind',
                     '100m_u_component_of_wind', '100m_v_component_of_wind',
                     '2m_temperature'],
        'location': {'longitude': float(lon), 'latitude': float(lat)},
        'date': [f'{int(year)}-01-01/{int(year)}-12-31'],
        'data_format': 'csv',
    }
    tmp = tempfile.mkdtemp(prefix='hpps_era5_')
    target = os.path.join(tmp, 'era5.zip')
    try:
        client = cdsapi.Client(url=url, key=token.strip(), quiet=True)
        client.retrieve(CDS_DATASET, req, target)
        text = None
        if zipfile.is_zipfile(target):
            with zipfile.ZipFile(target) as z:
                names = [n for n in z.namelist() if n.lower().endswith('.csv')]
                if not names:
                    raise ERA5Error('CDS archive contains no CSV file.')
                text = z.read(names[0]).decode('utf-8', 'replace')
        else:
            with open(target, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()
    except ERA5Error:
        raise
    except Exception as e:
        raise ERA5Error(f'CDS download failed: {e}')
    finally:
        try:
            for n in os.listdir(tmp):
                os.remove(os.path.join(tmp, n))
            os.rmdir(tmp)
        except Exception:
            pass
    return parse_cds_csv(text, lat, lon, year)


def fetch_wind(lat, lon, year: int, provider: str = 'open-meteo',
               api_key: str = '') -> dict:
    if abs(float(lat)) < 1e-9 and abs(float(lon)) < 1e-9:
        raise ERA5Error('Project location is not set (latitude/longitude 0, 0).')
    if str(provider).lower().startswith('cds'):
        return fetch_cds(lat, lon, year, api_key)
    return fetch_open_meteo(lat, lon, year, api_key)


def export_era5_xlsx(path: str, res: dict, datetimes=None) -> str:
    import pandas as pd
    n = len(res['ws100'])
    if datetimes is None or len(datetimes) != n:
        datetimes = pd.date_range(f"{res['year']}-01-01", periods=n, freq='h')
    df = pd.DataFrame({'Datetime': pd.DatetimeIndex(datetimes),
                       'Wind Speed 100 m (m/s)': res['ws100']})
    if res.get('ws10') is not None:
        df['Wind Speed 10 m (m/s)'] = res['ws10']
    if res.get('t2m') is not None:
        df['Temperature 2 m (°C)'] = res['t2m']
    info = pd.DataFrame([
        ('Source', res.get('provider', 'ERA5')),
        ('Latitude', res['lat']), ('Longitude', res['lon']),
        ('Year', res['year']),
        ('Time basis', f"local time (UTC{res.get('utc_offset_h', 0):+d} from longitude)"),
        ('Mean wind speed 100 m (m/s)', res['mean_ws100']),
        ('Mean wind speed 10 m (m/s)', res.get('mean_ws10')),
        ('Effective shear exponent 10→100 m', res.get('shear_10_100')),
        ('Attribution', res.get('attribution', ATTRIBUTION)),
    ], columns=['Item', 'Value'])
    with pd.ExcelWriter(path, engine='openpyxl') as xw:
        df.to_excel(xw, sheet_name='ERA5 Wind', index=False)
        info.to_excel(xw, sheet_name='Info', index=False)
    return path
