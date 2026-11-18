"""Mode Case Analysis — klasifikasi kasus operasi per langkah waktu.

v179 — dimensi case MENGIKUTI pembangkit yang tersedia pada sistem (skema
dinamis). Dimensi biner, urut dari yang paling signifikan:
    DEG (ON/OFF) · GTG (ON/OFF) · STG (ON/OFF) · Grid (status 1/0) ·
    WTG (tersedia/tidak) · PV (tersedia/tidak)
lalu BESS (charge / can not charge / discharge / can not discharge) bila BESS
terpasang. Dimensi untuk aset yang TIDAK ada dihilangkan.

  Nomor case = 1 + Σ bit_off(dim)·bobot(dim) + idx_BESS
  bobot dim terakhir = 4 (dengan BESS) atau 1 (tanpa BESS), lalu ×2 ke kiri.

Skema bawaan (DEG, Grid, PV + BESS) identik dengan penomoran lama 32 kasus:
  case 1..16 = DEG ON ; 17..32 = DEG OFF ; (Grid 0 ? 8) ; (PV n/a ? 4) ; idx.

Modul MURNI (tanpa GUI): hanya MEMBACA deret hasil simulasi + parameter
sistem; tidak mengubah logika dispatch. Dipakai bersama Dashboard dan laporan
agar klasifikasi identik.
"""
from __future__ import annotations
import colorsys

import numpy as np

_BESS_STATES = ['charge', 'can not charge', 'discharge', 'can not discharge']
_BESS_SHORT = ['charge', 'no charge', 'dischg', 'no dischg']

# urutan signifikansi (kiri = paling signifikan); BESS selalu terakhir
DIM_ORDER = ('deg', 'gtg', 'stg', 'grid', 'wtg', 'pv')
# (teks ON, teks OFF) — deskripsi lengkap
_DIM_TEXT = {
    'deg': ('DEG ON', 'DEG OFF'),
    'gtg': ('GTG ON', 'GTG OFF'),
    'stg': ('STG ON', 'STG OFF'),
    'grid': ('Grid status 1', 'Grid status 0'),
    'wtg': ('WTG available', 'WTG not available'),
    'pv': ('PV available', 'PV not available'),
}
_DIM_SHORT = {
    'deg': ('DEG✓', 'DEG✗'), 'gtg': ('GTG✓', 'GTG✗'),
    'stg': ('STG✓', 'STG✗'), 'grid': ('G1', 'G0'),
    'wtg': ('WTG✓', 'WTG✗'), 'pv': ('PV✓', 'PV✗'),
}
DIM_NAME = {'deg': 'DEG', 'gtg': 'GTG', 'stg': 'STG', 'grid': 'Grid',
            'wtg': 'WTG', 'pv': 'PV', 'bess': 'BESS'}


class CaseScheme:
    """Skema case untuk satu konfigurasi pembangkit."""

    def __init__(self, dims=('deg', 'grid', 'pv'), bess=True):
        self.dims = tuple(d for d in DIM_ORDER if d in set(dims))
        self.bess = bool(bess)
        self.block = 4 if self.bess else 1
        self.n = (2 ** len(self.dims)) * self.block
        self._w = {}
        w = self.block
        for d in reversed(self.dims):
            self._w[d] = w
            w *= 2
        self.colors = self._make_colors()

    # -- identitas (dipakai utk cache/perbandingan) --
    def key(self):
        return (self.dims, self.bess)

    def __eq__(self, o):
        return isinstance(o, CaseScheme) and o.key() == self.key()

    def __hash__(self):
        return hash(self.key())

    @property
    def is_legacy(self):
        return self.key() == (('deg', 'grid', 'pv'), True)

    # -- komponen --
    def components(self, c: int):
        """-> (dict dim -> bool ON/tersedia, bess_idx 0..3 atau None)."""
        k = int(c) - 1
        st = {}
        for d in self.dims:
            st[d] = (k // self._w[d]) % 2 == 0
        bidx = (k % 4) if self.bess else None
        return st, bidx

    def group(self, c: int):
        """Kelompok kolom menu = status dimensi paling signifikan (None bila
        tak ada dimensi)."""
        if not self.dims:
            return None
        st, _b = self.components(c)
        return st[self.dims[0]]

    def group_label(self, on: bool, cases=None):
        d = self.dims[0]
        lab = _DIM_TEXT[d][0 if on else 1]
        half = self.n // 2
        lo, hi = (1, half) if on else (half + 1, self.n)
        return f'{lab}  ·  Case {lo}–{hi}'

    def text(self, c: int) -> str:
        st, bidx = self.components(c)
        parts = [_DIM_TEXT[d][0 if st[d] else 1] for d in self.dims_display()]
        if bidx is not None:
            parts.insert(self._bess_pos(), f'BESS {_BESS_STATES[bidx]}')
        return f'Case {c}:  ' + '  ·  '.join(parts)

    def short(self, c: int) -> str:
        """Label ringkas utk daftar filter (dimensi kolom tidak diulang)."""
        st, bidx = self.components(c)
        ds = [d for d in self.dims_display() if not (self.dims and d == self.dims[0])]
        parts = [_DIM_SHORT[d][0 if st[d] else 1] for d in ds]
        s = ' '.join(parts)
        if bidx is not None:
            s = (s + ' · ' if s else '') + _BESS_SHORT[bidx]
        return f'C{c}  ·  {s}' if s else f'C{c}'

    def dims_display(self):
        """Urutan tampil (seperti tabel lama): Grid, PV, WTG, STG, GTG, DEG."""
        order = ('grid', 'pv', 'wtg', 'stg', 'gtg', 'deg')
        return [d for d in order if d in self.dims]

    def _bess_pos(self):
        """BESS ditulis setelah sumber terbarukan (seperti format lama)."""
        disp = self.dims_display()
        pos = 0
        for i, d in enumerate(disp):
            if d in ('grid', 'pv', 'wtg'):
                pos = i + 1
        return pos

    def describe(self) -> str:
        """Ringkasan dimensi, mis. 'Grid (1/0) × PV × BESS (4 states) × DEG'."""
        parts = []
        for d in self.dims_display():
            parts.append(DIM_NAME[d])
        if self.bess:
            parts.insert(self._bess_pos(), 'BESS')
        return ' × '.join(parts)

    def _make_colors(self):
        """Warna berbeda (hue golden-angle); kelompok paling signifikan OFF
        sedikit lebih redup sebagai isyarat visual (sama dgn skema lama)."""
        cols = {}
        for c in range(1, self.n + 1):
            h = ((c - 1) * 0.6180339887) % 1.0
            on = self.group(c)
            on = True if on is None else on
            s = 0.72 if on else 0.50
            val = 0.96 if on else 0.78
            r, g, b = colorsys.hsv_to_rgb(h, s, val)
            cols[c] = (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))
        return cols

    def hex(self, c: int) -> str:
        r, g, b = self.colors[int(c)]
        return f'#{r:02X}{g:02X}{b:02X}'


LEGACY = CaseScheme()
CASE_COLORS = LEGACY.colors


def _num(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def scheme_from(params=None, cfg=None, series=None) -> CaseScheme:
    """Skema case dari pembangkit yang tersedia. Urutan sumber info:
    SystemParams (hasil simulasi) → cfg GUI → keberadaan deret."""
    cfg = cfg or {}
    dims = []
    p = params

    def pget(name, cfg_key=None, default=None):
        if p is not None and hasattr(p, name):
            return getattr(p, name)
        if cfg_key is not None and cfg_key in cfg:
            return cfg.get(cfg_key)
        return default

    # Grid
    if bool(pget('grid_enabled', 'grid_enabled', True)):
        dims.append('grid')
    # PV
    if _num(pget('pv_kwp', 'pv_kwp', 1.0)) > 0:
        dims.append('pv')
    # DEG
    if p is not None and hasattr(p, 'deg_kw'):
        deg_on = sum(_num(x) for x in np.asarray(p.deg_kw, float).reshape(-1)) > 0
    elif cfg:
        try:
            n = int(str(cfg.get('deg_count', '1')))
        except Exception:
            n = 1
        deg_on = any(_num(cfg.get(f'deg{i + 1}_kw', 0)) > 0 for i in range(min(n, 3)))
    else:
        deg_on = True
    if deg_on:
        dims.append('deg')
    # WTG / STG / GTG
    ext = getattr(p, 'ext', None) if p is not None else None
    for k in ('wtg', 'stg', 'gtg'):
        on = None
        if isinstance(ext, dict):          # SystemParams.ext (ext_vals)
            on = _num(np.max(np.asarray(ext.get(k + '_on', 0.0), float))) > 0.5
        elif cfg:
            if k == 'wtg':
                on = bool(cfg.get('wtg_enabled', False)) and \
                    _num(cfg.get('wtg_count', 0)) * _num(cfg.get('wtg_unit_kw', 0)) > 0
            else:
                on = bool(cfg.get(k + '_enabled', False)) and _num(cfg.get(k + '_kw', 0)) > 0
        if on is None:
            on = series is not None and k in series
        if on:
            dims.append(k)
    bess = _num(pget('bess_kwh', 'bess_kwh', 1.0)) > 0
    return CaseScheme(dims, bess)


def _sch(scheme):
    return LEGACY if scheme is None else scheme


def case_hex(c: int, scheme=None) -> str:
    return _sch(scheme).hex(c)


def case_components(c: int):
    """Skema lama: (grid_status:int, pv_avail:bool, bess_idx 0..3, deg_on)."""
    st, bidx = LEGACY.components(c)
    return (1 if st['grid'] else 0), st['pv'], bidx, st['deg']


def case_text(c: int, scheme=None) -> str:
    return _sch(scheme).text(c)


def case_short(c: int, scheme=None) -> str:
    return _sch(scheme).short(c)


def classify_cases(series: dict, soc_min: float, soc_max: float,
                   bess_kwh: float = 0.0, dt: float = 1.0,
                   rte: float = 1.0, scheme=None) -> np.ndarray:
    """Nomor case 1..N tiap langkah (0 = tanpa case). Murni dari deret
    terekam: grid_status, pv, wtg, stg, gtg, deg, chg, dhg, soc, load. Tidak
    menyentuh logika simulasi. `bess_kwh`, `dt`, `rte` dipakai untuk uji 'can
    not discharge' memakai potensi discharge yang SAMA dengan engine
    (d_pot = (Z - SOC_min·E)/dt · √η_RT).
    Dengan BESS: langkah 'idle & energi cukup' tidak masuk case (0).
    Tanpa BESS: setiap langkah mendapat case."""
    sch = _sch(scheme)
    n = int(np.asarray(series['load']).reshape(-1).shape[0])

    def col(k):
        return np.asarray(series.get(k, np.zeros(n)), float).reshape(n, -1)[:, 0]

    on = {
        'grid': col('grid_status') > 0.5,
        'pv': col('pv') > 1e-6,
        'deg': col('deg') > 1e-6,
        'wtg': col('wtg') > 1e-6,
        'stg': col('stg') > 1e-6,
        'gtg': col('gtg') > 1e-6,
    }
    base = np.zeros(n, dtype=int)
    for d in sch.dims:
        base += np.where(on[d], 0, sch._w[d])
    if not sch.bess:
        return (base + 1).astype(int)
    chg, dhg, soc, load = col('chg'), col('dhg'), col('soc'), col('load')
    tol, eps = 1e-6, 1e-4
    srte = float(np.sqrt(max(float(rte), 0.0)))
    avail = (soc - soc_min) * float(bess_kwh) * srte
    need = load * float(dt)
    b = np.zeros(n, dtype=int)
    b[soc >= soc_max - eps] = 2           # penuh -> can not charge
    if float(bess_kwh) > tol:
        b[avail < need - 1e-9] = 4        # can not discharge
    b[dhg > tol] = 3                      # discharge
    b[chg > tol] = 1                      # charge
    return np.where(b > 0, base + b, 0).astype(int)


def case_summary(series, soc_min, soc_max, bess_kwh=0.0, dt=1.0, rte=1.0,
                 scheme=None):
    """Ringkasan durasi tiap case.

    Kembalikan (rows, marked_h, total_h):
      rows      : [(case_num, hours), ...] untuk case yang muncul (jam>0),
                  terurut jam menurun;
      marked_h  : total jam yang tergolong salah satu case;
      total_h   : total jam simulasi.
    """
    sch = _sch(scheme)
    cases = classify_cases(series, soc_min, soc_max, bess_kwh, dt, rte, sch)
    total_h = float(len(cases) * float(dt))
    rows = []
    for c in range(1, sch.n + 1):
        cnt = int(np.count_nonzero(cases == c))
        if cnt:
            rows.append((c, cnt * float(dt)))
    rows.sort(key=lambda t: t[1], reverse=True)
    marked_h = float(sum(h for _c, h in rows))
    return rows, marked_h, total_h
