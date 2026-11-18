"""Model energi Wind Turbine Generator (WTG) untuk dispatch.

Rantai konversi (acuan standar di tiap langkah):

1. Koreksi ketinggian — hukum pangkat (IEC 61400-1, Normal Wind Profile):
       v_hub = v_meas · (h_hub / h_meas)^α            (α = 0,20 darat; 0,14 laut)
2. Normalisasi kerapatan udara (IEC 61400-12-1, turbin pitch-regulated):
       v_eq = v_hub · (ρ_site / ρ0)^(1/3)             (ρ0 = 1,225 kg/m³)
   ρ_site dari elevasi & suhu (atmosfer standar ISO 2533):
       p = 101325 · (1 − 2,25577e-5 · h)^5,25588 ;  ρ = p / (287,05 · T)
3. Kurva daya generik tiga-wilayah:
       v < v_ci            : 0
       v_ci ≤ v < v_r      : P_r · (v^k − v_ci^k) / (v_r^k − v_ci^k)   (k = 3)
       v_r ≤ v ≤ v_co      : P_r   (pitch menahan daya nominal)
       v > v_co            : 0     (high-wind shutdown)
4. Rugi-rugi plant (wake, kelistrikan, ketersediaan): P_net = P · (1 − loss).

Seluruh fungsi MURNI & tervektorisasi. Modul ini TIDAK memodelkan dinamika
(inersia rotor, pitch, LVRT) — itu bagian engine/transient.py (IEC 61400-27-1).

Keterbatasan yang harus disadari pengguna: dengan angin rata-rata per jam,
kurva kubik cenderung MEREMEHKAN energi (E[v³] > E[v]³) bila turbulensi dalam
jam tsb besar; gunakan data 10-menit (basis IEC 61400-12-1) bila tersedia.
"""
from __future__ import annotations
import numpy as np

RHO0 = 1.225            # kg/m³ — kerapatan acuan ISO (15 °C, permukaan laut)
R_AIR = 287.05          # J/(kg·K) — konstanta gas udara kering


def air_density(elev_m: float = 0.0, temp_c: float = 15.0) -> float:
    """Kerapatan udara (kg/m³) dari elevasi site & suhu rata-rata."""
    h = max(-500.0, min(float(elev_m), 6000.0))
    p = 101325.0 * (1.0 - 2.25577e-5 * h) ** 5.25588
    return float(p / (R_AIR * (float(temp_c) + 273.15)))


def hub_speed(v_meas, h_hub: float, h_meas: float, shear: float):
    """Kecepatan angin di hub (hukum pangkat IEC 61400-1)."""
    v = np.maximum(0.0, np.asarray(v_meas, float))
    if h_hub <= 0 or h_meas <= 0:
        return v
    return v * (float(h_hub) / float(h_meas)) ** float(shear)


def power_curve_pu(v_eq, v_ci: float, v_r: float, v_co: float, k: float = 3.0):
    """Daya per-unit (0..1) dari kecepatan ekuivalen (sudah ternormalisasi ρ)."""
    v = np.asarray(v_eq, float)
    v_ci = max(0.0, float(v_ci))
    v_r = max(v_ci + 1e-6, float(v_r))
    v_co = max(v_r, float(v_co))
    k = max(1.0, float(k))
    ramp = (np.power(np.maximum(v, 0.0), k) - v_ci ** k) / (v_r ** k - v_ci ** k)
    p = np.where(v < v_ci, 0.0, np.where(v < v_r, ramp, 1.0))
    p = np.where(v > v_co, 0.0, p)
    return np.clip(p, 0.0, 1.0)


def wtg_power_kw(profile, n_units: float, unit_kw: float, mode: int = 0,
                 base_kw: float = 1.0, h_hub: float = 80.0, h_meas: float = 10.0,
                 shear: float = 0.2, v_ci: float = 3.0, v_r: float = 12.0,
                 v_co: float = 25.0, rho: float = RHO0, loss: float = 0.0,
                 curve_k: float = 3.0):
    """Daya AC bersih plant WTG (kW) per langkah.

    profile : (T,) kecepatan angin [m/s] (mode 0) ATAU daya plant acuan [kW]
              (mode 1; diskalakan n_units·unit_kw / base_kw — analog profil PV).
    NaN pada profil dianggap 0 (tak ada data -> tak ada produksi)."""
    x = np.nan_to_num(np.asarray(profile, float), nan=0.0)
    cap = max(0.0, float(n_units)) * max(0.0, float(unit_kw))
    if cap <= 0:
        return np.zeros_like(x)
    lossf = 1.0 - min(max(float(loss), 0.0), 1.0)
    if int(mode) == 1:
        return np.clip(x * cap / max(float(base_kw), 1e-9), 0.0, cap) * lossf
    v = hub_speed(x, h_hub, h_meas, shear)
    v = v * (max(float(rho), 1e-3) / RHO0) ** (1.0 / 3.0)
    return cap * power_curve_pu(v, v_ci, v_r, v_co, curve_k) * lossf


def capacity_factor(power_kw, n_units: float, unit_kw: float) -> float:
    cap = float(n_units) * float(unit_kw)
    p = np.asarray(power_kw, float)
    return float(p.mean() / cap) if cap > 0 and p.size else 0.0
