"""Transient Analysis — simulator RMS (fasor) satu-bus untuk hybrid power plant.

LINGKUP & VALIDITAS
    Model fasor urutan-positif, satu bus (seluruh sumber & beban pada busbar
    utama), langkah 1 ms. Berlaku untuk dinamika elektromekanik & tegangan
    ~10 ms hingga beberapa menit: frekuensi (nadir, RoCoF), tegangan, pembagian
    daya, batas arus konverter, percepatan motor, sinkronisasi, osilasi antar
    sumber. TIDAK mencakup gejala sub-siklus (offset DC arus gangguan/inrush,
    harmonik, switching) — itu ranah studi EMT dengan model vendor.

MODEL (acuan standar)
    Mesin sinkron (STG, DEG) — IEEE Std 1110: model satu-sumbu, EMF transien
        E′q di belakang X′d dengan peluruhan fluks (T′d0); untuk kasus siklus
        pertama (gangguan, penutupan) dipakai X″d.
        AVR — IEEE Std 421.5 (disederhanakan): PI + lag eksiter, droop reaktif,
        pembatas V/Hz.
        Governor/turbin — IEEE PES-TR1 (TGOV1/DEGOV disederhanakan): droop R,
        lag aktuator/katup Tg, lag steam-chest/mesin Tt, plafon daya (steam
        limit) yang dapat berubah terhadap waktu (boiler pressure drop).
    BESS PCS grid-forming (VSG) — rotor virtual (H, droop P-f), reaktansi
        virtual, droop Q-V, batas arus bergantung waktu; trip bila tertahan di
        batas arus dengan tegangan runtuh. Opsi grid-following + fast
        frequency response.
    PV inverter & WTG konverter (IEC 61400-27-1 Type 3/4, disederhanakan ke
        sumber arus terkendali): prioritas arus reaktif saat LVRT (gain K),
        batas arus, laju pemulihan daya aktif, proteksi ride-through
        tegangan/frekuensi (gaya IEEE 2800).
    Utility Grid — sumber Thevenin (tingkat hubung singkat & X/R, IEC 60909).
    Beban statis — P ∝ V^kpv·(1 + kpf·Δf), Q ∝ V^kqv; impedansi konstan di
        bawah 0,7 pu.
    Motor induksi — rangkaian ekivalen (rotor deep-bar: R_r bergantung slip)
        + dinamika mekanik (torsi beban kuadratik).

Semua besaran internal per-unit pada S_base; sudut relatif terhadap kerangka
sinkron pada frekuensi nominal.
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field

import numpy as np

SQ3 = math.sqrt(3.0)


# ---------------------------------------------------------------- elemen
@dataclass
class Machine:
    """Generator sinkron (STG / DEG). Reaktansi pu pada rating mesin."""
    name: str
    kind: str = 'DEG'                 # 'STG' | 'GTG' | 'DEG'
    s_kva: float = 365.0
    h: float = 1.0                    # MW·s/MVA
    xd1: float = 0.20                 # X′d
    xd2: float = 0.12                 # X″d
    xd: float = 1.8
    td0: float = 3.0                  # T′d0
    droop: float = 0.03
    # Droop transien (kompensasi governor, mis. Woodward UG): penguatan
    # sesaat = 1/droop_t, kembali ke 1/droop dgn waktu reset t_reset.
    # 0 = tanpa kompensasi (droop murni).
    droop_t: float = 0.0
    t_reset: float = 5.0
    tg: float = 0.05
    tt: float = 0.2
    pmax_kw: float = 0.0              # plafon turbin (0 = s_kva × pf_rated)
    pf_rated: float = 0.8
    p0_kw: float = 0.0
    online: bool = True
    # AVR
    avr_kp: float = 20.0
    avr_ki: float = 40.0
    avr_te: float = 0.2
    avr_qdroop: float = 0.04
    efd_max: float = 5.0
    vhz_knee: float = 0.95            # pu frekuensi
    vhz_slope: float = 1.9
    damping: float = 1.0            # koefisien torsi peredam (belitan damper), pu


@dataclass
class Pcs:
    """BESS PCS. mode 'gfm' (VSG) atau 'gfl' (grid-following + FFR)."""
    name: str = 'BESS'
    s_kva: float = 1000.0
    mode: str = 'gfm'
    h: float = 3.0
    droop: float = 0.01
    xv: float = 0.10
    qv_droop: float = 0.04
    ilim_st: float = 1.3
    t_st: float = 10.0
    ilim_cont: float = 1.1
    p0_kw: float = 0.0
    online: bool = True
    charge_limit_kw: float | None = None    # batas daya charge (None = rating)
    t_uv_trip: float = 1.0                  # s di batas arus & V < 0,5 pu
    kv: float = 4.0                         # 1/s — gain integrator loop tegangan
    ffr_droop: float = 0.02                 # GFL: droop FFR
    ffr_h: float = 3.0                      # GFL: inersia sintetis
    # GFL: sumber yang dianggap "grid" (acuan PLL & izin operasi):
    # 'Auto' (pembentuk tegangan mana pun) | 'GRID' | 'STG' | 'GTG' | 'DEG'
    gfl_ref: str = 'Auto'
    gfl_loss: str = 'trip'                  # 'trip' | 'gfm' (beralih ke VSG)
    gfl_detect: float = 0.15                # s deteksi kehilangan acuan


@dataclass
class Ibr:
    """PV inverter / WTG konverter (sumber arus terkendali)."""
    name: str = 'PV'
    s_kva: float = 100.0
    p0_kw: float = 0.0
    ilim: float = 1.1
    k_lvrt: float = 2.0
    recov: float = 2.0                # pu/s pemulihan daya aktif
    tp: float = 0.1                   # lag kendali daya
    wtg_type: int = 4                 # 3 = DFIG, 4 = full converter (WTG)
    online: bool = True


@dataclass
class GridSrc:
    sc_mva: float = 10.0
    xr: float = 5.0
    p0_kw: float = 0.0
    online: bool = True


@dataclass
class Motor:
    name: str = 'Motor'
    p_kw: float = 100.0               # daya poros nominal
    lrc: float = 6.5                  # arus rotor terkunci × FLC
    pf_start: float = 0.3
    h: float = 1.0
    eff: float = 0.93
    pf: float = 0.86
    s_rated: float = 0.015
    load_frac: float = 0.8            # torsi beban / torsi nominal saat berjalan
    start_frac: float = 0.4           # idem saat run-up (damper tertutup)
    running: bool = True


@dataclass
class System:
    f_nom: float = 50.0
    v_kv: float = 0.4
    s_base: float = 1000.0
    load_kw: float = 500.0            # beban STATIS (di luar motor)
    load_pf: float = 0.9
    kpv: float = 1.0
    kpf: float = 1.0
    kqv: float = 2.0
    machines: list = field(default_factory=list)
    pcs: Pcs | None = None
    ibrs: list = field(default_factory=list)
    grid: GridSrc | None = None
    motors: list = field(default_factory=list)
    use_subtransient: bool = False

    @property
    def i_base(self) -> float:        # A
        return self.s_base / (SQ3 * self.v_kv)


# ---------------------------------------------------------------- motor
class _MotorState:
    def __init__(self, m: Motor, s_base: float):
        self.m = m
        self.s_m = m.p_kw / max(m.eff * m.pf, 1e-6)        # kVA dasar motor
        self.ratio = self.s_m / s_base
        zlr = 1.0 / max(m.lrc, 1.0)
        rlr = zlr * m.pf_start
        xlr = math.sqrt(max(zlr * zlr - rlr * rlr, 1e-8))
        self.rs = min(0.03, 0.4 * rlr)
        self.rr_start = max(rlr - self.rs, 1e-3)
        self.rr_run = max(m.s_rated * 1.0, 1e-3)
        self.xs = 0.5 * xlr
        self.xr = 0.5 * xlr
        self.xm = 3.0
        self.connected = bool(m.running)
        self.slip = 1.0
        self.t_rated = self.torque(1.0, m.s_rated)[0]
        self.frac = m.load_frac
        if self.connected:
            self.slip = self._steady_slip()
        self.t_start = None
        self.t_up = None

    def rr(self, s):                                       # rotor deep-bar
        s = min(max(s, 0.0), 1.0)
        return self.rr_run + (self.rr_start - self.rr_run) * s

    def y(self, s):
        s = max(s, 1e-4)
        zr = complex(self.rr(s) / s, self.xr)
        zm = complex(0.0, self.xm)
        zp = zm * zr / (zm + zr)
        return 1.0 / (complex(self.rs, self.xs) + zp)

    def torque(self, vmag, s):
        """(Te pu-motor, |I_stator| pu-motor) pada tegangan |V| & slip s."""
        s = max(s, 1e-4)
        zr = complex(self.rr(s) / s, self.xr)
        zm = complex(0.0, self.xm)
        zp = zm * zr / (zm + zr)
        i_s = vmag / (complex(self.rs, self.xs) + zp)
        i_r = i_s * zp / zr
        return abs(i_r) ** 2 * self.rr(s) / s, abs(i_s)

    def t_load(self, s):
        w = 1.0 - s
        return self.frac * self.t_rated * (0.1 + 0.9 * w * w)

    def _steady_slip(self):
        lo, hi = 1e-4, 0.2
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if self.torque(1.0, mid)[0] < self.t_load(mid):
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)


# ---------------------------------------------------------------- simulator
class Simulator:
    """Integrasi waktu sistem satu-bus. Pakai run(events, t_end)."""

    def __init__(self, sysdef: System, dt: float = 0.001):
        self.S = sysdef
        self.dt = float(dt)
        self.w0 = 2.0 * math.pi * sysdef.f_nom
        self._init()

    # -- inisialisasi kondisi tunak pada V = 1∠0 -----------------------
    def _init(self):
        S = self.S
        sb = S.s_base
        self.V = complex(1.0, 0.0)
        self.t = 0.0
        self.fault_y = 0j
        self.blackout = False
        self.log = []
        # beban statis
        self.pl0 = S.load_kw / sb
        tanphi = math.tan(math.acos(min(max(S.load_pf, 0.1), 1.0)))
        self.ql0 = self.pl0 * tanphi
        self.mot = [_MotorState(m, sb) for m in S.motors]
        # total beban pada V=1
        s_mot = 0j
        for ms in self.mot:
            if ms.connected:
                s_mot += (ms.y(ms.slip) * ms.ratio).conjugate()
        p_load = self.pl0 + s_mot.real
        q_load = self.ql0 + s_mot.imag
        # sumber arus (IBR; PCS GFL)
        self.ibr = []
        for b in S.ibrs:
            self.ibr.append(dict(d=b, r=b.s_kva / sb, p=b.p0_kw / sb,
                                 pav=b.p0_kw / sb, pav_tgt=b.p0_kw / sb,
                                 pav_rate=0.0, on=b.online and b.s_kva > 0,
                                 t_lv1=0.0, t_lv2=0.0, t_f=0.0, lvrt=False,
                                 i=0j, ffr=False))
        pcs = S.pcs
        self.pcs = None
        gfl = pcs is not None and pcs.online and pcs.mode != 'gfm'
        if gfl:
            self.ibr.append(dict(d=pcs, r=pcs.s_kva / sb, p=pcs.p0_kw / sb,
                                 pav=pcs.p0_kw / sb, pav_tgt=pcs.p0_kw / sb,
                                 pav_rate=0.0, on=True, t_lv1=0.0, t_lv2=0.0,
                                 t_f=0.0, lvrt=False, i=0j, ffr=True,
                                 iq=0.0, t_ref=0.0))
        p_ibr = sum(b['p'] for b in self.ibr if b['on'])
        # sumber tegangan
        vs = []
        for m in S.machines:
            if m.online:
                vs.append(('m', m, m.s_kva / sb, m.p0_kw / sb))
        if pcs is not None and pcs.online and pcs.mode == 'gfm':
            vs.append(('v', pcs, pcs.s_kva / sb, pcs.p0_kw / sb))
        g = S.grid if (S.grid is not None and S.grid.online) else None
        # slack: grid > VSG > mesin terbesar
        p_sched = sum(x[3] for x in vs) + (g.p0_kw / sb if g else 0.0) + p_ibr
        mismatch = p_load - p_sched
        self.grid = None
        if g is not None:
            zg = sb / (g.sc_mva * 1000.0)
            rg = zg / math.sqrt(1.0 + g.xr ** 2)
            self.grid = dict(d=g, z=complex(rg, rg * g.xr), on=True,
                             p=g.p0_kw / sb + mismatch, delta=0.0, e=1.0,
                             w=1.0)
            mismatch = 0.0
        elif vs:
            k = next((i for i, x in enumerate(vs) if x[0] == 'v'), None)
            if k is None:
                k = max(range(len(vs)), key=lambda i: vs[i][2])
            vs[k] = (vs[k][0], vs[k][1], vs[k][2], vs[k][3] + mismatch)
            mismatch = 0.0
        # pembagian Q: sebanding rating di antara sumber tegangan (grid = sisa)
        r_tot = sum(x[2] for x in vs)
        self.mach, self.vsg = [], None
        q_rest = q_load
        if g is not None:
            q_vs = 0.0           # mesin/VSG paralel grid: pf 1 (grid memasok Q)
        else:
            q_vs = q_rest
        for kind, d, r, p in vs:
            q = q_vs * (r / r_tot) if r_tot > 0 else 0.0
            i = complex(p, -q)                    # conj(S/V), V = 1
            if kind == 'm':
                x = (d.xd2 if S.use_subtransient else d.xd1) / r
                e = 1.0 + 1j * x * i
                delta = cmath.phase(e)
                it = i * cmath.exp(-1j * delta)
                idm = -it.imag / r
                eq = abs(e)
                efd = eq + (d.xd - d.xd1) * idm
                pmax = (d.pmax_kw if d.pmax_kw > 0 else d.s_kva * d.pf_rated) / sb
                self.mach.append(dict(
                    d=d, r=r, x=x, on=True, delta=delta, w=1.0, eq=eq,
                    efd=efd, xi=efd, vref=1.0 + d.avr_qdroop * (q / r),
                    pm=p, pv=p, pref=p, ceil=pmax, ceil_tgt=pmax, ceil_rate=0.0,
                    pmax=pmax, pref_tgt=p, pref_rate=0.0, i=i, pe=p, qe=q,
                    xg=0.0,
                    ipk=abs(i), ppk=p, t_rev=0.0, rev=False))
            else:
                x = d.xv / r
                e = 1.0 + 1j * x * i
                self.vsg = dict(
                    d=d, r=r, x=x, on=True, delta=cmath.phase(e), w=1.0,
                    e=abs(e), e0=abs(e), q0=q, vref=1.0, pset=p, wset=1.0,
                    bias=0.0,
                    lim=False, t_over=0.0, t_uv=0.0, i=i, pe=p, qe=q,
                    ipk=abs(i) / r, t_lim=0.0, tripped=False)
        if self.grid is not None:
            gi = complex(self.grid['p'], -q_rest)
            eg = 1.0 + self.grid['z'] * gi
            self.grid['e'] = abs(eg)
            self.grid['delta'] = cmath.phase(eg)
            self.grid['i'] = gi
        # status frekuensi
        self.f = S.f_nom
        self.f_pll = S.f_nom
        self._vprev = self.V
        self.shed_auto = []
        self._rec = None

    # -- penyelesaian jaringan ----------------------------------------
    def _yload(self, vm, dfpu):
        S = self.S
        v = vm if vm > 0.7 else 0.7
        p = self.pl0 * v ** (S.kpv - 2.0) * max(0.0, 1.0 + S.kpf * dfpu)
        q = self.ql0 * v ** (S.kqv - 2.0)
        return complex(p, -q)

    def _solve(self):
        S = self.S
        ysum = self.fault_y
        inor = 0j
        n_vs = 0
        for m in self.mach:
            if m['on']:
                y = 1.0 / (1j * m['x'])
                ysum += y
                inor += cmath.rect(m['eq'], m['delta']) * y
                n_vs += 1
        if self.grid is not None and self.grid['on']:
            y = 1.0 / self.grid['z']
            ysum += y
            inor += cmath.rect(self.grid['e'], self.grid['delta']) * y
            n_vs += 1
        for ms in self.mot:
            if ms.connected:
                ysum += ms.y(ms.slip) * ms.ratio
        vsg = self.vsg
        ev = None
        if vsg is not None and vsg['on']:
            ev = cmath.rect(vsg['e'], vsg['delta'])
            yv = 1.0 / (1j * vsg['x'])
            n_vs += 1
        if n_vs == 0:
            # Tanpa pembentuk tegangan. Bila PCS grid-following sedang dalam
            # jeda deteksi sebelum beralih ke grid-forming, bus ditopang
            # sumber-sumber arus (tegangan mengikuti neraca arus/beban).
            if not self._gfm_pending():
                self.V = 0j
                return
            V = self.V if abs(self.V) > 1e-3 else complex(1.0, 0.0)
            dfpu = (self.f - S.f_nom) / S.f_nom
            for _ in range(6):
                ii = 0j
                for b in self.ibr:
                    if b['on']:
                        ii += self._ibr_current(b, V)
                den = ysum + self._yload(abs(V), dfpu)
                Vn = ii / den if abs(den) > 1e-9 else 0j
                V = 0.5 * V + 0.5 * Vn
            self.V = V
            return
        V = self.V if abs(self.V) > 1e-6 else complex(1e-3, 0.0)
        dfpu = (self.f - S.f_nom) / S.f_nom
        ilim = None
        if ev is not None:
            d = vsg['d']
            ilim = (d.ilim_st if vsg['t_over'] < d.t_st else d.ilim_cont) * vsg['r']
        def _iterate(V, limited):
            for _ in range(8):
                vm = abs(V)
                yl = self._yload(vm, dfpu)
                ii = 0j
                for b in self.ibr:
                    if b['on']:
                        ii += self._ibr_current(b, V)
                num = inor + ii
                den = ysum + yl
                if ev is not None:
                    if limited:
                        iv = (ev - V) * yv
                        a = abs(iv)
                        num += (ilim * iv / a) if a > 1e-12 else 0j
                    else:
                        num += ev * yv
                        den += yv
                Vn = num / den if abs(den) > 1e-9 else 0j
                if abs(Vn - V) < 1e-7:
                    return Vn
                V = 0.5 * V + 0.5 * Vn if limited else Vn
            return V

        # 1) coba solusi TANPA batas arus (VSG = sumber tegangan). Bila arus
        #    VSG melampaui batas -> 2) VSG menjadi sumber arus pada batasnya.
        Vu = _iterate(V, False)
        if ev is not None and abs((ev - Vu) * yv) > ilim:
            Vl = _iterate(V if vsg['lim'] else Vu, True)
            # lepas dari batas bila referensi arus internal (E − V)/X_v pada
            # tegangan bus AKTUAL sudah kembali di bawah batas
            if vsg['lim'] and abs((ev - Vl) * yv) <= 0.98 * ilim:
                V = Vu
                vsg['lim'] = False
            else:
                V = Vl
                vsg['lim'] = True
        else:
            V = Vu
            if ev is not None:
                vsg['lim'] = False
        self.V = V

    def _ibr_current(self, b, V):
        d = b['d']
        vm = abs(V)
        r = b['r']
        if vm < 1e-3:
            b['i'] = 0j
            return 0j
        ilim = (d.ilim if not b['ffr'] else d.ilim_cont) * r
        iq = 0.0
        if vm < 0.9 and not b['ffr']:
            iq = min(d.k_lvrt * (0.9 - vm) * r, ilim)
        elif b['ffr']:
            # PCS grid-following: dukungan tegangan droop Q-V (state b['iq'],
            # diperbarui di _step dgn lag 50 ms) + prioritas reaktif saat LVRT
            iq = b.get('iq', 0.0)
            if vm < 0.9:
                iq = max(iq, 2.0 * (0.9 - vm) * r)
            iq = max(-ilim, min(ilim, iq))
        idmax = math.sqrt(max(ilim * ilim - iq * iq, 0.0))
        if not b['ffr']:
            iq = max(iq, 0.0)
        idc = b['p'] / vm
        idc = max(-idmax, min(idmax, idc))
        ph = V / vm
        i = complex(idc, -iq) * ph
        b['i'] = i
        return i

    # -- satu langkah --------------------------------------------------
    def _step(self):
        S, dt, w0 = self.S, self.dt, self.w0
        self._solve()
        V = self.V
        vm = abs(V)
        # frekuensi: COI sumber pembentuk tegangan (pulau) / PLL (paralel grid)
        msum, wsum = 0.0, 0.0
        for m in self.mach:
            if m['on']:
                M = 2.0 * m['d'].h * m['r']
                msum += M
                wsum += M * m['w']
        vsg = self.vsg
        if vsg is not None and vsg['on']:
            M = 2.0 * vsg['d'].h * vsg['r']
            msum += M
            wsum += M * vsg['w']
        if vm > 0.05 and abs(self._vprev) > 0.05:
            dth = cmath.phase(V * self._vprev.conjugate())
            self.f_pll += (S.f_nom + dth / (2 * math.pi * dt) - self.f_pll) * dt / 0.05
        self._vprev = V
        grid_on = self.grid is not None and self.grid['on']
        if grid_on or msum <= 0:
            self.f = self.f_pll
        else:
            self.f = S.f_nom * wsum / msum
            self.f_pll = self.f
        fpu = self.f / S.f_nom

        # --- mesin sinkron ---
        for m in self.mach:
            d = m['d']
            if not m['on']:
                continue
            e = cmath.rect(m['eq'], m['delta'])
            i = (e - V) / (1j * m['x'])
            s = V * i.conjugate()
            m['i'], m['pe'], m['qe'] = i, s.real, s.imag
            m['ipk'] = max(m['ipk'], abs(i))
            m['ppk'] = max(m['ppk'], abs(s.real))
            r = m['r']
            # governor
            if m['pref_rate'] != 0.0:
                stp = m['pref_rate'] * dt
                if abs(m['pref_tgt'] - m['pref']) <= abs(stp):
                    m['pref'] = m['pref_tgt']; m['pref_rate'] = 0.0
                else:
                    m['pref'] += stp
            if m['ceil_rate'] != 0.0:
                stp = m['ceil_rate'] * dt
                if abs(m['ceil_tgt'] - m['ceil']) <= abs(stp):
                    m['ceil'] = m['ceil_tgt']; m['ceil_rate'] = 0.0
                else:
                    m['ceil'] += stp
            if d.droop > 0:
                ew = 1.0 - m['w']
                if d.droop_t > d.droop and d.t_reset > 0:
                    # lag-lead (1 + sTr)/(1 + sTr·Rt/R): transien 1/Rt, tunak 1/R
                    t2 = d.t_reset * d.droop_t / d.droop
                    m['xg'] += (ew - m['xg']) * dt / t2
                    ew = m['xg'] + (d.t_reset / t2) * (ew - m['xg'])
                cmd = m['pref'] + ew / d.droop * r
            else:
                cmd = m['pref']
            cmd = min(max(cmd, 0.0), m['pmax'])
            m['pv'] += (cmd - m['pv']) * dt / max(d.tg, dt)
            m['pm'] += (min(m['pv'], m['ceil']) - m['pm']) * dt / max(d.tt, dt)
            # ayunan
            M = 2.0 * d.h * r
            m['w'] += (m['pm'] - m['pe'] - d.damping * r * (m['w'] - fpu)) / M * dt
            m['delta'] += w0 * (m['w'] - 1.0) * dt
            # fluks & AVR
            it = i * cmath.exp(-1j * m['delta'])
            idm = -it.imag / r
            vhz = 1.0 - d.vhz_slope * max(0.0, d.vhz_knee - m['w'])
            err = m['vref'] * vhz - vm - d.avr_qdroop * (m['qe'] / r)
            m['xi'] = min(max(m['xi'] + d.avr_ki * err * dt, 0.0), d.efd_max)
            efc = min(max(d.avr_kp * err + m['xi'], 0.0), d.efd_max)
            m['efd'] += (efc - m['efd']) * dt / max(d.avr_te, dt)
            m['eq'] += (m['efd'] - m['eq'] - (d.xd - d.xd1) * idm) * dt / d.td0
            m['eq'] = max(m['eq'], 0.05)
            # daya balik (ANSI 32)
            if m['pe'] < -0.03 * r:
                m['t_rev'] += dt
                if m['t_rev'] > 5.0:
                    m['rev'] = True
            else:
                m['t_rev'] = 0.0

        # --- VSG ---
        if vsg is not None and vsg['on']:
            d = vsg['d']
            r = vsg['r']
            ev = cmath.rect(vsg['e'], vsg['delta'])
            iv = (ev - V) / (1j * vsg['x'])
            if vsg['lim']:
                ilim = (d.ilim_st if vsg['t_over'] < d.t_st else d.ilim_cont) * r
                iv = ilim * iv / abs(iv)
            s = V * iv.conjugate()
            vsg['i'], vsg['pe'], vsg['qe'] = iv, s.real, s.imag
            ipu = abs(iv) / r
            vsg['ipk'] = max(vsg['ipk'], ipu)
            if ipu > d.ilim_cont * 0.995:
                vsg['t_over'] += dt
            else:
                vsg['t_over'] = max(0.0, vsg['t_over'] - dt)
            # proteksi tegangan-rendah PCS saat tertahan di batas arus:
            #   V < 0,5 pu lebih dari t_uv_trip (runtuh / motor stall), atau
            #   V < 0,85 pu lebih dari 5 s (27 tunda — aman utk motor starting)
            if vsg['lim']:
                vsg['t_lim'] += dt
                vsg['t_uv'] = vsg['t_uv'] + dt if vm < 0.5 else 0.0
                vsg['t_uv2'] = vsg.get('t_uv2', 0.0) + dt if vm < 0.85 else 0.0
            else:
                vsg['t_uv'] = 0.0
                vsg['t_uv2'] = 0.0
            # batas daya charge di pengendali arus -> geser set-point frekuensi
            cl = d.charge_limit_kw
            if cl is not None:
                viol = (-cl / S.s_base) - vsg['pe']
                if viol > 0:
                    vsg['bias'] += 2.0 * viol / r * dt
                else:
                    vsg['bias'] = max(0.0, vsg['bias'] - vsg['bias'] * dt / 2.0)
            M = 2.0 * d.h * r
            acc = (vsg['pset'] - vsg['pe']
                   - (vsg['w'] - vsg['wset'] - vsg['bias']) / d.droop * r) / M
            if vsg['lim']:
                # anti-windup: rotor virtual tak boleh menjauh selama dibatasi
                ang = cmath.phase(ev * V.conjugate()) if vm > 1e-3 else 0.0
                if (ang > 0 and acc > 0) or (ang < 0 and acc < 0):
                    acc = 0.0
                vsg['w'] += (1.0 - vsg['w']) * dt / 0.5 if vm < 0.3 else 0.0
            vsg['w'] += acc * dt
            vsg['delta'] += w0 * (vsg['w'] - 1.0) * dt
            # loop tegangan: tegangan terminal diatur ke Vref − nq·ΔQ (droop
            # Q-V) lewat integrator pada EMF virtual — jatuh tegangan sesaat
            # sebesar X_v·ΔI lalu pulih (dibekukan selama batas arus).
            if not vsg['lim']:
                verr = vsg['vref'] - d.qv_droop * (vsg['qe'] - vsg['q0']) / r - vm
                vsg['e'] = min(max(vsg['e'] + d.kv * verr * dt, 0.5), 1.25)
            if vsg['t_uv'] > d.t_uv_trip or vsg.get('t_uv2', 0.0) > 5.0:
                vsg['on'] = False
                vsg['tripped'] = True
                self.log.append((self.t, 'PCS trip: current limit with collapsed '
                                         'bus voltage (undervoltage protection)'))

        # --- grid (bus tak hingga pada frekuensi nominal) ---
        if grid_on:
            g = self.grid
            gi = (cmath.rect(g['e'], g['delta']) - V) / g['z']
            g['i'] = gi
            g['pe'] = (V * gi.conjugate()).real

        # --- IBR ---
        rocof = getattr(self, '_rocof', 0.0)
        for b in self.ibr:
            if not b['on']:
                continue
            d = b['d']
            r = b['r']
            if b['pav_rate'] != 0.0:
                stp = b['pav_rate'] * dt
                if abs(b['pav_tgt'] - b['pav']) <= abs(stp):
                    b['pav'] = b['pav_tgt']; b['pav_rate'] = 0.0
                else:
                    b['pav'] += stp
            tgt = b['pav']
            if b['ffr']:
                # --- sumber acuan ("grid") PCS grid-following ---
                if self._ref_present(d.gfl_ref):
                    b['t_ref'] = 0.0
                else:
                    b['t_ref'] += dt
                    if b['t_ref'] >= d.gfl_detect:
                        if d.gfl_loss == 'gfm':
                            self._to_gfm(b)
                        else:
                            b['on'] = False
                            self.log.append((
                                self.t, 'PCS trip: loss of grid-following '
                                        f'reference ({d.gfl_ref})'))
                        continue
                if d.qv_droop > 0:
                    iqt = (1.0 - vm) / d.qv_droop * r
                    b['iq'] += (iqt - b['iq']) * dt / 0.05
                tgt += (-(fpu - 1.0) / d.ffr_droop - 2.0 * d.ffr_h * rocof
                        / S.f_nom) * r
                tgt = min(max(tgt, -d.ilim_cont * r), d.ilim_cont * r)
                tp = 0.05
                rate = 50.0 * r
            else:
                tp = d.tp
                rate = d.recov * r
            if vm < 0.9:
                b['lvrt'] = True
            elif vm > 0.92:
                b['lvrt'] = False
            dp = (tgt - b['p']) * dt / max(tp, dt)
            if dp > rate * dt:
                dp = rate * dt
            b['p'] += dp
            # ride-through (gaya IEEE 2800)
            b['t_lv1'] = b['t_lv1'] + dt if vm < 0.10 else 0.0
            b['t_lv2'] = b['t_lv2'] + dt if vm < 0.50 else 0.0
            off = abs(fpu - 1.0) > 0.06
            b['t_f'] = b['t_f'] + dt if off else 0.0
            if not b['ffr'] and (b['t_lv1'] > 0.32 or b['t_lv2'] > 1.2
                                 or b['t_f'] > 0.3):
                b['on'] = False
                self.log.append((self.t, f'{d.name} trip (ride-through limit exceeded)'))

        # --- motor ---
        for ms in self.mot:
            if not ms.connected:
                continue
            te, _ = ms.torque(vm, ms.slip)
            ms.slip += (ms.t_load(ms.slip) - te) / (2.0 * ms.m.h) * dt
            ms.slip = min(max(ms.slip, 1e-4), 1.0)
            if ms.t_start is not None and ms.t_up is None and ms.slip < 0.05:
                ms.t_up = self.t - ms.t_start
                ms.frac = ms.m.load_frac
        self.t += dt

    # -- PCS grid-following: sumber acuan & alih ke grid-forming --------
    def _ref_present(self, ref: str) -> bool:
        grid_on = self.grid is not None and self.grid['on']
        if ref == 'GRID':
            return grid_on
        if ref in ('STG', 'GTG', 'DEG'):
            return any(m['on'] and m['d'].kind == ref for m in self.mach)
        return grid_on or any(m['on'] for m in self.mach) or (
            self.vsg is not None and self.vsg['on'])

    def _gfm_pending(self) -> bool:
        return any(b['on'] and b['ffr'] and b['d'].gfl_loss == 'gfm'
                   for b in self.ibr)

    def _to_gfm(self, b):
        """PCS grid-following -> VSG pada tegangan & arus saat ini."""
        d = b['d']
        r = b['r']
        V = self.V if abs(self.V) > 0.05 else complex(1.0, 0.0)
        i = b['i']
        x = d.xv / r
        e = V + 1j * x * i
        s_ = V * i.conjugate()
        self.vsg = dict(
            d=d, r=r, x=x, on=True, delta=cmath.phase(e),
            w=self.f / self.S.f_nom, e=abs(e), e0=abs(e), q0=s_.imag,
            vref=1.0, pset=s_.real, wset=1.0, bias=0.0, lim=False,
            t_over=0.0, t_uv=0.0, i=i, pe=s_.real, qe=s_.imag,
            ipk=abs(i) / r, t_lim=0.0, tripped=False)
        b['on'] = False
        b['manual'] = True
        self.log.append((self.t, 'PCS switched grid-following -> grid-forming '
                                 f'(reference {d.gfl_ref} lost)'))

    # -- kejadian ------------------------------------------------------
    def _unit(self, name):
        for m in self.mach:
            if m['d'].name == name:
                return 'm', m
        if self.vsg is not None and self.vsg['d'].name == name:
            return 'v', self.vsg
        for b in self.ibr:
            if b['d'].name == name:
                return 'i', b
        if name == 'GRID' and self.grid is not None:
            return 'g', self.grid
        return None, None

    def _apply(self, ev):
        S = self.S
        sb = S.s_base
        k = ev['type']
        if k == 'trip':
            kind, u = self._unit(ev['unit'])
            if u is not None:
                u['on'] = False
                u['manual'] = True          # trip yang memang kejadian studinya
                self.log.append((self.t, f"{ev['unit']} trip"))
        elif k == 'load_step':
            dp = ev['dp_kw'] / sb
            pf = ev.get('pf', S.load_pf)
            self.pl0 = max(0.0, self.pl0 + dp)
            self.ql0 = max(0.0, self.ql0 + dp * math.tan(math.acos(pf)))
        elif k == 'motor_start':
            ms = self.mot[ev['index']]
            ms.connected = True
            ms.slip = 1.0
            ms.frac = ms.m.start_frac
            ms.t_start = self.t
        elif k == 'fault_on':
            self.fault_y = 1.0 / ev['z'] if abs(ev['z']) > 1e-9 else 1e6
        elif k == 'fault_off':
            self.fault_y = 0j
        elif k == 'ceil':
            kind, u = self._unit(ev['unit'])
            if u is not None:
                u['ceil_tgt'] = ev['p_kw'] / sb
                rs = ev.get('ramp_s', 0.0)
                if rs <= 0:
                    u['ceil'] = u['ceil_tgt']
                else:
                    u['ceil_rate'] = (u['ceil_tgt'] - u['ceil']) / rs
        elif k == 'ref_ramp':
            kind, u = self._unit(ev['unit'])
            if u is not None and kind == 'm':
                u['pref_tgt'] = ev['to_kw'] / sb
                u['pref_rate'] = math.copysign(
                    abs(ev['rate_kw_s']) / sb, u['pref_tgt'] - u['pref'])
        elif k == 'ibr_set':
            kind, u = self._unit(ev['unit'])
            if u is not None and kind == 'i':
                u['pav_tgt'] = ev['p_kw'] / sb
                rs = ev.get('ramp_s', 0.0)
                if rs <= 0:
                    u['pav'] = u['pav_tgt']
                else:
                    u['pav_rate'] = (u['pav_tgt'] - u['pav']) / rs
        elif k == 'close':
            self._close(ev)
        elif k == 'vsg_set':
            if self.vsg is not None:
                if 'f_hz' in ev:
                    self.vsg['wset'] = ev['f_hz'] / S.f_nom
                if 'p_kw' in ev:
                    self.vsg['pset'] = ev['p_kw'] / sb

    def _close(self, ev):
        """Tutup pemutus unit ke bus dengan selisih sudut/tegangan/frekuensi."""
        S = self.S
        sb = S.s_base
        V = self.V
        vm, th = abs(V), cmath.phase(V)
        dphi = math.radians(ev.get('dphi_deg', 0.0))
        dv = ev.get('dv', 0.0)
        df = ev.get('df_hz', 0.0)
        if ev['unit'] == 'GRID':
            g = ev['grid']
            zg = sb / (g.sc_mva * 1000.0)
            rg = zg / math.sqrt(1.0 + g.xr ** 2)
            self.grid = dict(d=g, z=complex(rg, rg * g.xr), on=True, p=0.0,
                             delta=th + dphi, e=vm * (1.0 + dv), w=1.0, i=0j,
                             pe=0.0)
            if self.vsg is not None:
                # EMS menyamakan referensi tegangan & frekuensi VSG ke grid
                # saat paralel (tanpa ini droop Q-V melawan grid yang kaku)
                self.vsg['vref'] = vm * (1.0 + dv)
                self.vsg['wset'] = 1.0 + (self.vsg['pset'] - self.vsg['pe']) \
                    * 0.0
            self.log.append((self.t, 'Utility Grid breaker closed'))
            return
        d = ev['machine']
        r = d.s_kva / sb
        x = (d.xd2 if S.use_subtransient else d.xd1) / r
        eq = vm * (1.0 + dv)
        pmax = (d.pmax_kw if d.pmax_kw > 0 else d.s_kva * d.pf_rated) / sb
        w = self.f / S.f_nom + df / S.f_nom
        self.mach.append(dict(
            d=d, r=r, x=x, on=True, delta=th + dphi, w=w, eq=eq, efd=eq,
            # ΔV = selisih EMF saat penutupan; referensi AVR tetap pada
            # tegangan bus (operator menyetel tegangan nominal) sehingga
            # arus reaktif sirkulasi meluruh mengikuti AVR & T′d0.
            xi=eq, vref=vm, pm=0.0, pv=0.0,
            pref=-(1.0 - w) / d.droop * r if d.droop > 0 else 0.0,
            ceil=pmax, ceil_tgt=pmax, ceil_rate=0.0, pmax=pmax, pref_tgt=0.0,
            pref_rate=0.0, i=0j, pe=0.0, qe=0.0, ipk=0.0, ppk=0.0, t_rev=0.0,
            rev=False, xg=1.0 - w))
        self.log.append((self.t, f'{d.name} breaker closed'))

    # -- eksekusi ------------------------------------------------------
    def run(self, events, t_end: float, rec_dt: float = 0.005,
            ufls=None, progress=None):
        """events: list dict {'t', 'type', ...}. ufls: list (f_hz, delay_s,
        shed_frac) — pelepasan beban frekuensi-rendah otomatis (opsional)."""
        S = self.S
        evs = sorted(events, key=lambda e: e['t'])
        ei = 0
        n = int(round(t_end / self.dt))
        k_rec = max(1, int(round(rec_dt / self.dt)))
        cols = ['t', 'f', 'v', 'th', 'p_load']
        rec = {c: [] for c in cols}
        names = ([m.name for m in S.machines]
                 + [e['machine'].name for e in evs if e['type'] == 'close'
                    and e.get('machine') is not None])
        for nm in names:
            rec['p_' + nm] = []; rec['i_' + nm] = []; rec['q_' + nm] = []
        rec['p_BESS'] = []; rec['i_BESS'] = []; rec['q_BESS'] = []
        for b in self.ibr:
            if not b['ffr']:
                rec['p_' + b['d'].name] = []; rec['q_' + b['d'].name] = []
        rec['p_GRID'] = []; rec['i_GRID'] = []; rec['q_GRID'] = []
        rec['q_load'] = []
        for j, _ in enumerate(self.mot):
            rec[f'w_mot{j}'] = []; rec[f'i_mot{j}'] = []
        rec['i_fault'] = []
        uf = [dict(f=a, d=b, frac=c, t=0.0, done=False) for a, b, c in (ufls or [])]
        f_hist = []
        sb = S.s_base
        for step in range(n + 1):
            while ei < len(evs) and evs[ei]['t'] <= self.t + 1e-9:
                self._apply(evs[ei]); ei += 1
            self._step()
            # RoCoF jendela 100 ms (untuk FFR & metrik)
            f_hist.append(self.f)
            w = int(0.1 / self.dt)
            if len(f_hist) > w:
                self._rocof = (f_hist[-1] - f_hist[-1 - w]) / 0.1
            for u in uf:
                if u['done']:
                    continue
                u['t'] = u['t'] + self.dt if self.f < u['f'] else 0.0
                if u['t'] >= u['d']:
                    u['done'] = True
                    self.pl0 *= (1.0 - u['frac']); self.ql0 *= (1.0 - u['frac'])
                    for ms in self.mot:           # kelompok motor ikut dilepas
                        if ms.connected and ms.t_start is None:
                            ms.ratio *= (1.0 - u['frac'])
                    self.log.append((self.t, f"UFLS {u['f']:.1f} Hz: shed "
                                             f"{u['frac'] * 100:.0f} % of load"))
            vm = abs(self.V)
            alive = any(m['on'] for m in self.mach) or (
                self.vsg is not None and self.vsg['on']) or (
                self.grid is not None and self.grid['on']) or \
                self._gfm_pending()
            if not alive and not self.blackout:
                self.blackout = True
                self.log.append((self.t, 'BLACKOUT: no grid-forming source left'))
            if step % k_rec == 0:
                rec['t'].append(self.t)
                rec['f'].append(self.f if alive else float('nan'))
                rec['v'].append(vm)
                rec['th'].append(cmath.phase(self.V) if vm > 1e-6 else 0.0)
                yl = self._yload(vm, (self.f - S.f_nom) / S.f_nom)
                rec['p_load'].append(yl.real * vm * vm * sb)
                ql = -yl.imag * vm * vm
                for ms in self.mot:
                    if ms.connected:
                        ql += -(ms.y(ms.slip) * ms.ratio).imag * vm * vm
                rec['q_load'].append(ql * sb)
                md = {m['d'].name: m for m in self.mach}
                for nm in names:
                    m = md.get(nm)
                    on = m is not None and m['on']
                    rec['p_' + nm].append(m['pe'] * sb if on else 0.0)
                    rec['q_' + nm].append(m['qe'] * sb if on else 0.0)
                    rec['i_' + nm].append(abs(m['i']) * S.i_base if on else 0.0)
                v = self.vsg
                on = v is not None and v['on']
                gfl = next((b for b in self.ibr if b['ffr']), None)
                if on:
                    rec['p_BESS'].append(v['pe'] * sb)
                    rec['q_BESS'].append(v['qe'] * sb)
                    rec['i_BESS'].append(abs(v['i']) / v['r'])
                elif gfl is not None and gfl['on']:
                    s = self.V * gfl['i'].conjugate()
                    rec['p_BESS'].append(s.real * sb)
                    rec['q_BESS'].append(s.imag * sb)
                    rec['i_BESS'].append(abs(gfl['i']) / gfl['r'])
                else:
                    rec['p_BESS'].append(0.0); rec['q_BESS'].append(0.0)
                    rec['i_BESS'].append(0.0)
                for b in self.ibr:
                    if not b['ffr']:
                        sv_ = self.V * b['i'].conjugate() if b['on'] else 0j
                        rec['p_' + b['d'].name].append(sv_.real * sb)
                        rec['q_' + b['d'].name].append(sv_.imag * sb)
                g = self.grid
                on = g is not None and g['on']
                rec['p_GRID'].append(g.get('pe', 0.0) * sb if on else 0.0)
                rec['q_GRID'].append(
                    (self.V * g.get('i', 0j).conjugate()).imag * sb if on else 0.0)
                rec['i_GRID'].append(abs(g.get('i', 0j)) * S.i_base if on else 0.0)
                for j, ms in enumerate(self.mot):
                    rec[f'w_mot{j}'].append(1.0 - ms.slip if ms.connected else 0.0)
                    rec[f'i_mot{j}'].append(
                        abs(self.V * ms.y(ms.slip)) * ms.ratio * S.i_base
                        if ms.connected else 0.0)
                rec['i_fault'].append(abs(self.V * self.fault_y) * S.i_base)
            if self.blackout:
                break
            if progress is not None and step % 2000 == 0:
                progress(step, n)
        out = {k: np.asarray(v, float) for k, v in rec.items()}
        out['log'] = list(self.log)
        out['blackout'] = self.blackout
        v = self.vsg
        out['pcs'] = (dict(ipk=v['ipk'], t_lim=v['t_lim'], tripped=v['tripped'])
                      if v is not None else None)
        out['mach'] = {m['d'].name: dict(ipk_a=m['ipk'] * S.i_base,
                                         ppk_kw=m['ppk'] * sb, rev=m['rev'])
                       for m in self.mach}
        out['motors'] = [dict(t_up=ms.t_up, name=ms.m.name) for ms in self.mot]
        out['ibr_trip'] = [b['d'].name for b in self.ibr
                           if not b['on'] and not b['ffr']
                           and not b.get('manual')]
        return out


# ---------------------------------------------------------------- metrik
def metrics(res: dict, t_ev: float, f_nom: float = 50.0,
            t_clear: float | None = None) -> dict:
    """Ringkasan numerik satu kasus (setelah kejadian pada t_ev)."""
    t, f, v = res['t'], res['f'], res['v']
    if t.size == 0:
        return {}
    pre = t < t_ev - 1e-9
    post = ~pre
    f_pre = float(f[pre][-1]) if pre.any() else float(f[0])
    v_pre = float(v[pre][-1]) if pre.any() else float(v[0])
    fp, vp, tp = f[post], v[post], t[post]
    ok = np.isfinite(fp)
    out = dict(f_pre=f_pre, v_pre=v_pre)
    if ok.any():
        out['f_min'] = float(np.nanmin(fp)); out['f_max'] = float(np.nanmax(fp))
        out['f_end'] = float(fp[ok][-1])
        i100 = np.searchsorted(tp, t_ev + 0.1)
        if i100 < fp.size and np.isfinite(fp[i100]):
            out['rocof'] = float((fp[i100] - f_pre) / 0.1)
        w = max(1, int(round(0.1 / max(t[1] - t[0], 1e-6))))
        if fp.size > w:
            d = (fp[w:] - fp[:-w]) / 0.1
            if np.isfinite(d).any():
                out['rocof_max'] = float(d[np.nanargmax(np.abs(d))])
    out['v_min'] = float(vp.min()) if vp.size else v_pre
    out['v_max'] = float(vp.max()) if vp.size else v_pre
    out['v_end'] = float(vp[-1]) if vp.size else v_pre
    i1 = np.searchsorted(tp, t_ev + 1.0)
    if i1 < vp.size:
        out['v_1s'] = float(vp[i1])
    # lompatan fasa: perubahan sudut bus 20 ms setelah kejadian, bebas hanyutan
    th = res['th']
    i0 = np.searchsorted(t, t_ev) - 1
    i2 = np.searchsorted(t, t_ev + 0.02)
    if 0 <= i0 < th.size and i2 < th.size:
        d = th[i2] - th[i0]
        drift = 2 * math.pi * (f_pre - f_nom) * (t[i2] - t[i0])
        d = (d - drift + math.pi) % (2 * math.pi) - math.pi
        out['phase_jump_deg'] = float(math.degrees(d))
    if t_clear is not None:
        after = t >= t_clear
        rec = np.where(after & (v >= 0.9))[0]
        out['t_v_recover'] = float(t[rec[0]] - t_clear) if rec.size else float('nan')
    pcs = res.get('pcs')
    if pcs:
        out['pcs_ipk'] = float(pcs['ipk']); out['pcs_t_lim'] = float(pcs['t_lim'])
        out['pcs_trip'] = bool(pcs['tripped'])
    if 'i_BESS' in res and post.any():
        out['pcs_end'] = float(res['i_BESS'][post][-1])
    out['blackout'] = bool(res.get('blackout'))
    # Waktu respons daya reaktif: sumber dgn perubahan Q terbesar; t90 = waktu
    # Q pertama kali mencapai 90 % perubahan akhirnya (IEC 61400-21-1:
    # definisi response time besaran reaktif), dan puncak Q-nya.
    best = None
    for k, q in res.items():
        if not (isinstance(k, str) and k.startswith('q_') and k != 'q_load'):
            continue
        q = np.asarray(q, float)
        if q.size != t.size or not post.any() or not pre.any():
            continue
        q0, q1 = float(q[pre][-1]), float(q[post][-1])
        if abs(q0) > 1e-6 and abs(q1) < 1e-9:
            continue                 # unit yang lepas (trip) bukan penanggap
        pk = float(q[post][np.argmax(np.abs(q[post] - q0))])
        dq = q1 - q0
        score = max(abs(dq), abs(pk - q0))
        if best is None or score > best[0]:
            t90 = float('nan')
            if abs(dq) > 1e-3:
                hit = np.where((q[post] - q0) * np.sign(dq) >= 0.9 * abs(dq))[0]
                if hit.size:
                    t90 = float(tp[hit[0]] - t_ev)
            best = (score, k[2:], t90, pk, dq)
    if best is not None and best[0] > 1e-3:
        out['q_unit'] = best[1]
        out['q_t90'] = best[2]
        out['q_peak_kvar'] = best[3]
        out['q_step_kvar'] = best[4]
    return out


def modal(t, y, t0: float) -> dict:
    """Frekuensi & rasio redaman mode osilasi dominan dari respons y(t) setelah
    t0 (dekremen logaritmik pada puncak-puncak deviasi terhadap nilai akhir)."""
    t = np.asarray(t, float); y = np.asarray(y, float)
    m = t >= t0
    t, y = t[m], y[m]
    if t.size < 20:
        return {}
    # buang tren lambat (rata-rata bergerak 1 s) agar yang tersisa osilasinya
    dt = t[1] - t[0]
    w = max(3, int(round(0.6 / dt)) | 1)
    k = np.ones(w) / w
    trend = np.convolve(np.pad(y, (w // 2, w // 2), mode='edge'), k, 'valid')
    x = y - trend
    amp = np.max(np.abs(x)) if x.size else 0.0
    if amp < 1e-9:
        return {}
    pk = [i for i in range(1, x.size - 1)
          if x[i] > x[i - 1] and x[i] >= x[i + 1] and x[i] > 0.02 * amp]
    if len(pk) < 2:
        return dict(damping=1.0, freq=float('nan'), t_decay=0.0)
    per = float(np.median(np.diff(t[pk])))
    a = x[pk]
    ratios = [math.log(a[i] / a[i + 1]) for i in range(len(a) - 1)
              if a[i] > 0 and a[i + 1] > 0 and a[i + 1] < a[i]]
    if not ratios:
        return dict(damping=0.0, freq=1.0 / per, t_decay=float('inf'))
    dl = float(np.median(ratios[:3]))
    zeta = dl / math.sqrt(4 * math.pi ** 2 + dl ** 2)
    env = np.abs(x)
    big = np.where(env > 0.1 * amp)[0]
    return dict(damping=float(zeta), freq=float(1.0 / per),
                t_decay=float(t[big[-1]] - t0) if big.size else 0.0)


# ---------------------------------------------------------------- hubung singkat
def cable_z_ohm(length_m: float, mm2: float):
    """Impedansi kabel tembaga LV (Ω): R = ρ·L/A (ρ 0,0225 Ω·mm²/m pada suhu
    operasi), X ≈ 0,08 mΩ/m."""
    return complex(0.0225 * length_m / max(mm2, 1.0), 0.08e-3 * length_m)


def short_circuit(S: System, config: dict) -> dict:
    """Arus hubung singkat tiga-fasa di busbar (metode IEC 60909, sumber
    setara + model arus-terbatas konverter). config: {'machines': [nama],
    'pcs': bool, 'ibr': bool, 'grid': bool, 'motors': bool}.

    Kembalikan kA: ik_max (awal, sub-transien, dengan motor, c_max), ik_min
    (transien, tanpa motor, c_min), ip (puncak), dan rincian per sumber."""
    lv = S.v_kv <= 1.0
    c_max, c_min = (1.05, 0.95) if lv else (1.10, 1.00)
    kv = S.v_kv
    rows = []
    ik_max = ik_min = 0.0
    xr_num = xr_den = 0.0
    for m in S.machines:
        if m.name not in config.get('machines', []):
            continue
        ir = m.s_kva / (SQ3 * kv) / 1000.0                  # kA
        i2 = c_max * ir / m.xd2
        i1 = c_min * ir / m.xd1
        rows.append((m.name, ir * 1000, f"X″d {m.xd2:.2f} / X′d {m.xd1:.2f} pu",
                     i2, i1))
        ik_max += i2; ik_min += i1
        xr_num += i2 * 10.0; xr_den += i2
    if config.get('grid') and S.grid is not None:
        ig = S.grid.sc_mva / (SQ3 * kv)
        rows.append(('Utility Grid', float('nan'),
                     f"S″k {S.grid.sc_mva:g} MVA, X/R {S.grid.xr:g}",
                     c_max * ig, c_min * ig))
        ik_max += c_max * ig; ik_min += c_min * ig
        xr_num += c_max * ig * S.grid.xr; xr_den += c_max * ig
    if config.get('pcs') and S.pcs is not None:
        ir = S.pcs.s_kva / (SQ3 * kv) / 1000.0
        rows.append(('BESS PCS', ir * 1000,
                     f"current-limited {S.pcs.ilim_st:.2f} pu ≤ {S.pcs.t_st:g} s",
                     S.pcs.ilim_st * ir, S.pcs.ilim_cont * ir))
        ik_max += S.pcs.ilim_st * ir; ik_min += S.pcs.ilim_cont * ir
    if config.get('ibr'):
        for b in S.ibrs:
            ir = b.s_kva / (SQ3 * kv) / 1000.0
            if b.wtg_type == 3:
                rows.append((b.name + ' (Type 3 DFIG)', ir * 1000,
                             'initial ≈ 3 pu (crowbar), then current-limited',
                             3.0 * ir, b.ilim * ir))
                ik_max += 3.0 * ir; ik_min += 0.0
            else:
                rows.append((b.name, ir * 1000,
                             f"current-limited {b.ilim:.2f} pu", b.ilim * ir, 0.0))
                ik_max += b.ilim * ir
    if config.get('motors'):
        for mt in S.motors:
            if not mt.running:
                continue
            flc = (mt.p_kw / (mt.eff * mt.pf) / (SQ3 * kv) / 1000.0
                   * float(config.get('motor_scale', 1.0)))
            rows.append((mt.name, flc * 1000,
                         f"{mt.lrc:.1f} × FLC, decays within a few cycles",
                         mt.lrc * flc, 0.0))
            ik_max += mt.lrc * flc
    xr = xr_num / xr_den if xr_den > 0 else 1.0
    kappa = 1.02 + 0.98 * math.exp(-3.0 / max(xr, 0.1))
    return dict(rows=rows, ik_max=ik_max, ik_min=ik_min,
                ip=kappa * math.sqrt(2.0) * ik_max, kappa=kappa)


FEEDER_RATINGS = (63, 100, 160, 250, 400, 630, 800, 1000, 1250, 1600)


def feeder_clearing(ik_min_ka: float) -> list:
    """Apakah trip INSTAN pemutus feeder (pickup 5–10 × In) masih bekerja pada
    arus gangguan minimum. -> [(In, pickup_lo_kA, pickup_hi_kA, verdict)]."""
    out = []
    for n in FEEDER_RATINGS:
        lo, hi = 5 * n / 1000.0, 10 * n / 1000.0
        if ik_min_ka >= hi * 1.2:
            vd = 'yes'
        elif ik_min_ka >= lo * 1.2:
            vd = 'partial'
        else:
            vd = 'no'
        out.append((n, lo, hi, vd))
    return out
