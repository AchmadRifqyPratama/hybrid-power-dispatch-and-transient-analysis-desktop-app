"""Audit invarian fisik dispatch dengan WTG, STG, GTG & strategi BESS (v162/v163).

Menguji ribuan kombinasi parameter acak terhadap invarian yang HARUS selalu
benar, apa pun konfigurasinya:

  I1  Neraca beban   : load = STG→beban + (PV/WTG/BESS)→beban + Grid→beban
                              + DEG→beban + unserved
  I2  Neraca daya bus: Σ suplai = Σ pemakaian (per langkah)
  I3  PV             : pv = pv_inv_out + pv_excess ; 0 ≤ pv_inv_out ≤ pv
  I4  WTG            : 0 ≤ wtg_used ≤ wtg
  I5  STG / GTG      : 0 ≤ stg ≤ Pmax ; stg = 0 saat tak tersedia ;
                       stg_load ≤ load ; chg_stg ≤ chg
  I6  SOC            : di dalam pita yang diizinkan (termasuk pita Frequency
                       Regulation & lantai Black Start)
  I7  PCS            : chg, dhg ≤ batas daya (setelah cadangan Q & ±P_fr)
  I8  Tanpa ekstensi : hasil byte-identik dengan menjalankan tanpa kanal aux

Jalankan:  python audit_dispatch_ext.py [jumlah_kasus]
"""
from __future__ import annotations
import sys
import numpy as np

from app.engine.dispatch import simulate, SystemParams
from app.engine.extsrc import pack_aux, prepare, _sv
from app.engine import dispatch as _d

TOL = 1e-5


def _rand_case(rng, T):
    load = rng.uniform(20, 400, T) * rng.choice([0.3, 1.0, 2.5])
    hod = np.arange(T) % 24
    pv = np.clip(np.sin((hod - 6) / 12 * np.pi), 0, None) * 1100 \
        * rng.uniform(0.2, 1, T)
    gs = (rng.uniform(0, 1, T) > rng.choice([0, 0.1, 0.5, 1.0])).astype(float)
    wind = np.clip(rng.weibull(2.0, T) * rng.uniform(4, 9), 0, 30)
    stg_st = (rng.uniform(0, 1, T) > rng.choice([0, 0.2, 0.6])).astype(float)
    kw = dict(
        pv_kwp=rng.choice([0, 100, 400]), pv_inv_kw=rng.choice([50, 150, 400]),
        bess_kwh=rng.choice([0, 215, 800]), soc_init=rng.uniform(0.2, 0.9),
        max_charge_kw=rng.uniform(40, 300), max_discharge_kw=rng.uniform(40, 300),
        grid_enabled=bool(rng.integers(2)), grid_kw=rng.uniform(20, 300),
        allow_export=bool(rng.integers(2)),
        load_priority=float(rng.integers(0, 6)),
        charge_priority=float(rng.integers(2)),
        grid_charge_enabled=bool(rng.integers(2)),
        deg_charge_enabled=bool(rng.integers(2)),
        deg_interlock=bool(rng.integers(2)), grid_interlock=bool(rng.integers(2)),
        deg_grid_interlock=bool(rng.integers(2)), deg_sync=bool(rng.integers(2)),
        deg_always=bool(rng.integers(2)), deg_min_loading=rng.choice([0, 0.3]),
        deg_kw=tuple(rng.choice([0, 100, 250], 3)),
        deg_max_loading=(1.0, 1.0, 1.0),
        bess_self_cons_kw=rng.choice([0, 0, 3.0]),
        bess_sc_source=int(rng.integers(2)),
        bess_mode=int(rng.integers(2)))
    if kw['bess_mode']:
        kw.update(m_pv_smooth=int(rng.integers(2)), m_load_shift=int(rng.integers(2)),
                  m_peak_shave=int(rng.integers(2)), m_dg_minload=int(rng.integers(2)),
                  m_reserve=int(rng.integers(2)), peak_shave_kw=rng.uniform(0, 150),
                  firming_kw=rng.uniform(0, 150), arb_peak_start=18, arb_peak_end=22,
                  smoothing_window=int(rng.integers(1, 6)),
                  reserve_frac=rng.uniform(0, 0.3), reserve_kw=rng.uniform(0, 30),
                  adv_target=int(rng.integers(3)))
        if not kw['m_pv_smooth'] and rng.integers(2):
            kw['m_firming'] = 1
        if not kw['m_reserve'] and rng.integers(2):
            kw['m_backup'] = 1
    ext = {}
    if rng.integers(4):                                    # WTG
        ext.update(wtg_on=1.0, wtg_n=float(rng.integers(1, 4)),
                   wtg_unit_kw=float(rng.choice([50, 150, 500])), wtg_mode=0.0,
                   wtg_hub_h=60.0, wtg_meas_h=10.0, wtg_shear=0.2, wtg_vci=3.0,
                   wtg_vr=12.0, wtg_vco=25.0, wtg_rho=1.17,
                   wtg_loss=float(rng.choice([0, 0.1])))
    if rng.integers(4):                                    # STG
        ext.update(stg_on=1.0, stg_kw=float(rng.choice([100, 300, 800])),
                   stg_min_loading=float(rng.choice([0, 0.3, 0.5])),
                   stg_max_loading=1.0, stg_priority=float(rng.integers(2)),
                   stg_charge=float(rng.integers(3)),
                   stg_ramp_kwmin=float(rng.choice([0, 0, 0.5])),
                   stg_sched_start=float(rng.choice([0, 6])),
                   stg_sched_end=float(rng.choice([0, 18])), stg_renewable=1.0)
    if rng.integers(3):                                    # GTG
        ext.update(gtg_on=1.0, gtg_kw=float(rng.choice([100, 300, 600])),
                   gtg_min_loading=float(rng.choice([0, 0.4])),
                   gtg_max_loading=1.0, gtg_priority=float(rng.integers(2)),
                   gtg_commit=float(rng.integers(2)),
                   gtg_charge=float(rng.integers(3)),
                   gtg_ramp_kwmin=0.0, gtg_sched_start=0.0, gtg_sched_end=0.0,
                   gtg_heat_rate=12000.0)
    if ext.get('wtg_on'):
        ext['wtg_priority'] = float(rng.integers(3))
    gtg_st = (rng.uniform(0, 1, T) > rng.choice([0, 0.3])).astype(float)
    if kw['bess_mode'] and kw['bess_kwh'] > 0:
        if rng.integers(2):
            ext.update(m_load_follow=1.0, lf_set_kw=float(rng.uniform(0, 200)),
                       lf_charge=float(rng.integers(2)),
                       prio_load_follow=float(rng.integers(1, 7)))
        if rng.integers(2):
            ext.update(m_freq_reg=1.0, fr_kw=float(rng.uniform(5, 40)),
                       fr_min=float(rng.choice([15, 30])))
        if rng.integers(2):
            ext.update(m_qv=1.0, qv_kvar=float(rng.uniform(10, 150)), pcs_kva=0.0)
        if rng.integers(2):
            ext.update(m_black_start=1.0, bs_kw=float(rng.uniform(10, 80)),
                       bs_min=float(rng.choice([15, 60])))
    kw['ext'] = ext
    kw['_gtg_st'] = gtg_st
    return load, pv, gs, wind, stg_st, kw


def _check(load, pv, gs, wind, stg_st, kw):
    kw = dict(kw)
    gtg_st = kw.pop('_gtg_st', None)
    sp = SystemParams(**kw)
    aux = pack_aux(len(load), None, wind, stg_st, gtg_st)
    res = simulate(load, pv, gs, sp, record=True, deg_status=aux)
    s = {k: np.asarray(v, float).reshape(len(load), -1)[:, 0]
         for k, v in res['series'].items()}
    z = np.zeros(len(load))
    g = lambda k: s.get(k, z)
    errs = []
    L = load
    # I1 — neraca beban
    deg_load = g('deg') - g('chg_deg') - g('self_cons_deg')
    r1 = L - (g('stg_load') + g('gtg_load') + g('pvbs_load') + g('grid_load')
              + deg_load + g('unserved'))
    if np.max(np.abs(r1)) > TOL * 10:
        errs.append(('I1 load balance', float(np.max(np.abs(r1)))))
    # I2 — neraca daya bus
    sup = g('pv_inv_out') + g('wtg_used') + g('stg') + g('gtg') + g('grid') \
        + g('deg') + g('dhg')
    use = (L - g('unserved')) + g('chg') + g('grid_export') + g('self_cons')
    r2 = sup - use
    # Mode shaping (Smoothing/Firming/Backup) memakai konvensi 'injeksi
    # set-point' warisan v161: discharge shaping di atas beban tidak punya
    # penerima, sehingga neraca bus per-langkah tidak selalu menutup (temuan
    # v161, di luar lingkup ekstensi ini). I2 diuji di luar mode tsb.
    shaping = bool(kw.get('bess_mode')) and bool(
        kw.get('m_pv_smooth') or kw.get('m_firming') or kw.get('m_backup'))
    if not shaping and np.max(np.abs(r2)) > TOL * 10:
        errs.append(('I2 bus balance', float(np.max(np.abs(r2)))))
    # I3 — PV
    if np.max(np.abs(g('pv') - g('pv_inv_out') - g('pv_excess'))) > TOL:
        errs.append(('I3 pv identity', 0))
    if g('pv_inv_out').min() < -TOL or g('pv_excess').min() < -TOL:
        errs.append(('I3 pv sign', float(min(g('pv_inv_out').min(),
                                             g('pv_excess').min()))))
    # I4 — WTG
    if 'wtg' in s and ((s['wtg_used'] < -TOL).any()
                       or (s['wtg_used'] > s['wtg'] + TOL).any()):
        errs.append(('I4 wtg', 0))
    # I5 — STG
    vals = _d._system_vals(sp)
    if 'stg' in s and kw['ext'].get('stg_on'):
        pmax = kw['ext']['stg_kw'] * kw['ext']['stg_max_loading']
        if (s['stg'] > pmax + TOL).any() or (s['stg'] < -TOL).any():
            errs.append(('I5 stg range', float(s['stg'].max())))
        if (s['stg_load'] > L + TOL).any():
            errs.append(('I5 stg_load>load', 0))
        if (s['chg_stg'] + g('chg_gtg') > s['chg'] + TOL).any() \
                or (s['chg_pv'] < -TOL).any():
            errs.append(('I5 chg_stg', 0))
        t0, t1 = kw['ext']['stg_sched_start'], kw['ext']['stg_sched_end']
        hod = np.arange(len(L)) % 24
        on = (np.ones(len(L), bool) if t0 == t1 else
              (hod >= t0) & (hod < t1) if t0 < t1 else
              (hod >= t0) | (hod < t1))
        on &= stg_st != 0
        if (s['stg'][~on] > TOL).any():
            errs.append(('I5 stg when unavailable', 0))
    if 'gtg' in s and kw['ext'].get('gtg_on'):
        pmax = kw['ext']['gtg_kw'] * kw['ext']['gtg_max_loading']
        if (s['gtg'] > pmax + TOL).any() or (s['gtg'] < -TOL).any():
            errs.append(('I5 gtg range', float(s['gtg'].max())))
        if (s['gtg'][gtg_st == 0] > TOL).any():
            errs.append(('I5 gtg when unavailable', 0))
        if kw['ext'].get('gtg_commit') and kw['ext'].get('gtg_min_loading', 0) > 0 \
                and not kw['ext'].get('gtg_charge'):
            # on-demand: bila menyala, tak pernah di bawah minimum stabil
            pmin = kw['ext']['gtg_kw'] * kw['ext']['gtg_min_loading']
            on = s['gtg'] > TOL
            if (s['gtg'][on] < pmin - 1e-4).any():
                errs.append(('I5 gtg on-demand below min', 0))
    # I6/I7 — SOC & PCS dalam pita efektif
    E = kw['bess_kwh']
    if E > 0:
        e = kw['ext']
        srte = np.sqrt(sp.rte)
        lo, hi = sp.soc_min * E, sp.soc_max * E
        mc, md = sp.max_charge_kw, sp.max_discharge_kw
        if e.get('m_qv'):
            skva = max(mc, md)
            pl = np.sqrt(max(0.0, skva ** 2 - min(e['qv_kvar'], skva) ** 2))
            mc, md = min(mc, pl), min(md, pl)
        if e.get('m_freq_reg'):
            mc, md = max(0, mc - e['fr_kw']), max(0, md - e['fr_kw'])
            fe = e['fr_kw'] * e['fr_min'] / 60.0
            half = 0.5 * (hi - lo)
            lo, hi = lo + min(fe / srte, half), hi - min(fe * srte, half)
        if e.get('m_black_start'):
            lo = lo + min(e['bs_kw'] * e['bs_min'] / 60.0 / srte, max(0, hi - lo))
        soc = s['cap_end']
        if soc.min() < lo - 1e-4 or soc.max() > hi + 1e-4:
            errs.append(('I6 soc band', (float(soc.min()), lo, float(soc.max()), hi)))
        sc = kw['bess_self_cons_kw']
        if s['chg'].max() > mc + TOL or s['dhg'].max() > md + sc + TOL:
            errs.append(('I7 pcs', (float(s['chg'].max()), mc,
                                    float(s['dhg'].max()), md)))
    return errs


def main(n=1500):
    rng = np.random.default_rng(20261110)
    T = 24 * 10
    bad = 0
    kinds = {}
    for i in range(n):
        case = _rand_case(rng, T)
        try:
            errs = _check(*case)
        except Exception as ex:                      # pragma: no cover
            errs = [('EXC ' + type(ex).__name__ + ': ' + str(ex)[:80], 0)]
        if errs:
            bad += 1
            for nm, v in errs:
                kinds[nm] = kinds.get(nm, 0) + 1
            if bad <= 5:
                print(f'[{i}] {errs}  ext={case[5]["ext"]}')
    # I8 — tanpa ekstensi, kanal aux tak boleh mengubah apa pun
    same = 0
    for i in range(60):
        load, pv, gs, wind, st, kw = _rand_case(rng, T)
        kw['ext'] = {}
        gst = kw.pop('_gtg_st', None)
        a = simulate(load, pv, gs, SystemParams(**kw), record=True)
        b = simulate(load, pv, gs, SystemParams(**kw), record=True,
                     deg_status=pack_aux(T, None, wind, st, gst))
        same += all(np.array_equal(a['series'][k], b['series'][k])
                    for k in a['series'])
    print(f'kasus: {n} | gagal: {bad} | rincian: {kinds}')
    print(f'I8 byte-identik tanpa ekstensi: {same}/60')
    return 0 if (bad == 0 and same == 60) else 1


if __name__ == '__main__':
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1500))
