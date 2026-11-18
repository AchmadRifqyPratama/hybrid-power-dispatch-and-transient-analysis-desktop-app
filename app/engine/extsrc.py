"""Sumber tambahan dispatch: Wind Turbine Generator (WTG) & Steam Turbine
Generator (STG) — pra-dispatch & kanal data pendamping.

PRINSIP INTEGRASI (tanpa menyentuh rantai keputusan engine lama):

* Bus AC pembangkit must-take ("RE bus"): PV (setelah inverter) + WTG +
  surplus STG. Engine lama melihatnya sebagai SATU sumber must-take (kanal
  "PV"), sehingga SELURUH logika yang sudah teraudit — load priority,
  interlock, charging, Smoothing/Firming, Backup — otomatis berlaku untuk
  PV+WTG tanpa percabangan baru. Hasilnya dipecah kembali per sumber
  (PV / WTG / STG) di akhir tiap langkah (lihat dispatch.py, blok _ext_on).
* STG = unit termal MUST-RUN: saat tersedia ia memikul beban dalam pita
  [Pmin, Pmax]; beban yang diteruskan ke engine = beban − porsi STG.
    - Prioritas 0 (STG first)  : STG mengisi beban lebih dulu (baseload),
      PV/WTG menutup sisanya.
    - Prioritas 1 (RE first)   : PV/WTG dulu; STG mengikuti beban sisa, tetapi
      TAK PERNAH turun di bawah Pmin (PV/WTG yang tergeser -> charge/curtail).
  Batas laju naik (kW/menit) membatasi kenaikan antar-langkah; unit yang
  baru sinkron selalu boleh mencapai Pmin.
* Charging BESS dari STG (stg_charge):
    0 = tidak; 1 = hanya surplus minimum-loading (beban < Pmin -> STG ditahan
    di Pmin & selisihnya mengisi BESS); 2 = juga kapasitas cadangan
    (Pmax − output) — pola "charge dari STG saat proses, suplai saat pabrik
    berhenti".

Kanal data pendamping: profil Wind & STG Status menumpang pada argumen
`deg_status` sebagai array 2-D (n, 3) = [DEG status, wind, STG status]
(NaN = kanal tak diimpor). Array 1-D lama tetap berarti DEG status saja.
"""
from __future__ import annotations
import numpy as np

from . import wtg as _wtg

N_AUX = 4          # [DEG status, wind, STG status, GTG status]


def pack_aux(n: int, deg=None, wind=None, stg=None, gtg=None):
    """Gabungkan kanal pendamping. Tanpa wind/stg/gtg -> kembalikan `deg` apa
    adanya (1-D atau None) agar jalur lama byte-identik."""
    def _ok(a):
        return a is not None and np.size(a) == n
    if not _ok(wind) and not _ok(stg) and not _ok(gtg):
        return deg if _ok(deg) else None
    out = np.full((int(n), N_AUX), np.nan)
    for j, a in enumerate((deg, wind, stg, gtg)):
        if _ok(a):
            out[:, j] = np.asarray(a, float).reshape(-1)
    return out


def unpack_aux(a):
    """-> (deg_status, wind, stg_status, gtg_status) — None bila tak ada."""
    if a is None:
        return None, None, None, None
    a = np.asarray(a, float)
    if a.ndim != 2:
        return a, None, None, None
    def _col(i):
        if a.shape[1] <= i:
            return None
        c = a[:, i]
        return None if np.all(np.isnan(c)) else c
    return _col(0), _col(1), _col(2), _col(3)


def _sv(vals: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(np.max(np.asarray(vals.get(key, default), float)))
    except Exception:
        return float(default)


THERMAL = ('stg', 'gtg')      # urutan pra-dispatch: STG lalu GTG


def ext_active(vals: dict) -> bool:
    return (_sv(vals, 'wtg_on') > 0.5 and _sv(vals, 'wtg_n') * _sv(vals, 'wtg_unit_kw') > 0) \
        or any(_sv(vals, k + '_on') > 0.5 and _sv(vals, k + '_kw') > 0
               for k in THERMAL)


def wtg_series(vals: dict, wind, T: int):
    """Daya WTG bersih (T,) [kW]; nol bila WTG mati / profil angin tak ada."""
    if wind is None or not (_sv(vals, 'wtg_on') > 0.5):
        return np.zeros(int(T))
    return _wtg.wtg_power_kw(
        wind, _sv(vals, 'wtg_n'), _sv(vals, 'wtg_unit_kw'),
        mode=int(round(_sv(vals, 'wtg_mode'))),
        base_kw=_sv(vals, 'wtg_base_kw', 1.0) or 1.0,
        h_hub=_sv(vals, 'wtg_hub_h', 80.0), h_meas=_sv(vals, 'wtg_meas_h', 10.0),
        shear=_sv(vals, 'wtg_shear', 0.2), v_ci=_sv(vals, 'wtg_vci', 3.0),
        v_r=_sv(vals, 'wtg_vr', 12.0), v_co=_sv(vals, 'wtg_vco', 25.0),
        rho=_sv(vals, 'wtg_rho', _wtg.RHO0) or _wtg.RHO0,
        loss=_sv(vals, 'wtg_loss', 0.0), curve_k=_sv(vals, 'wtg_curve_k', 3.0) or 3.0)


def prepare(vals: dict, load, pv_norm, wind, status, pinv, pv_scale, dt):
    """Pra-dispatch WTG & unit termal (STG, GTG). None bila semua tak aktif.

    status : dict {'stg': (T,)|None, 'gtg': (T,)|None} ketersediaan per langkah.

    Unit termal diproses BERURUTAN (STG lalu GTG); tiap unit melihat beban
    SISA dari unit sebelumnya. Per unit (kunci k = 'stg' / 'gtg'):
      k_priority 0 = unit dulu (baseload), 1 = PV/WTG dulu (unit mengikuti)
      k_commit   0 = must-run saat tersedia, 1 = on-demand (hanya menyala bila
                 beban sisanya ≥ minimum stabil; di bawah itu unit mati &
                 beban diteruskan ke BESS/Grid/DEG)
      k_charge   0 tidak, 1 surplus minimum-loading, 2 kapasitas cadangan

    Hasil (semua (T,) atau (T,N), kW):
      wt        daya WTG bersih
      units     list dict(key, sl, smin, ssp, pmin, re_first, re_flag, hr)
      bx        = wt + Σ(smin + ssp)   (tambahan pada RE bus)
      load_eff  = beban − Σ sl         (beban yang diteruskan ke engine)
    """
    if not ext_active(vals):
        return None
    load = np.asarray(load, float)
    T = load.shape[0]
    sc = np.asarray(pv_scale, float)
    pi = np.asarray(pinv, float)
    nd = max(sc.ndim, pi.ndim)
    col = (lambda a: np.asarray(a, float).reshape((-1,) + (1,) * nd))
    dt_h = float(np.max(np.asarray(dt, float)))

    wt = col(wtg_series(vals, wind, T))                       # (T,1..)
    pvac = np.minimum(col(pv_norm) * sc, pi)                  # (T,*S)
    re_av = pvac + wt
    zero = np.zeros_like(re_av)
    if nd == 0:
        rs = (lambda a: np.asarray(a, float).reshape(-1))
    else:
        rs = (lambda a: np.broadcast_to(a, re_av.shape))
    hod = (np.arange(T) * dt_h) % 24.0
    L_rem = col(load) + zero
    units = []
    # v165 — urutan pra-dispatch: unit 'baseload' lebih dulu, lalu unit
    # 'PV/WTG dulu'; di dalam tiap sisi menurut thermal_gtg_first (bawaan STG
    # lalu GTG). Dengan begitu unit baseload tak pernah melihat beban yang
    # sudah dikurangi unit pengikut — konsisten dengan urutan yang ditampilkan.
    _order = list(THERMAL)
    if _sv(vals, 'thermal_gtg_first') > 0.5:
        _order.reverse()
    _order.sort(key=lambda _k: int(round(_sv(vals, _k + '_priority'))) == 1)
    for k in _order:
        if not (_sv(vals, k + '_on') > 0.5 and _sv(vals, k + '_kw') > 0):
            continue
        kw = _sv(vals, k + '_kw')
        lmin = min(max(_sv(vals, k + '_min_loading'), 0.0), 1.0)
        lmax = max(lmin, _sv(vals, k + '_max_loading', 1.0) or 1.0)
        re_first = int(round(_sv(vals, k + '_priority'))) == 1
        on_demand = int(round(_sv(vals, k + '_commit'))) == 1
        chg = int(round(_sv(vals, k + '_charge')))
        ramp = _sv(vals, k + '_ramp_kwmin') * 60.0 * dt_h        # kW/langkah
        t0, t1 = _sv(vals, k + '_sched_start'), _sv(vals, k + '_sched_end')
        if abs(t0 - t1) < 1e-9:
            av = np.ones(T, bool)
        elif t0 < t1:
            av = (hod >= t0) & (hod < t1)
        else:
            av = (hod >= t0) | (hod < t1)
        st = (status or {}).get(k)
        if st is not None:
            av = av & (np.nan_to_num(np.asarray(st, float), nan=1.0) != 0.0)
        pmax = col(kw * lmax * av) + zero
        pmin_c = col(kw * lmin * av) + zero
        want = L_rem - (re_av if re_first else 0.0)
        if on_demand:
            # komitmen: menyala hanya bila porsi yang diminta ≥ minimum stabil
            run = want >= np.maximum(pmin_c, 1e-9)
            pmax = np.where(run, pmax, 0.0)
            pmin_c = np.where(run, pmin_c, 0.0)
        sl = np.minimum(L_rem, np.clip(want, pmin_c, pmax))
        cap = pmax
        if ramp > 0:
            sl = sl.copy(); cap = cap.copy()
            prev = np.zeros_like(sl[0])
            for t in range(T):
                c = np.minimum(pmax[t], np.maximum(pmin_c[t], prev + ramp))
                cap[t] = c
                sl[t] = np.minimum(sl[t], c)
                prev = np.maximum(sl[t], np.minimum(pmin_c[t], c))
        smin = np.maximum(0.0, pmin_c - sl) if chg >= 1 else zero
        ssp = (np.maximum(0.0, cap - sl - smin) if chg >= 2 else zero)
        units.append(dict(key=k, sl=rs(sl), smin=rs(smin), ssp=rs(ssp),
                          pmin=rs(pmin_c), re_first=bool(re_first),
                          re_flag=_sv(vals, k + '_renewable',
                                      1.0 if k == 'stg' else 0.0) > 0.5,
                          hr=_sv(vals, k + '_heat_rate', 0.0)))
        L_rem = L_rem - sl
    out = dict(wt=rs(wt + zero), units=units,
               # kebijakan pakai/curtail PV vs WTG: 0 pro-rata, 1 PV dulu,
               # 2 WTG dulu (yang 'dulu' dipakai lebih dulu, lainnya di-curtail)
               wtg_prio=int(round(_sv(vals, 'wtg_priority'))))
    # v165 — urutan sumber bus untuk charging BESS: list kelompok berisi
    # 'pv' / 'wtg' / indeks unit termal. Peringkat dari vals['chg_rank_*']
    # bila diatur; bawaan = cadangan unit baseload, PV/WTG (menurut
    # wtg_priority), cadangan unit pengikut.
    _wp = out['wtg_prio']
    _rk = {'pv': 1.0 if _wp != 2 else 1.5, 'wtg': 1.0 if _wp != 1 else 1.5}
    for _i, _u in enumerate(units):
        _rk[_i] = (2.0 if _u['re_first'] else 0.0) + 0.01 * _i
    if any(('chg_rank_' + _s) in vals for _s in ('pv', 'wtg', 'stg', 'gtg')):
        _rk = {'pv': _sv(vals, 'chg_rank_pv', 90.0),
               'wtg': _sv(vals, 'chg_rank_wtg', 90.0)}
        for _i, _u in enumerate(units):
            _rk[_i] = _sv(vals, 'chg_rank_' + _u['key'], 95.0) + 0.001 * (_i + 1)
    _cg = []
    for _s in sorted(_rk, key=lambda _x: (_rk[_x], str(_x))):
        if _cg and abs(_rk[_cg[-1][0]] - _rk[_s]) < 1e-9:
            _cg[-1].append(_s)
        else:
            _cg.append([_s])
    out['chg_groups'] = _cg
    bx = out['wt']
    for u in units:
        bx = bx + u['smin'] + u['ssp']
    out['bx'] = bx
    out['load_eff'] = rs(L_rem)
    return out
