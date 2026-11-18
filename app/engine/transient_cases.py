"""Transient Study — penyusun kasus & eksekutor di atas engine/transient.py.

Dari konfigurasi proyek (halaman Parameters + grup "Transient — …") modul ini
menyusun sistem satu-bus, menentukan titik operasi, lalu menjalankan paket
kasus standar setara studi sistem tenaga tahap desain:

    A  Loss of generation   : trip STG / DEG terbesar / Utility Grid (islanding)
    B  Loss of the BESS     : PCS trip, tanpa & dengan load shedding (UFLS)
    C  Renewable variability: awan (PV), kehilangan WTG, gust
    D  Steam shortfall      : penurunan kemampuan STG (boiler pressure drop)
    E  Load step & damping  : ±20 % beban, mode osilasi & rasio redaman
    F  Motor starting       : DOL terbesar — semua sumber / BESS saja / tanpa BESS
    G  Synchronisation      : penutupan STG / DEG / Utility Grid ke bus BESS
    H  Feeder fault         : tiga-fasa, waktu pemutusan utama & cadangan
    I  Black start          : energisasi & block-load pick-up oleh BESS
    J  Short circuit & protection (IEC 60909 + arus-terbatas konverter)

Hasil berupa dict serialisasi-ramah (angka, string, ndarray) agar dapat
disimpan ke berkas proyek & diekspor. Teks hasil teknis ditulis dalam bahasa
Inggris (bahasa laporan engineering), judul UI mengikuti i18n aplikasi.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from . import transient as T


# ---------------------------------------------------------------- helper cfg
def _f(cfg, k, d=0.0):
    try:
        return float(cfg.get(k, d))
    except (TypeError, ValueError):
        return float(d)


def _n_deg(cfg):
    try:
        return int(str(cfg.get('deg_count', '1')))
    except Exception:
        return 1


SRC_LABEL = {'stg': 'STG', 'grid': 'Utility Grid', 'gtg': 'GTG', 'wtg': 'WTG',
             'deg': 'DEG', 'pv': 'PV', 'bess': 'BESS'}
EXISTING_CHOICES = ('stg', 'grid', 'gtg', 'wtg', 'deg')
NEW_CHOICES = ('pv', 'bess', 'stg', 'gtg', 'wtg')


def components(cfg: dict, load_peak_kw: float | None = None,
               include=None) -> dict:
    """Bangun komponen sistem dari cfg. -> dict(stg, degs, pcs, pv, wtg, grid,
    load_kw, motor_kw, f_nom, v_kv). `include` = himpunan kunci sumber
    ('stg','grid','gtg','wtg','deg','pv','bess') yang diikutkan (None = semua
    yang dikonfigurasi di halaman Parameters)."""
    f_nom = float(str(cfg.get('tr_f_nom', '50')))
    out = dict(f_nom=f_nom, v_kv=_f(cfg, 'tr_bus_kv', 0.4))
    stg = None
    if cfg.get('stg_enabled') and _f(cfg, 'stg_kw') > 0:
        kw = _f(cfg, 'stg_kw')
        pf = _f(cfg, 'tr_stg_pf', 0.85)
        stg = T.Machine('STG', 'STG', s_kva=kw / pf, h=_f(cfg, 'tr_stg_h', 1.5),
                        xd1=_f(cfg, 'tr_stg_xd1', 0.22), xd2=_f(cfg, 'tr_stg_xd2', 0.13),
                        xd=_f(cfg, 'tr_stg_xd', 1.9), td0=_f(cfg, 'tr_stg_td0', 3.0),
                        droop=_f(cfg, 'tr_stg_droop', 0.04),
                        droop_t=_f(cfg, 'tr_stg_droop_t', 0.16), t_reset=5.0,
                        tg=_f(cfg, 'tr_stg_tg', 0.15),
                        tt=_f(cfg, 'tr_stg_tt', 0.3),
                        pmax_kw=kw * (_f(cfg, 'stg_max_loading', 1.0) or 1.0),
                        pf_rated=pf)
    out['stg'] = stg
    gtg = None
    if cfg.get('gtg_enabled') and _f(cfg, 'gtg_kw') > 0:
        kw = _f(cfg, 'gtg_kw')
        pf = _f(cfg, 'tr_gtg_pf', 0.8)
        gtg = T.Machine('GTG', 'GTG', s_kva=kw / pf, h=_f(cfg, 'tr_gtg_h', 3.0),
                        xd1=_f(cfg, 'tr_gtg_xd1', 0.25), xd2=_f(cfg, 'tr_gtg_xd2', 0.15),
                        xd=2.0, td0=5.0, droop=_f(cfg, 'tr_gtg_droop', 0.04),
                        tg=_f(cfg, 'tr_gtg_tg', 0.4), tt=_f(cfg, 'tr_gtg_tt', 0.1),
                        pmax_kw=kw * (_f(cfg, 'gtg_max_loading', 1.0) or 1.0),
                        pf_rated=pf)
    out['gtg'] = gtg
    degs = []
    pf = _f(cfg, 'tr_deg_pf', 0.8)
    for i in range(min(_n_deg(cfg), 3)):
        kw = _f(cfg, f'deg{i + 1}_kw')
        if kw <= 0:
            continue
        degs.append(T.Machine(
            f'DEG-{i + 1}', 'DEG', s_kva=kw / pf, h=_f(cfg, 'tr_deg_h', 1.0),
            xd1=_f(cfg, 'tr_deg_xd1', 0.20), xd2=_f(cfg, 'tr_deg_xd2', 0.12),
            xd=1.8, td0=2.0, droop=_f(cfg, 'tr_deg_droop', 0.03),
            droop_t=_f(cfg, 'tr_deg_droop_t', 0.10), t_reset=1.5,
            tg=_f(cfg, 'tr_deg_tg', 0.05), tt=_f(cfg, 'tr_deg_tt', 0.2),
            pmax_kw=kw * (_f(cfg, 'deg_max_loading', 1.0) or 1.0), pf_rated=pf))
    out['degs'] = degs
    pcs = None
    if _f(cfg, 'bess_kwh') > 0:
        kva = _f(cfg, 'tr_pcs_kva')
        if kva <= 0:
            kva = _f(cfg, 'pcs_kva') if cfg.get('m_qv') else 0.0
        if kva <= 0:
            kva = max(_f(cfg, 'max_charge_kw'), _f(cfg, 'max_discharge_kw')) / 0.9
        gfm = str(cfg.get('tr_pcs_mode', 'Grid-Forming')).lower().startswith('grid-form')
        pcs = T.Pcs('BESS', s_kva=kva, mode='gfm' if gfm else 'gfl',
                    h=_f(cfg, 'tr_vsg_h', 3.0), droop=_f(cfg, 'tr_vsg_droop', 0.01),
                    xv=_f(cfg, 'tr_vsg_xv', 0.10), qv_droop=_f(cfg, 'tr_vsg_qv', 0.04),
                    ilim_st=_f(cfg, 'tr_pcs_ilim1', 1.3), t_st=_f(cfg, 'tr_pcs_t1', 10.0),
                    ilim_cont=_f(cfg, 'tr_pcs_ilim2', 1.1),
                    gfl_ref={'utility grid': 'GRID', 'stg': 'STG', 'gtg': 'GTG',
                             'deg': 'DEG'}.get(
                        str(cfg.get('tr_gfl_ref', 'Auto')).strip().lower(), 'Auto'),
                    gfl_loss=('gfm' if str(cfg.get('tr_gfl_loss', '')).lower()
                              .startswith('switch') else 'trip'),
                    gfl_detect=_f(cfg, 'tr_gfl_detect_ms', 150.0) / 1000.0)
    out['pcs'] = pcs
    ibk = dict(ilim=_f(cfg, 'tr_ibr_ilim', 1.1), k_lvrt=_f(cfg, 'tr_ibr_k', 2.0),
               recov=_f(cfg, 'tr_ibr_recov', 2.0))
    out['pv'] = (T.Ibr('PV', s_kva=_f(cfg, 'pv_inv_kw'), **ibk)
                 if _f(cfg, 'pv_kwp') > 0 and _f(cfg, 'pv_inv_kw') > 0 else None)
    wkw = _f(cfg, 'wtg_count') * _f(cfg, 'wtg_unit_kw') if cfg.get('wtg_enabled') else 0.0
    out['wtg'] = (T.Ibr('WTG', s_kva=wkw / 0.95,
                        wtg_type=3 if 'Type 3' in str(cfg.get('wtg_type', '')) else 4,
                        **ibk) if wkw > 0 else None)
    out['wtg_kw'] = wkw
    out['grid'] = (T.GridSrc(sc_mva=_f(cfg, 'tr_grid_sc_mva', 10.0),
                             xr=_f(cfg, 'tr_grid_xr', 5.0))
                   if cfg.get('grid_enabled', True) and _f(cfg, 'grid_kw') > 0 else None)
    if include is not None:
        inc = set(include)
        if 'stg' not in inc:
            out['stg'] = stg = None
        if 'gtg' not in inc:
            out['gtg'] = gtg = None
        if 'deg' not in inc:
            out['degs'] = degs = []
        if 'bess' not in inc:
            out['pcs'] = pcs = None
        if 'pv' not in inc:
            out['pv'] = None
        if 'wtg' not in inc:
            out['wtg'] = None; out['wtg_kw'] = 0.0
        if 'grid' not in inc:
            out['grid'] = None
    from ..data.pqa import study_load
    pqa_kw, pqa_pf = study_load(cfg)
    out['load_pf'] = pqa_pf if pqa_pf else _f(cfg, 'tr_load_pf', 0.9)
    out['pqa'] = cfg.get('tr_pqa') if pqa_kw else None
    load = pqa_kw if pqa_kw else _f(cfg, 'tr_load_kw')
    if load <= 0:
        load = float(load_peak_kw or 0.0)
    if load <= 0:
        cap = (_f(cfg, 'stg_kw') if stg else 0.0) + (
            _f(cfg, 'gtg_kw') if gtg else 0.0) + sum(
            m.s_kva * m.pf_rated for m in degs) + (pcs.s_kva * 0.9 if pcs else 0.0)
        load = 0.6 * cap if cap > 0 else 100.0
    out['load_kw'] = load
    mk = _f(cfg, 'tr_motor_kw')
    out['motor_basis'] = 'Largest DOL Motor (input)'
    if mk <= 0:
        # v168 — dari lonjakan arus setengah-siklus PQA: kVA rotor-terkunci
        # setara = lonjakan terukur; kW motor ≈ kVA / LRC × (η·cos φ ≈ 0,8)
        sk = float((cfg.get('tr_pqa') or {}).get('surge_kva') or 0.0) \
            if isinstance(cfg.get('tr_pqa'), dict) else 0.0
        lrc = max(_f(cfg, 'tr_motor_lrc', 6.5), 1.0)
        if sk > 0 and sk / lrc * 0.8 >= 5.0:
            mk = sk / lrc * 0.8
            out['motor_basis'] = ('PQA half-cycle current surge '
                                  f'({sk:,.0f} kVA ÷ LRC {lrc:g} × 0.8)')
        else:
            mk = max(5.0, 0.15 * load)
            out['motor_basis'] = '15 % of the study load (default)'
    out['motor_kw'] = mk
    return out


def configured_sources(cfg: dict) -> set:
    """Kunci sumber yang benar-benar terkonfigurasi (punya ukuran) di
    halaman Parameters."""
    c = components(cfg)
    return {k for k, ok in (('stg', c['stg'] is not None),
                            ('gtg', c.get('gtg') is not None),
                            ('deg', bool(c['degs'])), ('bess', c['pcs'] is not None),
                            ('pv', c['pv'] is not None), ('wtg', c['wtg'] is not None),
                            ('grid', c['grid'] is not None)) if ok}


def system_scenarios(cfg: dict) -> list:
    """Sistem yang dianalisis menurut pilihan pengguna -> [(key, name,
    include)]: Existing, New, Existing + New. Kosong bila pengguna tidak
    memilih apa pun (studi tunggal seluruh sumber terkonfigurasi)."""
    ex = [k for k in (cfg.get('tr_existing') or []) if k in EXISTING_CHOICES]
    nw = [k for k in (cfg.get('tr_new') or []) if k in NEW_CHOICES
          and k not in ex]
    out = []
    if ex:
        out.append(('existing', 'Existing', set(ex)))
    if nw:
        out.append(('new', 'New', set(nw)))
    if ex and nw:
        out.append(('both', 'Existing + New', set(ex) | set(nw)))
    return out


def _former_reason(comp) -> str | None:
    """None bila sistem punya sumber pembentuk tegangan; selain itu alasan."""
    if comp['stg'] is not None or comp.get('gtg') is not None or comp['degs'] \
            or comp['grid'] is not None:
        return None
    if comp['pcs'] is not None and comp['pcs'].mode == 'gfm':
        return None
    if comp['pcs'] is None and comp['pv'] is None and comp['wtg'] is None:
        return ('None of the selected sources is configured on the Parameters '
                'page (no rating).')
    return ('No grid-forming source: PV / WTG and a grid-following BESS cannot '
            'energise the bus on their own. Add a grid-forming BESS, a '
            'generator or the Utility Grid.')


def operating_point(cfg, comp, load_kw, use=None, re_frac=0.7):
    """Titik operasi (kW per sumber) pada beban `load_kw`.

    Urutan: PV/WTG (dibatasi 80 % beban) -> STG (≥ minimum stabil) -> Utility
    Grid -> DEG (bila masih kurang) -> BESS sebagai penyeimbang. `use` =
    himpunan nama sumber yang diikutkan (default semua yang ada)."""
    have = dict(STG=comp['stg'] is not None, GTG=comp.get('gtg') is not None,
                GRID=comp['grid'] is not None,
                BESS=comp['pcs'] is not None, PV=comp['pv'] is not None,
                WTG=comp['wtg'] is not None)
    for m in comp['degs']:
        have[m.name] = True
    if use is not None:
        have = {k: (v and k in use) for k, v in have.items()}
    p = {k: 0.0 for k in have}
    pv = re_frac * comp['pv'].s_kva if have['PV'] else 0.0
    wt = re_frac * comp['wtg_kw'] if have['WTG'] else 0.0
    re_cap = 0.8 * load_kw
    if pv + wt > re_cap and pv + wt > 0:
        k = re_cap / (pv + wt)
        pv, wt = pv * k, wt * k
    rem = load_kw - pv - wt
    if have['STG']:
        m = comp['stg']
        pmin = _f(cfg, 'stg_kw') * _f(cfg, 'stg_min_loading', 0.3)
        ps = min(max(rem, min(pmin, load_kw)), 0.9 * m.pmax_kw)
        if ps > rem and pv + wt > 0:                  # STG di minimum -> RE dikurangi
            k = max(0.0, (load_kw - ps)) / (pv + wt)
            pv, wt = pv * k, wt * k
        p['STG'] = ps
        rem = load_kw - pv - wt - ps
    gcap = (_f(cfg, 'grid_kw') * (_f(cfg, 'grid_max_loading', 1.0) or 1.0)
            if have['GRID'] else 0.0)
    if have['GTG']:
        # Must-Run: selalu ikut (≥ minimum stabil). On Demand: menyala bila
        # beban sisa (setelah Utility Grid) ≥ minimum stabilnya.
        m = comp['gtg']
        pmin = _f(cfg, 'gtg_kw') * _f(cfg, 'gtg_min_loading', 0.4)
        must = str(cfg.get('gtg_commit', 'On Demand')).lower().startswith('must')
        need = rem if must else rem - gcap
        if must or need >= max(pmin, 1.0):
            pg = min(max(need, pmin), 0.9 * m.pmax_kw)
            p['GTG'] = pg
            rem -= pg
    if have['GRID'] and rem > 0:
        pg = min(rem, gcap)
        p['GRID'] = pg
        rem -= pg
    pcs_cap = 0.5 * comp['pcs'].s_kva if have['BESS'] else 0.0
    always = bool(cfg.get('deg_always')) and not have['GRID']
    for m in comp['degs']:
        if not have.get(m.name):
            continue
        if rem > pcs_cap + 1e-6 or (always and m is comp['degs'][0]) \
                or not (have['BESS'] or have['STG'] or have['GRID']
                        or p.get('GTG', 0.0) > 0):
            pd = min(max(rem, 0.3 * m.pmax_kw if always else 0.0), 0.85 * m.pmax_kw)
            p[m.name] = pd
            rem -= pd
    p['PV'], p['WTG'] = pv, wt
    if have['BESS']:
        p['BESS'] = rem
    # hanya sumber yang DIIKUTKAN yang punya kunci (kunci 'BESS' = PCS online)
    return {k: v for k, v in p.items() if have.get(k)}


def make_system(cfg, comp, load_kw, p, *, motor_start=False, subtransient=False,
                motor_frac=None) -> T.System:
    """Rakit System dari titik operasi p (sumber dgn kunci di p = online)."""
    mf = _f(cfg, 'tr_motor_frac', 0.5) if motor_frac is None else motor_frac
    mf = min(max(mf, 0.0), 0.95)
    S = T.System(f_nom=comp['f_nom'], v_kv=comp['v_kv'], s_base=1000.0,
                 load_kw=load_kw * (1.0 - mf),
                 load_pf=comp.get('load_pf', _f(cfg, 'tr_load_pf', 0.9)),
                 kpv=_f(cfg, 'tr_load_kpv', 1.0), kpf=_f(cfg, 'tr_load_kpf', 1.0),
                 use_subtransient=subtransient)
    if mf > 0 and load_kw > 0:
        S.motors.append(T.Motor('Running motors', p_kw=load_kw * mf * 0.93 / 0.85,
                                lrc=_f(cfg, 'tr_motor_lrc', 6.5),
                                h=_f(cfg, 'tr_motor_h', 1.0), load_frac=0.85))
    if motor_start:
        S.motors.append(T.Motor('DOL motor', p_kw=comp['motor_kw'],
                                lrc=_f(cfg, 'tr_motor_lrc', 6.5),
                                h=_f(cfg, 'tr_motor_h', 1.0), running=False))
    if comp['stg'] is not None and 'STG' in p and p['STG'] > 0:
        m = copy.copy(comp['stg']); m.p0_kw = p['STG']; S.machines.append(m)
    if comp.get('gtg') is not None and p.get('GTG', 0.0) > 0:
        m = copy.copy(comp['gtg']); m.p0_kw = p['GTG']; S.machines.append(m)
    for d in comp['degs']:
        if p.get(d.name, 0.0) > 0:
            m = copy.copy(d); m.p0_kw = p[d.name]; S.machines.append(m)
    if comp['pcs'] is not None and 'BESS' in p:
        pc = copy.copy(comp['pcs']); pc.p0_kw = p['BESS']; S.pcs = pc
    for key in ('pv', 'wtg'):
        b = comp[key]
        if b is not None and p.get(b.name, 0.0) > 0:
            bb = copy.copy(b); bb.p0_kw = p[b.name]; S.ibrs.append(bb)
    if comp['grid'] is not None and p.get('GRID', 0.0) > 0:
        g = copy.copy(comp['grid']); g.p0_kw = p['GRID']; S.grid = g
    return S


def _has_former(S: T.System) -> bool:
    return bool(S.machines) or S.grid is not None or (
        S.pcs is not None and S.pcs.mode == 'gfm')


def _scen(p):
    """Titik operasi sebagai teks. BESS yang online selalu disebut — juga
    saat dayanya 0 kW (siaga sebagai penyeimbang / pembentuk tegangan)."""
    out = [f'{k} {v:,.0f} kW' for k, v in p.items()
           if abs(v) > 0.5 and k != 'BESS']
    if 'BESS' in p:
        v = p['BESS']
        out.append(f'BESS {v:,.0f} kW' if abs(v) > 0.5
                   else 'BESS 0 kW (online, standby)')
    return ', '.join(out) or '—'


# ---------------------------------------------------------------- deret & vonis
_KEEP = 600


def _thin(res):
    """Deret untuk grafik/ekspor (≤ ~600 titik, puncak tetap terjaga)."""
    t = res['t']
    n = t.size
    if n == 0:
        return {}
    idx = np.arange(n) if n <= _KEEP else np.unique(
        np.linspace(0, n - 1, _KEEP).round().astype(int))
    out = {}
    for k, v in res.items():
        if isinstance(v, np.ndarray) and v.size == n and k not in ('th',):
            if not (k in ('t', 'f', 'v', 'p_load', 'i_BESS') or np.any(np.abs(v) > 1e-9)):
                continue
            out[k] = v[idx].astype(np.float32)
    return out


def _verdict(m, crit, kind='dyn', ref=False):
    """-> (status, [alasan])."""
    why = []
    if m.get('blackout'):
        why.append('blackout')
    if m.get('pcs_trip'):
        why.append('PCS trip')
    # penutupan pemutus: lonjakan frekuensi terukur = lompatan fasa (artefak
    # pengukuran), jadi pita frekuensi tak dinilai pada kasus sinkronisasi
    if kind != 'sync' and 'f_min' in m and m['f_min'] < crit['f_lo'] - 1e-9:
        why.append(f"f min {m['f_min']:.2f} Hz < {crit['f_lo']:.1f}")
    if kind != 'sync' and 'f_max' in m and m['f_max'] > crit['f_hi'] + 1e-9:
        why.append(f"f max {m['f_max']:.2f} Hz > {crit['f_hi']:.1f}")
    if kind != 'fault' and m.get('v_min', 1.0) < crit['v_lo'] - 1e-9:
        why.append(f"V min {m['v_min']:.2f} pu < {crit['v_lo']:.2f}")
    if kind == 'fault' and not (m.get('t_v_recover', 9.9) <= 1.0):
        why.append('voltage not back above 0.9 pu within 1 s')
    if kind in ('trip', 'dyn') and abs(m.get('rocof', 0.0)) > crit['rocof'] + 1e-9:
        why.append(f"RoCoF {m['rocof']:+.2f} Hz/s > {crit['rocof']:.1f}")
    if m.get('pcs_end', 0.0) > crit['ilim_cont'] + 0.005:
        why.append(f"PCS {m['pcs_end']:.2f} pu > continuous rating "
                   f"(short-time window {crit['t_st']:g} s only)")
    if m.get('ibr_trip'):
        why.append('converter trip: ' + ', '.join(m['ibr_trip']))
    if ref:
        return 'Ref', why
    return ('Pass', why) if not why else ('Fail', why)


_CRIT_BASIS = {
    'f_lo': 'IEC 60034-1 Zone B (−5 %)', 'f_hi': 'IEC 60034-1 Zone B (+3 %)',
    'v_lo': 'ISO 8528-5 G2 transient voltage / contactor hold-in',
    'rocof': 'EN 50549-1 / IEC TS 62786 RoCoF immunity',
    'ilim': 'IEC 62477-1 / IEC 62933-2-1 continuous converter rating',
    'rec': 'IEC 60364 / grid-code fault ride-through: back above 0.9 pu',
}


def case_evidence(c: dict, crit: dict) -> tuple:
    """Bukti penilaian satu kasus -> (checks, explanation).

    checks = [dict(criterion, measured, limit, status, basis)] dengan status
    'Pass' | 'Fail' | 'Not assessed' (tidak dinilai untuk jenis kasus ini) — aturan
    yang SAMA dengan _verdict(), dihitung ulang dari metrik yang tersimpan
    sehingga juga berlaku untuk hasil studi lama. explanation = satu kalimat
    yang menjelaskan mengapa hasilnya Pass / Fail / Ref / Error."""
    m = c.get('metrics') or {}
    kind = c.get('kind', 'dyn')
    st = c.get('status', '')
    out = []

    band = max(crit.get('f_hi', 52.0) - crit.get('f_lo', 47.5), 1e-6)

    def chk(name, measured, limit, ok, basis='', na=None, margin=None):
        # margin = jarak ke batas (ternormalisasi; kecil = paling kritis)
        out.append(dict(criterion=name, measured=measured, limit=limit,
                        status='Not assessed' if na else ('Pass' if ok else 'Fail'),
                        basis=na or basis, margin=None if na else margin))

    def num(k):
        v = m.get(k)
        return v if isinstance(v, (int, float)) and v == v else None
    if st == 'Error':
        why = '; '.join(c.get('reasons') or []) or 'simulation error'
        return ([dict(criterion='Simulation', measured='—', limit='—',
                      status='Fail', basis=why)],
                'Error — the case could not be simulated: ' + why + '.')
    chk('Bus remains energised', 'blackout' if m.get('blackout') else 'energised',
        'no blackout', not m.get('blackout'),
        'at least one source keeps forming the voltage')
    if 'pcs_trip' in m:
        chk('PCS stays connected', 'tripped' if m.get('pcs_trip') else 'connected',
            'no trip', not m.get('pcs_trip'), 'PCS protection / current limit')
    trips = list(m.get('ibr_trip') or [])
    chk('PV / WTG inverters ride through', ', '.join(trips) + ' tripped' if trips
        else 'no trip', 'no trip', not trips, 'IEEE 2800 / IEC 61400-21-1 ride-through')
    fmin, fmax = num('f_min'), num('f_max')
    sync = 'breaker closing: the measured frequency spike is a phase-jump ' \
           'artefact, so the frequency band is not assessed'
    if fmin is not None:
        chk('Minimum frequency', f'{fmin:.2f} Hz', f"≥ {crit['f_lo']:g} Hz",
            fmin >= crit['f_lo'] - 1e-9, _CRIT_BASIS['f_lo'],
            na=sync if kind == 'sync' else None,
            margin=(fmin - crit['f_lo']) / band)
    if fmax is not None:
        chk('Maximum frequency', f'{fmax:.2f} Hz', f"≤ {crit['f_hi']:g} Hz",
            fmax <= crit['f_hi'] + 1e-9, _CRIT_BASIS['f_hi'],
            na=sync if kind == 'sync' else None,
            margin=(crit['f_hi'] - fmax) / band)
    vmin = num('v_min')
    if vmin is not None:
        chk('Minimum bus voltage', f'{vmin:.3f} pu', f"≥ {crit['v_lo']:g} pu",
            vmin >= crit['v_lo'] - 1e-9, _CRIT_BASIS['v_lo'],
            na=('fault case: the voltage collapses during the fault by '
                'definition — judged on recovery instead') if kind == 'fault'
            else None, margin=(vmin - crit['v_lo']) / max(crit['v_lo'], 1e-6))
    if kind == 'fault':
        rec = num('t_v_recover')
        chk('Voltage recovery after clearing',
            f'{rec:.3f} s' if rec is not None else 'not recovered', '≤ 1.0 s',
            rec is not None and rec <= 1.0, _CRIT_BASIS['rec'],
            margin=(1.0 - rec) if rec is not None else None)
    ro = num('rocof')
    if ro is not None:
        chk('RoCoF (first 100 ms)', f'{ro:+.2f} Hz/s', f"|RoCoF| ≤ {crit['rocof']:g} Hz/s",
            abs(ro) <= crit['rocof'] + 1e-9, _CRIT_BASIS['rocof'],
            na=None if kind in ('trip', 'dyn') else
            f'not assessed for {kind} cases (event is not a power imbalance)',
            margin=(crit['rocof'] - abs(ro)) / max(crit['rocof'], 1e-6))
    pe = num('pcs_end')
    if pe is not None:
        chk('PCS current after the event', f'{pe:.2f} pu',
            f"≤ {crit['ilim_cont']:g} pu (continuous)",
            pe <= crit['ilim_cont'] + 0.005, _CRIT_BASIS['ilim'],
            margin=(crit['ilim_cont'] - pe) / max(crit['ilim_cont'], 1e-6))
    fails = [x for x in out if x['status'] == 'Fail']
    met = [x for x in out if x['status'] == 'Pass']

    na_ = [x for x in out if x['status'] == 'Not assessed']

    def brief(x):
        return f"{x['criterion']} {x['measured']} (limit {x['limit']})"
    tight = min((x for x in met if x.get('margin') is not None),
                key=lambda x: x['margin'], default=None)
    tail = (f" Not assessed for this case type: "
            + ', '.join(x['criterion'] for x in na_) + '.') if na_ else ''
    if st == 'Ref':
        expl = ('Reference case — not judged; shown for comparison with the '
                'case that has the remedy (e.g. without BESS). '
                + (('It would fail on: ' + '; '.join(brief(x) for x in fails)
                    + '.') if fails else 'It would also meet every criterion.'))
    elif fails:
        expl = ('Fail — ' + '; '.join(brief(x) for x in fails) + '. '
                + (f"The other {len(met)} criteria are met." if met else '')
                + tail)
    else:
        expl = (f"Pass — all {len(met)} assessed criteria met"
                + (f"; closest to its limit: {brief(tight)}." if tight else '.')
                + tail)
    if c.get('note'):
        expl += ' ' + c['note']
    return out, expl


def _case(cid, group, title, scen, res, t_ev, crit, f_nom, kind='dyn', ref=False,
          t_clear=None, extra=None, note=''):
    m = T.metrics(res, t_ev, f_nom, t_clear=t_clear)
    m['ibr_trip'] = list(res.get('ibr_trip') or [])
    if extra:
        m.update(extra)
    st, why = _verdict(m, crit, kind, ref)
    return dict(id=cid, group=group, title=title, scenario=scen, kind=kind,
                metrics={k: (float(v) if isinstance(v, (int, float, np.floating))
                             and not isinstance(v, bool) else v)
                         for k, v in m.items()},
                status=st, reasons=why, note=note, t_ev=float(t_ev),
                log=[f'{t:.2f} s — {msg}' for t, msg in res.get('log', [])],
                series=_thin(res))


# ---------------------------------------------------------------- studi
def run_study(cfg: dict, load_peak_kw: float | None = None, progress=None,
              cancel=None, include=None) -> dict:
    """Jalankan seluruh paket kasus untuk SATU sistem. progress(done, total,
    title). `include` = himpunan sumber yang diikutkan (lihat components)."""
    comp = components(cfg, load_peak_kw, include)
    f0 = comp['f_nom']
    _why = _former_reason(comp)
    if _why:
        return _empty_study(cfg, comp, _why)
    crit = dict(f_lo=_f(cfg, 'tr_f_lo', 47.5), f_hi=_f(cfg, 'tr_f_hi', 52.0),
                v_lo=_f(cfg, 'tr_v_lo', 0.8), rocof=_f(cfg, 'tr_rocof', 2.0),
                ilim_cont=_f(cfg, 'tr_pcs_ilim2', 1.1), t_st=_f(cfg, 'tr_pcs_t1', 10.0))
    if f0 > 55 and crit['f_lo'] < 50:                 # sistem 60 Hz: geser pita
        crit['f_lo'] += 10.0; crit['f_hi'] += 10.0
    L = comp['load_kw']
    pcs = comp['pcs']
    gfm = pcs is not None and pcs.mode == 'gfm'
    base_p = operating_point(cfg, comp, L)
    jobs = []                                           # (fungsi tanpa argumen)
    cases = []

    def sim(S, events, t_end, **kw):
        return T.Simulator(S).run(events, t_end, **kw)

    def add(fn):
        jobs.append(fn)

    # ---------- A. Loss of generation ----------
    def trip_case(cid, unit, load, title):
        p = operating_point(cfg, comp, load)
        if abs(p.get(unit, 0.0)) < 1.0:
            return None
        S = make_system(cfg, comp, load, p)
        ok_after = (len(S.machines) - (unit != 'GRID' and unit != 'BESS')
                    + (S.grid is not None and unit != 'GRID')
                    + (gfm and unit != 'BESS')) > 0
        res = sim(S, [dict(t=1.0, type='trip', unit=unit)], 12.0)
        note = '' if ok_after else 'No grid-forming source remains after the trip.'
        left = [k for k, v in p.items() if abs(v) > 0.5 and k != unit]
        if gfm and unit != 'BESS' and 'BESS' not in left:
            left.append('BESS')
        return _case(cid, 'A. Loss of generation', title, _scen(p), res, 1.0, crit,
                     f0, kind='trip', note=note,
                     extra=dict(lost_kw=p[unit], remaining=', '.join(left)))

    if comp['stg'] is not None:
        add(lambda: trip_case('A1', 'STG', L, f'STG trip at {L:,.0f} kW'))
        add(lambda: trip_case('A2', 'STG', 0.75 * L,
                              f'STG trip at {0.75 * L:,.0f} kW (75 % load)'))
    if comp.get('gtg') is not None:
        def gtg_trip():
            p = operating_point(cfg, comp, L)
            ld = L
            if p.get('GTG', 0.0) < 1.0:
                # GTG tak ikut di titik dasar (on demand) -> skenario GTG memikul
                use = {'BESS', 'PV', 'WTG', 'GTG'}
                ld = min(L, 0.8 * comp['gtg'].pmax_kw
                         + (0.3 * pcs.s_kva if pcs else 0.0))
                p = operating_point(cfg, comp, ld, use=use)
                if p.get('GTG', 0.0) < 1.0:
                    p['GTG'] = min(0.7 * comp['gtg'].pmax_kw, ld)
                    if 'BESS' in p:
                        p['BESS'] = ld - sum(v for k, v in p.items() if k != 'BESS')
            S = make_system(cfg, comp, ld, p)
            if not _has_former(S):
                return None
            res = sim(S, [dict(t=1.0, type='trip', unit='GTG')], 12.0)
            left = len(S.machines) - 1 + (1 if gfm else 0) + (
                1 if S.grid is not None else 0)
            return _case('A5', 'A. Loss of generation',
                         f'GTG trip at {ld:,.0f} kW', _scen(p), res, 1.0, crit,
                         f0, kind='trip',
                         note=('' if left > 0 else
                               'No grid-forming source remains after the trip.'),
                         extra=dict(lost_kw=p['GTG']))
        add(gtg_trip)
    if comp['grid'] is not None:
        add(lambda: trip_case('A3', 'GRID', L,
                              f'Loss of Utility Grid (islanding) at {L:,.0f} kW'))
    if comp['degs']:
        big = max(comp['degs'], key=lambda m: m.s_kva)

        def deg_trip():
            # skenario dgn DEG berbeban: tanpa STG/grid agar DEG memang jalan
            use = {'BESS', 'PV', 'WTG'} | {m.name for m in comp['degs']}
            load = min(L, 0.8 * sum(m.pmax_kw for m in comp['degs'])
                       + (0.3 * pcs.s_kva if pcs else 0.0))
            p = operating_point(cfg, comp, load, use=use)
            if p.get(big.name, 0.0) < 1.0:
                p[big.name] = min(0.7 * big.pmax_kw, load)
                if 'BESS' in p:
                    p['BESS'] = load - sum(v for k, v in p.items() if k != 'BESS')
            S = make_system(cfg, comp, load, p)
            if not _has_former(S):
                return None
            res = sim(S, [dict(t=1.0, type='trip', unit=big.name)], 12.0)
            left = len(S.machines) - 1 + (1 if gfm else 0)
            return _case('A4', 'A. Loss of generation',
                         f'{big.name} trip at {load:,.0f} kW (DEG supplying)',
                         _scen(p), res, 1.0, crit, f0, kind='trip',
                         note=('' if left > 0 else 'No grid-forming source remains '
                               'after the trip (grid-following PCS cannot hold '
                               'the island).'),
                         extra=dict(lost_kw=p[big.name]))
        add(deg_trip)

    # ---------- B. Loss of the BESS ----------
    if pcs is not None and (comp['stg'] or comp['degs'] or comp['grid']
                            or comp.get('gtg')):
        def pcs_trip(cid, shed, limited):
            # BESS sedang memikul 20 % beban (menggantikan sumber dispatchable
            # terbesar). 'limited' = STG tak punya cadangan uap (steam-limited
            # pada output saat itu) -> kehilangan BESS tak bisa diambil alih.
            p = dict(base_p)
            share = min(0.2 * L, 0.8 * pcs.s_kva)
            donors = [k for k in ('STG', 'GTG', 'GRID') + tuple(
                m.name for m in comp['degs'])
                      if p.get(k, 0.0) > 1.0]
            if not donors:
                return None
            d = max(donors, key=lambda k: p[k])
            take = min(share, 0.8 * p[d])
            p[d] -= take
            p['BESS'] = p.get('BESS', 0.0) + take
            S = make_system(cfg, comp, L, p)
            if not (S.machines or S.grid):
                return None
            if limited:
                for m in S.machines:
                    if m.kind == 'STG':
                        m.pmax_kw = m.p0_kw
            k = f0 / 50.0
            uf = [(49.0 * k, 0.2, 0.15), (48.5 * k, 0.2, 0.15),
                  (48.0 * k, 0.2, 0.20)] if shed else None
            res = sim(S, [dict(t=1.0, type='trip', unit='BESS')], 25.0, ufls=uf)
            ttl = (f'PCS trip while supplying {p["BESS"]:,.0f} kW'
                   + (', STG steam-limited' if limited else ', sources with margin')
                   + (', automatic UFLS' if shed else ', no load shedding'))
            return _case(cid, 'B. Loss of the BESS', ttl, _scen(p), res, 1.0, crit,
                         f0, kind='trip', extra=dict(lost_kw=p.get('BESS', 0.0)))
        add(lambda: pcs_trip('B1', False, False))
        if comp['stg'] is not None:
            add(lambda: pcs_trip('B2', False, True))
            add(lambda: pcs_trip('B3', True, True))
        else:
            add(lambda: pcs_trip('B2', True, False))

    # ---------- C. Renewable variability ----------
    drop = min(max(_f(cfg, 'tr_re_drop', 0.7), 0.0), 1.0)
    ramp = _f(cfg, 'tr_re_ramp_s', 5.0)
    if comp['pv'] is not None and base_p.get('PV', 0) > 1:
        def pv_cloud():
            S = make_system(cfg, comp, L, base_p)
            if not _has_former(S):
                return None
            res = sim(S, [dict(t=1.0, type='ibr_set', unit='PV',
                               p_kw=base_p['PV'] * (1 - drop), ramp_s=ramp)],
                      max(12.0, ramp + 8.0))
            return _case('C1', 'C. Renewable variability',
                         f'PV cloud transient: −{drop * 100:.0f} % in {ramp:g} s',
                         _scen(base_p), res, 1.0, crit, f0,
                         extra=dict(lost_kw=base_p['PV'] * drop))
        add(pv_cloud)
    if comp['wtg'] is not None and base_p.get('WTG', 0) > 1:
        def wtg_trip():
            S = make_system(cfg, comp, L, base_p)
            if not _has_former(S):
                return None
            res = sim(S, [dict(t=1.0, type='trip', unit='WTG')], 12.0)
            return _case('C2', 'C. Renewable variability',
                         'WTG trip (high-wind shutdown / protection)',
                         _scen(base_p), res, 1.0, crit, f0, kind='trip',
                         extra=dict(lost_kw=base_p['WTG']))
        add(wtg_trip)

        def wtg_gust():
            # Extreme Operating Gust (IEC 61400-1): turun – naik – kembali ~10,5 s
            S = make_system(cfg, comp, L, base_p)
            if not _has_former(S):
                return None
            pw = base_p['WTG']
            hi = min(comp['wtg_kw'], pw * 1.35)
            ev = [dict(t=1.0, type='ibr_set', unit='WTG', p_kw=pw * 0.75, ramp_s=2.6),
                  dict(t=3.6, type='ibr_set', unit='WTG', p_kw=hi, ramp_s=2.6),
                  dict(t=6.2, type='ibr_set', unit='WTG', p_kw=pw * 0.75, ramp_s=2.6),
                  dict(t=8.8, type='ibr_set', unit='WTG', p_kw=pw, ramp_s=2.7)]
            res = sim(S, ev, 18.0)
            return _case('C3', 'C. Renewable variability',
                         'WTG extreme operating gust (IEC 61400-1 EOG shape)',
                         _scen(base_p), res, 1.0, crit, f0,
                         extra=dict(lost_kw=pw * 0.25))
        add(wtg_gust)

    # ---------- D. Steam shortfall ----------
    if comp['stg'] is not None and base_p.get('STG', 0) > 1:
        sd = min(max(_f(cfg, 'tr_stg_steam_drop', 0.2), 0.0), 1.0)

        def steam(cid, with_bess):
            p = dict(base_p)
            if not with_bess:
                p = operating_point(cfg, comp, L,
                                    use={k for k in p if k != 'BESS'})
                if p.get('STG', 0) < 1:
                    return None
            S = make_system(cfg, comp, L, p)
            res = sim(S, [dict(t=1.0, type='ceil', unit='STG',
                               p_kw=p['STG'] * (1 - sd), ramp_s=2.0)], 25.0)
            return _case(cid, 'D. Steam shortfall',
                         f'Boiler pressure drop: STG limited to '
                         f'{p["STG"] * (1 - sd):,.0f} kW '
                         + ('(with BESS)' if with_bess else '(without BESS — reference)'),
                         _scen(p), res, 1.0, crit, f0, ref=not with_bess,
                         extra=dict(lost_kw=p['STG'] * sd))
        if pcs is not None:
            add(lambda: steam('D1', True))
        add(lambda: steam('D2', False))

    # ---------- E. Load step & damping ----------
    def load_step(cid, frac, label=''):
        S = make_system(cfg, comp, L, base_p)
        if not _has_former(S):
            return None
        res = sim(S, [dict(t=1.0, type='load_step', dp_kw=frac * L)], 12.0,
                  rec_dt=0.002)
        ex = {}
        sig = None
        for m in S.machines:
            sig = res.get('p_' + m.name)
            break
        if sig is None:
            sig = res.get('p_BESS')
        md = T.modal(res['t'], sig, 1.0) if sig is not None else {}
        if md:
            ex = dict(mode_hz=md.get('freq', float('nan')),
                      damping=md.get('damping', float('nan')),
                      t_decay=md.get('t_decay', float('nan')))
        if gfm and 'p_BESS' in res:
            i = np.searchsorted(res['t'], 1.3)
            if i < res['t'].size:
                ex['bess_share'] = float((res['p_BESS'][i] - res['p_BESS'][0])
                                         / (frac * L))
        return _case(cid, 'E. Load step & damping',
                     f'Load step {frac * 100:+.0f} % ({frac * L:+,.0f} kW)'
                     + (f' — {label}' if label else ''),
                     _scen(base_p), res, 1.0, crit, f0, extra=ex)
    pqa = comp.get('pqa')
    up = float(pqa.get('step_up_kw', 0.0)) if pqa else 0.0
    dn = float(pqa.get('step_dn_kw', 0.0)) if pqa else 0.0
    if pqa and up > 1.0:
        add(lambda: load_step('E1', up / L, 'largest measured (PQA) load rise'))
    else:
        add(lambda: load_step('E1', 0.2))
    if pqa and dn < -1.0:
        add(lambda: load_step('E2', dn / L, 'largest measured (PQA) load drop'))
    else:
        add(lambda: load_step('E2', -0.2))
    if pqa and len(pqa.get('window_kw') or []) >= 4:
        def replay():
            # Level beban terukur berurutan (jendela di sekitar step terbesar)
            # diterapkan sebagai step; tiap level ditahan 4 s hingga mapan.
            w = [float(x) for x in pqa['window_kw']][:16]
            p0 = operating_point(cfg, comp, w[0])
            S = make_system(cfg, comp, w[0], p0)
            if not _has_former(S):
                return None
            ev = [dict(t=1.0 + 4.0 * (i - 1), type='load_step',
                       dp_kw=w[i] - w[i - 1]) for i in range(1, len(w))]
            res = sim(S, ev, 1.0 + 4.0 * (len(w) - 1) + 4.0, rec_dt=0.01)
            dts = pqa.get('dt_s')
            return _case('K1', 'K. Measured load replay (PQA)',
                         f'{len(w)} consecutive measured load levels '
                         f'({min(w):,.0f}–{max(w):,.0f} kW'
                         + (f', sampled every {dts:g} s' if dts else '')
                         + ') applied as steps, 4 s each',
                         _scen(p0), res, 1.0, crit, f0,
                         extra=dict(lost_kw=max(abs(w[i] - w[i - 1])
                                                for i in range(1, len(w)))),
                         note=f"Source: {pqa.get('source', 'PQA')}")
        add(replay)

    # ---------- F. Motor starting ----------
    mk = comp['motor_kw']

    def motor(cid, title, load, p, ref=False):
        S = make_system(cfg, comp, load, p, motor_start=True)
        if not _has_former(S):
            return None
        res = sim(S, [dict(t=1.0, type='motor_start', index=len(S.motors) - 1)],
                  14.0)
        j = len(S.motors) - 1
        ex = dict(motor_ipk_a=float(res[f'i_mot{j}'].max()),
                  t_runup=(res['motors'][j]['t_up']
                           if res['motors'][j]['t_up'] is not None else float('nan')))
        return _case(cid, 'F. Motor starting', title, _scen(p), res, 1.0, crit, f0,
                     ref=ref, extra=ex)
    add(lambda: motor('F1', f'DOL start {mk:,.0f} kW — all sources',
                      max(L - mk, 0.2 * L), operating_point(
                          cfg, comp, max(L - mk, 0.2 * L))))
    if gfm:
        lo = min(0.3 * L, 0.4 * pcs.s_kva)
        add(lambda: motor('F2', f'DOL start {mk:,.0f} kW — BESS alone', lo,
                          {'BESS': lo}))
    if pcs is not None and (comp['stg'] or comp['degs'] or comp['grid']
                            or comp.get('gtg')):
        def motor_nobess():
            ld = max(L - mk, 0.2 * L)
            p = operating_point(cfg, comp, ld, use={
                k for k in base_p if k != 'BESS'} | {m.name for m in comp['degs']})
            return motor('F3', f'DOL start {mk:,.0f} kW — without BESS (reference)',
                         ld, p, ref=True)
        add(motor_nobess)

    # ---------- G. Synchronisation ----------
    if gfm:
        lo = min(0.3 * L, 0.4 * pcs.s_kva)
        units = []
        if comp['stg'] is not None:
            units.append(('STG', comp['stg']))
        if comp.get('gtg') is not None:
            units.append(('GTG', comp['gtg']))
        if comp['degs']:
            units.append((comp['degs'][0].name, comp['degs'][0]))
        if comp['grid'] is not None:
            units.append(('GRID', comp['grid']))
        k = 0
        for nm, obj in units:
            for dphi, dv, lab in ((10.0, 0.03, 'ANSI 25 window edge (10°, 3 %)'),
                                  (60.0, 0.10, 'out-of-phase closing (60°, 10 %)')):
                k += 1

                def sync(nm=nm, obj=obj, dphi=dphi, dv=dv, lab=lab, k=k):
                    S = make_system(cfg, comp, lo, {'BESS': lo}, subtransient=True)
                    ev = dict(t=1.0, type='close', unit=nm, dphi_deg=dphi, dv=dv,
                              df_hz=0.1)
                    if nm == 'GRID':
                        ev['grid'] = copy.copy(obj); ev['df_hz'] = 0.0
                    else:
                        ev['machine'] = copy.copy(obj)
                    res = sim(S, [ev], 6.0, rec_dt=0.001)
                    ex = {}
                    if nm == 'GRID':
                        ex['unit_ipk_a'] = float(res['i_GRID'].max())
                    else:
                        ex['unit_ipk_a'] = float(res['mach'][nm]['ipk_a'])
                        ex['unit_swing_kw'] = float(res['mach'][nm]['ppk_kw'])
                    who = 'Utility Grid' if nm == 'GRID' else nm
                    return _case(f'G{k}', 'G. Synchronisation',
                                 f'{who} closing onto BESS bus — {lab}',
                                 _scen({'BESS': lo}), res, 1.0, crit, f0,
                                 kind='sync', extra=ex)
                add(sync)

    # ---------- H. Feeder fault ----------
    zb = comp['v_kv'] ** 2 / 1.0                              # Ω pada 1 MVA
    zf = T.cable_z_ohm(_f(cfg, 'tr_feeder_m', 50.0), _f(cfg, 'tr_feeder_mm2', 120.0)) / zb
    tc = _f(cfg, 'tr_t_clear_ms', 150.0) / 1000.0

    def fault(cid, title, load, p, t_c):
        S = make_system(cfg, comp, load, p)
        if not _has_former(S):
            return None
        res = sim(S, [dict(t=1.0, type='fault_on', z=zf),
                      dict(t=1.0 + t_c, type='fault_off')], 8.0, rec_dt=0.001)
        i = max(0, np.searchsorted(res['t'], 1.0 + t_c - 0.005) - 1)
        ex = dict(i_fault_ka=float(res['i_fault'][i] / 1000.0),
                  v_fault=float(res['v'][i]), t_clear=t_c)
        w = [res[k].min() for k in res if k.startswith('w_mot')
             and res[k].max() > 0.5]
        if w:
            ex['motor_w_min'] = float(min(w))
        return _case(cid, 'H. Feeder fault', title, _scen(p), res, 1.0, crit, f0,
                     kind='fault', t_clear=1.0 + t_c, extra=ex)
    add(lambda: fault('H1', f'3-phase feeder fault, cleared in {tc * 1000:.0f} ms '
                            '— all sources', L, base_p, tc))
    add(lambda: fault('H2', f'3-phase feeder fault, backup clearing '
                            f'{(tc + 0.25) * 1000:.0f} ms — all sources',
                      L, base_p, tc + 0.25))
    if gfm:
        lo = min(0.3 * L, 0.4 * pcs.s_kva)
        add(lambda: fault('H3', f'3-phase feeder fault, cleared in {tc * 1000:.0f} ms '
                                '— BESS alone', lo, {'BESS': lo}, tc))

    # ---------- I. Black start ----------
    if gfm:
        def black_start():
            blk = _f(cfg, 'bs_kw') if cfg.get('m_black_start') else 0.0
            if blk <= 0:
                blk = min(0.3 * L, 0.5 * pcs.s_kva)
            S = make_system(cfg, comp, 0.02 * blk, {'BESS': 0.02 * blk},
                            motor_start=True, motor_frac=0.0)
            S.motors[-1].p_kw = min(comp['motor_kw'], 0.25 * blk)
            ev = [dict(t=1.0, type='load_step', dp_kw=0.5 * blk),
                  dict(t=3.0, type='load_step', dp_kw=0.5 * blk),
                  dict(t=5.0, type='motor_start', index=0)]
            res = sim(S, ev, 14.0)
            return _case('I1', 'I. Black start',
                         f'BESS black start: block-load pick-up 2 × {0.5 * blk:,.0f} kW '
                         f'then DOL start {S.motors[-1].p_kw:,.0f} kW',
                         'BESS alone (dead-bus energisation)', res, 1.0, crit, f0,
                         extra=dict(block_kw=blk))
        add(black_start)

    # ---------- eksekusi ----------
    n = len(jobs)
    for i, fn in enumerate(jobs):
        if cancel is not None and cancel():
            break
        if progress is not None:
            progress(i, n + 1, '')
        try:
            c = fn()
        except Exception as ex:                       # satu kasus gagal -> lanjut
            c = dict(id=f'X{i}', group='—', title=f'case error: {ex}',
                     scenario='', kind='dyn', metrics={}, status='Error',
                     reasons=[str(ex)], note='', t_ev=0.0, log=[], series={})
        if c is not None:
            cases.append(c)

    # ---------- J. Short circuit & protection ----------
    Sall = make_system(cfg, comp, L, {**{k: 1.0 for k in base_p},
                                      **{m.name: 1.0 for m in comp['degs']}})
    Sall.machines = ([copy.copy(comp['stg'])] if comp['stg'] else []) + \
        ([copy.copy(comp['gtg'])] if comp.get('gtg') else []) + \
        [copy.copy(m) for m in comp['degs']]
    Sall.pcs = copy.copy(pcs) if pcs else None
    Sall.ibrs = [copy.copy(b) for b in (comp['pv'], comp['wtg']) if b is not None]
    Sall.grid = copy.copy(comp['grid']) if comp['grid'] else None
    names = [m.name for m in Sall.machines]
    degn = [m.name for m in comp['degs']]
    cfgs = []
    cfgs.append(('All sources in service', dict(
        machines=names, pcs=pcs is not None, ibr=True, grid=True, motors=True)))
    if Sall.grid is not None:
        cfgs.append(('Islanded (Utility Grid out)', dict(
            machines=names, pcs=pcs is not None, ibr=True, grid=False, motors=True)))
    if pcs is not None:
        lo_f = min(0.3, 0.4 * pcs.s_kva / max(L, 1e-9))      # beban rendah
        cfgs.append(('BESS only (low load)', dict(
            machines=[], pcs=True, ibr=False, grid=False, motors=True,
            motor_scale=lo_f)))
        if Sall.ibrs:
            cfgs.append(('BESS + PV/WTG', dict(machines=[], pcs=True, ibr=True,
                                               grid=False, motors=True,
                                               motor_scale=lo_f)))
        if degn:
            cfgs.append((f'BESS + {degn[0]}', dict(
                machines=degn[:1], pcs=True, ibr=False, grid=False, motors=True)))
        if comp['stg']:
            cfgs.append(('STG + BESS', dict(machines=['STG'], pcs=True, ibr=False,
                                            grid=False, motors=True)))
        if comp.get('gtg'):
            cfgs.append(('GTG + BESS', dict(machines=['GTG'], pcs=True, ibr=False,
                                            grid=False, motors=True)))
    if degn:
        cfgs.append((f'{degn[0]} only (BESS out)', dict(
            machines=degn[:1], pcs=False, ibr=False, grid=False, motors=True)))
        if len(degn) > 1:
            cfgs.append(('All DEG (BESS out)', dict(
                machines=degn, pcs=False, ibr=False, grid=False, motors=True)))
    sc = []
    for name, c in cfgs:
        r = T.short_circuit(Sall, c)
        sc.append(dict(config=name, ik_max=r['ik_max'], ik_min=r['ik_min'],
                       ip=r['ip'], rows=[list(x) for x in r['rows']]))
    icu = _f(cfg, 'tr_icu_ka', 50.0)
    ik_all = max((s['ik_max'] for s in sc), default=0.0)
    ik_weak = min((s['ik_min'] for s in sc if s['ik_min'] > 0), default=0.0)
    weak_name = next((s['config'] for s in sc if s['ik_min'] == ik_weak), '')
    prot = [dict(rating=a, lo=b, hi=c, verdict=d)
            for a, b, c, d in T.feeder_clearing(ik_weak)]
    src = [dict(name=x[0], ir_a=x[1], basis=x[2], ik_sub=x[3], ik_tr=x[4])
           for x in T.short_circuit(Sall, cfgs[0][1])['rows']]

    study = dict(
        version=2, f_nom=f0, v_kv=comp['v_kv'], load_kw=L,
        load_pf=comp.get('load_pf'), pqa=comp.get('pqa'),
        basis=parameter_basis(cfg),
        motor_kw=comp['motor_kw'], motor_basis=comp.get('motor_basis', ''),
        base_scenario=_scen(base_p), crit=crit,
        pcs=(dict(kva=pcs.s_kva, mode=pcs.mode, ilim_st=pcs.ilim_st,
                  t_st=pcs.t_st, ilim_cont=pcs.ilim_cont) if pcs else None),
        sources=source_table(comp), cases=cases,
        sc=sc, sc_sources=src, icu_ka=icu, ik_all=ik_all, ik_weak=ik_weak,
        weak_config=weak_name, protection=prot)
    study['requirements'] = requirements(study)
    if progress is not None:
        progress(n + 1, n + 1, '')
    return study


def _empty_study(cfg, comp, reason: str) -> dict:
    """Studi kosong untuk sistem yang tidak dapat berdiri sendiri."""
    f0 = comp['f_nom']
    crit = dict(f_lo=_f(cfg, 'tr_f_lo', 47.5), f_hi=_f(cfg, 'tr_f_hi', 52.0),
                v_lo=_f(cfg, 'tr_v_lo', 0.8), rocof=_f(cfg, 'tr_rocof', 2.0),
                ilim_cont=_f(cfg, 'tr_pcs_ilim2', 1.1), t_st=_f(cfg, 'tr_pcs_t1', 10.0))
    return dict(
        version=2, f_nom=f0, v_kv=comp['v_kv'], load_kw=comp['load_kw'],
        load_pf=comp.get('load_pf'), pqa=comp.get('pqa'),
        basis=parameter_basis(cfg), motor_kw=comp['motor_kw'],
        motor_basis=comp.get('motor_basis', ''), base_scenario='—', crit=crit,
        pcs=None, sources=source_table(comp), cases=[], sc=[], sc_sources=[],
        icu_ka=_f(cfg, 'tr_icu_ka', 50.0), ik_all=0.0, ik_weak=0.0,
        weak_config='—', protection=[], not_viable=reason,
        requirements=[('System not analysed', reason,
                       'Dynamic cases need at least one grid-forming source')])


# ---------------------------------------------------------------- multi-sistem
def _firm_kw(cfg, comp):
    """(kapasitas firm kW, unit terbesar kW, daftar) — pembangkit yang dapat
    diatur + Utility Grid; PV/WTG (tak pasti) dan BESS (energi terbatas) tidak
    dihitung firm."""
    units = []
    if comp['stg'] is not None:
        units.append(('STG', comp['stg'].pmax_kw))
    if comp.get('gtg') is not None:
        units.append(('GTG', comp['gtg'].pmax_kw))
    for m in comp['degs']:
        units.append((m.name, m.pmax_kw))
    if comp['grid'] is not None:
        units.append(('Utility Grid', _f(cfg, 'grid_kw') * (
            _f(cfg, 'grid_max_loading', 1.0) or 1.0)))
    tot = sum(v for _n, v in units)
    big = max((v for _n, v in units), default=0.0)
    return tot, big, units


def _worst(cases, key, fn, kinds=None, skip=('Ref', 'Error')):
    v = [c['metrics'].get(key) for c in cases
         if c['status'] not in skip and (kinds is None or c['kind'] in kinds)
         and c['metrics'].get(key) is not None
         and np.isfinite(c['metrics'].get(key))]
    return fn(v) if v else None


def compare_systems(cfg, items) -> dict:
    """Tabel perbandingan antar-sistem. items = [(name, study, comp)]."""
    head = ['Item'] + [n for n, _s, _c in items]
    rows = []

    def row(label, fn):
        rows.append([label] + [fn(s, c) for _n, s, c in items])
    row('Sources', lambda s, c: ', '.join(
        [x[0] for x in s['sources']]) or '—')
    row('Selected but not configured (no rating on Parameters page)',
        lambda s, c: ', '.join(s.get('missing_sources') or []) or '—')
    row('Analysed', lambda s, c: 'No — ' + s['not_viable']
        if s.get('not_viable') else 'Yes')
    row('Cases: pass / fail', lambda s, c: '—' if s.get('not_viable') else
        f"{sum(x['status'] == 'Pass' for x in s['cases'])} / "
        f"{sum(x['status'] in ('Fail', 'Error') for x in s['cases'])}")
    row('Base operating point', lambda s, c: s['base_scenario'].replace(
        'GRID', 'Utility Grid'))

    def num(key, fn, fmt, kinds=None):
        def f(s, c):
            v = _worst(s['cases'], key, fn, kinds)
            return '—' if v is None else fmt.format(v)
        return f
    dyn = ('trip', 'dyn')
    row('Lowest frequency, all cases (Hz)', num('f_min', min, '{:.2f}',
                                                ('trip', 'dyn', 'fault')))
    row('Highest frequency, all cases (Hz)', num('f_max', max, '{:.2f}',
                                                 ('trip', 'dyn', 'fault')))
    row('Lowest voltage outside faults (pu)', num('v_min', min, '{:.3f}', dyn))
    row('Largest RoCoF (Hz/s)', num('rocof', lambda v: max(v, key=abs),
                                    '{:+.2f}', dyn))

    def cap(s, c):
        tot, big, _u = _firm_kw(cfg, c)
        return f'{tot:,.0f} kW (N-1: {tot - big:,.0f} kW)'
    row('Firm capacity (generators + Utility Grid)', cap)
    row('PCS rating', lambda s, c: f"{c['pcs'].s_kva:,.0f} kVA "
        f"({'grid-forming' if c['pcs'].mode == 'gfm' else 'grid-following'})"
        if c['pcs'] is not None else '—')
    row('Maximum fault level I″k (kA)', lambda s, c: '—' if not s['sc']
        else f"{s['ik_all']:.2f}")
    row('Minimum fault level (kA)', lambda s, c: '—' if not s['sc']
        else f"{s['ik_weak']:.2f} ({s['weak_config']})")
    return dict(head=head, rows=rows)


def pqa_assessment(cfg, pqa, items) -> dict | None:
    """Penilaian tiap sistem terhadap SELURUH kelompok kolom PQA.

    items = [(name, study, comp)]. Baris: [Item, PQA columns used, Measured,
    <satu kolom per sistem>, Criterion]. Besaran yang bergantung pada
    kekuatan sumber (dip akibat lonjakan arus, harmonisa & unbalance
    tegangan) diskalakan dengan rasio tingkat hubung singkat terhadap sistem
    tempat pengukuran dilakukan (Existing bila ada)."""
    if not isinstance(pqa, dict) or not pqa.get('analysis'):
        return None
    head = (['Item', 'PQA columns used', 'Measured']
            + [n for n, _s, _c in items] + ['Criterion'])
    rows = []
    kv = items[0][2]['v_kv']
    sk = [T.SQ3 * kv * s['ik_all'] if s.get('ik_all') else 0.0
          for _n, s, _c in items]                       # MVA
    ref = next((i for i, (n, _s, _c) in enumerate(items)
                if n == 'Existing' and sk[i] > 0), None)
    crit = items[0][1]['crit']

    def verdict(ok):
        return 'Pass' if ok else 'Fail'

    def per(fn):
        out = []
        for i, (n, s, c) in enumerate(items):
            try:
                out.append('—' if s.get('not_viable') else fn(i, s, c))
            except Exception:
                out.append('—')
        return out

    def scaled(i, val):
        """Skala besaran ∝ impedansi sumber dari sistem acuan ke sistem i."""
        if ref is None or sk[i] <= 0:
            return None
        return val * sk[ref] / sk[i]
    # 1 — beban studi & faktor daya
    if 'p_max' in pqa:
        rows.append(['Study load and power factor', 'P_sum_AVG, PF_sum_AVG',
                     f"max {pqa['p_max']:,.0f} · P95 {pqa['p_p95']:,.0f} · mean "
                     f"{pqa['p_mean']:,.0f} kW"
                     + (f" · PF {pqa['pf']:.3f}" if pqa.get('pf') else '')]
                    + per(lambda i, s, c: f"{s['load_kw']:,.0f} kW at PF "
                          f"{(s.get('load_pf') or 0):.3f} — "
                          + s['base_scenario'].replace('GRID', 'Utility Grid'))
                    + ['Load of every case = measured load'])
        # 2 — kecukupan kapasitas thd. demand
        dem = float(pqa.get('demand_kw') or pqa['p_max'])

        def adequacy(i, s, c):
            tot, big, _u = _firm_kw(cfg, c)
            pc = c['pcs'].s_kva * 0.9 if c['pcs'] is not None else 0.0
            t_ = f'firm {tot:,.0f} kW, N-1 {tot - big:,.0f} kW'
            if tot >= dem:
                return t_ + (' — Pass' if tot - big >= dem else
                             ' — Pass (N); N-1 Fail'
                             + (f' unless BESS {pc:,.0f} kW bridges' if pc else ''))
            return t_ + (f' + BESS {pc:,.0f} kW (energy-limited)' if pc else '') \
                + ' — Fail'
        rows.append(['Capacity against measured demand', 'Dem_P+, WP+, P_sum_AVG',
                     f'max demand {dem:,.0f} kW'
                     + (f" · energy {pqa['energy_kwh']:,.0f} kWh"
                        if pqa.get('energy_kwh') else '')]
                    + per(adequacy)
                    + ['Firm capacity ≥ maximum demand (N and N-1)'])
    # 3 — step beban terukur
    if pqa.get('step_up_kw') is not None:
        def steps(i, s, c):
            cs = [x for x in s['cases'] if x['id'] in ('E1', 'E2')]
            if not cs:
                return 'not simulated'
            return '; '.join(
                f"{x['id']}: f {x['metrics'].get('f_min', float('nan')):.2f}–"
                f"{x['metrics'].get('f_max', float('nan')):.2f} Hz, V min "
                f"{x['metrics'].get('v_min', float('nan')):.3f} pu ({x['status']})"
                for x in cs)
        rows.append(['Largest measured load steps', 'P_sum_AVG (interval change)',
                     f"+{pqa['step_up_kw']:,.0f} / {pqa['step_dn_kw']:,.0f} kW"]
                    + per(steps)
                    + [f"f {crit['f_lo']:g}–{crit['f_hi']:g} Hz, V ≥ "
                       f"{crit['v_lo']:g} pu"])
    # 4 — lonjakan arus setengah-siklus -> motor start / inrush
    if pqa.get('surge_kva'):
        sg = float(pqa['surge_kva'])

        def inrush(i, s, c):
            t_ = []
            if sk[i] > 0:
                dv = sg / (sk[i] * 1000.0)
                t_.append(f'ΔV ≈ {dv * 100:.1f} % (S″k {sk[i]:.1f} MVA)')
            f1 = [x for x in s['cases'] if x['group'].startswith('F')
                  and x['status'] not in ('Ref', 'Error')]
            if f1:
                w = min(f1, key=lambda x: x['metrics'].get('v_min', 9))
                t_.append(f"{w['id']} DOL {s['motor_kw']:,.0f} kW: V min "
                          f"{w['metrics'].get('v_min', float('nan')):.3f} pu "
                          f"({w['status']})")
            return '; '.join(t_) or '—'
        rows.append(['Starting / inrush current surge',
                     'I1..3_rms1/2_MAX, I1..3_rms1/2_MIN, I1..3_rms_AVG',
                     f"{sg:,.0f} kVA above the interval average"
                     + (f" at {pqa['surge_at']}" if pqa.get('surge_at') else '')]
                    + per(inrush)
                    + [f"V ≥ {crit['v_lo']:g} pu during starting"])
    # 5 — dip / interupsi setengah-siklus
    if pqa.get('n_dip') is not None:
        def dips(i, s, c):
            v = _worst(s['cases'], 'v_min', min, ('trip', 'dyn'))
            t_ = ('simulated worst V min —' if v is None else
                  f'simulated worst V min {v:.3f} pu '
                  f"({verdict(v >= crit['v_lo'])})")
            if pqa.get('n_interruption_events'):
                gfm = c['pcs'] is not None and c['pcs'].mode == 'gfm'
                t_ += ('; grid-forming BESS can hold the bus through source '
                       'interruptions' if gfm else
                       '; no grid-forming BESS — interruptions not bridged')
            return t_
        rows.append(['Voltage dips and interruptions',
                     'U1..3_rms1/2_MIN, U1..3_rms1/2_MAX',
                     (f"worst dip {pqa['dip_min_pu']:.3f} pu, "
                      if pqa.get('dip_min_pu') is not None else '')
                     + f"{pqa.get('n_dip_events', 0)} dip events, "
                     f"{pqa.get('n_interruption_events', 0)} interruptions"
                     + (f" (≈ {pqa['interruption_min']:,.0f} min)"
                        if pqa.get('interruption_min') else '')
                     + f", {pqa.get('n_swell', 0)} swell intervals"]
                    + per(dips) + [f"V ≥ {crit['v_lo']:g} pu outside faults"])
    # 6 — frekuensi
    if pqa.get('f_min') is not None:
        def freq(i, s, c):
            lo = _worst(s['cases'], 'f_min', min, ('trip', 'dyn'))
            hi = _worst(s['cases'], 'f_max', max, ('trip', 'dyn'))
            ro = _worst(s['cases'], 'rocof', lambda v: max(v, key=abs),
                        ('trip', 'dyn'))
            if lo is None:
                return '—'
            ok = lo >= crit['f_lo'] and (hi is None or hi <= crit['f_hi'])
            return (f'simulated {lo:.2f}–{hi:.2f} Hz'
                    + (f', RoCoF {ro:+.2f} Hz/s' if ro is not None else '')
                    + f' ({verdict(ok)})'
                    + ('; better than measured minimum'
                       if lo > pqa['f_min'] + 0.05 else
                       '; below measured minimum' if lo < pqa['f_min'] - 0.05
                       else ''))
        rows.append(['Frequency excursions and RoCoF',
                     'Freq_wav_MIN, Freq_wav_MAX, Freq_AVG',
                     f"{pqa['f_min']:.2f}–{pqa['f_max']:.2f} Hz"
                     + (f", RoCoF ≥ {pqa['rocof_avg']:.3f} Hz/s (interval "
                        'average)' if pqa.get('rocof_avg') is not None else '')]
                    + per(freq)
                    + [f"{crit['f_lo']:g}–{crit['f_hi']:g} Hz, RoCoF ≤ "
                       f"{crit['rocof']:g} Hz/s"])
    # 7 — unbalance
    if pqa.get('uunb_p95') is not None:
        def uunb(i, s, c):
            v = scaled(i, pqa['uunb_p95'])
            if v is None:
                return (f"{pqa['uunb_p95']:.2f} % (as measured)"
                        if ref is None else '—')
            return f'≈ {v:.2f} % ({verdict(v <= 2.0)})'
        rows.append(['Voltage unbalance', 'Uunb_AVG',
                     f"P95 {pqa['uunb_p95']:.2f} %"] + per(uunb)
                    + ['≤ 2 % (EN 50160 / IEC 61000-2-2), scaled with source '
                       'fault level'])
    if pqa.get('iunb_p95') is not None:
        def iunb(i, s, c):
            kva = sum(m.s_kva for m in ([c['stg']] if c['stg'] else [])
                      + ([c['gtg']] if c.get('gtg') else []) + list(c['degs']))
            sl = s['load_kw'] / max(s.get('load_pf') or 0.9, 0.1)
            if kva <= 0:
                return ('no synchronous machine — converters must supply the '
                        'negative-sequence current (specify unbalanced-load '
                        'capability)')
            v = pqa['iunb_p95'] * min(1.0, sl / kva)
            return (f'≈ {v:.1f} % of machine rating '
                    f'({kva:,.0f} kVA) ({verdict(v <= 8.0)})')
        rows.append(['Current unbalance on generators',
                     'Iunb_AVG, I1..3_rms_AVG', f"P95 {pqa['iunb_p95']:.2f} %"]
                    + per(iunb)
                    + ['Negative-sequence current ≤ 8 % of rated (IEC 60034-1, '
                       'continuous)'])
    # 8 — harmonisa
    if pqa.get('thd_p95') is not None:
        def thd(i, s, c):
            v = scaled(i, pqa['thd_p95'])
            if v is None:
                return (f"{pqa['thd_p95']:.2f} % (as measured)"
                        if ref is None else '—')
            return f'≈ {v:.2f} % ({verdict(v <= 8.0)})'
        rows.append(['Voltage THD', 'U1..3_thd-f_AVG',
                     f"P95 {pqa['thd_p95']:.2f} %"] + per(thd)
                    + ['≤ 8 % (EN 50160 / IEC 61000-2-2), scaled with source '
                       'fault level'])
    hu, hi_ = pqa.get('h_u_p95') or {}, pqa.get('h_i_p95') or {}
    if hu:
        def hv(i, s, c):
            t_ = []
            for h, lim in (('5', 6.0), ('7', 5.0)):
                if h in hu:
                    v = scaled(i, hu[h])
                    t_.append(f'H{h} {hu[h]:.2f} % (as measured)' if v is None
                              else f'H{h} ≈ {v:.2f} % ({verdict(v <= lim)})')
            return '; '.join(t_)
        rows.append(['Voltage harmonics, order 5 and 7',
                     'U1..3_H5_AVG, U1..3_H7_AVG',
                     ' · '.join(f'H{h} P95 {v:.2f} %' for h, v in sorted(hu.items()))]
                    + per(hv) + ['H5 ≤ 6 %, H7 ≤ 5 %, scaled with source fault '
                                 'level'])
    if hi_:
        def hc(i, s, c):
            tot = float(np.sqrt(sum(v * v for v in hi_.values())))
            kva = sum(m.s_kva for m in ([c['stg']] if c['stg'] else [])
                      + ([c['gtg']] if c.get('gtg') else []) + list(c['degs']))
            sl = s['load_kw'] / max(s.get('load_pf') or 0.9, 0.1)
            if kva <= 0:
                return (f'{tot:.1f} % of load current absorbed by the '
                        'converters / Utility Grid — include in PCS filter '
                        'and control specification')
            return (f'≈ {tot * min(1.0, sl / kva):.1f} % of machine rating as '
                    'harmonic current (rotor heating margin)')
        rows.append(['Load harmonic current, order 5 and 7',
                     'I1..3_H5_AVG, I1..3_H7_AVG',
                     ' · '.join(f'H{h} P95 {v:.2f} %' for h, v in sorted(hi_.items()))]
                    + per(hc) + ['No fixed limit (IEEE 519 needs Isc/IL)'])
    note = ('Voltage unbalance, THD and harmonic voltages of each system are '
            'first-order estimates: measured value × (fault level of the '
            'measured system ÷ fault level of that system). '
            + ('The measurement is taken as made on the Existing system.'
               if ref is not None else
               'No Existing system is defined, so the measured values are '
               'shown unscaled.'))
    return dict(head=head, rows=rows, note=note,
                source=pqa.get('source', ''))


_PQA_EVENT = {
    'A': ('f_low', 'loss of generation shows as an under-frequency event'),
    'B': ('f_low', 'loss of the BESS shows as an under-frequency event'),
    'C': ('step_up', 'loss of PV / WTG output acts on the other sources like '
                     'a sudden load rise'),
    'D': ('f_low', 'steam shortfall shows as a sustained under-frequency'),
    'E': ('step_up', 'measured load step'),
    'F': ('surge', 'motor starting / inrush appears as a half-cycle current '
                   'surge'),
    'G': ('restore', 'closing a source onto the bus — nearest measured event '
                     'is the re-energisation after an interruption'),
    'H': ('dip', 'a feeder fault appears as a voltage dip'),
    'I': ('restore', 'black start = re-energisation of the dead bus'),
    'K': ('step_up', 'measured load window replayed in the case'),
}


def pqa_event_for(case: dict, pqa) -> tuple:
    """(excerpt | None, kunci, alasan) — cuplikan data PQA yang paling terkait
    dengan kasus. E2 (load drop) -> 'step_dn'; kasus lain menurut kelompok."""
    ev = (pqa or {}).get('events') if isinstance(pqa, dict) else None
    if not ev:
        return None, '', ''
    g = str(case.get('group', ' '))[:1]
    key, why = _PQA_EVENT.get(g, ('peak', 'measured maximum load'))
    title = str(case.get('title', '')).lower()
    if g == 'E' and ('drop' in title or 'load step -' in title
                     or 'rejection' in title):
        key, why = 'step_dn', 'measured load drop'
    if g == 'I' and 'restore' not in ev:
        key = 'interruption'
    for k in (key, 'f_low', 'peak'):
        if k in ev:
            return ev[k], k, why if k == key else (
                why + ' (no such event in the record — nearest available '
                'excerpt shown)')
    return None, '', ''


def run_scenarios(cfg: dict, load_peak_kw: float | None = None, progress=None,
                  cancel=None) -> dict:
    """Studi multi-sistem: Existing, New, Existing + New (pilihan pengguna di
    halaman Transient). Tanpa pilihan -> satu studi seluruh sumber.

    Hasil = studi sistem UTAMA (Existing + New bila ada) ditambah:
      scenarios  : [dict(key, name, sources, primary, study)] — study = None
                   untuk sistem utama (isinya ada di tingkat atas)
      comparison : tabel perbandingan antar-sistem
      assessment : penilaian tiap sistem terhadap seluruh kolom PQA"""
    scen = system_scenarios(cfg)
    if not scen:
        scen = [('all', 'All configured sources', None)]
    n = len(scen)
    done = []
    for k, (key, name, inc) in enumerate(scen):
        if cancel is not None and cancel():
            break

        def _cb(d, tot, title='', _k=k):
            if progress is not None:
                progress(_k * 1000 + int(1000 * d / max(tot, 1)), n * 1000,
                         f'{name}: {title}')
        st = run_study(cfg, load_peak_kw, progress=_cb, cancel=cancel,
                       include=inc)
        if inc is not None:
            _conf = configured_sources(cfg)
            st['missing_sources'] = [SRC_LABEL[x] for x in SRC_LABEL
                                     if x in inc and x not in _conf]
        done.append((key, name, inc, st, components(cfg, load_peak_kw, inc)))
    pk = next((i for i, d in enumerate(done) if d[0] == 'both'), len(done) - 1)
    top = done[pk][3]
    items = [(d[1], d[3], d[4]) for d in done]
    top['version'] = 3
    top['system'] = done[pk][1]
    top['scenarios'] = [dict(
        key=d[0], name=d[1], primary=(i == pk),
        sources=([SRC_LABEL[x] for x in SRC_LABEL if x in d[2]]
                 if d[2] is not None else []),
        study=None if i == pk else d[3]) for i, d in enumerate(done)]
    top['comparison'] = compare_systems(cfg, items)
    top['assessment'] = pqa_assessment(cfg, cfg.get('tr_pqa'), items)
    if progress is not None:
        progress(n * 1000, n * 1000, '')
    return top


def scenario_studies(study: dict) -> list:
    """[(name, study)] seluruh sistem pada hasil run_scenarios (atau satu
    entri untuk hasil format lama)."""
    sc = study.get('scenarios') or []
    if not sc:
        return [(study.get('system', 'System'), study)]
    return [(s['name'], study if s.get('study') is None else s['study'])
            for s in sc]


def parameter_basis(cfg: dict) -> list:
    """[(parameter, nilai, satuan, dasar standar)] seluruh parameter Transient
    — untuk sheet/bab 'Parameter Basis'."""
    from ..config.parameters import SCHEMA
    rows = []
    for g, ps in SCHEMA.items():
        if not g.startswith('Transient'):
            continue
        for p in ps:
            if p.dtype == 'heading':
                rows.append([f'— {p.label} —', '', '', ''])
                continue
            v = cfg.get(p.key, p.default)
            if isinstance(v, float) and '%' in p.unit:
                v = round(v * 100.0, 4)
            rows.append([p.label, v, p.unit, p.basis or '—'])
    return rows


def source_table(comp) -> list:
    rows = []
    kv = comp['v_kv']
    ir = lambda kva: kva / (T.SQ3 * kv)
    m = comp['stg']
    if m is not None:
        rows.append(['STG', f'{m.s_kva:,.0f} kVA', f'{ir(m.s_kva):,.0f} A',
                     f"One-axis synchronous machine, E′q behind X′d with flux decay; "
                     f"PI AVR with reactive droop and V/Hz limiter; droop governor, "
                     f"valve and steam-chest lags, steam-limit ceiling",
                     f"H {m.h:g} s, X′d {m.xd1:g} pu (X″d {m.xd2:g}), Xd {m.xd:g} pu, "
                     f"T′d0 {m.td0:g} s; droop {m.droop * 100:g} % steady, "
                     f"{m.droop_t * 100:g} % transient with {m.t_reset:g} s reset; "
                     f"Tg {m.tg:g} s, Tt {m.tt:g} s"])
    g_ = comp.get('gtg')
    if g_ is not None:
        rows.append(['GTG', f'{g_.s_kva:,.0f} kVA', f'{ir(g_.s_kva):,.0f} A',
                     'As STG, gas-turbine governor (IEEE GAST structure: fuel-valve '
                     'and combustor/turbine lags, droop)',
                     f"H {g_.h:g} s, X′d {g_.xd1:g} pu (X″d {g_.xd2:g}); droop "
                     f"{g_.droop * 100:g} %, T1 {g_.tg:g} s, T2 {g_.tt:g} s"])
    for d in comp['degs']:
        rows.append([d.name, f'{d.s_kva:,.0f} kVA', f'{ir(d.s_kva):,.0f} A',
                     'As STG, diesel governor (actuator and engine lags)',
                     f"H {d.h:g} s, X′d {d.xd1:g} pu (X″d {d.xd2:g}); droop "
                     f"{d.droop * 100:g} % steady, {d.droop_t * 100:g} % transient; "
                     f"Tg {d.tg:g} s, Tt {d.tt:g} s"])
    p = comp['pcs']
    if p is not None:
        if p.mode == 'gfm':
            rows.append(['BESS PCS (VSG)', f'{p.s_kva:,.0f} kVA', f'{ir(p.s_kva):,.0f} A',
                         'Virtual rotor with inertia and P-f droop; virtual reactance; '
                         'Q-V droop voltage loop; time-dependent current limit',
                         f"H_v {p.h:g} s, droop {p.droop * 100:g} %, X_v {p.xv:g} pu, "
                         f"Q-V droop {p.qv_droop * 100:g} %; current limit "
                         f"{p.ilim_st * 100:.0f} % for {p.t_st:g} s, then "
                         f"{p.ilim_cont * 100:.0f} %"])
        else:
            rows.append(['BESS PCS (grid-following)', f'{p.s_kva:,.0f} kVA',
                         f'{ir(p.s_kva):,.0f} A',
                         'Controlled current source with fast frequency response '
                         '(droop + synthetic inertia) and Q-V droop; follows the '
                         'designated reference source',
                         f"reference source {p.gfl_ref.replace('GRID', 'Utility Grid')}; "
                         f"on loss: {'switch to grid-forming' if p.gfl_loss == 'gfm' else 'trip'} "
                         f"after {p.gfl_detect * 1000:.0f} ms; FFR droop "
                         f"{p.ffr_droop * 100:g} %, H_syn {p.ffr_h:g} s; "
                         f"current limit {p.ilim_cont * 100:.0f} %"])
    for key, lab in (('pv', 'PV inverter'), ('wtg', 'WTG')):
        b = comp[key]
        if b is not None:
            typ = '' if key == 'pv' else f' (IEC 61400-27-1 Type {b.wtg_type})'
            rows.append([lab + typ, f'{b.s_kva:,.0f} kVA', f'{ir(b.s_kva):,.0f} A',
                         'Controlled current source; reactive-current priority '
                         'during voltage dips; active-power recovery ramp; '
                         'voltage/frequency ride-through trip',
                         f"current limit {b.ilim * 100:.0f} %, LVRT gain K {b.k_lvrt:g}, "
                         f"recovery {b.recov:g} pu/s"])
    g = comp['grid']
    if g is not None:
        rows.append(['Utility Grid', f'S″k {g.sc_mva:g} MVA',
                     f'{g.sc_mva * 1000 / (T.SQ3 * kv):,.0f} A (fault)',
                     'Thevenin source at nominal frequency', f'X/R {g.xr:g}'])
    return rows


# ---------------------------------------------------------------- persyaratan
def requirements(study: dict) -> list:
    """Turunkan persyaratan desain dari hasil -> [(event, result, requirement)]."""
    out = []
    by = {}
    for c in study['cases']:
        by.setdefault(c['group'][0], []).append(c)
    pcs = study.get('pcs')
    f0 = study['f_nom']

    def worst(cs, key, fn=min):
        v = [c['metrics'].get(key) for c in cs if c['metrics'].get(key) is not None
             and np.isfinite(c['metrics'].get(key))]
        return fn(v) if v else None

    a = [c for c in by.get('A', []) if c['status'] != 'Error']
    if a:
        fails = [c for c in a if c['status'] == 'Fail']
        fmin = worst(a, 'f_min'); ro = worst(a, 'rocof', lambda v: max(v, key=abs))
        pj = worst(a, 'phase_jump_deg', lambda v: max(v, key=abs))
        res = (f"f min {fmin:.2f} Hz, RoCoF {ro:+.1f} Hz/s, phase jump {pj:+.1f}°"
               if None not in (fmin, ro, pj) else 'see case table')
        req = []
        if ro is not None and abs(ro) > 0.5:
            req.append(f"Frequency (81) and RoCoF relays: ≥ 100 ms measuring delay; "
                       f"RoCoF setting above {abs(ro) * 1.3:.1f} Hz/s")
        if pj is not None and abs(pj) > 2.0:
            req.append('Vector-shift (loss-of-mains) functions disabled or set above '
                       f'{abs(pj) * 1.5:.0f}°')
        if fails:
            req.append('Not carried: ' + '; '.join(
                f"{c['id']} ({', '.join(c['reasons'][:2])})" for c in fails)
                + ' — add fast load shedding or raise PCS rating / spinning reserve')
        if pcs and pcs['mode'] == 'gfm':
            pk = worst(a, 'pcs_ipk', max)
            if pk is not None:
                req.append(f"PCS takes the lost generation at once (peak {pk:.2f} pu): "
                           f"spinning-reserve power ≥ largest unit output")
        out.append(('Loss of generation', res, '; '.join(req) or '—'))
    b = by.get('B', [])
    if b:
        res = []
        for c in b:
            mm = c['metrics']
            tag = ('UFLS' if 'UFLS' in c['title'] else 'no shedding') + (
                ', steam-limited' if 'steam-limited' in c['title'] else '')
            res.append(f"{tag}: f min {mm.get('f_min', float('nan')):.2f} Hz, "
                       f"f end {mm.get('f_end', float('nan')):.2f} Hz"
                       + (' (blackout)' if mm.get('blackout') else ''))
        nosh = [c for c in b if 'no load shedding' in c['title']]
        if nosh and all(c['status'] == 'Pass' for c in nosh):
            req = 'Remaining sources carry the load without the BESS; no shedding needed'
        else:
            req = ('Under-frequency load shedding required when the BESS is lost '
                   'while sources have no margin: stages at '
                   f'{49.0 * f0 / 50:.1f}/{48.5 * f0 / 50:.1f}/{48.0 * f0 / 50:.1f} Hz '
                   '(15/15/20 %), 0.2 s; generator 81U set below the last stage; '
                   'DG-start alarm on PCS fault')
        out.append(('Loss of the BESS', '; '.join(res), req))
    cc = by.get('C', []) + by.get('D', [])
    cc = [c for c in cc if c['status'] != 'Ref']
    if cc:
        fmin = worst(cc, 'f_min'); pk = worst(cc, 'pcs_ipk', max)
        res = f"f min {fmin:.2f} Hz" + (f", PCS peak {pk:.2f} pu" if pk else '')
        lost = max((c['metrics'].get('lost_kw', 0.0) for c in cc), default=0.0)
        req = (f"Frequency-regulation / smoothing power ≥ {lost:,.0f} kW held on the PCS "
               "(Dispatch Strategy → Frequency Regulation, Renewable Smoothing)")
        if any(c['group'].startswith('D') for c in cc):
            req += '; freeze the EMS power-sharing reference while the STG is steam-limited'
        out.append(('Renewable loss / steam shortfall', res, req))
    e = by.get('E', [])
    if e:
        z = worst(e, 'damping'); hz = worst(e, 'mode_hz', max)
        if z is not None and hz is not None and np.isfinite(hz):
            ok = z >= 0.05
            out.append(('Load step',
                        f"mode {hz:.1f} Hz, damping ratio {z:.2f}",
                        ('Damped' if ok else 'POORLY DAMPED') +
                        ': keep virtual inertia H_v 2–4 s and X_v 0.10–0.15 pu; '
                        'final tuning at commissioning'))
    fm = by.get('F', [])
    if fm:
        act = [c for c in fm if c['status'] != 'Ref']
        vmin = worst(act, 'v_min'); pk = worst(act, 'pcs_ipk', max)
        req = []
        bad = [c for c in act if c['status'] == 'Fail']
        if vmin is not None:
            if bad:
                req.append('DOL start NOT viable in: ' + ', '.join(
                    c['title'].split('—')[-1].strip() for c in bad)
                    + ' — soft starter / VFD, or start with a generator online')
            elif vmin < 0.9:
                req.append(f"Undervoltage (27) elements below {min(vmin, 0.8):.2f} pu "
                           "or ≥ 5 s delay at 0.85 pu")
        if pk is not None and pk > 1.0:
            req.append(f"PCS short-time rating ≥ {pk:.2f} pu for the run-up time; "
                       "one large start at a time (EMS start permissive)")
        out.append(('Motor starting',
                    f"V min {vmin:.2f} pu" + (f", PCS peak {pk:.2f} pu" if pk else '')
                    if vmin is not None else 'see case table', '; '.join(req) or '—'))
    g = by.get('G', [])
    if g:
        edge = [c for c in g if 'window edge' in c['title']]
        bad = [c for c in g if 'out-of-phase' in c['title']]
        pk = worst(edge, 'pcs_ipk', max); pb = worst(bad, 'pcs_ipk', max)
        tl = worst(bad, 'pcs_t_lim', max)
        res = (f"window edge: PCS {pk:.2f} pu" if pk is not None else '') + (
            f"; out-of-phase: PCS {pb:.2f} pu, {tl:.2f} s at current limit"
            if pb is not None and tl is not None else '')
        out.append(('Synchronisation', res,
                    'ANSI 25 sync-check hard-wired in every close circuit '
                    '(Δf ≤ 0.1 Hz, ΔV ≤ 3 %, Δφ ≤ 10°; synchroniser aim Δφ ≤ 5°); '
                    'PCS phase-jump and current-limit ride-through specified'))
    h = by.get('H', [])
    if h:
        bo = next((c for c in h if c['id'] == 'H3'), None)
        al = next((c for c in h if c['id'] == 'H1'), None)
        res = []
        if al:
            res.append(f"all sources: {al['metrics'].get('i_fault_ka', 0):.1f} kA, "
                       f"V {al['metrics'].get('v_fault', 0):.2f} pu")
        if bo:
            res.append(f"BESS alone: {bo['metrics'].get('i_fault_ka', 0):.1f} kA")
        req = 'Generator 81U delay longer than the backup clearing time'
        out.append(('Feeder fault', '; '.join(res), req))
    if study.get('ik_weak', 0) > 0:
        no = [p['rating'] for p in study['protection'] if p['verdict'] != 'yes']
        req = []
        if no:
            req.append(f"Feeders ≥ {min(no)} A do not clear instantaneously at the "
                       f"minimum fault level ({study['weak_config']}): electronic LSIG "
                       f"trip units with a low-fault setting group, short-time pickup "
                       f"≤ {0.8 * study['ik_weak']:.1f} kA, 0.1–0.2 s, selected "
                       "automatically when no synchronous source is connected; "
                       "earth-fault element on the BESS incomer")
        if study['ik_all'] > study['icu_ka']:
            req.append(f"Maximum fault {study['ik_all']:.1f} kA exceeds switchgear "
                       f"rating {study['icu_ka']:.0f} kA")
        else:
            req.append(f"Switchgear {study['icu_ka']:.0f} kA adequate for "
                       f"{study['ik_all']:.1f} kA")
        out.append(('Short circuit & protection',
                    f"max {study['ik_all']:.1f} kA; min {study['ik_weak']:.1f} kA "
                    f"({study['weak_config']})", '; '.join(req)))
    i = by.get('I', [])
    if i:
        c = i[0]
        out.append(('Black start',
                    f"V min {c['metrics'].get('v_min', 0):.2f} pu, f min "
                    f"{c['metrics'].get('f_min', 0):.2f} Hz, PCS peak "
                    f"{c['metrics'].get('pcs_ipk', 0):.2f} pu",
                    'Black-start sequence: energise dead bus with soft voltage ramp, '
                    'restore essential feeders in steps ≤ 50 % of the block load; '
                    'hold the black-start energy reserve (Dispatch Strategy → Black Start)'))
    return out
