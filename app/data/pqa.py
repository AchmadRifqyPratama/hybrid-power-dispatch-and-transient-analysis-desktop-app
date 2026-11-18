"""Impor data Power Quality Analyzer (PQA) untuk Transient Analysis.

v166 — format utama = KOLOM TEMPLATE (lihat GROUPS / write_template()) dengan
lima analisis pengukuran (sag/swell, frekuensi & RoCoF, profil beban, unbalance,
harmonisa); analisis yang kolomnya tidak tersedia dilewati. Uraian di bawah
adalah parser longgar lama, kini hanya cadangan untuk berkas tanpa kolom
template.

Berkas Excel/CSV rekaman PQA (interval bebas: 200 ms … 10 menit) dibaca dengan
pengenalan kolom yang longgar:

    waktu          : datetime / timestamp / time / waktu / tanggal
    daya aktif     : P, P total, kW, active power, Ptot, W        (wajib)
    daya reaktif   : Q, kvar, reactive power                      (opsional)
    daya semu      : S, kVA, apparent power                       (opsional)
    faktor daya    : PF, cos phi, power factor                    (opsional)
    frekuensi      : f, Hz, frequency                             (opsional)
    tegangan       : U, V, voltage (L-L atau L-N)                 (opsional)

Kolom bersufiks min/max (nilai ekstrem per interval) dikenali terpisah agar
langkah beban terbesar & dip tidak tersamarkan oleh nilai rata-rata.

Hasil = ringkasan kecil (JSON-ramah) yang disimpan di konfigurasi proyek:
beban maksimum / persentil-95 / rata-rata / minimum, faktor daya, step beban
naik & turun terbesar antar-sampel, jendela sampel di sekitar step terbesar
(untuk kasus "measured load replay"), serta rentang frekuensi & tegangan.
"""
from __future__ import annotations

import os
import re

import numpy as np


class PQAError(Exception):
    pass


_PAT = {
    'time': r'date|time|waktu|tanggal|stamp',
    'p': r'(^|[^a-z])(p\b|p[ _-]?(tot|total|sum|avg|mean)|ptot|kw\b|watt|active|daya aktif|real power)',
    'q': r'(^|[^a-z])(q\b|q[ _-]?(tot|total|sum|avg|mean)|qtot|kvar|var\b|reactive|daya reaktif)',
    's': r'(^|[^a-z])(s\b|s[ _-]?(tot|total|sum|avg)|kva\b|apparent|daya semu)',
    'pf': r'(^|[^a-z])(pf|cos|power factor|faktor daya)',
    'f': r'(^|[^a-z])(f\b|freq|hz|frekuensi)',
    'v': r'(^|[^a-z])(u\b|u[ _-]?(avg|ll|ln|12|l1)|v\b|v[ _-]?(avg|ll|ln|12|l1)|volt|tegangan|urms|vrms)',
}


def _pick(cols, kind, used, want=None):
    """Kolom pertama yang cocok pola `kind`; `want` = 'max' / 'min' / None
    (None = hindari kolom ekstrem bila ada pilihan rata-rata)."""
    best = None
    for c in cols:
        if c in used:
            continue
        n = str(c).strip().lower()
        if not re.search(_PAT[kind], n):
            continue
        if kind == 'p' and re.search(r'kvar|kva|pf|factor|react|appar', n):
            continue
        if kind == 'q' and re.search(r'freq', n):
            continue
        if kind == 'v' and re.search(r'kvar|kva|var\b', n):
            continue
        is_max = bool(re.search(r'max|maks|peak', n))
        is_min = bool(re.search(r'\bmin\b|minimum|_min|min_| min', n)) and not is_max
        if want == 'max' and is_max:
            return c
        if want == 'min' and is_min:
            return c
        if want is None and not is_max and not is_min:
            return c
        if want is None and best is None:
            best = c
    return best if want is None else None


def _scale_kw(name, arr):
    """Satuan -> kW/kvar/kVA. Kolom ber-label W/var/VA (tanpa k/M) atau
    bernilai sangat besar dianggap satuan dasar."""
    n = str(name).lower()
    if re.search(r'\bmw\b|mvar|mva', n):
        return arr * 1000.0
    if re.search(r'\(w\)|\[w\]|\bw\b|\(var\)|\[var\]|\(va\)|\[va\]', n) \
            and not re.search(r'kw|kvar|kva', n):
        return arr / 1000.0
    return arr


def _read_generic(df, path: str) -> dict:
    """Parser LONGGAR (format bebas v163) — dipakai hanya bila berkas tidak
    memuat satu pun kolom template."""
    import pandas as pd
    cols = list(df.columns)
    used = set()
    tcol = _pick(cols, 'time', used)
    if tcol is not None:
        used.add(tcol)

    def num(c):
        return pd.to_numeric(df[c], errors='coerce').to_numpy(float)

    pcol = _pick(cols, 'p', used)
    if pcol is None:
        raise PQAError('Active-power column not found (expected a column '
                       'such as "P (kW)", "Active Power", "kW").')
    used.add(pcol)
    p = _scale_kw(pcol, num(pcol))
    ok = np.isfinite(p)
    if ok.sum() < 3:
        raise PQAError(f'Column "{pcol}" has no numeric data.')
    out = dict(source=os.path.basename(path), p_col=str(pcol))
    # interval sampel
    dt_s = None
    if tcol is not None:
        try:
            ts = pd.to_datetime(df[tcol], errors='coerce')
            d = ts.diff().dt.total_seconds().to_numpy(float)
            d = d[np.isfinite(d) & (d > 0)]
            if d.size:
                dt_s = float(np.median(d))
                out['t_start'] = str(ts.dropna().iloc[0])
                out['t_end'] = str(ts.dropna().iloc[-1])
        except Exception:
            dt_s = None
    out['dt_s'] = dt_s
    p = np.where(ok, p, np.nan)
    pv = p[ok]
    out.update(n=int(ok.sum()), p_max=float(np.max(pv)),
               p_p95=float(np.percentile(pv, 95)), p_mean=float(np.mean(pv)),
               p_min=float(np.min(pv)))
    # kolom ekstrem (maks/min per interval) bila ada
    pmx = _pick(cols, 'p', used, 'max')
    if pmx is not None:
        used.add(pmx)
        a = _scale_kw(pmx, num(pmx))
        if np.isfinite(a).any():
            out['p_max'] = float(max(out['p_max'], np.nanmax(a)))
    # daya reaktif / faktor daya
    qcol = _pick(cols, 'q', used)
    pf = None
    q = None
    if qcol is not None:
        used.add(qcol)
        q = _scale_kw(qcol, num(qcol))
    pfcol = _pick(cols, 'pf', used)
    scol = _pick(cols, 's', used)
    if q is not None and np.isfinite(q).any():
        m = ok & np.isfinite(q)
        sp, sq = float(np.sum(p[m])), float(np.sum(np.abs(q[m])))
        if sp > 0:
            pf = sp / float(np.hypot(sp, sq))
        out['q_mean'] = float(np.nanmean(q[m]))
        out['q_max'] = float(np.nanmax(q[m]))
    elif scol is not None:
        sv = _scale_kw(scol, num(scol))
        m = ok & np.isfinite(sv) & (sv > 0)
        if m.any():
            pf = float(np.sum(p[m]) / np.sum(sv[m]))
    elif pfcol is not None:
        a = np.abs(num(pfcol))
        a = a[np.isfinite(a) & (a > 0)]
        if a.size:
            a = np.where(a > 1.0, a / 100.0, a)
            pf = float(np.clip(np.average(a), 0.1, 1.0))
    out['pf'] = None if pf is None else float(min(max(pf, 0.1), 1.0))
    # step beban antar-sampel
    d = np.diff(p)
    dm = np.isfinite(d)
    if dm.any():
        iu = int(np.nanargmax(np.where(dm, d, -np.inf)))
        idn = int(np.nanargmin(np.where(dm, d, np.inf)))
        out['step_up_kw'] = float(max(d[iu], 0.0))
        out['step_dn_kw'] = float(min(d[idn], 0.0))
        k = iu if abs(d[iu]) >= abs(d[idn]) else idn
        a, b = max(0, k - 5), min(p.size, k + 11)
        w = p[a:b]
        w = w[np.isfinite(w)]
        out['window_kw'] = [float(x) for x in w]
        if q is not None:
            wq = q[a:b]
            out['window_kvar'] = [float(x) if np.isfinite(x) else 0.0
                                  for x in wq][:len(out['window_kw'])]
    # frekuensi & tegangan (rentang terukur)
    for kind, key in (('f', 'f'), ('v', 'v')):
        lo = hi = None
        c = _pick(cols, kind, used)
        cmin = _pick(cols, kind, used, 'min')
        cmax = _pick(cols, kind, used, 'max')
        for cc in (c, cmin, cmax):
            if cc is None:
                continue
            used.add(cc)
            a = num(cc)
            a = a[np.isfinite(a) & (a > 0)]
            if a.size:
                lo = float(a.min()) if lo is None else min(lo, float(a.min()))
                hi = float(a.max()) if hi is None else max(hi, float(a.max()))
        if lo is not None:
            out[key + '_min'], out[key + '_max'] = lo, hi
    return out


# =============================================================================
# v166 — FORMAT TEMPLATE PQA (kolom baku) + lima analisis pengukuran
# =============================================================================
GROUPS = [
    ('Identification', ['Date', 'Time']),
    ('Half-Cycle RMS (Max & Min)',
     [f'{q}{i}_rms1/2_{m}' for q in 'UI' for i in (1, 2, 3)
      for m in ('MAX', 'MIN')]),
    ('Frequency & Waveform Metrics',
     ['Freq_wav_MAX', 'Freq_wav_MIN', 'Freq_AVG']),
    ('Phase RMS Averages',
     [f'{q}{i}_rms_AVG' for q in 'UI' for i in (1, 2, 3)]),
    ('System Unbalance & Distortion (THD)',
     ['Uunb_AVG', 'Iunb_AVG'] + [f'U{i}_thd-f_AVG' for i in (1, 2, 3)]),
    ('Harmonic Components (Order 5 & 7)',
     [f'{q}{i}_H{h}_AVG' for q in 'UI' for i in (1, 2, 3) for h in (5, 7)]),
    ('Power, Factor, Energy & Demand',
     ['P_sum_AVG', 'PF_sum_AVG', 'WP+', 'Dem_P+']),
]
TEMPLATE_COLUMNS = [c for _, cs in GROUPS for c in cs]
_UNIT = {'Date': 'date (DD/MM/YYYY or YYYY-MM-DD)', 'Time': 'time (hh:mm:ss)',
         'Freq': 'Hz', 'Uunb_AVG': '%', 'Iunb_AVG': '%', 'P_sum_AVG': 'W or kW',
         'PF_sum_AVG': '- (0…1)', 'WP+': 'Wh or kWh (cumulative)', 'Dem_P+': 'W or kW'}

ANALYSES = [
    ('sag', 'Half-Cycle Transient & Sag/Swell',
     [c for c in TEMPLATE_COLUMNS if 'rms1/2' in c]),
    ('freq', 'Frequency Stability & RoCoF',
     ['Freq_wav_MAX', 'Freq_wav_MIN', 'Freq_AVG']),
    ('load', 'Load Flow, Active & Reactive Power Profiling',
     ['P_sum_AVG', 'PF_sum_AVG', 'WP+', 'Dem_P+']
     + [f'{q}{i}_rms_AVG' for q in 'UI' for i in (1, 2, 3)]),
    ('unb', 'Voltage & Current Unbalance', ['Uunb_AVG', 'Iunb_AVG']),
    ('harm', 'THD & Dominant Harmonics (Order 5 & 7)',
     [f'U{i}_thd-f_AVG' for i in (1, 2, 3)]
     + [f'{q}{i}_H{h}_AVG' for q in 'UI' for i in (1, 2, 3) for h in (5, 7)]),
]
# Batas acuan (EN 50160 / IEC 61000-2-2, jaringan LV-MV publik; indikatif untuk
# jaringan industri/islanded): THD-U 8 %, H5 6 %, H7 5 %, unbalance tegangan
# 2 %, frekuensi ±1 %. Dip < 90 %, swell > 110 %, interupsi < 10 % dari
# tegangan acuan (IEC 61000-4-30 / IEEE 1159).
LIM = dict(thd=8.0, h5=6.0, h7=5.0, uunb=2.0, f_pct=1.0, dip=0.90, swell=1.10,
           intr=0.10)


def _unit_of(col: str) -> str:
    if col in _UNIT:
        return _UNIT[col]
    if col.startswith('Freq'):
        return 'Hz'
    if 'thd' in col:
        return '% of fundamental'
    if '_H' in col:
        return ('V' if col.startswith('U') else 'A') + ' (RMS) or %'
    return 'V' if col.startswith('U') else 'A'


def _norm(name) -> str:
    n = re.sub(r'\s*[\(\[][^\)\]]*[\)\]]\s*$', '',
               str(name).replace('\ufeff', '')).strip().lower()
    return re.sub(r'[\s_\-]+', '', n)


def write_template(path: str) -> str:
    """Template Excel impor PQA: sheet 'PQA Data' (kolom baku, satu contoh
    baris) + sheet 'Columns' (satuan, kelompok, analisis yang memakainya)."""
    import pandas as pd
    ex = {}
    for c in TEMPLATE_COLUMNS:
        u = _unit_of(c)
        ex[c] = ('25/05/2026' if c == 'Date' else '08:03:00' if c == 'Time'
                 else 50.0 if u == 'Hz' else 0.92 if c == 'PF_sum_AVG'
                 else 15240.0 if c == 'WP+' else 913500.0 if u.startswith('W')
                 else 2.0 if u.startswith('%') else
                 (4.2 if c.startswith('U') else 15.5) if '_H' in c else
                 230.0 if u == 'V' else 1420.0)
    used = {c: [] for c in TEMPLATE_COLUMNS}
    for _id, title, cols in ANALYSES:
        for c in cols:
            used[c].append(title)
    rows = []
    for g, cs in GROUPS:
        for c in cs:
            rows.append((c, g, _unit_of(c),
                         'All (time axis)' if c in ('Date', 'Time')
                         else '; '.join(used[c])))
    notes = pd.DataFrame({'Notes': [
        'Fill sheet "PQA Data" with one row per PQA recording interval '
        '(any interval, e.g. 1 s … 10 min). Keep the column names unchanged.',
        'Columns that are not available may be left empty or deleted: the '
        'analysis that needs them is skipped, the others still run.',
        'U = voltage per phase (L-N or L-L, consistently), I = current per '
        'phase. rms1/2 = half-cycle RMS extreme within the interval.',
        'THD in % of the fundamental. Harmonics H5/H7 as exported by the '
        'analyser: absolute RMS (V, A) or % of the fundamental — detected '
        'automatically (needs the THD and RMS average columns).',
        'P_sum_AVG / Dem_P+ in W or kW and WP+ in Wh or kWh: the unit is '
        'detected from Σ U·I, which needs the U and I RMS average columns; '
        'without them the values are read as kW / kWh.',
        'WP+ = cumulative imported active energy; Dem_P+ = active power demand.',
        'Extra columns (e.g. Status1, Status2) are ignored. The direct CSV '
        'export of the analyser can be imported as is.',
    ]})
    with pd.ExcelWriter(path, engine='openpyxl') as xw:
        pd.DataFrame([ex]).to_excel(xw, sheet_name='PQA Data', index=False)
        pd.DataFrame(rows, columns=['Column', 'Group', 'Unit', 'Used by analysis']
                     ).to_excel(xw, sheet_name='Columns', index=False)
        notes.to_excel(xw, sheet_name='Notes', index=False)
        for ws, widths in ((xw.sheets['PQA Data'], None),
                           (xw.sheets['Columns'], (18, 36, 22, 80)),
                           (xw.sheets['Notes'], (120,))):
            for i, col in enumerate(ws.columns):
                ws.column_dimensions[col[0].column_letter].width = (
                    widths[i] if widths else 15)
    return path


def _to_date(col):
    """Tanggal: ISO (yyyy-mm-dd), sel tanggal Excel, atau dd/mm/yyyy
    (format ekspor PQA: hari lebih dulu)."""
    import pandas as pd
    if pd.api.types.is_datetime64_any_dtype(col):
        return col
    s_ = col.astype(str).str.strip()
    if s_.str.match(r'^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}').mean() > 0.5:
        return pd.to_datetime(s_, errors='coerce', dayfirst=True)
    return pd.to_datetime(s_, errors='coerce')


def _f(v, d=2):
    return f'{v:,.{d}f}'


def _thin(t, ys: dict, kinds: dict, nmax: int = 600):
    """Perkecil deret untuk grafik (≤ nmax titik): 'min' -> minimum kotak,
    'max' -> maksimum kotak, lainnya rata-rata."""
    n = len(t)
    if n <= nmax:
        return ([round(float(x), 4) for x in t],
                {k: [None if not np.isfinite(x) else round(float(x), 4)
                     for x in y] for k, y in ys.items()})
    edges = np.linspace(0, n, nmax + 1).astype(int)
    tt = [round(float(np.mean(t[a:b])), 4) for a, b in zip(edges[:-1], edges[1:])]
    out = {}
    for k, y in ys.items():
        fn = {'min': np.nanmin, 'max': np.nanmax}.get(kinds.get(k), np.nanmean)
        v = []
        for a, b in zip(edges[:-1], edges[1:]):
            seg = y[a:b]
            v.append(round(float(fn(seg)), 4) if np.isfinite(seg).any() else None)
        out[k] = v
    return tt, out


def _read_template(df, colmap: dict, path: str) -> dict:
    import warnings
    import pandas as pd
    warnings.simplefilter('ignore', RuntimeWarning)
    n = len(df)

    def col(c):
        if c not in colmap:
            return None
        a = pd.to_numeric(df[colmap[c]], errors='coerce').to_numpy(float)
        return a if np.isfinite(a).any() else None
    have = {c: col(c) for c in TEMPLATE_COLUMNS if c not in ('Date', 'Time')}
    have = {c: a for c, a in have.items() if a is not None}
    out = dict(source=os.path.basename(path), format='template', n=int(n),
               columns_found=[c for c in TEMPLATE_COLUMNS
                              if c in have or c in colmap and c in ('Date', 'Time')],
               columns_missing=[c for c in TEMPLATE_COLUMNS
                                if c not in have and not (
                                    c in ('Date', 'Time') and c in colmap)])
    # ---- sumbu waktu ----
    ts = None
    try:
        if 'Date' in colmap and 'Time' in colmap:
            d = _to_date(df[colmap['Date']]).dt.normalize()
            tr_ = df[colmap['Time']]
            td = pd.to_timedelta(tr_.astype(str).str.strip(), errors='coerce')
            if td.isna().mean() > 0.5:
                t2 = pd.to_datetime(tr_.astype(str), errors='coerce')
                td = t2 - t2.dt.normalize()
            ts = d + td
        elif 'Date' in colmap or 'Time' in colmap:
            ts = _to_date(df[colmap.get('Date', colmap.get('Time'))])
    except Exception:
        ts = None
    dt_s = None
    if ts is not None and ts.notna().sum() > 2:
        dd = ts.diff().dt.total_seconds().to_numpy(float)
        dd = dd[np.isfinite(dd) & (dd > 0)]
        if dd.size:
            dt_s = float(np.median(dd))
            out['t_start'] = str(ts.dropna().iloc[0])
            out['t_end'] = str(ts.dropna().iloc[-1])
    out['dt_s'] = dt_s
    if dt_s:
        th = (ts - ts.dropna().iloc[0]).dt.total_seconds().to_numpy(float) / 3600.0
        bad = ~np.isfinite(th)
        if bad.any():
            th = np.where(bad, np.arange(n) * dt_s / 3600.0, th)
    else:
        th = np.arange(n, dtype=float)       # tanpa waktu: indeks sampel
    out['t_unit'] = 'h' if dt_s else 'sample'

    def when(i):
        if ts is not None and 0 <= i < n and pd.notna(ts.iloc[i]):
            return str(ts.iloc[i])
        return f'sample {i + 1}'

    def stats(a):
        a = a[np.isfinite(a)]
        return (float(a.mean()), float(np.percentile(a, 95)), float(a.max()),
                float(a.min()))
    analysis, series = [], {}

    def add(aid, rows, notes=()):
        title, need = next((t, c) for i_, t, c in ANALYSES if i_ == aid)
        miss = [c for c in need if c not in have]
        analysis.append(dict(
            id=aid, title=title,
            status=('skipped' if not rows else 'partial' if miss else 'done'),
            missing=miss, rows=[list(r) for r in rows], notes=list(notes)))

    # ================= 1. Half-cycle transient & sag/swell =================
    rows, notes = [], []
    uref = {}
    for i in (1, 2, 3):
        a = have.get(f'U{i}_rms_AVG')
        if a is None:
            lo, hi = have.get(f'U{i}_rms1/2_MIN'), have.get(f'U{i}_rms1/2_MAX')
            a = (lo + hi) / 2.0 if lo is not None and hi is not None else (
                lo if lo is not None else hi)
        if a is not None:
            v = a[np.isfinite(a) & (a > 0)]
            if v.size:
                uref[i] = float(np.median(v))
    # Interval BERTEGANGAN NORMAL (`live`): semua fasa ≥ 85 % acuan. Interval
    # padam / transisi dikeluarkan dari statistik frekuensi, unbalance,
    # harmonisa dan faktor daya (rasio terhadap ~0 tidak bermakna).
    live = np.ones(n, bool)
    dead = np.zeros(n, bool)
    _ua = [(i, have.get(f'U{i}_rms_AVG')) for i in (1, 2, 3)]
    _ua = [(i, a) for i, a in _ua if a is not None and i in uref]
    if _ua:
        lo_ = np.nanmin(np.vstack([a / uref[i] for i, a in _ua]), axis=0)
        hi_ = np.nanmax(np.vstack([a / uref[i] for i, a in _ua]), axis=0)
        live = np.isfinite(lo_) & (lo_ >= 0.85)
        dead = np.isfinite(hi_) & (hi_ < LIM['intr'])
    elif have.get('Freq_AVG') is not None:
        live = np.nan_to_num(have['Freq_AVG']) > 40.0
    n_off = int((~live).sum())
    out['n_not_energised'] = n_off
    off_note = (f'{n_off:,} of {n:,} intervals were de-energised or in '
                'transition (a phase below 85 % of the reference voltage) and '
                'are excluded from these statistics.') if n_off else None

    def runs(mask):
        """Kelompok interval berurutan -> [(awal, akhir)] (inklusif)."""
        idx = np.flatnonzero(mask)
        if not idx.size:
            return []
        cut = np.flatnonzero(np.diff(idx) > 1)
        a_ = np.r_[idx[0], idx[cut + 1]]
        b_ = np.r_[idx[cut], idx[-1]]
        return list(zip(a_.tolist(), b_.tolist()))

    def dur(a_, b_):
        k = b_ - a_ + 1
        return (f'{k} interval' + ('s' if k > 1 else '')
                + (f' ≈ {k * dt_s / 60.0:,.0f} min' if dt_s else ''))
    ev = []                                   # (keparahan, teks)
    ys, kinds = {}, {}
    n_dip = n_sw = n_int = 0
    m_int = np.zeros(n, bool)                 # interupsi (fasa mana pun)
    m_dip = np.zeros(n, bool)
    worst = np.full(n, np.inf)                # pu terendah (fasa mana pun)
    wphase = np.zeros(n, int)
    for i in (1, 2, 3):
        lo, hi = have.get(f'U{i}_rms1/2_MIN'), have.get(f'U{i}_rms1/2_MAX')
        if (lo is None and hi is None) or i not in uref:
            continue
        ur = uref[i]
        if lo is not None:
            pu = lo / ur
            k = int(np.nanargmin(pu))
            dip = np.isfinite(pu) & (pu < LIM['dip']) & (pu >= LIM['intr'])
            itr = np.isfinite(pu) & (pu < LIM['intr'])
            n_dip += int(dip.sum()); n_int += int(itr.sum())
            m_int |= itr; m_dip |= dip
            better = np.isfinite(pu) & (pu < worst)
            worst = np.where(better, pu, worst)
            wphase = np.where(better, i, wphase)
            rows.append((f'U{i} minimum half-cycle RMS', _f(np.nanmin(lo), 1),
                         'V', f'{_f(np.nanmin(pu), 3)} pu at {when(k)}',
                         'Fail' if np.nanmin(pu) < LIM['dip'] else 'Pass'))
            rows.append((f'U{i} intervals with dip (<90 %) / interruption (<10 %)',
                         f'{int(dip.sum())} / {int(itr.sum())}', 'intervals',
                         f'of {int(np.isfinite(pu).sum()):,}',
                         'Fail' if (dip.sum() + itr.sum()) else 'Pass'))
            ys[f'U{i} min (pu)'] = pu; kinds[f'U{i} min (pu)'] = 'min'
        if hi is not None:
            pu = hi / ur
            k = int(np.nanargmax(pu))
            sw = np.isfinite(pu) & (pu > LIM['swell'])
            n_sw += int(sw.sum())
            rows.append((f'U{i} maximum half-cycle RMS', _f(np.nanmax(hi), 1),
                         'V', f'{_f(np.nanmax(pu), 3)} pu at {when(k)}',
                         'Fail' if np.nanmax(pu) > LIM['swell'] else 'Pass'))
            rows.append((f'U{i} intervals with swell (>110 %)',
                         f'{int(sw.sum())}', 'intervals',
                         f'of {int(np.isfinite(pu).sum()):,}',
                         'Fail' if sw.sum() else 'Pass'))
            for a_, b_ in runs(sw):
                j = a_ + int(np.nanargmax(pu[a_:b_ + 1]))
                ev.append((pu[j] - 1, f'Swell to {_f(pu[j], 3)} pu on U{i} '
                           f'({_f(hi[j], 1)} V) — {when(j)} ({dur(a_, b_)})'))
            ys[f'U{i} max (pu)'] = pu; kinds[f'U{i} max (pu)'] = 'max'
    if m_int.any() or m_dip.any():
        # interupsi: interval berurutan (termasuk interval padam di antaranya)
        r_int = runs(m_int | dead)
        r_int = [(a_, b_) for a_, b_ in r_int if m_int[a_:b_ + 1].any()]
        tot = sum(b_ - a_ + 1 for a_, b_ in r_int)
        rows.append(('Interruption events (contiguous intervals, any phase '
                     '< 10 %)', f'{len(r_int)}', 'events',
                     (f'{tot} intervals in total'
                      + (f' ≈ {tot * dt_s / 60.0:,.0f} min' if dt_s else ''))
                     if r_int else '', 'Fail' if r_int else 'Pass'))
        for a_, b_ in sorted(r_int, key=lambda x: x[0] - 1e6 * (x[1] - x[0]))[:8]:
            ev.append((10.0 + (b_ - a_), f'Interruption — {when(a_)} to '
                       f'{when(b_)} ({dur(a_, b_)})'))
        # dip di luar interupsi & interval tepinya (transisi padam/nyala)
        near = m_int | dead
        near = near | np.r_[near[1:], False] | np.r_[False, near[:-1]]
        r_dip = runs(m_dip & ~near)
        rows.append(('Dip events outside interruptions (any phase 10–90 %)',
                     f'{len(r_dip)}', 'events', '', 'Fail' if r_dip else 'Pass'))
        for a_, b_ in r_dip:
            j = a_ + int(np.argmin(worst[a_:b_ + 1]))
            ev.append((1.0 - worst[j], f'Dip to {_f(worst[j], 3)} pu on '
                       f'U{wphase[j]} — {when(j)} ({dur(a_, b_)})'))
        out['n_interruption_events'] = len(r_int)
        out['n_dip_events'] = len(r_dip)
        if r_dip:
            out['dip_min_pu'] = float(min(np.min(worst[a_:b_ + 1])
                                          for a_, b_ in r_dip))
        out['interruption_min'] = (tot * dt_s / 60.0) if dt_s else None
    if ys:
        rows.insert(0, ('Reference voltage (median of measured RMS)',
                        ' / '.join(_f(uref[i], 1) for i in sorted(uref)), 'V',
                        'sliding reference per phase', 'Ref'))
        t_, y_ = _thin(th, ys, kinds)
        series['sag'] = dict(t=t_, y=y_, ylabel='Half-cycle voltage (pu)',
                             hlines=[LIM['dip'], LIM['swell']])
    isurge = {}
    surge_va = np.zeros(n)                    # Σ fasa U_ref·(I½max − Iavg)
    for i in (1, 2, 3):
        hi = have.get(f'I{i}_rms1/2_MAX')
        if hi is None:
            continue
        av = have.get(f'I{i}_rms_AVG')
        if av is not None and i in uref:
            d_ = np.where(live & np.isfinite(hi) & np.isfinite(av), hi - av, 0.0)
            surge_va = surge_va + uref[i] * np.maximum(d_, 0.0)
        base = None
        if av is not None:
            b_ = av[np.isfinite(av) & (av > 0)]
            base = float(np.median(b_)) if b_.size else None
        if base is None:
            b_ = hi[np.isfinite(hi) & (hi > 0)]
            base = float(np.median(b_)) if b_.size else None
        k = int(np.nanargmax(hi))
        ratio = float(np.nanmax(hi) / base) if base else float('nan')
        isurge[i] = ratio
        rows.append((f'I{i} maximum half-cycle RMS', _f(np.nanmax(hi), 1), 'A',
                     (f'{_f(ratio, 2)} × median current ({_f(base, 1)} A) at '
                      f'{when(k)}') if base else f'at {when(k)}', 'Ref'))
        lo = have.get(f'I{i}_rms1/2_MIN')
        if lo is not None:
            rows.append((f'I{i} minimum half-cycle RMS', _f(np.nanmin(lo), 1),
                         'A', f'at {when(int(np.nanargmin(lo)))}', 'Ref'))
        if av is not None and base:
            r_ = hi / np.where(av > 0.1 * base, av, np.nan)
            for j in np.argsort(-np.where(np.isfinite(r_), r_, 0))[:2]:
                if np.isfinite(r_[j]) and r_[j] > 2.0:
                    ev.append((0.05 * r_[j], f'I{i} surge to {_f(hi[j], 1)} A '
                               f'= {_f(r_[j], 1)} × interval average — '
                               f'{when(int(j))}'))
    if np.any(surge_va > 0):
        j = int(np.argmax(surge_va))
        out['surge_kva_ln'] = float(surge_va[j]) / 1000.0
        out['surge_at'] = when(j)
        rows.append(('Largest simultaneous current surge above the interval '
                     'average (Σ U·ΔI)', _f(out['surge_kva_ln'], 0), 'kVA',
                     f'at {when(j)} — equivalent starting / inrush demand '
                     '(L-N voltage basis)', 'Ref'))
    if isurge:
        rows.append(('Largest current surge factor (half-cycle max / median)',
                     _f(max(isurge.values()), 2), '×',
                     'motor starting / transformer inrush / fault indicator',
                     'Ref'))
    ev.sort(key=lambda x: -x[0])
    for sev, txt in ev[:14]:
        rows.append(('Event', txt, '', '', 'Ref'))
    if rows:
        notes.append('Half-cycle RMS extremes are per recording interval: the '
                     'count is the number of intervals containing an event; '
                     'event duration is not available from aggregated data.')
        out.update(n_dip=n_dip, n_swell=n_sw, n_interruption=n_int)
    add('sag', rows, notes)

    # ================= 2. Frequency stability & RoCoF =================
    rows, notes = [], []
    fa, fmx, fmn = (have.get('Freq_AVG'), have.get('Freq_wav_MAX'),
                    have.get('Freq_wav_MIN'))
    def fclean(a):
        if a is None:
            return None
        a = np.where(live & np.isfinite(a) & (a > 40.0), a, np.nan)
        return a if np.isfinite(a).any() else None
    fa, fmx, fmn = fclean(fa), fclean(fmx), fclean(fmn)
    fany = fa if fa is not None else (fmx if fmx is not None else fmn)
    if fany is not None:
        if off_note:
            notes.append(off_note)
        fnom = 60.0 if float(np.nanmedian(fany)) > 55.0 else 50.0
        band = fnom * LIM['f_pct'] / 100.0
        rows.append(('Nominal frequency (detected)', _f(fnom, 0), 'Hz', '', 'Ref'))
        ys, kinds = {}, {}
        if fa is not None:
            m, p95, mx, mn = stats(fa)
            ok = np.isfinite(fa)
            inb = float(np.mean(np.abs(fa[ok] - fnom) <= band) * 100.0)
            rows += [('Mean frequency', _f(m, 3), 'Hz', '', 'Ref'),
                     ('Interval-average frequency range',
                      f'{_f(mn, 3)} … {_f(mx, 3)}', 'Hz',
                      f'{_f(fnom - band, 1)} … {_f(fnom + band, 1)} Hz (±1 %)',
                      'Pass' if (mn >= fnom - band and mx <= fnom + band)
                      else 'Fail'),
                     ('Time within ±1 % of nominal', _f(inb, 2), '%',
                      '≥ 99.5 % (interconnected) / ≥ 95 % (islanded)',
                      'Pass' if inb >= 99.5 else 'Ref' if inb >= 95.0 else 'Fail'),
                     ('Standard deviation', _f(float(np.nanstd(fa)), 4), 'Hz',
                      '', 'Ref')]
            ys['f avg (Hz)'] = fa
            out['f_min'], out['f_max'] = mn, mx
            if dt_s and ok.sum() > 2:
                r = np.diff(fa) / dt_s        # NaN bila salah satu tak valid
                if np.isfinite(r).any():
                    k = int(np.nanargmax(np.abs(r)))
                    rows.append(('Maximum RoCoF between interval averages',
                                 _f(float(np.nanmax(np.abs(r))), 4), 'Hz/s',
                                 f'window {dt_s:g} s — at {when(k + 1)}', 'Ref'))
                    out['rocof_avg'] = float(np.nanmax(np.abs(r)))
            else:
                notes.append('RoCoF needs the Date/Time columns.')
        else:
            notes.append('Freq_AVG not available: mean, ±1 % statistics and '
                         'RoCoF between intervals were not evaluated.')
        if fmn is not None:
            k = int(np.nanargmin(fmn))
            rows.append(('Lowest instantaneous frequency (Freq_wav_MIN)',
                         _f(float(np.nanmin(fmn)), 3), 'Hz',
                         f'{_f(float(np.nanmin(fmn)) - fnom, 3)} Hz from nominal '
                         f'at {when(k)}', 'Ref'))
            ys['f min (Hz)'] = fmn; kinds['f min (Hz)'] = 'min'
            out['f_min'] = min(out.get('f_min', 1e9), float(np.nanmin(fmn)))
        if fmx is not None:
            k = int(np.nanargmax(fmx))
            rows.append(('Highest instantaneous frequency (Freq_wav_MAX)',
                         _f(float(np.nanmax(fmx)), 3), 'Hz',
                         f'+{_f(float(np.nanmax(fmx)) - fnom, 3)} Hz from nominal '
                         f'at {when(k)}', 'Ref'))
            ys['f max (Hz)'] = fmx; kinds['f max (Hz)'] = 'max'
            out['f_max'] = max(out.get('f_max', 0.0), float(np.nanmax(fmx)))
        if fmn is not None and fmx is not None:
            ex = fmx - fmn
            k = int(np.nanargmax(ex))
            rows.append(('Largest excursion within one interval (MAX − MIN)',
                         _f(float(np.nanmax(ex)), 3), 'Hz', f'at {when(k)}',
                         'Ref'))
            if dt_s:
                rows.append(('Lower bound of RoCoF within that interval',
                             _f(float(np.nanmax(ex)) / dt_s, 4), 'Hz/s',
                             'excursion ÷ interval length (true RoCoF is higher)',
                             'Ref'))
        notes.append('RoCoF from aggregated data is an average over the '
                     'recording interval and understates the instantaneous '
                     'RoCoF; use it as a lower bound next to the simulated '
                     'cases.')
        t_, y_ = _thin(th, ys, kinds)
        series['freq'] = dict(t=t_, y=y_, ylabel='Frequency (Hz)',
                              hlines=[fnom - band, fnom + band])
        out['f_nom'] = fnom
    add('freq', rows, notes)

    # ================= 3. Load flow, P & Q profiling =================
    rows, notes = [], []
    p = have.get('P_sum_AVG')
    pf = have.get('PF_sum_AVG')
    ua = [have.get(f'U{i}_rms_AVG') for i in (1, 2, 3)]
    ia = [have.get(f'I{i}_rms_AVG') for i in (1, 2, 3)]
    s_est = None
    if all(a is not None for a in ua) and all(a is not None for a in ia):
        u_med = float(np.nanmedian(np.concatenate(ua)))
        # L-L (≈ √3 × L-N) tak dapat dibedakan pasti: jumlah U·I dianggap L-N;
        # bila hasilnya ≈ √3 × P/PF, tegangan adalah L-L.
        s_est = sum(u * i for u, i in zip(ua, ia)) / 1000.0        # kVA (L-N)
    if p is not None:
        scale = 1.0
        if s_est is not None:
            m = np.isfinite(p) & np.isfinite(s_est) & (s_est > 0)
            if m.sum() > 2:
                r_ = float(np.nanmedian(np.abs(p[m]) / s_est[m]))
                if r_ > 50.0:                 # P tercatat dalam W
                    scale = 1e-3
                    notes.append('P_sum_AVG was recorded in W and converted '
                                 'to kW (cross-check against Σ U·I).')
        p = p * scale
        ok = np.isfinite(p)
        pv_ = p[ok]
        out.update(p_col='P_sum_AVG', p_max=float(pv_.max()),
                   p_p95=float(np.percentile(pv_, 95)),
                   p_mean=float(pv_.mean()), p_min=float(pv_.min()))
        rows += [('Active power — maximum', _f(out['p_max'], 1), 'kW',
                  f'at {when(int(np.nanargmax(p)))}', 'Ref'),
                 ('Active power — 95th percentile', _f(out['p_p95'], 1), 'kW',
                  '', 'Ref'),
                 ('Active power — mean', _f(out['p_mean'], 1), 'kW', '', 'Ref'),
                 ('Active power — minimum', _f(out['p_min'], 1), 'kW',
                  f'at {when(int(np.nanargmin(p)))}', 'Ref'),
                 ] + ([('Active power — minimum while energised',
                        _f(float(np.nanmin(p[ok & live])), 1), 'kW',
                        f'{n_off:,} de-energised / transition intervals excluded',
                        'Ref')] if n_off and (ok & live).any() else []) + [
                 ('Load factor (mean / maximum)',
                  _f(out['p_mean'] / max(out['p_max'], 1e-9), 3), '-', '', 'Ref')]
        ys = {'P (kW)': p}
        q = None
        if pf is not None:
            a = np.abs(pf)
            a = np.where(a > 1.0, a / 100.0, a)
            a = np.clip(a, 0.01, 1.0)
            q = np.abs(p) * np.tan(np.arccos(a))
            s_ = np.abs(p) / a
            m = ok & np.isfinite(a)
            sp, sq = float(np.sum(np.abs(p[m]))), float(np.sum(q[m]))
            out['pf'] = float(min(max(sp / max(np.hypot(sp, sq), 1e-9), 0.1), 1.0))
            out['q_mean'] = float(np.nanmean(q[m]))
            out['q_max'] = float(np.nanmax(q[m]))
            rows += [('Reactive power — maximum', _f(out['q_max'], 1), 'kvar',
                      f'at {when(int(np.nanargmax(np.where(m, q, -1))))}', 'Ref'),
                     ('Reactive power — mean', _f(out['q_mean'], 1), 'kvar',
                      '', 'Ref'),
                     ('Apparent power — maximum',
                      _f(float(np.nanmax(s_[m])), 1), 'kVA',
                      f'at {when(int(np.nanargmax(np.where(m, s_, -1))))}', 'Ref'),
                     ('Power factor — energy-weighted mean', _f(out['pf'], 3),
                      '-', '', 'Ref'),
                     ]
            ml = m & live & (np.abs(p) > 0.05 * out['p_max'])
            if ml.any():
                rows.append(('Power factor — minimum (energised, load > 5 %)',
                             _f(float(np.nanmin(a[ml])), 3), '-',
                             f'at {when(int(np.nanargmin(np.where(ml, a, 9))))}',
                             'Ref'))
            ys['Q (kvar)'] = q
            notes.append('Reactive power is derived from P and PF '
                         '(Q = P·tan(acos PF)); its sign (lagging/leading) is '
                         'not known from PF_sum_AVG and is taken as lagging.')
        else:
            out['pf'] = None
            notes.append('PF_sum_AVG not available: reactive / apparent power '
                         'and power factor were not evaluated.')
        d = np.diff(p)
        # hanya antar dua interval BERTEGANGAN: turun ke 0 saat padam bukan
        # step beban
        dm = np.isfinite(d) & live[1:] & live[:-1]
        if dm.any():
            iu = int(np.nanargmax(np.where(dm, d, -np.inf)))
            idn = int(np.nanargmin(np.where(dm, d, np.inf)))
            out['step_up_kw'] = float(max(d[iu], 0.0))
            out['step_dn_kw'] = float(min(d[idn], 0.0))
            rows += [('Largest load rise between intervals',
                      '+' + _f(out['step_up_kw'], 1), 'kW',
                      f'at {when(iu + 1)}', 'Ref'),
                     ('Largest load drop between intervals',
                      _f(out['step_dn_kw'], 1), 'kW', f'at {when(idn + 1)}',
                      'Ref')]
            k = iu if abs(d[iu]) >= abs(d[idn]) else idn
            a_, b_ = max(0, k - 5), min(p.size, k + 11)
            w = p[a_:b_]
            out['window_kw'] = [float(x) for x in w[np.isfinite(w)]]
            if q is not None:
                out['window_kvar'] = [float(x) if np.isfinite(x) else 0.0
                                      for x in q[a_:b_]][:len(out['window_kw'])]
        if ts is not None and dt_s and ts.notna().sum() > 2:
            hod = ts.dt.hour.to_numpy(float)
            prof = [float(np.nanmean(p[(hod == h) & ok]))
                    if ((hod == h) & ok).any() else None for h in range(24)]
            if sum(v is not None for v in prof) >= 12:
                out['p_by_hour'] = prof
                hp = int(np.nanargmax([v if v is not None else -1e18
                                       for v in prof]))
                rows.append(('Peak hour of the average daily profile',
                             f'{hp:02d}:00', 'h',
                             f'{_f(prof[hp], 1)} kW average', 'Ref'))
        t_, y_ = _thin(th, ys, {})
        series['load'] = dict(t=t_, y=y_, ylabel='Power (kW / kvar)', hlines=[])
    else:
        notes.append('P_sum_AVG not available: load profiling skipped; the '
                     'study load cannot be taken from the PQA data.')
    wp = have.get('WP+')
    if wp is not None and p is not None:
        w_ = wp[np.isfinite(wp)]
        e = float(w_[-1] - w_[0]) if np.all(np.diff(w_) >= -1e-9) else float(w_.sum())
        if dt_s and out.get('p_mean'):
            e_p = out['p_mean'] * n * dt_s / 3600.0
            if e_p > 0 and e / e_p > 50.0:
                e /= 1000.0                    # Wh -> kWh
            rows.append(('Imported active energy (WP+)', _f(e, 1), 'kWh',
                         f'Σ P·Δt = {_f(e_p, 1)} kWh', 'Ref'))
        else:
            rows.append(('Imported active energy (WP+)', _f(e, 1), 'kWh', '',
                         'Ref'))
        out['energy_kwh'] = e
    dem = have.get('Dem_P+')
    if dem is not None and p is not None:
        dmx = float(np.nanmax(dem))
        if out.get('p_max') and dmx / max(out['p_max'], 1e-9) > 50.0:
            dmx /= 1000.0
        rows.append(('Maximum demand (Dem_P+)', _f(dmx, 1), 'kW',
                     f'at {when(int(np.nanargmax(dem)))}', 'Ref'))
        out['demand_kw'] = dmx
    if s_est is not None and p is not None and out.get('pf'):
        m = np.isfinite(s_est) & np.isfinite(p) & (s_est > 0)
        if m.sum() > 2:
            r_ = float(np.nanmedian((np.abs(p[m]) / out['pf']) / s_est[m]))
            basis = ('line-to-neutral' if 0.8 < r_ < 1.2 else
                     'line-to-line' if 0.5 < r_ <= 0.8 else None)
            if basis:
                rows.append(('Voltage basis (from Σ U·I against P/PF)', basis,
                             '', f'ratio {_f(r_, 2)}', 'Ref'))
                out['v_basis'] = basis
    for i in (1, 2, 3):
        if ia[i - 1] is not None:
            m_, p95_, mx_, _mn = stats(ia[i - 1])
            rows.append((f'I{i} average RMS — mean / P95 / max',
                         f'{_f(m_, 1)} / {_f(p95_, 1)} / {_f(mx_, 1)}', 'A', '',
                         'Ref'))
    uu = [a for a in ua if a is not None]
    if uu:
        allu = np.concatenate([a[np.isfinite(a)] for a in uu])
        if allu.size:
            out['v_min'], out['v_max'] = float(allu.min()), float(allu.max())
            rows.append(('Average RMS voltage range (all phases)',
                         f'{_f(out["v_min"], 1)} … {_f(out["v_max"], 1)}', 'V',
                         '', 'Ref'))
    add('load', rows if p is not None else [], notes)

    # ================= 4. Voltage & current unbalance =================
    rows, notes = [], []
    ys = {}

    def nema(parts):
        st_ = np.vstack(parts)
        mean = np.nanmean(st_, axis=0)
        return np.where(mean > 0, np.nanmax(np.abs(st_ - mean), axis=0)
                        / np.where(mean > 0, mean, 1.0) * 100.0, np.nan)
    for key, nm, parts, lim in (('Uunb_AVG', 'Voltage', ua, LIM['uunb']),
                                ('Iunb_AVG', 'Current', ia, None)):
        a = have.get(key)
        src = key
        if a is None and all(x is not None for x in parts):
            a = nema(parts)
            src = 'max deviation from mean of phase RMS (NEMA definition)'
            notes.append(f'{key} not available: {nm.lower()} unbalance '
                         'approximated from the three phase RMS averages '
                         '(NEMA definition, not the negative-sequence ratio).')
        if a is not None:
            a = np.where(live, a, np.nan)
        if a is None or not np.isfinite(a).any():
            continue
        m_, p95_, mx_, _mn = stats(a)
        k = int(np.nanargmax(a))
        rows.append((f'{nm} unbalance — mean / P95 / max',
                     f'{_f(m_, 2)} / {_f(p95_, 2)} / {_f(mx_, 2)}', '%',
                     (f'P95 ≤ {lim:g} % — ' if lim else 'no normative limit — ')
                     + f'max at {when(k)}',
                     ('Pass' if p95_ <= lim else 'Fail') if lim else 'Ref'))
        if lim:
            over = float(np.mean(a[np.isfinite(a)] > lim) * 100.0)
            rows.append((f'{nm} unbalance — time above {lim:g} %',
                         _f(over, 2), '%', '≤ 5 % of the time',
                         'Pass' if over <= 5.0 else 'Fail'))
        else:
            over = float(np.mean(a[np.isfinite(a)] > 10.0) * 100.0)
            rows.append((f'{nm} unbalance — time above 10 %', _f(over, 2), '%',
                         'indicative (single-phase loading)', 'Ref'))
        rows.append((f'{nm} unbalance — source', src, '', '', 'Ref'))
        ys[f'{nm} unbalance (%)'] = a
        out['uunb_p95' if nm == 'Voltage' else 'iunb_p95'] = p95_
    if rows and off_note:
        notes.append(off_note)
    if ys:
        t_, y_ = _thin(th, ys, {})
        series['unb'] = dict(t=t_, y=y_, ylabel='Unbalance (%)',
                             hlines=[LIM['uunb']])
    add('unb', rows, notes)
    if rows and not [c for c in ('Uunb_AVG', 'Iunb_AVG') if c in have]:
        analysis[-1]['status'] = 'partial'

    # ================= 5. THD & dominant harmonics =================
    rows, notes = [], []
    ys = {}
    for i in (1, 2, 3):
        a = have.get(f'U{i}_thd-f_AVG')
        if a is not None:
            a = np.where(live, a, np.nan)
        if a is None or not np.isfinite(a).any():
            continue
        m_, p95_, mx_, _mn = stats(a)
        rows.append((f'U{i} THD — mean / P95 / max',
                     f'{_f(m_, 2)} / {_f(p95_, 2)} / {_f(mx_, 2)}', '%',
                     f'P95 ≤ {LIM["thd"]:g} % — max at {when(int(np.nanargmax(a)))}',
                     'Pass' if p95_ <= LIM['thd'] else 'Fail'))
        ys[f'U{i} THD (%)'] = a
        out['thd_p95'] = max(out.get('thd_p95', 0.0), p95_)
    dom = {}
    # Satuan harmonisa: PQA umumnya mengekspor nilai RMS ABSOLUT (V / A);
    # sebagian mengekspor % fundamental. Deteksi dari tegangan: dalam %,
    # √(H5²+H7²) tak mungkin melebihi THD. Tanpa THD: nilai dianggap absolut.
    h_abs = None
    for i in (1, 2, 3):
        thd_, h5_, h7_ = (have.get(f'U{i}_thd-f_AVG'), have.get(f'U{i}_H5_AVG'),
                          have.get(f'U{i}_H7_AVG'))
        if thd_ is not None and (h5_ is not None or h7_ is not None):
            hh = np.hypot(h5_ if h5_ is not None else 0.0,
                          h7_ if h7_ is not None else 0.0)
            h_abs = bool(np.nanmedian(hh) > 1.1 * np.nanmedian(thd_))
            break
    if h_abs is None:
        h_abs = True
    any_h = any(f'{qn}{i}_H{h}_AVG' in have for qn in 'UI' for i in (1, 2, 3)
                for h in (5, 7))
    for qn in 'UI':
        for i in (1, 2, 3):
            for h, lim in ((5, LIM['h5']), (7, LIM['h7'])):
                a = have.get(f'{qn}{i}_H{h}_AVG')
                if a is None:
                    continue
                if h_abs:
                    base = have.get(f'{qn}{i}_rms_AVG')
                    if base is None:
                        m_, p95_, mx_, _mn = stats(a)
                        rows.append((f'{qn}{i} harmonic H{h} — mean / P95 / max',
                                     f'{_f(m_, 2)} / {_f(p95_, 2)} / {_f(mx_, 2)}',
                                     'V' if qn == 'U' else 'A',
                                     f'{qn}{i}_rms_AVG missing — cannot express '
                                     'in % of fundamental', 'Ref'))
                        continue
                    a = a / np.where(base > 0, base, np.nan) * 100.0
                a = np.where(live, a, np.nan)
                if not np.isfinite(a).any():
                    continue
                m_, p95_, mx_, _mn = stats(a)
                dom.setdefault(qn, {}).setdefault(h, []).append(p95_)
                if qn == 'U':
                    rows.append((f'U{i} harmonic H{h} — mean / P95 / max',
                                 f'{_f(m_, 2)} / {_f(p95_, 2)} / {_f(mx_, 2)}',
                                 '%', f'P95 ≤ {lim:g} %',
                                 'Pass' if p95_ <= lim else 'Fail'))
                else:
                    rows.append((f'I{i} harmonic H{h} — mean / P95 / max',
                                 f'{_f(m_, 2)} / {_f(p95_, 2)} / {_f(mx_, 2)}',
                                 '%', 'no limit assessed (IEEE 519 needs Isc/IL)',
                                 'Ref'))
    for qn, nm in (('U', 'voltage'), ('I', 'current')):
        d_ = dom.get(qn) or {}
        if d_:
            out[f'h_{qn.lower()}_p95'] = {str(h): float(max(v))
                                          for h, v in d_.items()}
            best = max(d_, key=lambda h: max(d_[h]))
            txt = f'H{best} ({_f(max(d_[best]), 2)} % P95, worst phase)'
            if len(d_) == 2:
                other = 7 if best == 5 else 5
                txt += f' vs H{other} {_f(max(d_[other]), 2)} %'
            rows.append((f'Dominant low-order {nm} harmonic', txt, '',
                         '5th & 7th = 6-pulse rectifier / VFD signature', 'Ref'))
            out[f'dom_h_{qn.lower()}'] = int(best)
    if rows and any_h:
        notes.append(
            ('H5/H7 were recorded as absolute RMS values (V, A) and are shown '
             'in % of the phase RMS average.') if h_abs else
            'H5/H7 were recorded in % of the fundamental.')
    if rows and off_note:
        notes.append(off_note)
    if rows:
        notes.append('Limits: '
                     'EN 50160 / IEC 61000-2-2 compatibility levels (THD 8 %, '
                     'H5 6 %, H7 5 %), assessed on the 95th percentile.')
    if ys:
        t_, y_ = _thin(th, ys, {})
        series['harm'] = dict(t=t_, y=y_, ylabel='Voltage THD (%)',
                              hlines=[LIM['thd']])
    add('harm', rows, notes)

    # ================= cuplikan kejadian (v170) =================
    # Jendela data MENTAH di sekitar tiap kejadian terukur, dipakai halaman
    # Transient untuk disandingkan dengan kasus simulasi yang terkait.
    def _env(prefix, suffix, fn):
        parts = []
        for i in (1, 2, 3):
            a = have.get(f'{prefix}{i}{suffix}')
            if a is not None:
                parts.append(a / uref[i] if prefix == 'U' and i in uref else a)
        if not parts:
            return None
        return fn(np.vstack(parts), axis=0)
    u_lo = _env('U', '_rms1/2_MIN', np.nanmin)
    u_hi = _env('U', '_rms1/2_MAX', np.nanmax)
    i_hi = _env('I', '_rms1/2_MAX', np.nanmax)
    i_av = _env('I', '_rms_AVG', np.nanmax)
    f_av, f_lo, f_hi = (have.get('Freq_AVG'), have.get('Freq_wav_MIN'),
                        have.get('Freq_wav_MAX'))
    p_kw = p if have.get('P_sum_AVG') is not None else None
    events = {}

    def excerpt(key, label, k, pre=15, post=30):
        if k is None or not (0 <= k < n):
            return
        a_, b_ = max(0, k - pre), min(n, k + post + 1)
        if b_ - a_ < 3:
            return
        step = dt_s if dt_s else 1.0
        tt = (np.arange(a_, b_) - k) * step
        ser = {}
        for nm, arr, valid in (
                ('P (kW)', p_kw, None), ('f avg (Hz)', f_av, 40.0),
                ('f min (Hz)', f_lo, 40.0), ('f max (Hz)', f_hi, 40.0),
                ('U min (pu)', u_lo, None), ('U max (pu)', u_hi, None),
                ('I half-cycle max (A)', i_hi, None), ('I avg (A)', i_av, None)):
            if arr is None:
                continue
            seg = np.asarray(arr[a_:b_], float)
            if valid is not None:                 # frekuensi 0 = bus padam
                seg = np.where(seg > valid, seg, np.nan)
            if np.isfinite(seg).any():
                ser[nm] = [None if not np.isfinite(x) else round(float(x), 4)
                           for x in seg]
        if not ser:
            return
        events[key] = dict(
            label=label, at=when(k), t_from=when(a_), t_to=when(b_ - 1),
            dt_s=dt_s, t_unit='s' if dt_s else 'sample',
            t=[round(float(x), 3) for x in tt], series=ser)

    def amax(a, mask=None):
        if a is None:
            return None
        b_ = np.where(np.isfinite(a) & (mask if mask is not None else True),
                      a, -np.inf)
        return int(np.argmax(b_)) if np.isfinite(b_).any() else None

    def amin(a, mask=None):
        if a is None:
            return None
        b_ = np.where(np.isfinite(a) & (mask if mask is not None else True),
                      a, np.inf)
        return int(np.argmin(b_)) if np.isfinite(b_).any() else None
    if p_kw is not None:
        d_ = np.diff(p_kw)
        _lv = live[1:] & live[:-1]
        if (np.isfinite(d_) & _lv).any():
            excerpt('step_up', 'Largest measured load rise',
                    amax(d_, _lv) + 1 if amax(d_, _lv) is not None else None)
            excerpt('step_dn', 'Largest measured load drop',
                    amin(d_, _lv) + 1 if amin(d_, _lv) is not None else None)
        excerpt('peak', 'Maximum measured load', amax(p_kw))
    if np.any(surge_va > 0):
        excerpt('surge', 'Largest half-cycle current surge',
                int(np.argmax(surge_va)))
    _fl = f_lo if f_lo is not None else f_av
    if _fl is not None:
        excerpt('f_low', 'Lowest measured frequency (bus energised)',
                amin(_fl, live & (np.nan_to_num(_fl) > 40.0)))
    _fh = f_hi if f_hi is not None else f_av
    if _fh is not None:
        excerpt('f_high', 'Highest measured frequency', amax(_fh, live))
    if u_lo is not None:
        near_ = m_int | dead
        near_ = near_ | np.r_[near_[1:], False] | np.r_[False, near_[:-1]]
        excerpt('dip', 'Deepest voltage dip outside interruptions',
                amin(u_lo, ~near_))
        r_ = [(a_, b_) for a_, b_ in runs(m_int | dead)
              if m_int[a_:b_ + 1].any()]
        if r_:
            a_, b_ = max(r_, key=lambda x: x[1] - x[0])
            excerpt('interruption', 'Longest supply interruption — start', a_)
            excerpt('restore', 'Re-energisation after the longest interruption',
                    min(b_ + 1, n - 1))
    out['events'] = events
    if 'surge_kva_ln' in out:
        out['surge_kva'] = out['surge_kva_ln'] / (
            3 ** 0.5 if out.get('v_basis') == 'line-to-line' else 1.0)
    if uref:
        out['u_ref_v'] = float(np.mean(list(uref.values())))
    out['analysis'] = analysis
    out['series'] = series
    if not any(a['rows'] for a in analysis):
        raise PQAError('No usable PQA data columns found. Use the PQA template '
                       '(button "PQA Template…").')
    return out


def read_pqa_file(path: str) -> dict:
    """Baca berkas PQA. Format utama = kolom template (GROUPS); berkas tanpa
    satu pun kolom template dibaca dengan parser longgar lama."""
    import pandas as pd
    if path.lower().endswith(('.xlsx', '.xlsm', '.xls')):
        df = pd.read_excel(path)
    else:
        try:
            df = pd.read_csv(path, sep=None, engine='python',
                             encoding='utf-8-sig')
        except Exception:
            df = pd.read_csv(path, encoding='utf-8-sig')
    if df.empty:
        raise PQAError('PQA file is empty.')
    want = {_norm(c): c for c in TEMPLATE_COLUMNS}
    colmap = {}
    for c in df.columns:
        k = want.get(_norm(c))
        if k and k not in colmap:
            colmap[k] = c
    if any(k not in ('Date', 'Time') for k in colmap):
        return _read_template(df, colmap, path)
    return _read_generic(df, path)


def analysis_rows(pqa: dict) -> list:
    """Baris tabel datar [Analysis, Item, Value, Unit, Reference / limit,
    Result] untuk halaman & laporan (termasuk analisis yang DILEWATI)."""
    rows = []
    for a in (pqa or {}).get('analysis') or []:
        if a['status'] == 'skipped':
            rows.append([a['title'], 'Not performed — required columns missing',
                         ', '.join(a['missing']), '', '', 'Skipped'])
            continue
        for r in a['rows']:
            rows.append([a['title']] + list(r))
        if a['missing']:
            rows.append([a['title'], 'Columns not available (related items '
                         'omitted)', ', '.join(a['missing']), '', '', 'Skipped'])
        for nt in a.get('notes') or []:
            rows.append([a['title'], 'Note', nt, '', '', ''])
    return rows


def study_load(cfg: dict):
    """(beban studi kW | None, faktor daya | None) dari PQA.

    v168 — bila data PQA memuat daya aktif, beban sistem SELALU diambil dari
    PQA; 'Study Load Source' hanya memilih statistiknya (Maximum / 95th
    Percentile / Mean; pilihan 'Manual' diperlakukan sebagai Maximum)."""
    src = str(cfg.get('tr_load_source', '')).strip().lower()
    pqa = cfg.get('tr_pqa') or None
    if not isinstance(pqa, dict) or 'p_max' not in pqa:
        return None, None
    key = ('p_p95' if '95' in src else 'p_mean' if 'mean' in src else 'p_max')
    try:
        return float(pqa[key]), (float(pqa['pf']) if pqa.get('pf') else None)
    except (KeyError, TypeError, ValueError):
        return None, None
