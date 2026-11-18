"""Skema parameter — SATU-SATUNYA tempat mendefinisikan parameter aplikasi.

Menambah parameter baru = menambah satu entri Param di SCHEMA; halaman
Parameters otomatis membuat widget (textbox/dropdown/checkbox), tooltip,
satuan, dan validasi min/maks dari definisi ini.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import os


@dataclass
class Param:
    key: str
    # dtype 'heading' = judul sub-bagian (label full-width, tanpa input);
    # tak masuk cfg/defaults, hanya penata tampilan halaman Parameters.
    label: str
    dtype: str = 'float'            # float | int | bool | choice | text | heading
    default: object = 0.0
    unit: str = ''
    tooltip: str = ''
    minimum: float | None = None
    maximum: float | None = None
    choices: list = field(default_factory=list)
    decimals: int = 3
    # v163 — dasar standar nilai default (ditampilkan di tooltip & sheet
    # "Parameter Basis" ekspor Transient). Kosong = tidak ada.
    basis: str = ''


def _hdr(key: str, label: str) -> 'Param':
    """Buat baris JUDUL sub-bagian untuk halaman Parameters."""
    return Param(key, label, 'heading', '')


# Peta mode BESS (checkbox) -> kunci prioritasnya. Dipakai ParamGroupBox agar
# dropdown prioritas tampil SEBARIS dengan checkbox mode (bukan baris sendiri).
MODE_PRIORITY = {
    'm_pv_smooth':  'prio_pv_smooth',
    'm_firming':    'prio_firming',
    'm_load_shift': 'prio_load_shift',
    'm_peak_shave': 'prio_peak_shave',
    'm_dg_minload': 'prio_dg_minload',
    'm_reserve':    'prio_reserve',
    'm_backup':     'prio_backup',
    'm_load_follow': 'prio_load_follow',
}


# Laju konsumsi bahan bakar DEG bawaan (L/kWh). 0,303 L/kWh setara dengan
# efisiensi generator 33% pada model lama: fuel = energi / (0,33 × 10 kWh/L)
# = energi × 0,303. Fuel = laju × energi DEG (kWh) — konversi langsung.
DEFAULT_FUEL_RATE = round(1.0 / (0.33 * 10.0), 3)     # 0.303


SCHEMA: dict[str, list[Param]] = {
    'General': [
        Param('project_name', 'Project Name', 'text', 'Hybrid Plant Project',
              tooltip='Nama proyek untuk laporan'),
        Param('customer', 'Customer', 'text', '', tooltip='Nama pelanggan'),
        Param('site_name', 'Site Name', 'text', '',
              tooltip='Nama site / lokasi pembangkit (dipakai pada nama '
                      'file ekspor dan lembar Info)'),
        Param('location', 'Location', 'text', '', tooltip='Lokasi site'),
        Param('latitude', 'Latitude', 'float', 0.0, '°',
              'Lintang lokasi proyek (−90…90). Pilih lewat tombol '
              '"Pilih di Peta" pada halaman Home.', -90.0, 90.0, decimals=6),
        Param('longitude', 'Longitude', 'float', 0.0, '°',
              'Bujur lokasi proyek (−180…180). Pilih lewat tombol '
              '"Pilih di Peta" pada halaman Home.', -180.0, 180.0, decimals=6),
        Param('simulation_year', 'Simulation Year', 'int', 2025, '',
              'Tahun kalender profil data', 2000, 2100),
        Param('sim_interval', 'Simulation Interval', 'choice', '1 hour',
              tooltip='Resolusi waktu simulasi (khusus halaman Dashboard). '
                      'Interval lebih halus memakai JENDELA lebih pendek agar '
                      'ringan: 1 hour & 30 minute = 1 tahun penuh; 1 minute & '
                      '30 second = 1 bulan; 15 second = 1 minggu; 1 second = '
                      '1 hari. Titik MULAI jendela dipilih di Dashboard. Energi '
                      'diekstrapolasi ke setahun (kWh/tahun). Data per-jam '
                      'otomatis di-resample; boleh juga import data resolusi '
                      'tinggi. Optimization & Multi-Year tetap basis 1 jam.',
              choices=['1 hour', '30 minute', '1 minute', '30 second',
                       '15 second', '1 second']),
    ],
    'Grid': [
        Param('grid_enabled', 'Any Grid Connection', 'bool', True,
              tooltip='Nonaktifkan untuk sistem off-grid'),
        Param('grid_kw', 'Grid Capacity', 'float', 23.0, 'kW',
              'Kapasitas sambungan PLN', 0.0, 1e6),
        Param('grid_min_loading', 'Grid Minimum Loading', 'float', 0.01, '%',
              'Loading minimum grid saat tersambung', 0.0, 1.0),
        Param('grid_max_loading', 'Grid Maximum Loading', 'float', 1.0, '%',
              'Loading maksimum grid', 0.0, 1.5),
        Param('allow_export', 'PV-BESS Export to Grid', 'bool', False,
              tooltip='Izinkan ekspor kelebihan PV ke grid (ekstensi; '
                      'default OFF)'),
        Param('grid_tariff_per_kwh', 'Grid Tariff', 'float', 1500.0, 'Rp/kWh',
              'Tarif energi impor grid', 0.0, 1e6),
        Param('export_tariff_per_kwh', 'Export Tariff', 'float', 1000.0,
              'Rp/kWh', 'Harga jual energi ekspor ke grid (dipakai bila '
              'PV-BESS Export to Grid aktif)', 0.0, 1e6),
    ],
    'Dispatch Strategy': [
        Param('bess_mode', 'Dispatch Mode', 'choice', 'Standard',
              tooltip='Standard: dispatch seperti biasa (prioritas beban). '
                      'Advanced: pilih FUNGSI BESS khusus (Peak Shaving, dll.) '
                      'di atas dispatch dasar.',
              choices=['Standard', 'Advanced']),
        # ==== EMS BESS multi-mode (mode Advanced) — beberapa boleh aktif ====
        # serentak; satu baterai melayani semua menurut PRIORITAS (nomor di
        # sebelah tiap mode; 1 = tertinggi). Lihat engine/bess_modes.py.
        # Judul sub-bagian (tampil hanya saat Advanced) — memisahkan fungsi
        # peran BESS lanjutan dari aturan dispatch dasar di bawahnya.
        _hdr('__hdr_bess_role', 'BESS Role Function'),
        Param('adv_target', 'Discharge Target', 'choice', 'Both',
              tooltip='Suplai yang DIKURANGI saat BESS discharge (mode '
                      'Advanced): Grid saja, DEG saja, atau keduanya. '
                      'Memengaruhi Peak Shaving & Load Shifting dan penerapan '
                      'discharge ke suplai.',
              choices=['Both', 'Grid', 'DEG']),
        Param('m_pv_smooth', 'Renewable Smoothing', 'bool', False,
              tooltip='Haluskan output PV yang dikirim ke sistem. Setpoint output '
                      'PV = Moving Average (MA) PV EnetAC, lalu laju NAIK/TURUN-nya '
                      'dibatasi PV Ramp-Up/Down Limit. BESS mengisi kekurangan '
                      '(setpoint > PV EnetAC → discharge) & menyerap kelebihan '
                      '(setpoint < PV EnetAC → charge) agar output PV mengikuti '
                      'kurva halus; DEG menjadi base load. Tak dapat aktif '
                      'bersamaan dengan Firming — mengaktifkan salah satu '
                      'otomatis menonaktifkan yang lain.'),
        Param('prio_pv_smooth', 'Priority', 'choice', '2',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5', '6']),
        Param('pv_ramp_up_kwmin', 'PV Ramp-Up Limit', 'float', 0.0,
              'kW/min', 'Batas laju NAIK (kW/menit) output PV ter-smoothed '
              '(setpoint). 0 = tanpa batas naik (hanya MA).', 0.0, 1e7),
        Param('pv_ramp_dn_kwmin', 'PV Ramp-Down Limit', 'float', 0.0,
              'kW/min', 'Batas laju TURUN (kW/menit) output PV ter-smoothed '
              '(setpoint). 0 = tanpa batas turun (hanya MA).', 0.0, 1e7),
        Param('smoothing_window', 'MA Window', 'int', 10, 'langkah',
              'Ukuran jendela Moving Average (jumlah nilai PV EnetAC sebelumnya). '
              'Setpoint = rata-rata bergerak PV sepanjang window ini, lalu '
              'dibatasi PV Ramp-Up/Down Limit. Besar = lebih halus/lag besar.',
              1, 100000),
        Param('m_firming', 'Firming Capacity', 'bool', False,
              tooltip='PV+BESS men-deliver DAYA KONSTAN (target) sebagai base load '
                      'dalam JENDELA firming: BESS discharge saat PV di bawah target '
                      '& charge dari kelebihan PV saat di atas target. Di LUAR '
                      'jendela, PV dipakai untuk charge BESS saja (tak diinjeksi). '
                      'Tak dapat aktif bersamaan dengan Smoothing — mengaktifkan '
                      'salah satu otomatis menonaktifkan yang lain.'),
        Param('prio_firming', 'Priority', 'choice', '2',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5', '6']),
        Param('firming_kw', 'Target Power', 'float', 0.0, 'kW',
              'Daya konstan (kW) yang di-deliver PV+BESS sebagai base load. BESS '
              'menutup kekurangan (PV < target) & menyerap kelebihan (PV > '
              'target).', 0.0, 1e7),
        Param('firming_trigger', 'Firming Window', 'choice', 'PV Power',
              tooltip='Penentu KAPAN Firming aktif: "PV Power" (ambang daya PV '
                      'EnetAC) atau "Time" (jam mulai/berhenti). Di luar jendela, '
                      'PV hanya untuk charge BESS.', choices=['PV Power', 'Time']),
        Param('firming_pv_start', 'PV Threshold Start', 'float', 0.0, 'kW',
              'Pagi: Firming MULAI saat PV EnetAC melampaui nilai ini. Sebelum itu '
              'PV hanya untuk charge BESS. (mode Firming Window = PV Power)', 0.0, 1e7),
        Param('firming_pv_end', 'PV Threshold End', 'float', 0.0, 'kW',
              'Sore: Firming BERHENTI saat PV EnetAC turun di bawah nilai ini. '
              'Setelahnya PV hanya untuk charge BESS. (mode PV Power)', 0.0, 1e7),
        Param('firming_time_start', 'Start Time', 'float', 0.0, 'h',
              'Jam (0–24) Firming MULAI. Sebelumnya PV hanya untuk charge BESS. '
              '(mode Firming Window = Time)', 0.0, 24.0),
        Param('firming_time_end', 'End Time', 'float', 0.0, 'h',
              'Jam (0–24) Firming BERHENTI. Setelahnya PV hanya untuk charge BESS. '
              '(mode Time)', 0.0, 24.0),
        Param('m_load_shift', 'Energy Time-Shifting / Arbitrage', 'bool', False,
              tooltip='Simpan energi saat surplus/luar-puncak, lepaskan saat '
                      'puncak untuk mengurangi grid/DEG. Memperhitungkan '
                      'efisiensi charge/discharge (RTE).'),
        Param('prio_load_shift', 'Priority', 'choice', '4',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5', '6']),
        Param('arb_peak_start', 'Peak Window Start', 'int', 18,
              'h', 'Jam MULAI jendela puncak (0-23): di dalamnya BESS discharge; '
                   'di luar BESS diisi. Start > End → melewati tengah malam.',
              0, 23),
        Param('arb_peak_end', 'Peak Window End', 'int', 22,
              'h', 'Jam AKHIR jendela puncak (0-23, eksklusif).', 0, 23),
        Param('tariff_offpeak_per_kwh', 'Off-Peak Tariff',
              'float', 1000.0, 'Rp/kWh', 'Tarif grid luar puncak (finansial). '
              'Impor jam puncak memakai Grid Tariff biasa.', 0.0, 1e6),
        Param('m_peak_shave', 'Peak Shaving', 'bool', False,
              tooltip='Batasi daya puncak dari grid/DEG. BESS discharge saat '
                      'net load melebihi ambang. discharge = max(0, net load − '
                      'ambang).'),
        Param('prio_peak_shave', 'Priority', 'choice', '5',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5', '6']),
        Param('peak_shave_kw', 'Threshold', 'float', 0.0, 'kW',
              'Ambang net load. Di atas ambang, BESS discharge menutup '
              'selisihnya (sebatas SOC & PCS).', 0.0, 1e7),
        Param('m_dg_minload', 'DG Minimum Loading', 'bool', False,
              tooltip='Cegah DG beroperasi di bawah minimum loading: kelebihan '
                      'output DG (di atas beban) dialihkan mengisi BESS. Pakai '
                      'Minimum Loading (grup Diesel).'),
        Param('prio_dg_minload', 'Priority', 'choice', '3',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5', '6']),
        Param('m_reserve', 'Spinning Reserve', 'bool', False,
              tooltip='Tahan sebagian kapasitas BESS (SOC & daya PCS) agar '
                      'SELALU tersedia untuk kejadian tak terduga (DG trip, PV '
                      'anjlok, lonjakan beban). Dispatch normal tak boleh '
                      'memakai cadangan ini. Tak dapat aktif bersamaan dengan '
                      'Backup — mengaktifkan salah satu otomatis menonaktifkan '
                      'yang lain.'),
        Param('prio_reserve', 'Priority', 'choice', '1',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5', '6']),
        Param('reserve_frac', 'SOC Fraction', 'float', 0.0,
              '%', 'Persentase energi guna BESS (SOC maks−min) yang DITAHAN '
              'sebagai cadangan (0–100%). Dispatch normal tak menyentuhnya.',
              0.0, 100.0),
        Param('reserve_kw', 'Power', 'float', 0.0, 'kW',
              'Daya PCS yang DITAHAN sebagai cadangan (tak dipakai dispatch '
              'normal).', 0.0, 1e7),
        Param('m_backup', 'Backup Power', 'bool', False,
              tooltip='BESS (+PV bila tersedia) mengambil alih PENUH pelayanan '
                      'beban saat Grid DAN DEG sama-sama tak tersedia (outage) '
                      '— mengesampingkan Smoothing/Firming kapan pun outage '
                      'terjadi. Di luar outage: BESS hanya charge oportunistik '
                      'dari surplus PV (siaga), tak pernah discharge. Tak dapat '
                      'aktif bersamaan dengan Operating Reserve — mengaktifkan '
                      'salah satu otomatis menonaktifkan yang lain.'),
        Param('prio_backup', 'Priority', 'choice', '1',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5', '6']),
        # ==== Strategi BESS tambahan (v162) ====
        Param('m_load_follow', 'Load Follower', 'bool', False,
              tooltip='Tahan sumber dispatchable (Utility Grid / DEG) pada '
                      'SET-POINT tetap; BESS memikul selisih beban bersih '
                      'terhadap set-point itu, dua arah: di atas set-point '
                      'BESS discharge, di bawahnya (opsional) BESS charge dari '
                      'sumber tersebut. Berbeda dari Peak Shaving (ambang = '
                      'batas atas kontrak, satu arah).'),
        Param('prio_load_follow', 'Priority', 'choice', '4',
              tooltip='Nomor PRIORITAS mode ini dalam co-dispatch (1 = tertinggi). Saat beberapa mode aktif, mode prioritas lebih tinggi mendapat anggaran SOC/PCS lebih dulu.', choices=['1', '2', '3', '4', '5', '6']),
        Param('lf_set_kw', 'Source Set-Point', 'float', 0.0, 'kW',
              'Titik kerja sumber dispatchable (Utility Grid/DEG) yang '
              'dipertahankan Load Follower (kW).', 0.0, 1e9),
        Param('lf_charge', 'Charge below Set-Point', 'bool', True,
              tooltip='Aktif: saat beban bersih < set-point, sumber tetap di '
                      'set-point dan selisihnya mengisi BESS (valley filling). '
                      'Nonaktif: BESS hanya discharge.'),
        Param('m_freq_reg', 'Frequency Regulation', 'bool', False,
              tooltip='Sediakan pita regulasi frekuensi SIMETRIS: daya ±P '
                      'ditahan dari PCS (arah charge maupun discharge) dan '
                      'energi P × durasi ditahan di KEDUA sisi SOC, sehingga '
                      'respons droop/inersia selalu tersedia. Pita ini tidak '
                      'dipakai mode energi lain. Kecukupan dinamik (nadir, '
                      'RoCoF) diverifikasi di halaman Transient.'),
        Param('fr_kw', 'Regulation Power (±)', 'float', 0.0, 'kW',
              'Daya regulasi simetris yang ditahan dari PCS (kW).', 0.0, 1e9),
        Param('fr_min', 'Regulation Duration', 'float', 15.0, 'min',
              'Durasi penuh daya regulasi yang harus dapat dipertahankan '
              '(menit) — menentukan pita energi SOC yang ditahan.', 0.0, 600.0),
        Param('m_qv', 'Reactive Power & Voltage Control', 'bool', False,
              tooltip='PCS menahan kapasitas daya reaktif untuk kendali '
                      'tegangan (Q-V droop / PF). Mengikuti kurva kapabilitas '
                      'PQ: daya aktif maksimum = √(S² − Q²). Fungsi power '
                      'quality (dip tegangan, flicker) dilayani oleh mode ini '
                      'bersama Renewable Smoothing — bukan mode terpisah.'),
        Param('pcs_kva', 'PCS Apparent Power', 'float', 0.0, 'kVA',
              'Daya semu PCS (kVA). 0 = Auto (= Maximum Charge/Discharge '
              'Power terbesar).', 0.0, 1e9),
        Param('qv_kvar', 'Reactive Reserve', 'float', 0.0, 'kvar',
              'Daya reaktif yang ditahan untuk kendali tegangan (kvar).',
              0.0, 1e9),
        Param('m_black_start', 'Black Start', 'bool', False,
              tooltip='Tahan energi di dasar SOC untuk menghidupkan kembali '
                      'sistem dari kondisi padam total (grid-forming, '
                      'energisasi bus & pick-up beban esensial). Energi ini '
                      'TIDAK dipakai dispatch normal maupun Backup. Tidak '
                      'dijumlahkan dengan Spinning Reserve (lantai efektif = '
                      'yang terbesar). Urutan black start diuji di Transient.'),
        Param('bs_kw', 'Black-Start Load', 'float', 0.0, 'kW',
              'Beban esensial yang dipikul BESS selama black start (kW).',
              0.0, 1e9),
        Param('bs_min', 'Black-Start Duration', 'float', 30.0, 'min',
              'Lama BESS memikul beban black start hingga sumber lain '
              'sinkron (menit).', 0.0, 1440.0),
        # Judul sub-bagian (SELALU tampil, di mode Standard MAUPUN Advanced) —
        # parameter dasar dispatch & sumber daya yang berlaku utk KEDUA mode
        # (bukan eksklusif salah satu). Lihat VISIBILITY: TIDAK boleh dibungkus
        # aturan _adv_bess (dulu pernah disembunyikan saat Advanced -- sudah
        # dibetulkan, lihat catatan di definisi VISIBILITY di bawah).
        _hdr('__hdr_base_dispatch', 'Base Parameters'),
        Param('load_priority', 'Load Supply Priority', 'choice',
              'PV -> Grid -> BESS -> DEG',
              tooltip='Urutan sumber yang melayani beban. Mode Grid dahulu '
                      'memaksimalkan impor grid sebelum PV/BESS. '
                      'Bila DEG Interlock with Grid dinonaktifkan, '
                      'genset naik satu tingkat sebelum BESS: '
                      'PV → Grid → DEG → BESS, dan '
                      'Grid → DEG → PV → BESS.',
              choices=['PV -> Grid -> BESS -> DEG',
                       'Grid -> PV -> BESS -> DEG',
                       'PV -> BESS -> Grid -> DEG']),
        Param('load_priority_split', 'Load Priority Follows Grid Status',
              'bool', False,
              tooltip='Aktif: pilih skenario load priority terpisah untuk saat '
                      'grid tersedia (status 1) dan saat grid padam '
                      '(status 0). Engine memakai skenario status-1 pada jam '
                      'grid menyala dan skenario status-0 pada jam grid padam. '
                      'Nonaktif: satu skenario Load Supply Priority berlaku '
                      'untuk semua jam.'),
        Param('load_priority_on', 'Load Priority — Grid Available (1)',
              'choice', 'Grid -> PV -> BESS -> DEG',
              tooltip='Skenario prioritas beban saat GRID TERSEDIA '
                      '(grid status = 1). Dipakai bila '
                      '"Load Priority Follows Grid Status" aktif.',
              choices=['PV -> Grid -> BESS -> DEG',
                       'Grid -> PV -> BESS -> DEG',
                       'PV -> BESS -> Grid -> DEG']),
        Param('load_priority_off', 'Load Priority — Grid Unavailable (0)',
              'choice', 'PV -> BESS -> DEG',
              tooltip='Skenario prioritas beban saat GRID PADAM '
                      '(grid status = 0). Grid memasok 0 kW sehingga posisi '
                      '"Grid" dalam rantai tak berpengaruh — opsi diringkas ke '
                      'strategi yang benar-benar berbeda (urutan PV/BESS/DEG). '
                      'Saat DEG Interlock with Grid nonaktif, genset dapat naik '
                      'sebelum BESS (PV → DEG → BESS / DEG → PV → BESS). '
                      'Dipakai bila "Load Priority Follows Grid Status" aktif.',
              choices=['PV -> BESS -> DEG',
                       'PV -> DEG -> BESS',
                       'DEG -> PV -> BESS']),
        Param('grid_charge_enabled', 'Allow Grid Charging to BESS', 'bool',
              True, tooltip='Nonaktifkan agar BESS hanya di-charge dari PV; '
                    'grid tidak pernah mengisi baterai (W = 0).'),
        Param('grid_charge_mode', 'Max Grid Charging Mode', 'choice', 'Auto',
              tooltip='Batas daya charge BESS dari Grid. Auto: hanya dibatasi '
              'sisa kapasitas grid (Grid Capacity × Max Loading − beban), daya '
              'charge PCS & SOC. Manual: daya Grid → BESS tidak melebihi nilai '
              'Max Grid Charging Power (kW) di bawah (tetap dibatasi juga oleh '
              'sisa kapasitas grid & PCS).',
              choices=['Auto', 'Manual']),
        Param('grid_charge_max_kw', 'Max Grid Charging Power (kW)', 'float',
              0.0, 'kW', 'Daya maksimum Grid → BESS saat mode Manual (kW). '
              'Isi 0 = grid tidak mengisi BESS.', 0.0, 1e6),
        Param('deg_charge_enabled', 'Allow DEG Charging to BESS', 'bool',
              False, tooltip='Genset menambah output '
                    'Saat genset menyala dengan pembebanan di bawah Minimum Loading, '
                    'kekurangannya dialihkan untuk mengisi BESS sehingga '
                    'genset beroperasi minimal pada minimum loading-nya. '
                    'Hanya berlaku bila DEG Interlock nonaktif (saat '
                    'interlock, bus DEG terpisah dari PV-BESS).'),
        Param('deg_grid_interlock', 'DEG Interlock with Grid', 'bool',
              True, tooltip='Aktif: bus grid dan bus genset saling kunci '
                    '(seperti transfer switch) — keduanya tidak pernah '
                    'memasok beban bersamaan. Bila grid (+PV/BESS) tidak '
                    'sanggup memikul beban, sistem beralih ke genset dan '
                    'grid dilepas. Nonaktif: genset boleh beroperasi '
                    'paralel dengan grid, hanya menutup kekurangan yang '
                    'tidak sanggup dipikul grid.'),
        Param('grid_interlock', 'Grid Interlock with PV-BESS', 'bool',
              False, tooltip='Aktif: beban dilayani Grid ATAU PV-BESS '
                    'secara eksklusif (bus terpisah). PV-BESS dipakai '
                    'bila sanggup memikul seluruh beban jam itu; selain '
                    'itu grid yang memikul dan PV hanya mengisi BESS. '
                    'Nonaktif: grid dan PV-BESS boleh memasok beban '
                    'bersamaan (perilaku standar).'),
        Param('deg_interlock', 'DEG Interlock with PV-BESS', 'bool',
              True, tooltip='Aktif: sumber beban eksklusif — Grid+PV-BESS '
                    'ATAU DEG; saat DEG memikul beban, PV hanya charge ke '
                    'BESS, BESS tidak discharge, dan grid hanya boleh '
                    'charge (bila diizinkan). Nonaktif: DEG hanya menutup '
                    'residu dan boleh paralel dengan PV/BESS/Grid.'),
        Param('deg_sync', 'DEG Can Synchronise', 'bool', True,
              tooltip='Aktif (default): genset boleh paralel & berbagi beban — '
                      'dispatch seperti sekarang. Nonaktif: genset TIDAK dapat '
                      'sinkron — hanya SATU genset menyala pada satu waktu; '
                      'yang terkecil kapasitasnya menyala lebih dulu, dan saat '
                      'mencapai maximum loading ia mati lalu genset lebih besar '
                      'yang menyala, dan seterusnya.'),
        Param('deg_always', 'DEG Must Always Run', 'bool', False,
              tooltip='Aktif: saat GRID PADAM atau proyek TANPA GRID, minimal '
                      'SATU genset (terkecil) WAJIB menyala & melayani beban '
                      'lebih dulu. Bila beban < MINIMUM LOADING: jika "Allow DEG '
                      'Charging to BESS" AKTIF, DEG naik ke minimum loading & '
                      'kelebihannya mengisi BESS (selama SOC < SOC maksimum & PCS '
                      'cukup); jika NONAKTIF, DEG hanya sebesar beban (di bawah '
                      'minimum loading) tanpa mengisi BESS. Saat grid TERSEDIA '
                      'fitur ini tak berpengaruh — DEG bekerja normal. Nonaktif '
                      '(default): DEG hanya menyala saat dibutuhkan.'),
        Param('deg_grid_former', 'Grid-Forming DEG Priority', 'choice', 'Auto',
              choices=['Auto', 'DEG-1', 'DEG-2', 'DEG-3'],
              tooltip='Genset mana yang WAJIB menyala lebih dulu sebagai '
                      'grid-forming saat "DEG Must Always Run" aktif & grid '
                      'padam. "Auto" memilih — tiap jam — genset yang MINIMUM '
                      'LOADING-nya (kapasitas × Lmin) paling dekat ke beban; '
                      'jadi saat beban rendah dipakai genset lebih KECIL agar '
                      'paling mendekati minimum loadingnya (surplus terkecil). '
                      'DEG-1/2/3 = genset tetap. Bila memilih unit 0 kW / tak '
                      'aktif, otomatis kembali ke Auto.'),
        Param('deg_options_split', 'DEG Options Follow Grid Status', 'bool',
              False,
              tooltip='Aktif: atur "DEG Interlock with PV-BESS" dan "Allow DEG '
                      'Charging to BESS" terpisah untuk saat grid tersedia '
                      '(status 1) dan grid padam (status 0). Engine memakai '
                      'setelan status-1 pada jam grid menyala dan setelan '
                      'status-0 pada jam grid padam. Nonaktif: satu setelan '
                      'berlaku untuk semua jam.'),
        Param('deg_interlock_on',
              'DEG Interlock with PV-BESS — Grid Available (1)', 'bool', True,
              tooltip='DEG Interlock with PV-BESS saat GRID TERSEDIA '
                      '(status 1). Dipakai bila "DEG Options Follow Grid '
                      'Status" aktif.'),
        Param('deg_interlock_off',
              'DEG Interlock with PV-BESS — Grid Unavailable (0)', 'bool', True,
              tooltip='DEG Interlock with PV-BESS saat GRID PADAM (status 0). '
                      'Dipakai bila "DEG Options Follow Grid Status" aktif.'),
        Param('deg_charge_on',
              'Allow DEG Charging to BESS — Grid Available (1)', 'bool', False,
              tooltip='Allow DEG Charging to BESS saat GRID TERSEDIA '
                      '(status 1). Otomatis nonaktif bila interlock status-1 '
                      'aktif (bus DEG terpisah).'),
        Param('deg_charge_off',
              'Allow DEG Charging to BESS — Grid Unavailable (0)', 'bool', False,
              tooltip='Allow DEG Charging to BESS saat GRID PADAM (status 0). '
                      'Otomatis nonaktif bila interlock status-0 aktif (bus '
                      'DEG terpisah).'),
        Param('strict_charge_priority', 'Strict Charging Priority', 'bool',
              False, tooltip='Aktif: sumber prioritas kedua MENUNGGU — pada '
                    'PV -> Grid, grid tidak mengisi BESS selama PV masih '
                    'mengisi; pada Grid -> PV sebaliknya. Nonaktif: keduanya '
                    'boleh mengisi bersamaan, berbagi limit PCS & headroom '
                    'SOC menurut urutan prioritas.'),
        Param('charge_priority', 'BESS Charging Priority', 'choice',
              'PV -> Grid',
              tooltip='Sumber energi yang diprioritaskan untuk mengisi BESS '
                      'ketika keduanya tersedia (charge dari grid tetap hanya '
                      'saat SOC di bawah ambang).',
              choices=['PV -> Grid', 'Grid -> PV']),
    ],
    'Diesel': [
        Param('deg_count', 'Total DEG', 'choice', '1',
              tooltip='Jumlah genset aktif', choices=['0', '1', '2', '3']),
        Param('diesel_price_per_l', 'Diesel Price', 'float', 21000.0, 'Rp/L',
              'Harga solar per liter', 0.0, 1e6),
        Param('deg1_kw', 'DEG-1 Capacity', 'float', 30.0, 'kW', '', 0.0, 1e6),
        Param('deg2_kw', 'DEG-2 Capacity', 'float', 0.0, 'kW', '', 0.0, 1e6),
        Param('deg3_kw', 'DEG-3 Capacity', 'float', 0.0, 'kW', '', 0.0, 1e6),
        Param('deg_min_loading', 'Minimum Loading per DEG', 'float', 0.0, '%',
              'Pembebanan minimum tiap genset. Bila Allow DEG Charging to BESS '
              'aktif, genset menambah output untuk mengisi BESS agar '
              'beroperasi minimal pada loading ini', 0.0, 1.0),
        Param('deg_max_loading', 'Maximum Loading per DEG', 'float', 1.0, '%',
              'Batas loading maksimum, asumsi sama untuk semua DEG — dipakai '
              'sebagai ambang eskalasi alokasi genset (AE* ≤ ΣD·Lmax)',
              0.0, 1.2),
        Param('deg1_fuel_rate', 'DEG-1 Fuel Consumption Rate', 'float',
              DEFAULT_FUEL_RATE, 'L/kWh',
              'Laju konsumsi bahan bakar DEG-1 — konversi langsung energi '
              'genset ke liter solar: Fuel (L) = laju × energi DEG (kWh). '
              'Nilai 0,303 setara efisiensi 33% (referensi sebelumnya).',
              0.0, 2.0),
        Param('deg2_fuel_rate', 'DEG-2 Fuel Consumption Rate', 'float',
              DEFAULT_FUEL_RATE, 'L/kWh',
              'Laju konsumsi bahan bakar DEG-2 — Fuel (L) = laju × energi '
              'DEG-2 (kWh). Boleh berbeda dari DEG lain.', 0.0, 2.0),
        Param('deg3_fuel_rate', 'DEG-3 Fuel Consumption Rate', 'float',
              DEFAULT_FUEL_RATE, 'L/kWh',
              'Laju konsumsi bahan bakar DEG-3 — Fuel (L) = laju × energi '
              'DEG-3 (kWh). Boleh berbeda dari DEG lain.', 0.0, 2.0),
        Param('deg_cost_per_kw', 'DEG CAPEX', 'float', 3000000.0, 'Rp/kW',
              'Biaya investasi genset', 0.0, 1e9),
    ],
    'Battery': [
        Param('bess_kwh', 'Nominal Capacity', 'float', 215.0, 'kWh',
              'Kapasitas nominal BESS', 0.0, 1e7),
        Param('soc_init', 'Initial SOC', 'float', 0.5, '%', '', 0.0, 1.0),
        Param('soc_min', 'Minimum SOC', 'float', 0.1, '%', '', 0.0, 1.0),
        Param('soc_max', 'Maximum SOC', 'float', 0.95, '%', '', 0.0, 1.0),
        Param('rte', 'Round Trip Efficiency', 'float', 0.913, '%', '', 0.3, 1.0),
        Param('max_charge_kw', 'Maximum Charge Power', 'float', 108.0, 'kW',
              'Batas daya charge PCS', 0.0, 1e6),
        Param('max_discharge_kw', 'Maximum Discharge Power', 'float', 108.0, 'kW',
              'Batas daya discharge PCS', 0.0, 1e6),
        Param('charge_from_grid_below_soc', 'Charge from Grid below SOC',
              'float', 0.6, '%', 'BESS di-charge dari grid bila SOC < nilai ini',
              0.0, 1.0),
        Param('bess_self_cons_kw', 'Self Consumption', 'float', 0.0, 'kWh/h',
              'Konsumsi sendiri BESS (HVAC, BMS, PCS idle, dll.) dalam kWh per '
              'jam, berlaku sepanjang waktu selama BESS terpasang. Merupakan '
              'beban TAMBAHAN: pembangkitan harus memasok beban + self '
              'consumption. Isi 0 untuk menonaktifkan.', 0.0, 1e6),
        Param('bess_sc_source', 'Self Consumption Supplied by', 'choice',
              'PV+BESS', tooltip=
              'Sumber utama pemasok self consumption BESS. PV+BESS: dipasok PV '
              'lalu discharge BESS lebih dulu; kekurangannya dipasok Grid lalu '
              'DEG. DEG/Grid: dipasok Grid (bila tersedia) lalu DEG lebih dulu; '
              'kekurangannya dipasok kelebihan PV lalu BESS.',
              choices=['PV+BESS', 'DEG/Grid']),
        Param('bess_cost_per_kwh', 'BESS CAPEX', 'float', 6000000.0, 'Rp/kWh',
              'Biaya investasi baterai', 0.0, 1e9),
    ],
    'PV': [
        Param('pv_kwp', 'PV Capacity (DC)', 'float', 37.5, 'kWp',
              'Kapasitas array PV terpasang', 0.0, 1e7),
        Param('pv_module_wp', 'PV Module Rating', 'float', 625.0, 'Wp',
              'Rating modul PV', 100.0, 1000.0),
        Param('pv_inv_kw', 'PV Inverter Capacity (AC)', 'float', 30.0, 'kW',
              '', 0.0, 1e7),
        Param('pv_base_annual', 'Base Profile Plant Size', 'float', 1103.76,
              'kWp', 'Kapasitas pembangkit acuan yang menghasilkan profil PV '
              'ENetAC yang diimpor (dari PVsyst). Output = ENetAC × kWp '
              'desain ÷ nilai ini. Isi 1 bila profil sudah per-kWp.',
              1e-6, 1e9),
        Param('pv_cost_per_kwp', 'PV CAPEX', 'float', 9000000.0, 'Rp/kWp',
              'Biaya investasi PV per kWp', 0.0, 1e9),
        Param('inverter_cost_per_kw', 'Inverter CAPEX', 'float', 1500000.0,
              'Rp/kW', 'Biaya inverter per kW', 0.0, 1e9),
    ],
    'Wind Turbine (WTG)': [
        Param('wtg_enabled', 'WTG Installed', 'bool', False,
              tooltip='Aktifkan pembangkit angin. Data angin (ERA5 atau Excel, '
                      'jenis data & ketinggian ukur) diatur di halaman Data — '
                      'tanpa data angin, produksi 0.'),
        Param('wtg_count', 'Number of Turbines', 'int', 1, 'unit', '', 0, 500),
        Param('wtg_unit_kw', 'Rated Power per Turbine', 'float', 1000.0, 'kW',
              '', 0.0, 1e6),
        Param('wtg_input', 'Wind Data Type', 'choice', 'Wind Speed (m/s)',
              tooltip='Wind Speed: profil kecepatan angin dikonversi lewat '
                      'kurva daya (IEC 61400-12-1). Power Profile: profil '
                      'adalah daya (kW) plant acuan, diskalakan seperti PV.',
              choices=['Wind Speed (m/s)', 'Power Profile (kW)']),
        Param('wtg_base_kw', 'Base Profile Plant Size', 'float', 1000.0, 'kW',
              'Kapasitas plant acuan profil daya WTG (kW).', 1e-6, 1e9),
        Param('wtg_hub_h', 'Hub Height', 'float', 80.0, 'm', '', 1.0, 300.0),
        Param('wtg_meas_h', 'Wind Measurement Height', 'float', 10.0, 'm',
              'Ketinggian pengukuran data angin pada berkas Excel (stasiun '
              'meteo umumnya 10 m). Data ERA5 selalu 100 m (otomatis).',
              1.0, 300.0),
        Param('wtg_shear', 'Wind Shear Exponent', 'float', 0.2, '',
              'Eksponen hukum pangkat profil angin (IEC 61400-1: 0,20 darat; '
              '0,14 lepas pantai).', 0.0, 0.6),
        Param('wtg_vci', 'Cut-in Wind Speed', 'float', 3.0, 'm/s', '', 0.0, 10.0),
        Param('wtg_vr', 'Rated Wind Speed', 'float', 12.0, 'm/s', '', 3.0, 25.0),
        Param('wtg_vco', 'Cut-out Wind Speed', 'float', 25.0, 'm/s', '',
              10.0, 40.0),
        Param('wtg_elev_m', 'Site Elevation', 'float', 0.0, 'm',
              'Elevasi site — untuk koreksi kerapatan udara '
              '(IEC 61400-12-1).', -400.0, 5000.0),
        Param('wtg_temp_c', 'Mean Air Temperature', 'float', 27.0, '°C',
              'Suhu udara rata-rata — untuk koreksi kerapatan udara.',
              -40.0, 55.0),
        Param('wtg_loss', 'Plant Losses', 'float', 0.10, '%',
              'Rugi total plant: wake, kelistrikan, ketersediaan.', 0.0, 0.6),
        Param('wtg_type', 'WTG Type', 'choice', 'Type 4 (Full Converter)',
              tooltip='Tipe generator menurut IEC 61400-27-1 (dipakai '
                      'Transient Analysis & short circuit).',
              choices=['Type 4 (Full Converter)', 'Type 3 (DFIG)']),
        Param('wtg_cost_per_kw', 'WTG CAPEX', 'float', 25000000.0, 'Rp/kW',
              '', 0.0, 1e12),
    ],
    'Steam Turbine (STG)': [
        Param('stg_enabled', 'STG Installed', 'bool', False,
              tooltip='Aktifkan steam turbine generator (unit termal '
                      'must-run). Ketersediaan per jam: kolom "STG Status" '
                      'pada berkas data (0 = tak tersedia) dan/atau jadwal '
                      'jam operasi di bawah.'),
        Param('stg_kw', 'STG Rated Power', 'float', 1000.0, 'kW', '', 0.0, 1e7),
        Param('stg_min_loading', 'Minimum Stable Load', 'float', 0.3, '%',
              'Beban stabil minimum turbin (fraksi rating).', 0.0, 1.0),
        Param('stg_max_loading', 'Maximum Loading', 'float', 1.0, '%',
              'Batas atas pembebanan (steam-limited) terhadap rating.',
              0.0, 1.2),
        Param('stg_priority', 'STG Dispatch Priority', 'choice',
              'STG -> PV/WTG',
              tooltip='STG -> PV/WTG: STG memikul beban lebih dulu '
                      '(baseload, bahan bakar murah); PV/WTG menutup sisanya. '
                      'PV/WTG -> STG: energi terbarukan dulu, STG mengikuti '
                      'beban sisa tetapi tak turun di bawah Minimum Stable '
                      'Load.',
              choices=['STG -> PV/WTG', 'PV/WTG -> STG']),
        Param('stg_charge', 'STG Charging to BESS', 'choice', 'No',
              tooltip='No: STG tak mengisi BESS. Minimum-Loading Surplus: '
                      'saat beban < minimum stabil, STG ditahan di minimum & '
                      'selisihnya mengisi BESS. Spare Capacity: seluruh '
                      'kapasitas cadangan STG boleh mengisi BESS.',
              choices=['No', 'Minimum-Loading Surplus', 'Spare Capacity']),
        Param('stg_ramp_kwmin', 'Loading Rate Limit', 'float', 0.0, 'kW/min',
              'Batas laju kenaikan beban STG (0 = tak dibatasi). Hanya '
              'berpengaruh pada interval simulasi halus.', 0.0, 1e6),
        Param('stg_sched_start', 'Operating Window Start', 'float', 0.0, 'h',
              'Jam mulai STG tersedia tiap hari. Start = End -> 24 jam.',
              0.0, 24.0),
        Param('stg_sched_end', 'Operating Window End', 'float', 0.0, 'h',
              'Jam berakhir STG tersedia tiap hari.', 0.0, 24.0),
        Param('stg_renewable', 'Renewable Fuel (Biomass / Waste Heat)',
              'bool', True,
              tooltip='Aktif: energi STG dihitung sebagai terbarukan pada '
                      'Renewable Fraction.'),
        Param('stg_fuel_cost_per_kwh', 'STG Fuel Cost', 'float', 0.0,
              'Rp/kWh', 'Biaya bahan bakar/uap per kWh listrik STG.',
              0.0, 1e6),
        Param('stg_cost_per_kw', 'STG CAPEX', 'float', 0.0, 'Rp/kW',
              '0 = STG eksisting (tanpa CAPEX baru).', 0.0, 1e12),
    ],
    'Finance': [
        Param('om_fraction', 'O&M Cost', 'float', 0.015, '%CAPEX/yr',
              'Biaya operasi & pemeliharaan tahunan', 0.0, 0.2),
        Param('accessories_cost', 'Accessories Cost', 'float', 0.0, 'Rp',
              'Biaya aksesoris — komponen CAPEX tetap, ditambahkan langsung '
              'ke total CAPEX', 0.0, 1e15),
        Param('logistic_cost', 'Logistic Cost', 'float', 0.0, 'Rp',
              'Biaya logistik — komponen CAPEX tetap, ditambahkan langsung '
              'ke total CAPEX', 0.0, 1e15),
        Param('epc_cost_per_kwp', 'EPC Cost', 'float', 0.0, 'Rp/kWp',
              'Biaya EPC per kWp PV — CAPEX EPC = nilai ini × kapasitas '
              'PV (kWp)', 0.0, 1e9),
        Param('baseline_mode', 'Baseline Comparison', 'choice', 'diesel_only',
              tooltip='Pembanding penghematan: diesel murni atau grid+diesel',
              choices=['diesel_only', 'grid_diesel']),
        Param('finance_scope', 'Financial Analysis', 'choice', 'PV-BESS-DEG',
              tooltip='Batasi LCOE, CAPEX & OPEX (halaman Results & '
              'Optimization Constraints) hanya ke komponen biaya & energi '
              'teknologi terpilih. "DEG" = Diesel genset + Grid (gabungan, '
              'selaras label "DEG/Grid" pada grafik EMS); "PV-BESS" = PV + '
              'Inverter + BESS saja; "PV-BESS-DEG" (baku) = seluruh sistem, '
              'tak berubah dari sebelumnya. Biaya CAPEX tetap (Accessories & '
              'Logistic) selalu diikutkan penuh apa pun pilihannya. NPV, '
              'IRR, ROI, dan Payback TETAP dihitung dari seluruh sistem '
              'terlepas dari pilihan ini.',
              choices=['DEG', 'PV-BESS', 'PV-BESS-DEG']),
    ],
    'Multi-Year (Lifetime)': [
        Param('project_lifetime_y', 'Project Lifetime', 'int', 20, 'yr',
              'Umur proyek untuk analisis finansial', 1, 40),
        Param('discount_rate', 'Discount Rate', 'float', 0.08, '%/yr',
              'Tingkat diskonto untuk NPV & LCOE', 0.0, 0.5),
        Param('inflation', 'Inflation', 'float', 0.03, '%/yr',
              'Eskalasi harga energi tahunan', 0.0, 0.5),
        Param('pv_degradation', 'PV Degradation per Year', 'float', 0.005,
              '%/yr', 'Degradasi tahunan (analisis finansial)', 0.0, 0.05),
        Param('bess_lifetime_y', 'BESS Lifetime', 'int', 10, 'yr',
              'Umur pakai BESS. Setelah mencapai umur ini, BESS diganti baru '
              '(biaya = CAPEX BESS) dan SOH kembali 100%. Isi 0 untuk '
              'menonaktifkan penggantian berbasis umur.', 0, 50),
        Param('bess_soh_threshold', 'BESS SOH Threshold', 'float', 0.7, '%',
              'Ambang State of Health. Bila SOH turun di bawah nilai ini, '
              'BESS diganti baru (biaya = CAPEX BESS) dan SOH kembali 100%. '
              'Isi 0 untuk menonaktifkan penggantian berbasis SOH.', 0.0, 1.0),
        Param('bess_soh_source', 'BESS SOH Model', 'choice',
              'Annual Degradation', tooltip=
              'Cara menentukan SOH BESS per tahun. Annual Degradation: SOH = '
              '(1 − degradasi)^umur. SOH Curve (Excel): SOH per tahun dari '
              'berkas Excel/CSV 2 kolom (kolom 1 = tahun/umur, kolom 2 = SOH).',
              choices=['Annual Degradation', 'SOH Curve (Excel)']),
        Param('bess_degradation', 'BESS Degradation per Year', 'float', 0.02,
              '%/yr', 'Degradasi kapasitas tahunan (analisis finansial)', 0.0, 0.2),
        Param('bess_soh_curve', 'BESS SOH Curve', 'soh_curve', [], tooltip=
              'Tabel SOH per tahun (umur BESS) dari berkas Excel/CSV: kolom '
              'pertama = tahun (End of Year, 0 = baru), kolom kedua = SOH '
              '(mis. 94.2% / 0.942 / 94.2). Umur di antara titik diinterpolasi '
              'linear; di luar tabel diekstrapolasi dengan laju tahun terakhir. '
              'Setelah penggantian BESS, kurva dimulai lagi dari tahun 0.'),
        Param('rte_source', 'BESS RTE Model', 'choice', 'Annual Degradation',
              tooltip='Cara menentukan Round Trip Efficiency (RTE) BESS per '
              'tahun. Annual Degradation: RTE = RTE awal (Battery → Round Trip '
              'Efficiency) × (1 − degradasi RTE)^umur. RTE Curve (Excel): RTE '
              'per tahun dari berkas Excel/CSV 2 kolom (kolom 1 = tahun/umur, '
              'kolom 2 = RTE); nilai tahun 0 dipakai sbg RTE simulasi satu '
              'tahun (Dashboard, Optimization, Results).',
              choices=['Annual Degradation', 'RTE Curve (Excel)']),
        Param('rte_degradation', 'RTE Degradation per Year', 'float', 0.0,
              '%/yr', 'Degradasi relatif RTE BESS per tahun (umur unit). Isi 0 '
              'agar RTE tetap sepanjang umur proyek.', 0.0, 0.2),
        Param('rte_curve', 'BESS RTE Curve', 'rte_curve', [], tooltip=
              'Tabel RTE per tahun (umur BESS) dari berkas Excel/CSV: kolom '
              'pertama = tahun (End of Year, 0 = baru), kolom kedua = RTE '
              '(mis. 89.5% / 0.895 / 89.5). Umur di antara titik diinterpolasi '
              'linear; di luar tabel diekstrapolasi dengan laju tahun terakhir. '
              'Setelah penggantian BESS, kurva dimulai lagi dari tahun 0.'),
    ],
    # ===== Transient Analysis (ditampilkan di halaman Transient) =====
    'Transient — System and Load': [
        Param('tr_f_nom', 'Nominal Frequency', 'choice', '50', 'Hz',
              choices=['50', '60']),
        Param('tr_bus_kv', 'Bus Voltage', 'float', 0.4, 'kV', '', 0.1, 150.0),
        Param('tr_load_kw', 'Study Load', 'float', 0.0, 'kW',
              'Beban dasar studi. 0 = Auto (beban puncak profil). Tidak '
              'dipakai bila data PQA diimpor — beban sistem seluruhnya dari '
              'PQA.', 0.0, 1e7),
        Param('tr_load_pf', 'Load Power Factor', 'float', 0.9, '', '', 0.5, 1.0),
        Param('tr_load_kpv', 'Load P–V Exponent', 'float', 1.0, '',
              'P ∝ V^kpv (0 = daya konstan, 1 = arus konstan, 2 = impedansi '
              'konstan).', 0.0, 3.0),
        Param('tr_load_kpf', 'Load P–f Sensitivity', 'float', 1.0, 'pu/pu',
              'P ∝ (1 + kpf·Δf/f). Beban kipas/pompa 1–2.', 0.0, 4.0),
        Param('tr_motor_frac', 'Running Motor Share of Load', 'float', 0.5,
              '%', 'Porsi beban berupa motor induksi yang sedang berjalan.',
              0.0, 0.95),
        Param('tr_motor_kw', 'Largest DOL Motor', 'float', 0.0, 'kW',
              'Motor direct-on-line terbesar untuk kasus motor starting. '
              '0 = Auto: dari lonjakan arus setengah-siklus PQA bila ada, '
              'selain itu 15 % beban studi.', 0.0, 1e6),
        Param('tr_motor_lrc', 'Locked-Rotor Current', 'float', 6.5, '× FLC',
              '', 2.0, 10.0),
        Param('tr_motor_h', 'Motor Inertia H', 'float', 1.0, 's', '', 0.1, 10.0),
        Param('tr_feeder_m', 'Faulted Feeder Length', 'float', 50.0, 'm',
              '', 0.0, 5000.0),
        Param('tr_feeder_mm2', 'Faulted Feeder Size', 'float', 120.0, 'mm²',
              '', 1.5, 1000.0),
        Param('tr_t_clear_ms', 'Fault Clearing Time', 'float', 150.0, 'ms',
              '', 20.0, 2000.0),
        Param('tr_icu_ka', 'Switchgear Breaking Capacity', 'float', 50.0,
              'kA', '', 1.0, 200.0),
    ],
    'Transient — Sources': [
        _hdr('__hdr_tr_grid', 'Utility Grid'),
        Param('tr_grid_sc_mva', 'Short-Circuit Level at PCC', 'float', 10.0,
              'MVA', 'Tingkat hubung singkat tiga-fasa di titik sambung.',
              0.01, 1e6),
        Param('tr_grid_xr', 'Utility Grid X/R', 'float', 5.0, '', '', 0.1, 50.0),
        _hdr('__hdr_tr_stg', 'Steam Turbine Generator'),
        Param('tr_stg_pf', 'STG Rated Power Factor', 'float', 0.85, '',
              'kVA alternator = kW / PF.', 0.5, 1.0),
        Param('tr_stg_h', 'STG Inertia H', 'float', 1.5, 's',
              'Konstanta inersia turbin+alternator (MW·s/MVA).', 0.2, 12.0),
        Param('tr_stg_xd1', "STG X'd", 'float', 0.22, 'pu', '', 0.05, 1.0),
        Param('tr_stg_xd2', "STG X''d", 'float', 0.13, 'pu', '', 0.03, 0.6),
        Param('tr_stg_xd', 'STG Xd', 'float', 1.9, 'pu', '', 0.5, 3.5),
        Param('tr_stg_td0', "STG T'd0", 'float', 3.0, 's', '', 0.3, 15.0),
        Param('tr_stg_droop', 'STG Governor Droop', 'float', 0.04, '%',
              '', 0.0, 0.2),
        Param('tr_stg_droop_t', 'STG Transient Droop', 'float', 0.16, '%',
              'Droop transien governor (kompensasi, mis. Woodward UG; reset '
              '5 s). Isi ≤ droop tunak untuk droop murni tanpa kompensasi.',
              0.0, 1.0),
        Param('tr_stg_tg', 'STG Governor/Valve Tg', 'float', 0.15, 's',
              '', 0.01, 5.0),
        Param('tr_stg_tt', 'STG Steam-Chest Tt', 'float', 0.3, 's',
              'Konstanta waktu steam chest/inlet (IEEE TGOV1 T1/T_CH).',
              0.01, 10.0),
        Param('tr_stg_steam_drop', 'Steam Shortfall Event', 'float', 0.2,
              '%', 'Penurunan kemampuan STG pada kasus boiler pressure drop '
              '(fraksi dari output).', 0.0, 1.0),
        _hdr('__hdr_tr_deg', 'Diesel Generator'),
        Param('tr_deg_pf', 'DEG Rated Power Factor', 'float', 0.8, '',
              '', 0.5, 1.0),
        Param('tr_deg_h', 'DEG Inertia H', 'float', 1.0, 's', '', 0.2, 6.0),
        Param('tr_deg_xd1', "DEG X'd", 'float', 0.20, 'pu', '', 0.05, 1.0),
        Param('tr_deg_xd2', "DEG X''d", 'float', 0.12, 'pu', '', 0.03, 0.6),
        Param('tr_deg_droop', 'DEG Governor Droop', 'float', 0.03, '%',
              '', 0.0, 0.2),
        Param('tr_deg_droop_t', 'DEG Transient Droop', 'float', 0.10, '%',
              'Droop transien governor diesel (reset 1,5 s).', 0.0, 1.0),
        Param('tr_deg_tg', 'DEG Actuator Tg', 'float', 0.05, 's', '',
              0.01, 2.0),
        Param('tr_deg_tt', 'DEG Engine Tt', 'float', 0.2, 's', '', 0.01, 5.0),
    ],
    'Transient — Converters': [
        _hdr('__hdr_tr_pcs', 'BESS PCS'),
        Param('tr_pcs_mode', 'PCS Control', 'choice', 'Grid-Forming (VSG)',
              choices=['Grid-Forming (VSG)', 'Grid-Following']),
        Param('tr_pcs_kva', 'PCS Rating', 'float', 0.0, 'kVA',
              '0 = Auto (Max Discharge Power / 0,9, atau PCS Apparent Power '
              'bila diisi).', 0.0, 1e7),
        Param('tr_vsg_h', 'Virtual Inertia H', 'float', 3.0, 's', '',
              0.1, 20.0),
        Param('tr_vsg_droop', 'P–f Droop', 'float', 0.01, '%', '',
              0.001, 0.1),
        Param('tr_vsg_xv', 'Virtual Reactance', 'float', 0.10, 'pu', '',
              0.02, 0.5),
        Param('tr_vsg_qv', 'Q–V Droop', 'float', 0.04, '%', '', 0.0, 0.2),
        Param('tr_pcs_ilim1', 'Current Limit — Short Time', 'float', 1.3,
              'pu', '', 1.0, 3.0),
        Param('tr_pcs_t1', 'Short-Time Duration', 'float', 10.0, 's', '',
              0.1, 600.0),
        Param('tr_pcs_ilim2', 'Current Limit — Continuous', 'float', 1.1,
              'pu', '', 1.0, 2.0),
        _hdr('__hdr_tr_ibr', 'PV Inverter & WTG Converter'),
        Param('tr_ibr_ilim', 'Converter Current Limit', 'float', 1.1, 'pu',
              '', 1.0, 2.0),
        Param('tr_ibr_k', 'LVRT Reactive Current Gain K', 'float', 2.0,
              'pu/pu', 'Arus reaktif tambahan per pu penurunan tegangan '
              '(IEC 61400-27-1 / grid code).', 0.0, 6.0),
        Param('tr_ibr_recov', 'Active Power Recovery Rate', 'float', 2.0,
              'pu/s', 'Laju pemulihan daya aktif pasca-gangguan.', 0.1, 50.0),
        Param('tr_re_drop', 'Renewable Loss Event', 'float', 0.7, '%',
              'Porsi PV/WTG yang hilang pada kasus awan/gust.', 0.0, 1.0),
        Param('tr_re_ramp_s', 'Renewable Loss Ramp Time', 'float', 5.0, 's',
              '', 0.0, 600.0),
        _hdr('__hdr_tr_crit', 'Acceptance Criteria'),
        Param('tr_f_lo', 'Frequency Minimum', 'float', 47.5, 'Hz', '',
              40.0, 60.0),
        Param('tr_f_hi', 'Frequency Maximum', 'float', 51.5, 'Hz', '',
              50.0, 66.0),
        Param('tr_v_lo', 'Voltage Minimum (transient)', 'float', 0.8, 'pu',
              '', 0.3, 1.0),
        Param('tr_rocof', 'RoCoF Limit', 'float', 2.0, 'Hz/s', '', 0.1, 20.0),
    ],
    'Optimization Constraints': [
        Param('max_pv_excess_ratio', 'Maximum Unused Energy (Curtailment)',
              'float', 1.0, '%',
              'Rasio energi PV tak terpakai terhadap produksi ENetAC — '
              'istilah PVsyst: Unused Energy / EUnused (ENetAC yang tidak '
              'tersalurkan melalui inverter)', 0.0, 1.0),
        Param('min_renewable_fraction', 'Minimum Renewable Fraction', 'float',
              0.0, '%', 'Fraksi beban dilayani PV+BESS', 0.0, 1.0),
        Param('max_lcoe', 'Maximum LCOE', 'float', 0.0, 'Rp/kWh',
              '0 = tidak dibatasi', 0.0, 1e6),
        Param('max_capex', 'Maximum CAPEX', 'float', 0.0, 'Rp',
              '0 = tidak dibatasi', 0.0, 1e15),
        Param('max_diesel_fuel_l', 'Maximum Diesel Consumption', 'float', 0.0,
              'L/yr', '0 = tidak dibatasi', 0.0, 1e9),
        Param('target_diesel_reduction', 'Target Diesel Reduction', 'float',
              0.0, '%', 'Reduksi fuel vs skenario diesel-only', 0.0, 1.0),
    ],
}


# =============================================================================
# v163 — penataan ulang section & parameter baru (GTG, prioritas dispatch,
# referensi grid-following, sumber beban studi). Dilakukan PROGRAMATIK di atas
# literal SCHEMA agar definisi lama tidak perlu dipindah-tangan:
#   * Utility Grid : + Allow Grid Charging to BESS, mode & batas dayanya
#   * Diesel       : + Allow DEG Charging to BESS, DEG Must Always Run,
#                      Grid-Forming DEG Priority
#   * Dispatch Strategy : + WTG / STG / GTG Dispatch Priority dan dua baris
#                      informasi urutan EFEKTIF (seluruh pembangkit aktif);
#                      interlock, load supply priority & charging priority tetap.
# =============================================================================
def _take(key: str) -> Param:
    for _g in SCHEMA.values():
        for _i, _p in enumerate(_g):
            if _p.key == key:
                return _g.pop(_i)
    raise KeyError(key)


def _put(group: str, params, after: str | None = None):
    g = SCHEMA[group]
    idx = len(g)
    if after is not None:
        idx = next(i for i, _p in enumerate(g) if _p.key == after) + 1
    for k, _p in enumerate(params):
        g.insert(idx + k, _p)


_put('Grid', [_take('grid_charge_enabled'), _take('grid_charge_mode'),
              _take('grid_charge_max_kw')], after='allow_export')
_put('Diesel', [_take('deg_charge_enabled'), _take('deg_always'),
                _take('deg_grid_former')], after='deg_max_loading')
# v164 — SATU konsep: "Load Supply Order". Semua pembangkit (PV, WTG, STG, GTG,
# Utility Grid, BESS, DEG) MEMASOK BEBAN. Dropdown 'Load Supply Priority'
# mengatur urutan PV / Utility Grid / BESS / DEG; tiga baris di bawahnya
# menentukan POSISI WTG, STG, GTG di dalam urutan yang SAMA (bukan konsep
# "dispatch priority" terpisah). Baris hasil menampilkan urutan lengkapnya.
_WTG_POS = ['Shared with PV (pro-rata)', 'After PV', 'Before PV']
_TH_POS = ['Before PV/WTG (baseload)', 'After PV/WTG (follows load)']
_stgp = _take('stg_priority')
_stgp.label = 'STG Position in Load Supply'
_stgp.choices = list(_TH_POS)
_stgp.default = _TH_POS[0]
_stgp.tooltip = ('Posisi STG dalam urutan suplai beban. Before PV/WTG '
                 '(baseload): STG memasok beban lebih dulu, PV/WTG menutup '
                 'sisanya. After PV/WTG (follows load): PV/WTG memasok beban '
                 'lebih dulu, STG menutup sisanya tetapi tak turun di bawah '
                 'Minimum Stable Load.')
_put('Dispatch Strategy', [
    Param('wtg_priority', 'WTG Position in Load Supply', 'choice', _WTG_POS[0],
          tooltip='Posisi WTG terhadap PV dalam urutan suplai beban. Shared '
                  'with PV: PV dan WTG memasok beban bersama, sebanding daya '
                  'tersedia. After PV: PV dipakai lebih dulu (WTG di-curtail '
                  'lebih dulu saat berlebih). Before PV: WTG dipakai lebih '
                  'dulu.',
          choices=list(_WTG_POS)),
    _stgp,
    Param('gtg_priority', 'GTG Position in Load Supply', 'choice', _TH_POS[1],
          tooltip='Posisi GTG dalam urutan suplai beban. Before PV/WTG '
                  '(baseload): GTG memasok beban lebih dulu, PV/WTG menutup '
                  'sisanya. After PV/WTG (follows load): PV/WTG memasok beban '
                  'lebih dulu, GTG menutup sisanya tetapi tak turun di bawah '
                  'Minimum Stable Load. STG selalu sebelum GTG.',
          choices=list(_TH_POS)),
    Param('__info_load_order', 'Resulting Load Supply Order', 'heading', ''),
], after='load_priority_off')


def _is_re_first(v) -> bool:
    """Posisi unit termal: True = setelah PV/WTG. Menerima nilai lama
    ('PV/WTG -> STG') maupun baru ('After PV/WTG …')."""
    u = str(v or '').strip().upper()
    return u.startswith('PV') or u.startswith('AFTER')


def _wtg_pos_code(v) -> float:
    """0 = bersama PV (pro-rata), 1 = PV dulu, 2 = WTG dulu."""
    u = str(v or '').strip().upper()
    if u.startswith('PV') or u.startswith('AFTER'):
        return 1.0
    if u.startswith('WTG') or u.startswith('BEFORE'):
        return 2.0
    return 0.0


# v164 — deskripsi DATA angin dipindah dari section WTG ke halaman Data
# (sumber data angin), agar tidak diisi dua kali. Section WTG tinggal memuat
# data TURBIN (kapasitas, hub, kurva daya, rugi, tipe).
SCHEMA['Data — Wind'] = [_take('wtg_input'), _take('wtg_meas_h'),
                         _take('wtg_base_kw')]
_put('Dispatch Strategy', [
    Param('__info_chg_order', 'Effective BESS Charging Order', 'heading', ''),
], after='charge_priority')

# v165 — PERINGKAT BERNOMOR. Urutan suplai beban & charging BESS diatur dengan
# nomor prioritas per sumber (1 = pertama). Kunci lama (load_priority,
# load_priority_on/off, wtg/stg/gtg_priority, charge_priority) tetap menjadi
# sumber kebenaran yang dibaca engine, tetapi TIDAK lagi ditampilkan; baris
# bernomor adalah tampilan/penyunting di atasnya (lihat apply_rank()).
RANK_SRC = ('pv', 'wtg', 'stg', 'gtg', 'grid', 'bess', 'deg')
SRC_LABEL = {'pv': 'PV', 'wtg': 'WTG', 'stg': 'STG', 'gtg': 'GTG',
             'grid': 'Grid', 'bess': 'BESS', 'deg': 'DEG'}
RANK_LISTS = ('lsr', 'lsr_on', 'lsr_off', 'chr')
HIDDEN_KEYS = {'load_priority', 'load_priority_on', 'load_priority_off',
               'wtg_priority', 'stg_priority', 'gtg_priority',
               'charge_priority'}
_RANK_TIP_LOAD = ('Nomor prioritas suplai beban tiap sumber (1 = memasok beban '
                  'lebih dulu). PV dan WTG boleh bernomor sama = berbagi '
                  'pro-rata. Batasan engine: STG/GTG selalu sebelum Utility '
                  'Grid, BESS dan DEG (unit termal dijadwalkan lebih dulu); '
                  'BESS selalu setelah PV/WTG; urutan Utility Grid / BESS / '
                  'DEG mengikuti kombinasi yang didukung dan opsi interlock. '
                  'Bila nomor yang diminta tidak didukung, urutan terdekat '
                  'yang didukung diterapkan.')
_RANK_TIP_CHG = ('Nomor prioritas sumber pengisi BESS (1 = mengisi lebih '
                 'dulu). Hanya sumber yang diizinkan mengisi BESS yang '
                 'tampil (STG/GTG: Charging to BESS = Spare Capacity; Utility '
                 'Grid & DEG: opsi charging di section masing-masing). PV dan '
                 'WTG boleh bernomor sama = pro-rata. Batasan engine: Utility '
                 'Grid hanya bisa sebelum atau sesudah SELURUH pembangkit di '
                 'bus; DEG selalu terakhir (hanya surplus minimum loading); '
                 'surplus minimum-loading STG/GTG selalu diserap lebih dulu.')


def is_rank_key(key: str) -> bool:
    return any(key.startswith(_l + '_') and key[len(_l) + 1:] in RANK_SRC
               for _l in RANK_LISTS)


def _rank_rows(prefix, title, tip, srcs):
    rows = [Param('__hdr_' + prefix, title, 'heading', '', tooltip=tip)]
    for s in srcs:
        rows.append(Param(f'{prefix}_{s}',
                          'Utility Grid' if s == 'grid' else SRC_LABEL[s],
                          'choice', '1',
                          tooltip=tip,
                          choices=[str(i) for i in range(1, 8)]))
    return rows


_put('Dispatch Strategy', _rank_rows(
    'lsr', 'Load Supply Priority (1 = first)', _RANK_TIP_LOAD, RANK_SRC),
    after='__hdr_base_dispatch')
_put('Dispatch Strategy', _rank_rows(
    'lsr_on', 'Load Supply Priority — Grid Available (1)', _RANK_TIP_LOAD,
    RANK_SRC) + _rank_rows(
    'lsr_off', 'Load Supply Priority — Grid Unavailable (0)', _RANK_TIP_LOAD,
    tuple(s for s in RANK_SRC if s != 'grid')), after='load_priority_split')
_put('Dispatch Strategy', _rank_rows(
    'chr', 'BESS Charging Priority (1 = first)', _RANK_TIP_CHG,
    tuple(s for s in RANK_SRC if s != 'bess')), after='strict_charge_priority')

_GTG_GROUP = [
    Param('gtg_enabled', 'GTG Installed', 'bool', False,
          tooltip='Aktifkan gas turbine generator. Ketersediaan per jam: '
                  'kolom "GTG Status" pada berkas data (0 = tak tersedia) '
                  'dan/atau jendela jam operasi di bawah.'),
    Param('gtg_kw', 'GTG Rated Power', 'float', 1000.0, 'kW',
          'Daya nominal pada kondisi site (derating suhu/elevasi sudah '
          'diperhitungkan).', 0.0, 1e7,
          basis='ISO 3977-2 / ISO 2314: rating at site conditions (ISO '
                'rating is at 15 °C, 101.3 kPa, 60 % RH)'),
    Param('gtg_commit', 'GTG Commitment', 'choice', 'On Demand',
          tooltip='Must-Run: GTG selalu menyala saat tersedia (minimal di '
                  'Minimum Stable Load). On Demand: GTG hanya menyala bila '
                  'beban yang harus dipikulnya ≥ Minimum Stable Load; di '
                  'bawah itu GTG mati dan beban diteruskan ke BESS / Utility '
                  'Grid / DEG.',
          choices=['Must-Run', 'On Demand']),
    Param('gtg_min_loading', 'Minimum Stable Load', 'float', 0.4, '%',
          'Beban stabil minimum (batas emisi/stabilitas pembakaran).',
          0.0, 1.0,
          basis='No IEC value; typical 40–50 % for DLN industrial gas '
                'turbines (emissions-compliant turndown), 20–30 % diffusion '
                'combustors'),
    Param('gtg_max_loading', 'Maximum Loading', 'float', 1.0, '%', '',
          0.0, 1.2),
    Param('gtg_charge', 'GTG Charging to BESS', 'choice', 'No',
          tooltip='No: GTG tak mengisi BESS. Minimum-Loading Surplus: saat '
                  'beban < minimum stabil, GTG ditahan di minimum & '
                  'selisihnya mengisi BESS. Spare Capacity: seluruh kapasitas '
                  'cadangan GTG boleh mengisi BESS.',
          choices=['No', 'Minimum-Loading Surplus', 'Spare Capacity']),
    Param('gtg_ramp_kwmin', 'Loading Rate Limit', 'float', 0.0, 'kW/min',
          'Batas laju kenaikan beban GTG (0 = tak dibatasi).', 0.0, 1e6),
    Param('gtg_sched_start', 'Operating Window Start', 'float', 0.0, 'h',
          'Jam mulai GTG tersedia tiap hari. Start = End -> 24 jam.',
          0.0, 24.0),
    Param('gtg_sched_end', 'Operating Window End', 'float', 0.0, 'h',
          'Jam berakhir GTG tersedia tiap hari.', 0.0, 24.0),
    Param('gtg_heat_rate', 'Heat Rate (LHV)', 'float', 12000.0, 'kJ/kWh',
          'Konsumsi panas spesifik pada beban operasi (LHV).', 5000.0, 30000.0,
          decimals=0,
          basis='ISO 2314 acceptance-test definition; 11 000–13 000 kJ/kWh '
                'typical for 1–10 MW simple-cycle units (28–33 % efficiency)'),
    Param('gas_price_per_mmbtu', 'Gas Price', 'float', 100000.0, 'Rp/MMBTU',
          '', 0.0, 1e9, decimals=0),
    Param('gtg_cost_per_kw', 'GTG CAPEX', 'float', 0.0, 'Rp/kW',
          '0 = GTG eksisting (tanpa CAPEX baru).', 0.0, 1e12),
]
_new = {}
for _name, _grp in SCHEMA.items():
    _new[_name] = _grp
    if _name == 'Steam Turbine (STG)':
        _new['Gas Turbine (GTG)'] = _GTG_GROUP
SCHEMA.clear()
SCHEMA.update(_new)

_put('Transient — System and Load', [
    Param('tr_load_source', 'Study Load Source', 'choice', 'Manual / Profile Peak',
          tooltip='Statistik beban PQA yang dipakai sebagai beban studi '
                  '(Maximum / 95th Percentile / Mean). Bila data PQA diimpor, '
                  'beban sistem, faktor daya, dan step beban seluruhnya '
                  'diambil dari PQA.',
          choices=['Manual / Profile Peak', 'PQA — Maximum',
                   'PQA — 95th Percentile', 'PQA — Mean']),
], after='tr_load_kw')
_put('Transient — Sources', [
    _hdr('__hdr_tr_gtg', 'Gas Turbine Generator'),
    Param('tr_gtg_pf', 'GTG Rated Power Factor', 'float', 0.8, '', '', 0.5, 1.0),
    Param('tr_gtg_h', 'GTG Inertia H', 'float', 3.0, 's',
          'Konstanta inersia turbin+kompresor+alternator.', 0.5, 12.0),
    Param('tr_gtg_xd1', "GTG X'd", 'float', 0.25, 'pu', '', 0.05, 1.0),
    Param('tr_gtg_xd2', "GTG X''d", 'float', 0.15, 'pu', '', 0.03, 0.6),
    Param('tr_gtg_droop', 'GTG Governor Droop', 'float', 0.04, '%', '',
          0.0, 0.2),
    Param('tr_gtg_tg', 'GTG Fuel-Valve Tg', 'float', 0.4, 's',
          'Konstanta waktu sistem bahan bakar/katup (GAST T1).', 0.01, 5.0),
    Param('tr_gtg_tt', 'GTG Combustor/Turbine Tt', 'float', 0.1, 's',
          'Konstanta waktu pembakaran & turbin (GAST T2).', 0.01, 5.0),
], after='tr_stg_steam_drop')
_put('Transient — Converters', [
    Param('tr_gfl_ref', 'Grid-Following Reference Source', 'choice', 'Auto',
          tooltip='Sumber yang dianggap sebagai "grid" oleh PCS mode '
                  'Grid-Following (acuan PLL & izin operasi). Auto: sumber '
                  'pembentuk tegangan mana pun yang tersambung. Bila sumber '
                  'acuan ini lepas, PCS bertindak sesuai "On Loss of '
                  'Reference" — walau sumber lain masih memegang bus.',
          choices=['Auto', 'Utility Grid', 'STG', 'GTG', 'DEG']),
    Param('tr_gfl_loss', 'On Loss of Reference', 'choice',
          'Trip (anti-islanding)',
          tooltip='Tindakan PCS Grid-Following saat sumber acuannya lepas. '
                  'Trip: PCS berhenti (anti-islanding). Switch to '
                  'Grid-Forming: PCS beralih ke mode VSG setelah waktu '
                  'deteksi dan memegang bus.',
          choices=['Trip (anti-islanding)', 'Switch to Grid-Forming']),
    Param('tr_gfl_detect_ms', 'Loss-of-Reference Detection Time', 'float',
          150.0, 'ms', '', 10.0, 2000.0,
          basis='IEC 62116 islanding-detection test: disconnection within '
                '2 s; fast transfer schemes use 100–200 ms'),
], after='tr_pcs_mode')

# Dasar standar nilai default (per item). Bila IEC tidak menetapkan angka,
# hal itu dinyatakan terang-terangan beserta sumber nilai tipikalnya.
_BASIS = {
    'tr_f_nom': 'IEC 60196: standard frequencies 50 Hz / 60 Hz',
    'tr_bus_kv': 'IEC 60038: 230/400 V standard LV system voltage',
    'tr_load_pf': 'No IEC value; site measurement (PQA) governs. 0.90 '
                  'typical uncompensated industrial load',
    'tr_load_kpv': 'No IEC value; IEEE Task Force on Load Representation: '
                   '1 = constant current (mixed load)',
    'tr_load_kpf': 'No IEC value; IEEE load-model surveys: 0–3, about 1 for '
                   'mixed industrial load',
    'tr_motor_frac': 'No IEC value; site-specific (process plants 50–70 %)',
    'tr_motor_lrc': 'IEC 60034-12 Design N: locked-rotor apparent power ≤ '
                    '10–13 kVA/kW (about 8–9 × FLC max); 6.5 typical',
    'tr_motor_h': 'No IEC value; motor + driven load 0.5–2 s typical',
    'tr_feeder_mm2': 'IEC 60228 class 2 copper: 0.153 Ω/km at 20 °C for '
                     '120 mm² (hot-conductor value used for minimum fault, '
                     'IEC 60909-0)',
    'tr_feeder_m': 'IEC 60909-0: fault at the remote end of the feeder '
                   'gives the minimum fault current',
    'tr_t_clear_ms': 'IEC 60364-4-41: disconnection ≤ 0.4 s (TN, 230 V); '
                     'short-time LSIG stage 0.1–0.2 s per IEC 60947-2',
    'tr_icu_ka': 'IEC 60947-2 / IEC 61439-1 preferred rating; verify '
                 'against IEC 60909-0 maximum fault',
    'tr_grid_sc_mva': 'IEC 60909-0: S″kQ at the connection point — to be '
                      'obtained from the utility',
    'tr_grid_xr': 'IEC 60909-0: RQ/XQ = 0.1 (X/R = 10) above 35 kV; MV/LV '
                  'feeders 3–7',
    'tr_stg_pf': 'IEC 60034-3: rated power factor 0.8–0.85 for turbine-type '
                 'synchronous machines',
    'tr_stg_h': 'No IEC value; small industrial steam sets 1–3 s',
    'tr_stg_xd1': 'IEC 60034-4 test-determined quantity; typical 0.20–0.30 pu '
                  'for 2/4-pole machines',
    'tr_stg_xd2': 'IEC 60034-4; IEC 60909-0 uses X″d (saturated) — typical '
                  '0.12–0.20 pu',
    'tr_stg_xd': 'IEC 60034-4; typical 1.6–2.2 pu (cylindrical rotor)',
    'tr_stg_td0': 'IEC 60034-4; typical 3–8 s',
    'tr_stg_droop': 'IEC 60045-1: speed-governing droop adjustable, '
                    'typically 3–5 %',
    'tr_stg_droop_t': 'No IEC value; mechanical-hydraulic governor '
                      'compensation (vendor data)',
    'tr_stg_tg': 'No IEC value; IEEE PES-TR1 TGOV1 valve/servo 0.1–0.3 s',
    'tr_stg_tt': 'No IEC value; IEEE PES-TR1 steam-chest 0.2–0.5 s',
    'tr_deg_pf': 'ISO 8528-1 / IEC 60034-22: rated power factor 0.8 lagging',
    'tr_deg_h': 'No IEC value; diesel sets 0.5–1.5 s',
    'tr_deg_xd1': 'IEC 60034-4; salient-pole generating-set alternators '
                  '0.15–0.25 pu',
    'tr_deg_xd2': 'IEC 60034-4 / IEC 60909-0; typical 0.10–0.15 pu',
    'tr_deg_droop': 'ISO 8528-5: frequency droop ≤ 5 % (G2), ≤ 3 % (G3)',
    'tr_gtg_pf': 'IEC 60034-3: rated power factor 0.8–0.85',
    'tr_gtg_h': 'No IEC value; single-shaft industrial gas turbines 3–6 s, '
                'aeroderivative 1–2 s',
    'tr_gtg_xd1': 'IEC 60034-4; 2-pole turbo-alternators 0.20–0.30 pu',
    'tr_gtg_xd2': 'IEC 60034-4 / IEC 60909-0; typical 0.12–0.20 pu',
    'tr_gtg_droop': 'ISO 3977-2: governor droop typically 4 % (adjustable '
                    '2–6 %)',
    'tr_gtg_tg': 'No IEC value; IEEE PES-TR1 GAST T1 = 0.4 s',
    'tr_gtg_tt': 'No IEC value; IEEE PES-TR1 GAST T2 = 0.1 s',
    'tr_pcs_ilim1': 'IEC 62933-2-1 (rated/short-duration power to be '
                    'declared); 1.2–1.5 pu for 10 s typical grid-forming PCS',
    'tr_pcs_ilim2': 'IEC 62477-1 / IEC 62933-2-1: continuous rating; 1.1 pu '
                    'overload margin typical',
    'tr_vsg_h': 'No IEC value; virtual inertia 2–5 s typical',
    'tr_vsg_droop': 'No IEC value; IEC TS 62898-3-1 (microgrid protection '
                    'and dynamic control) — droop per design, 0.5–2 %',
    'tr_vsg_qv': 'No IEC value; 2–5 % typical (matches generator AVR droop)',
    'tr_ibr_ilim': 'IEC 61400-27-1 / IEC 62109: converter current limit '
                   '1.0–1.2 pu',
    'tr_ibr_k': 'IEC 61400-27-1 reactive-current injection model; K = 2 is '
                'the common grid-code value (range 0–6)',
    'tr_ibr_recov': 'IEC 61400-21-1 measured quantity; grid codes require '
                    'recovery within 1 s (≥ 1 pu/s)',
    'tr_f_lo': 'IEC 60034-1 Zone B: −5 % frequency (47.5 Hz at 50 Hz)',
    'tr_f_hi': 'IEC 60034-1 Zone B: +3 % frequency (51.5 Hz at 50 Hz)',
    'tr_v_lo': 'ISO 8528-5 class G2: transient voltage deviation −20 %; '
               'IEC 60947-4-1 contactors hold in down to 75 % Us',
    'tr_rocof': 'No IEC limit; EN 50549-1 / IEC TS 62786 immunity 2 Hz/s',
    'wtg_shear': 'IEC 61400-1: normal wind profile exponent 0.2 '
                 '(IEC 61400-3-1 offshore 0.14)',
    'wtg_vci': 'IEC 61400-12-1 power-curve data; 3–4 m/s typical',
    'wtg_vr': 'IEC 61400-12-1 power-curve data; 11–13 m/s typical',
    'wtg_vco': 'IEC 61400-1 design value; 25 m/s typical',
    'stg_min_loading': 'IEC 60045-1: minimum load to be agreed; 25–35 % '
                       'typical back-pressure/condensing sets',
}
for _g in SCHEMA.values():
    for _p in _g:
        if not _p.basis and _p.key in _BASIS:
            _p.basis = _BASIS[_p.key]


LANG_DEFAULT = 'ID'


def defaults() -> dict:
    d = {p.key: (list(p.default) if isinstance(p.default, list) else p.default)
         for group in SCHEMA.values() for p in group
         if p.dtype != 'heading'      # judul sub-bagian bukan parameter
         and not is_rank_key(p.key)}  # baris bernomor = tampilan, bukan cfg
    d['language'] = LANG_DEFAULT      # tidak ditampilkan di halaman Parameters
    return d


def deg_fuel_rates(cfg: dict) -> tuple:
    """Laju konsumsi bahan bakar per-DEG (L/kWh) sebagai (r1, r2, r3).

    Fuel (L) = laju × energi DEG (kWh) — konversi langsung, tanpa faktor kalor.
    Kompatibel-mundur: bila config lama hanya punya `deg_efficiency`, laju
    diturunkan sebagai 1/(eff × 10) agar hasil identik dengan model lama.
    """
    if any(k in cfg for k in
           ('deg1_fuel_rate', 'deg2_fuel_rate', 'deg3_fuel_rate')):
        r1 = float(cfg.get('deg1_fuel_rate', DEFAULT_FUEL_RATE))
        r2 = float(cfg.get('deg2_fuel_rate', r1))
        r3 = float(cfg.get('deg3_fuel_rate', r1))
        return (r1, r2, r3)
    try:
        eff = float(cfg.get('deg_efficiency', 0.33)) or 0.33
    except (TypeError, ValueError):
        eff = 0.33
    r = 1.0 / (eff * 10.0)
    return (r, r, r)


def deg_fuel_rate_eff(cfg: dict) -> float:
    """Laju bahan bakar efektif (skalar) untuk skenario *baseline* diesel yang
    tidak memiliki rincian energi per-DEG (mis. baseline diesel-only). Dihitung
    sebagai rata-rata laju per-DEG berbobot kapasitas DEG aktif; bila semua
    laju sama, hasilnya sama dengan laju tunggal (menjaga kompatibilitas)."""
    rates = deg_fuel_rates(cfg)
    n = _n_deg(cfg)
    caps = [float(cfg.get('deg1_kw', 0.0) or 0.0),
            float(cfg.get('deg2_kw', 0.0) or 0.0),
            float(cfg.get('deg3_kw', 0.0) or 0.0)]
    caps = [caps[i] if i < n else 0.0 for i in range(3)]
    tot = sum(caps)
    if tot > 0:
        return sum(c * r for c, r in zip(caps, rates)) / tot
    return rates[0]


def migrate_cfg(cfg: dict) -> dict:
    """Perbarui config lama secara in-place: efisiensi generator tunggal
    (`deg_efficiency`) → laju konsumsi bahan bakar per-DEG (L/kWh). Aman
    dipanggil berulang dan pada config yang sudah baru."""
    if not isinstance(cfg, dict):
        return cfg
    has_new = any(k in cfg for k in
                  ('deg1_fuel_rate', 'deg2_fuel_rate', 'deg3_fuel_rate'))
    if not has_new and 'deg_efficiency' in cfg:
        try:
            eff = float(cfg.get('deg_efficiency')) or 0.33
        except (TypeError, ValueError):
            eff = 0.33
        r = round(1.0 / (eff * 10.0), 6)
        cfg['deg1_fuel_rate'] = r
        cfg['deg2_fuel_rate'] = r
        cfg['deg3_fuel_rate'] = r
    cfg.pop('deg_efficiency', None)      # buang kunci warisan
    for _k in [k for k in cfg if is_rank_key(k)]:
        cfg.pop(_k, None)                # tampilan peringkat bukan setelan
    # v164 — nilai lama "…Dispatch Priority" -> "Position in Load Supply"
    _m = {'pro-rata with pv': 'Shared with PV (pro-rata)',
          'pv -> wtg': 'After PV', 'wtg -> pv': 'Before PV'}
    _v = str(cfg.get('wtg_priority', '')).strip().lower()
    if _v in _m:
        cfg['wtg_priority'] = _m[_v]
    for _k in ('stg', 'gtg'):
        _v = str(cfg.get(_k + '_priority', '')).strip().upper()
        if _v.startswith(_k.upper() + ' ->'):
            cfg[_k + '_priority'] = 'Before PV/WTG (baseload)'
        elif _v.startswith('PV/WTG ->'):
            cfg[_k + '_priority'] = 'After PV/WTG (follows load)'
    # 'Fixed CAPEX' lama -> 'Accessories Cost' agar total CAPEX proyek terjaga
    if 'fixed_capex' in cfg:
        if 'accessories_cost' not in cfg:
            try:
                cfg['accessories_cost'] = float(cfg.get('fixed_capex') or 0.0)
            except (TypeError, ValueError):
                pass
        cfg.pop('fixed_capex', None)
    return cfg


def load_config(path: str) -> dict:
    cfg = defaults()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            migrate_cfg(raw)             # naikkan config lama sebelum digabung
            cfg.update(raw)
        except Exception:
            pass
    cfg.setdefault('language', LANG_DEFAULT)
    return cfg


def save_config(path: str, cfg: dict):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def to_system_params(cfg: dict):
    """Konversi dict konfigurasi GUI -> SystemParams engine."""
    from ..engine.dispatch import SystemParams
    n = int(cfg.get('deg_count', '1') if str(cfg.get('deg_count', '1')).isdigit() else 1)
    deg = [cfg['deg1_kw'], cfg['deg2_kw'], cfg['deg3_kw']]
    lmax = _deg_lmax(cfg)
    degmax = [lmax, lmax, lmax]
    for i in range(3):
        if i >= n:
            deg[i] = 0.0
            degmax[i] = 0.0
    # Tanpa grid, status grid tak pernah berubah -> fitur "follows grid status"
    # dan interlock DEG-grid tak berlaku; load priority memakai pemetaan
    # grid-padam (posisi 'Grid' dalam rantai tak berpengaruh).
    grid_on = bool(cfg['grid_enabled'])
    lp_code = _prio_code(cfg) if grid_on else _off_code(
        cfg.get('load_priority', ''), cfg)
    return SystemParams(
        pv_kwp=cfg['pv_kwp'], pv_inv_kw=cfg['pv_inv_kw'],
        pv_base_annual=cfg['pv_base_annual'], pv_degradation=cfg['pv_degradation'],
        bess_kwh=cfg['bess_kwh'], soc_init=cfg['soc_init'],
        soc_min=cfg['soc_min'], soc_max=cfg['soc_max'], rte=rte_effective(cfg),
        max_charge_kw=cfg['max_charge_kw'], max_discharge_kw=cfg['max_discharge_kw'],
        charge_from_grid_below_soc=cfg['charge_from_grid_below_soc'],
        bess_degradation=cfg['bess_degradation'],
        bess_self_cons_kw=_fnum(cfg, 'bess_self_cons_kw', 0.0),
        bess_sc_source=_sc_source_code(cfg),
        grid_charge_max_kw=grid_charge_cap_kw(cfg),
        grid_enabled=grid_on, grid_kw=cfg['grid_kw'],
        grid_min_loading=cfg['grid_min_loading'],
        grid_max_loading=cfg['grid_max_loading'],
        allow_export=bool(cfg['allow_export']),
        load_priority=lp_code,
        load_priority_split=bool(cfg.get('load_priority_split', False)) and grid_on,
        load_priority_on=_prio_code(
            {**cfg, 'load_priority': cfg.get('load_priority_on',
                                             'Grid -> PV -> BESS -> DEG')}),
        load_priority_off=_off_code(
            cfg.get('load_priority_off', 'PV -> BESS -> DEG'), cfg),
        charge_priority=_prio(cfg['charge_priority']),
        strict_charge_priority=bool(cfg.get('strict_charge_priority', False)),
        grid_charge_enabled=grid_charge_allowed(cfg),
        deg_charge_enabled=bool(cfg['deg_charge_enabled'])
            and not bool(cfg['deg_interlock']),
        deg_interlock=bool(cfg['deg_interlock']),
        deg_sync=bool(cfg.get('deg_sync', True)),
        deg_always=bool(cfg.get('deg_always', False)),
        deg_grid_former=_deg_gridformer_code(cfg),
        deg_options_split=bool(cfg.get('deg_options_split', False)) and grid_on,
        deg_interlock_on=bool(cfg.get('deg_interlock_on', True)),
        deg_interlock_off=bool(cfg.get('deg_interlock_off', True)),
        deg_charge_on=bool(cfg.get('deg_charge_on', False)),
        deg_charge_off=bool(cfg.get('deg_charge_off', False)),
        grid_interlock=grid_interlock_active(cfg),
        deg_grid_interlock=bool(cfg.get('deg_grid_interlock', True)) and grid_on,
        deg_min_loading=float(cfg.get('deg_min_loading', 0.0)),
        deg_kw=tuple(deg), deg_max_loading=tuple(degmax),
        interval_h=_sim_dt_h(cfg),
        **_bess_adv(cfg))




def _sc_source_code(cfg: dict) -> int:
    """Pemasok self consumption BESS: 0 = PV+BESS (baku), 1 = DEG/Grid."""
    v = str(cfg.get('bess_sc_source', 'PV+BESS')).strip().upper()
    return 1 if (v.startswith('DEG') or v.startswith('GRID')) else 0


def parse_soh_curve(rows, fill0=1.0) -> list:
    """Bersihkan tabel SOH [(tahun, soh), ...] → [[tahun, soh_fraksi], ...]
    terurut menurut tahun. SOH boleh '94.2%', 0.942, atau 94.2 (persen).
    Baris tak numerik (judul) dilewati. Tahun 0 = 100% bila tak ada."""
    out = {}
    for r in rows or []:
        try:
            y, v = r[0], r[1]
        except (TypeError, IndexError, KeyError):
            continue
        try:
            y = float(str(y).strip().replace(',', '.'))
        except (TypeError, ValueError):
            continue
        if y != y or y < 0:
            continue
        pct = False
        if isinstance(v, str):
            t = v.strip().replace(' ', '')
            pct = t.endswith('%')
            t = t.rstrip('%').replace(',', '.')
            try:
                v = float(t)
            except ValueError:
                continue
        else:
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
        if v != v:
            continue
        if pct or v > 1.5:
            v = v / 100.0
        out[round(y, 6)] = max(0.0, min(1.5, v))
    if not out:
        return []
    if 0.0 not in out and fill0 is not None:
        out[0.0] = float(fill0)
    return [[float(k), float(out[k])] for k in sorted(out)]


def parse_rte_curve(rows) -> list:
    """Tabel RTE per tahun [(tahun, rte), ...] → [[tahun, rte_fraksi], ...]
    (format nilai sama dgn kurva SOH). Tanpa tahun 0 → nilai titik pertama
    dipakai mundur (tidak dipaksa 100%)."""
    return parse_soh_curve(rows, fill0=None)


def rte_curve_active(cfg: dict) -> bool:
    return (str(cfg.get('rte_source', 'Annual Degradation')).lower()
            .startswith('rte') and bool(parse_rte_curve(cfg.get('rte_curve'))))


def rte_at_age(cfg: dict, age: float) -> float:
    """RTE BESS pada umur `age` tahun (0 = baru): kurva impor (interpolasi /
    ekstrapolasi spt kurva SOH) ATAU rte × (1 − rte_degradation)^umur.
    Dibatasi 0.30–1.00 (rentang parameter Round Trip Efficiency)."""
    if rte_curve_active(cfg):
        pts = parse_rte_curve(cfg.get('rte_curve'))
        if pts and pts[0][0] > 0:
            pts = [[0.0, pts[0][1]]] + pts          # sebelum titik pertama: datar
        v = soh_from_curve(pts, age)
    else:
        try:
            base = float(cfg.get('rte', 0.913))
        except (TypeError, ValueError):
            base = 0.913
        try:
            deg = float(cfg.get('rte_degradation', 0.0) or 0.0)
        except (TypeError, ValueError):
            deg = 0.0
        if deg <= 0.0 or age <= 0:
            return base                             # jalur lama (byte-identik)
        v = base * (1.0 - deg) ** float(age)
    return float(min(1.0, max(0.3, v)))


def rte_effective(cfg: dict) -> float:
    """RTE yg dipakai simulasi satu tahun (Dashboard/Optimization/Results) =
    RTE unit baru (umur 0). Mode degradasi tahunan → sama dgn parameter
    Round Trip Efficiency (tak berubah); mode kurva → nilai kurva tahun 0."""
    if not rte_curve_active(cfg):
        return cfg['rte']
    return rte_at_age(cfg, 0.0)


def soh_from_curve(curve, age: float) -> float:
    """SOH pada umur `age` (tahun) dari kurva [[tahun, soh], ...]: interpolasi
    linear; di luar tabel diekstrapolasi dgn laju (rasio) tahun terakhir."""
    pts = parse_soh_curve(curve)
    if not pts:
        return 1.0
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    a = float(age)
    if a <= xs[0]:
        return ys[0]
    if a <= xs[-1]:
        for i in range(1, len(xs)):
            if a <= xs[i]:
                x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
                return y0 + (y1 - y0) * (a - x0) / max(1e-12, x1 - x0)
    if len(xs) >= 2 and ys[-2] > 0 and xs[-1] > xs[-2]:
        r = (ys[-1] / ys[-2]) ** (1.0 / (xs[-1] - xs[-2]))
        return max(0.0, ys[-1] * r ** (a - xs[-1]))
    return ys[-1]


def soh_curve_active(cfg: dict) -> bool:
    return (str(cfg.get('bess_soh_source', 'Annual Degradation')).lower()
            .startswith('soh') and bool(parse_soh_curve(cfg.get('bess_soh_curve'))))


def _deg_lmax(cfg: dict) -> float:
    """Max loading seragam semua DEG; fallback ke deg1_max config lama."""
    return float(cfg.get('deg_max_loading', cfg.get('deg1_max', 1.0)))

def _sim_dt_h(cfg: dict) -> float:
    """dt (jam) satu langkah simulasi dari pilihan 'sim_interval' (default 1 jam).
    Optimization & Multi-Year memakai 1.0 langsung (basis tahunan)."""
    from .intervals import interval_dt_h
    return interval_dt_h(str(cfg.get('sim_interval', '1 hour')))


def _bess_mode_code(cfg: dict) -> int:
    """0 = Standard (jalur Excel murni), 1 = Advanced (fungsi BESS aktif)."""
    return 1 if str(cfg.get('bess_mode', 'Standard')
                    ).strip().lower().startswith('adv') else 0


def _fnum(cfg: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _pi(cfg: dict, key: str, default: int) -> int:
    """Nomor prioritas mode (dropdown '1'..'7') -> int."""
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return int(default)


def _target_code(cfg: dict) -> int:
    """Kode target discharge mode Advanced: 0=Both, 1=Grid, 2=DEG."""
    v = str(cfg.get('adv_target', 'Both')).strip().lower()
    return 1 if v == 'grid' else (2 if v == 'deg' else 0)


def _bess_adv(cfg: dict) -> dict:
    """Bangun field EMS BESS multi-mode untuk SystemParams. Semua di-NOL-kan
    bila mode BUKAN Advanced atau mode terkait mati → engine no-op (Standard
    tetap bit-identik). Param tiap mode hanya diteruskan bila modenya aktif."""
    adv = _bess_mode_code(cfg) == 1

    def mf(key):                     # flag mode (hanya bila Advanced)
        return 1 if (adv and bool(cfg.get(key, False))) else 0

    def mp(mode_key, param_key, lo=0.0, hi=None):   # param mode (bila aktif)
        if not (adv and bool(cfg.get(mode_key, False))):
            return 0.0
        v = max(lo, _fnum(cfg, param_key))
        return min(hi, v) if hi is not None else v

    return dict(
        bess_mode=1 if adv else 0,
        adv_target=(_target_code(cfg) if adv else 0),
        m_pv_smooth=mf('m_pv_smooth'), m_firming=mf('m_firming'),
        m_load_shift=mf('m_load_shift'), m_peak_shave=mf('m_peak_shave'),
        m_dg_minload=mf('m_dg_minload'),
        m_reserve=mf('m_reserve'), m_backup=mf('m_backup'),
        peak_shave_kw=mp('m_peak_shave', 'peak_shave_kw'),
        firming_kw=mp('m_firming', 'firming_kw'),
        firming_trigger=((1 if str(cfg.get('firming_trigger', 'PV Power'))
                          .strip().lower().startswith('time') else 0)
                         if (adv and cfg.get('m_firming')) else 0),
        firming_pv_start=mp('m_firming', 'firming_pv_start'),
        firming_pv_end=mp('m_firming', 'firming_pv_end'),
        firming_time_start=mp('m_firming', 'firming_time_start', 0.0, 24.0),
        firming_time_end=mp('m_firming', 'firming_time_end', 0.0, 24.0),
        arb_peak_start=(_fnum(cfg, 'arb_peak_start', 18.0)
                        if (adv and cfg.get('m_load_shift')) else 0.0),
        arb_peak_end=(_fnum(cfg, 'arb_peak_end', 22.0)
                      if (adv and cfg.get('m_load_shift')) else 0.0),
        pv_ramp_up_kwmin=mp('m_pv_smooth', 'pv_ramp_up_kwmin'),
        pv_ramp_dn_kwmin=mp('m_pv_smooth', 'pv_ramp_dn_kwmin'),
        smoothing_window=(max(1, int(_fnum(cfg, 'smoothing_window', 10)))
                          if (adv and cfg.get('m_pv_smooth')) else 1),
        reserve_frac=mp('m_reserve', 'reserve_frac', 0.0, 100.0) / 100.0,
        reserve_kw=mp('m_reserve', 'reserve_kw'),
        prio_pv_smooth=_pi(cfg, 'prio_pv_smooth', 2),
        prio_firming=_pi(cfg, 'prio_firming', 2),
        prio_load_shift=_pi(cfg, 'prio_load_shift', 4),
        prio_peak_shave=_pi(cfg, 'prio_peak_shave', 5),
        prio_dg_minload=_pi(cfg, 'prio_dg_minload', 3),
        prio_reserve=_pi(cfg, 'prio_reserve', 1),
        prio_backup=_pi(cfg, 'prio_backup', 1),
        ext=ext_vals(cfg))


def wtg_active(cfg: dict) -> bool:
    return bool(cfg.get('wtg_enabled', False)) and \
        _fnum(cfg, 'wtg_count', 0) * _fnum(cfg, 'wtg_unit_kw', 0) > 0


def stg_active(cfg: dict) -> bool:
    return bool(cfg.get('stg_enabled', False)) and _fnum(cfg, 'stg_kw', 0) > 0


def gtg_active(cfg: dict) -> bool:
    return bool(cfg.get('gtg_enabled', False)) and _fnum(cfg, 'gtg_kw', 0) > 0


def _thermal_order(cfg: dict) -> tuple:
    s = str(cfg.get('thermal_order', 'stg,gtg')).strip().lower()
    return ('gtg', 'stg') if s.startswith('gtg') else ('stg', 'gtg')


def _src_active(cfg: dict) -> dict:
    return dict(
        pv=_fnum(cfg, 'pv_kwp', 0) > 0, wtg=wtg_active(cfg),
        stg=stg_active(cfg), gtg=gtg_active(cfg),
        grid=bool(cfg.get('grid_enabled', True)) and _fnum(cfg, 'grid_kw', 0) > 0,
        bess=_fnum(cfg, 'bess_kwh', 0) > 0, deg=_n_deg(cfg) > 0)


def _split_on(cfg: dict) -> bool:
    return bool(cfg.get('grid_enabled', True)) and bool(
        cfg.get('load_priority_split', False))


def _chain_tokens(cfg: dict, scenario: str) -> list:
    grid_on = bool(cfg.get('grid_enabled', True))
    if scenario == 'on':
        chain = load_priority_label(cfg.get('load_priority_on',
                                            'Grid -> PV -> BESS -> DEG'), cfg)
    elif scenario == 'off':
        chain = load_priority_off_label(cfg.get('load_priority_off',
                                                'PV -> BESS -> DEG'), cfg)
    elif grid_on:
        chain = load_priority_label(cfg.get('load_priority', ''), cfg)
    else:
        chain = load_priority_off_label(cfg.get('load_priority', ''), cfg)
    if '->' not in str(chain):                 # mode komposit lama (Auto)
        chain = PRIORITY_CHAINS[0.0][0]
    return [t.strip().upper().split()[0] for t in str(chain).split('->')]


def load_groups(cfg: dict, scenario: str = 'main') -> list:
    """Urutan suplai beban sebagai list KELOMPOK kunci sumber (kelompok berisi
    dua sumber = prioritas sama / pro-rata), dibangun dari aturan yang SAMA
    dengan yang dijalankan engine:
      * unit termal 'baseload' -> paling depan; unit termal 'follows load' ->
        setelah PV/WTG. Unit termal dijadwalkan sebelum engine inti, sehingga
        SELALU mendahului Utility Grid / BESS / DEG (pada rantai yang diawali
        Grid atau DEG, unit 'follows load' tetap tampil sebelum keduanya);
      * PV / WTG menurut wtg_priority; sisanya menurut rantai Load Supply."""
    act = _src_active(cfg)
    if scenario == 'off':
        act = dict(act, grid=False)
    _wc = _wtg_pos_code(cfg.get('wtg_priority', ''))
    if act['pv'] and act['wtg']:
        re = ([['pv'], ['wtg']] if _wc == 1.0 else
              [['wtg'], ['pv']] if _wc == 2.0 else [['pv', 'wtg']])
    else:
        re = ([['pv']] if act['pv'] else []) + ([['wtg']] if act['wtg'] else [])
    first, follow = [], []
    for k in _thermal_order(cfg):
        if act[k]:
            (follow if _is_re_first(cfg.get(k + '_priority')) else first
             ).append([k])
    toks = _chain_tokens(cfg, scenario)
    out = list(first)
    if toks and toks[0] == 'PV':
        out += re + follow
    else:
        out += follow
    for t in toks:
        k = t.lower()
        if k == 'pv':
            if toks[0] != 'PV':
                out += re
        elif k in ('grid', 'bess', 'deg') and act[k]:
            out.append([k])
    if 'PV' not in toks:
        out += re
    return out


def _chg_bus_sources(cfg: dict, act: dict) -> list:
    def spare(k):
        return act[k] and str(cfg.get(k + '_charge', 'No')).strip().lower() \
            .startswith('spare')
    return [s for s in ('pv', 'wtg', 'stg', 'gtg')
            if (act[s] if s in ('pv', 'wtg') else spare(s))]


def charge_bus_groups(cfg: dict) -> list:
    """Urutan sumber DI BUS (PV, WTG, kapasitas cadangan STG/GTG) untuk mengisi
    BESS. cfg['charge_bus_order'] ('stg>pv=wtg>gtg'); bila kosong -> urutan
    bawaan v163 (cadangan unit baseload, PV/WTG, cadangan unit follows-load)."""
    act = _src_active(cfg)
    srcs = _chg_bus_sources(cfg, act)
    _wc = _wtg_pos_code(cfg.get('wtg_priority', ''))
    dflt = [[k] for k in _thermal_order(cfg)
            if not _is_re_first(cfg.get(k + '_priority'))]
    dflt += ([['pv'], ['wtg']] if _wc == 1.0 else
             [['wtg'], ['pv']] if _wc == 2.0 else [['pv', 'wtg']])
    dflt += [[k] for k in _thermal_order(cfg)
             if _is_re_first(cfg.get(k + '_priority'))]
    raw = str(cfg.get('charge_bus_order', '') or '').strip().lower()
    groups = []
    if raw:
        for g in raw.split('>'):
            gg = [x.strip() for x in g.split('=') if x.strip() in
                  ('pv', 'wtg', 'stg', 'gtg')]
            if gg:
                groups.append(gg)
    seen = {x for g in groups for x in g}
    for g in dflt:                              # sumber yang belum disebut
        gg = [x for x in g if x not in seen]
        if gg:
            groups.append(gg)
    out = []
    for g in groups:
        gg = [x for x in g if x in srcs]
        if not gg:
            continue
        if len(gg) > 1 and set(gg) != {'pv', 'wtg'}:
            out += [[x] for x in gg]            # hanya PV=WTG boleh setara
        else:
            out.append(gg)
    return out


def _grid_chg(cfg: dict, act: dict) -> bool:
    return act['grid'] and act['bess'] and grid_charge_allowed(cfg)


def _deg_chg(cfg: dict, act: dict) -> bool:
    return (act['deg'] and act['bess']
            and bool(cfg.get('deg_charge_enabled', False))
            and not bool(cfg.get('deg_interlock', True)))


def charge_groups(cfg: dict) -> list:
    """Urutan charging BESS (list kelompok kunci sumber)."""
    act = _src_active(cfg)
    if not act['bess']:
        return []
    bus = charge_bus_groups(cfg)
    grid = [['grid']] if _grid_chg(cfg, act) else []
    if str(cfg.get('charge_priority', 'PV -> Grid')).strip().upper() \
            .startswith('GRID'):
        out = grid + bus
    else:
        out = bus + grid
    if _deg_chg(cfg, act):
        out.append(['deg'])
    return out


def charge_prefix(cfg: dict) -> list:
    """Unit termal yang surplus minimum-loading-nya diserap BESS (selalu
    lebih dulu, tidak diberi nomor)."""
    act = _src_active(cfg)
    if not act['bess']:
        return []
    return [k for k in _thermal_order(cfg) if act[k]
            and str(cfg.get(k + '_charge', 'No')).strip().lower() != 'no']


def rank_groups(cfg: dict, list_id: str) -> list:
    if list_id == 'chr':
        return charge_groups(cfg)
    return load_groups(cfg, {'lsr': 'main', 'lsr_on': 'on',
                             'lsr_off': 'off'}[list_id])


def rank_values(cfg: dict) -> dict:
    """Nilai tampilan semua baris peringkat: {'lsr_pv': '1', ...}."""
    out = {}
    for lid in RANK_LISTS:
        for i, g in enumerate(rank_groups(cfg, lid)):
            for s in g:
                out[f'{lid}_{s}'] = str(i + 1)
    return out


def rank_count(cfg: dict, list_id: str) -> int:
    return sum(len(g) for g in rank_groups(cfg, list_id))


def rank_list_visible(cfg: dict, list_id: str) -> bool:
    if list_id == 'lsr':
        return not _split_on(cfg)
    if list_id in ('lsr_on', 'lsr_off'):
        return _split_on(cfg)
    return bool(charge_groups(cfg))


def _rank_options(cfg: dict, list_id: str):
    """Semua urutan yang DIDUKUNG engine untuk daftar `list_id`:
    list (settings, groups)."""
    import itertools
    act = _src_active(cfg)
    if list_id == 'chr':
        srcs = _chg_bus_sources(cfg, act)
        items = []
        for perm in itertools.permutations(srcs):
            items.append([[x] for x in perm])
        if 'pv' in srcs and 'wtg' in srcs:
            rest = [x for x in srcs if x not in ('pv', 'wtg')]
            for perm in itertools.permutations(rest + ['re']):
                items.append([['pv', 'wtg'] if x == 're' else [x]
                              for x in perm])
        opts = []
        for bus in items:
            s_bus = '>'.join('='.join(g) for g in bus)
            for cp in (('PV -> Grid', 'Grid -> PV') if _grid_chg(cfg, act)
                       else (cfg.get('charge_priority', 'PV -> Grid'),)):
                st = {'charge_bus_order': s_bus, 'charge_priority': cp}
                opts.append((st, charge_groups({**cfg, **st})))
        return opts
    scen = {'lsr': 'main', 'lsr_on': 'on', 'lsr_off': 'off'}[list_id]
    if scen == 'on':
        ckey, chains = 'load_priority_on', load_priority_base_choices(cfg)
    elif scen == 'off':
        ckey, chains = 'load_priority_off', load_priority_off_choices(cfg)
    elif bool(cfg.get('grid_enabled', True)):
        ckey, chains = 'load_priority', load_priority_base_choices(cfg)
    else:
        ckey, chains = 'load_priority', load_priority_offgrid_choices(cfg)
    dims = [(ckey, list(chains))]
    if act['pv'] and act['wtg']:
        dims.append(('wtg_priority', list(_WTG_POS)))
    for k in ('stg', 'gtg'):
        if act[k]:
            dims.append((k + '_priority', list(_TH_POS)))
    if act['stg'] and act['gtg']:
        dims.append(('thermal_order', ['stg,gtg', 'gtg,stg']))
    opts = []
    for combo in itertools.product(*[d[1] for d in dims]):
        st = {d[0]: v for d, v in zip(dims, combo)}
        opts.append((st, load_groups({**cfg, **st}, scen)))
    return opts


def _rank_request(groups: list, src: str, rank: int) -> list:
    """Urutan yang DIMINTA setelah `src` diberi nomor `rank`."""
    g = [list(x) for x in groups]
    idx = max(0, min(int(rank) - 1, len(g) - 1))
    other = {'pv': 'wtg', 'wtg': 'pv'}.get(src)
    if other and g[idx] == [other]:             # nomor sama dgn PV/WTG = setara
        g = [[y for y in x if y != src] for x in g]
        for x in g:
            if x == [other]:
                x.append(src)
        return [x for x in g if x]
    g = [[y for y in x if y != src] for x in g]
    g = [x for x in g if x]
    g.insert(max(0, min(int(rank) - 1, len(g))), [src])
    return g


def _gpos(groups: list) -> dict:
    return {s: i for i, x in enumerate(groups) for s in x}


def apply_rank(cfg: dict, list_id: str, src: str, rank: int):
    """Terapkan permintaan 'sumber `src` = prioritas `rank`' pada daftar
    `list_id`. Kembalikan (settings, exact): `settings` = kunci cfg yang perlu
    diubah (urutan DIDUKUNG terdekat), `exact` = False bila permintaan tidak
    didukung engine sehingga disesuaikan."""
    cur = rank_groups(cfg, list_id)
    if src not in _gpos(cur):
        return {}, True
    req = _rank_request(cur, src, rank)
    rp = _gpos(req)
    best = None

    def _cv(k):
        return str(cfg.get(k, 'stg,gtg' if k == 'thermal_order' else ''))

    def _ahead(g):                         # jumlah sumber di depan `src`
        n = 0.0
        for x in g:
            if src in x:
                return n + 0.5 * (len(x) - 1)   # setara = setengah langkah
            n += len(x)
        return n
    a_req, a_cur = _ahead(req), _ahead(cur)
    for st, grp in _rank_options(cfg, list_id):
        op = _gpos(grp)
        if set(op) != set(rp):
            continue
        d = 0.0
        ks = sorted(rp)
        for i, a in enumerate(ks):
            for b_ in ks[i + 1:]:
                ra = (rp[a] > rp[b_]) - (rp[a] < rp[b_])
                oa = (op[a] > op[b_]) - (op[a] < op[b_])
                if ra != oa:
                    # sumber lain (tak disentuh pengguna) dijaga urutannya
                    d += 1.5 if src in (a, b_) else 2.0
        if grp != req and abs(_ahead(grp) - a_req) >= abs(a_cur - a_req):
            continue                      # tak mendekati permintaan -> abaikan
        d += 0.01 * sum(1 for k, v in st.items() if _cv(k) != str(v))
        if best is None or d < best[0] - 1e-12:
            best = (d, st, grp)
    if best is None:
        return {}, req == cur
    st = {k: v for k, v in best[1].items() if _cv(k) != str(v)}
    return st, best[2] == req


def order_names(cfg: dict, list_id: str) -> list:
    """Nama tampil tiap kelompok pada daftar (untuk teks urutan/ekspor)."""
    out = []
    for g in rank_groups(cfg, list_id):
        nm = []
        for s in g:
            lab = SRC_LABEL[s]
            if list_id == 'chr':
                if s in ('stg', 'gtg'):
                    lab += ' (spare)'
                elif s == 'deg':
                    lab += ' (to minimum loading)'
            elif s == 'gtg' and str(cfg.get('gtg_commit', 'On Demand')) \
                    .lower().startswith('on'):
                lab += ' (on demand)'
            nm.append(lab)
        out.append(' + '.join(nm))
    return out


def order_text(cfg: dict, list_id: str, sep: str = ' → ') -> str:
    """Urutan bernomor siap cetak: '1. STG → 2. PV + WTG → 3. Grid'."""
    return sep.join('%d. %s' % (i + 1, nm)
                    for i, nm in enumerate(order_names(cfg, list_id)))


def effective_orders(cfg: dict):
    """Urutan EFEKTIF seluruh pembangkit aktif -> (load_order, charge_order)
    sebagai list nama, dari aturan yang SAMA dengan engine (load_groups /
    charge_groups). Surplus minimum-loading STG/GTG mendahului daftar
    charging."""
    load = order_names(cfg, 'lsr_on' if _split_on(cfg) else 'lsr')
    chg = [SRC_LABEL[k] + ' (min-load surplus)' for k in charge_prefix(cfg)]
    chg += order_names(cfg, 'chr')
    return load, chg


def ext_vals(cfg: dict) -> dict:
    """Kunci engine untuk ekstensi v162 (WTG, STG, strategi BESS baru) —
    dict skalar float yang digabung apa adanya ke 'vals' dispatch. Hanya
    fitur yang AKTIF yang dimuat; tanpa fitur aktif -> {} (engine byte-identik
    dengan jalur lama)."""
    out = {}
    adv = _bess_mode_code(cfg) == 1 and _fnum(cfg, 'bess_kwh', 0) > 0
    if adv and cfg.get('m_load_follow'):
        out.update(m_load_follow=1.0, lf_set_kw=max(0.0, _fnum(cfg, 'lf_set_kw')),
                   lf_charge=1.0 if cfg.get('lf_charge', True) else 0.0,
                   prio_load_follow=float(_pi(cfg, 'prio_load_follow', 4)))
    if adv and cfg.get('m_freq_reg') and _fnum(cfg, 'fr_kw') > 0:
        out.update(m_freq_reg=1.0, fr_kw=_fnum(cfg, 'fr_kw'),
                   fr_min=max(0.0, _fnum(cfg, 'fr_min', 15.0)))
    if adv and cfg.get('m_qv') and _fnum(cfg, 'qv_kvar') > 0:
        out.update(m_qv=1.0, qv_kvar=_fnum(cfg, 'qv_kvar'),
                   pcs_kva=max(0.0, _fnum(cfg, 'pcs_kva')))
    if adv and cfg.get('m_black_start') and _fnum(cfg, 'bs_kw') > 0:
        out.update(m_black_start=1.0, bs_kw=_fnum(cfg, 'bs_kw'),
                   bs_min=max(0.0, _fnum(cfg, 'bs_min', 30.0)))
    if wtg_active(cfg):
        from ..engine.wtg import air_density
        # sumber angin ERA5 (halaman Data): selalu kecepatan angin 100 m
        _era5 = str(cfg.get('wind_source', 'excel')) == 'era5'
        out.update(
            wtg_on=1.0, wtg_n=_fnum(cfg, 'wtg_count', 1),
            wtg_unit_kw=_fnum(cfg, 'wtg_unit_kw'),
            wtg_mode=(0.0 if _era5 else
                      1.0 if str(cfg.get('wtg_input', '')).lower()
                      .startswith('power') else 0.0),
            wtg_base_kw=max(1e-6, _fnum(cfg, 'wtg_base_kw', 1000.0)),
            wtg_hub_h=_fnum(cfg, 'wtg_hub_h', 80.0),
            wtg_meas_h=(_fnum(cfg, 'wind_era5_height', 100.0) if _era5
                        else _fnum(cfg, 'wtg_meas_h', 10.0)),
            wtg_shear=_fnum(cfg, 'wtg_shear', 0.2),
            wtg_vci=_fnum(cfg, 'wtg_vci', 3.0), wtg_vr=_fnum(cfg, 'wtg_vr', 12.0),
            wtg_vco=_fnum(cfg, 'wtg_vco', 25.0),
            wtg_rho=air_density(_fnum(cfg, 'wtg_elev_m', 0.0),
                                _fnum(cfg, 'wtg_temp_c', 27.0)),
            wtg_loss=min(max(_fnum(cfg, 'wtg_loss', 0.1), 0.0), 1.0))
    for k in ('stg', 'gtg'):
        if not (bool(cfg.get(k + '_enabled', False)) and _fnum(cfg, k + '_kw', 0) > 0):
            continue
        chg = str(cfg.get(k + '_charge', 'No')).strip().lower()
        out.update({
            k + '_on': 1.0, k + '_kw': _fnum(cfg, k + '_kw'),
            k + '_min_loading': _fnum(cfg, k + '_min_loading', 0.3),
            k + '_max_loading': _fnum(cfg, k + '_max_loading', 1.0),
            k + '_priority': 1.0 if _is_re_first(cfg.get(k + '_priority')) else 0.0,
            k + '_charge': (2.0 if chg.startswith('spare') else
                            1.0 if chg.startswith('min') else 0.0),
            k + '_ramp_kwmin': max(0.0, _fnum(cfg, k + '_ramp_kwmin')),
            k + '_sched_start': _fnum(cfg, k + '_sched_start'),
            k + '_sched_end': _fnum(cfg, k + '_sched_end')})
    if 'stg_on' in out:
        out['stg_renewable'] = 1.0 if cfg.get('stg_renewable', True) else 0.0
    if 'gtg_on' in out:
        out['gtg_commit'] = (1.0 if str(cfg.get('gtg_commit', 'On Demand'))
                             .strip().lower().startswith('on') else 0.0)
        out['gtg_heat_rate'] = _fnum(cfg, 'gtg_heat_rate', 12000.0)
    if wtg_active(cfg):
        out['wtg_priority'] = _wtg_pos_code(cfg.get('wtg_priority'))
    if 'stg_on' in out and 'gtg_on' in out:
        out['thermal_gtg_first'] = (1.0 if _thermal_order(cfg)[0] == 'gtg'
                                    else 0.0)
    if ('stg_on' in out or 'gtg_on' in out or 'wtg_on' in out) \
            and str(cfg.get('charge_bus_order', '') or '').strip():
        # v165 — peringkat sumber bus untuk charging BESS (hanya bila diatur;
        # tanpa itu engine memakai urutan bawaan)
        for _i, _g in enumerate(charge_bus_groups(cfg)):
            for _s in _g:
                out['chg_rank_' + _s] = float(_i)
    return out


def _deg_gridformer_code(cfg: dict) -> int:
    """Kode DEG grid-forming (must-run) pilihan pengguna:
    0 = Auto (genset terkecil), 1/2/3 = DEG-1/2/3. Nilai tak dikenal -> 0."""
    v = str(cfg.get('deg_grid_former', 'Auto')).strip().upper()
    if v.startswith('DEG-') or v.startswith('DEG '):
        try:
            k = int(''.join(ch for ch in v if ch.isdigit()))
            return k if k in (1, 2, 3) else 0
        except Exception:
            return 0
    return 0

def _prio(val: str) -> float:
    """Kode mode prioritas beban (parser warisan untuk label lama):
    0 = PV -> Grid -> ..., 1 = Grid dahulu, 2 = PV -> BESS -> Grid.
    Aman terhadap label tanpa '->' (mis. label deskriptif baru)."""
    t = ' '.join(str(val).upper().split())
    if t.startswith('GRID'):
        return 1.0
    parts = t.split('->')
    seg = parts[1] if len(parts) > 1 else t
    return 2.0 if 'BESS' in seg else 0.0


def grid_interlock_active(cfg: dict) -> bool:
    """Interlock grid hanya berlaku bila mode prioritas beban memisahkan
    grid dari PV-BESS. Mode PV-dahulu (kode 0) & Auto (kode 4) mencampur
    keduanya, jadi interlock otomatis dinonaktifkan di sana."""
    if not bool(cfg.get('grid_interlock', False)):
        return False
    return _prio_code(cfg) not in (0.0, 4.0)


def grid_charge_cap_kw(cfg: dict) -> float:
    """Batas daya Grid → BESS (kW) utk engine: 0 = Auto (tak dibatasi).
    Manual dgn nilai 0 → grid praktis tak mengisi (1e-9 kW)."""
    if str(cfg.get('grid_charge_mode', 'Auto')).strip().lower() != 'manual':
        return 0.0
    v = _fnum(cfg, 'grid_charge_max_kw', 0.0)
    return v if v > 0 else 1e-9


def grid_charge_allowed(cfg: dict) -> bool:
    """Grid tidak dapat mengisi BESS saat bus grid ter-interlock."""
    return bool(cfg.get('grid_charge_enabled', True)) \
        and not grid_interlock_active(cfg)



# Label mode 'Auto by Grid Status' (kode 4). Strategi berpindah otomatis:
#   Grid ON  -> Grid -> DEG -> PV -> BESS  (charge Grid -> PV)
#   Grid OFF -> PV -> BESS -> DEG          (charge PV, DEG interlock PV-BESS)
# Label ringkas (rincian rantai dijelaskan di tooltip). Kode 4 = strategi
# yang berpindah otomatis menurut status grid.
AUTO_LABEL = 'Auto by Grid Status'
# Kode 5: Grid -> PV -> BESS -> DEG dengan interlock DEG↔PV-BESS yang hanya
# aktif saat grid padam (saat grid ada, DEG paralel penuh).
AUTO_INTERLOCK_LABEL = 'Grid -> PV -> BESS -> DEG (auto-interlock)'


# Rantai prioritas beban: label berubah mengikuti opsi DEG Interlock with Grid.
# Kode internal tetap sama (0 = PV dahulu, 1 = Grid dahulu, 2 = PV→BESS dahulu)
# sehingga berkas proyek lama tetap terbaca.
# Label deskriptif per kode. Tuple = (varian saat DEG interlock grid,
# varian saat DEG boleh paralel grid). Teks boleh membungkus di popup;
# lebar combo dibatasi sehingga layout tidak melebar (lihat WrapComboBox).
# Pemetaan label→kode memakai pencocokan tepat (lihat _prio_code), sehingga
# teks deskriptif bebas tanpa mengganggu logika.
PRIORITY_CHAINS = {
    0.0: ('PV -> Grid -> BESS -> DEG', 'PV -> Grid -> DEG -> BESS'),
    1.0: ('Grid -> PV -> BESS -> DEG', 'Grid -> DEG -> PV -> BESS'),
    2.0: ('PV -> BESS -> Grid -> DEG', 'PV -> BESS -> Grid -> DEG'),
    # Kode 3/4/5 hanya muncul saat DEG boleh paralel grid (interlock grid off).
    3.0: ('Grid -> PV -> BESS -> DEG', 'Grid -> PV -> BESS -> DEG'),
    4.0: (AUTO_LABEL, AUTO_LABEL),
    5.0: (AUTO_INTERLOCK_LABEL, AUTO_INTERLOCK_LABEL),
}


def _deg_parallel_grid(cfg: dict) -> bool:
    """Genset boleh beroperasi paralel dengan grid?"""
    return (bool(cfg.get('grid_enabled', True))
            and _n_deg(cfg) > 0
            and not bool(cfg.get('deg_grid_interlock', True)))


def _prio_code(cfg: dict) -> float:
    """Kode mode prioritas beban untuk engine, DENGAN konteks konfigurasi.

    Sama seperti _prio(), tetapi saat DEG boleh paralel grid (DEG Interlock
    with Grid nonaktif) opsi grid-dahulu terpecah menjadi dua rantai yang
    berbeda:
      'Grid -> DEG -> PV -> BESS'  -> genset naik sebelum PV/BESS (kode 1)
      'Grid -> PV -> BESS -> DEG'  -> genset cadangan TERAKHIR namun boleh
                                      menyala paralel grid              (kode 3)
    Berkas proyek lama tidak terpengaruh: labelnya selalu terpetakan ke
    kode yang sama seperti sebelumnya.

    Kode 4 = mode 'Auto by Grid Status': strategi berubah menurut status
    grid tiap jam (butuh grid aktif + ada DEG).

    Label 'Grid -> PV -> BESS -> DEG' dipetakan ke kode 3 saat DEG boleh
    paralel grid, atau kode 1 bila tidak — dibedakan lewat konteks, bukan
    teks. Kode 5 dikenali dari penanda '(auto-interlock)'."""
    s = ' '.join(str(cfg.get('load_priority', '')).upper().split())
    grid_deg = bool(cfg.get('grid_enabled', True)) and _n_deg(cfg) > 0
    if s.startswith('AUTO') and grid_deg:
        return 4.0
    base = _prio(cfg.get('load_priority', ''))
    if base == 1.0 and _deg_parallel_grid(cfg):
        if 'INTERLOCK' in s:               # 'Grid -> PV -> BESS -> DEG (auto-interlock)'
            return 5.0
        seg = s.split('->')
        if len(seg) > 1 and 'DEG' not in seg[1]:   # 'Grid -> PV -> ...'
            return 3.0
    return base


def load_priority_choices(cfg: dict) -> list:
    """Pilihan Load Supply Priority sesuai konfigurasi saat ini.
    Saat DEG boleh paralel grid, opsi 'Grid -> PV -> BESS -> DEG' (kode 3)
    ikut ditawarkan di samping 'Grid -> DEG -> PV -> BESS' (kode 1)."""
    parallel = _deg_parallel_grid(cfg)
    i = 1 if parallel else 0
    codes = (0.0, 1.0, 3.0, 5.0, 4.0, 2.0) if parallel else (0.0, 1.0, 2.0)
    out = []
    for code in codes:
        lbl = PRIORITY_CHAINS[code][i]
        if lbl not in out:
            out.append(lbl)
    return out


def load_priority_base_choices(cfg: dict) -> list:
    """Pilihan rantai DASAR (tanpa mode komposit 'Auto by Grid Status' /
    '(auto-interlock)') — dipakai untuk skenario per status grid, di mana
    komposit tidak relevan (statusnya sudah dipisah)."""
    return [c for c in load_priority_choices(cfg)
            if c not in (AUTO_LABEL, AUTO_INTERLOCK_LABEL)]


def load_priority_label(value, cfg: dict) -> str:
    """Terjemahkan nilai tersimpan ke label rantai yang berlaku."""
    code = _prio_code({**cfg, 'load_priority': value})
    i = 1 if _deg_parallel_grid(cfg) else 0
    return PRIORITY_CHAINS.get(code, PRIORITY_CHAINS[0.0])[i]


# ---- Skenario khusus saat GRID PADAM (status 0) ----------------------------
# Saat grid tidak tersedia, grid memasok 0 kW sehingga posisi 'Grid' dalam
# rantai tak berpengaruh: rantai yang hanya berbeda pada letak Grid menjadi
# IDENTIK saat padam. Karena itu selektor 'Grid Unavailable (0)' cukup
# menampilkan strategi grid-padam yang benar-benar berbeda — urutan PV/BESS/DEG
# saja:
#   'PV -> BESS -> DEG'  (DEG cadangan terakhir)  -> kode 2  (== kode 3 saat padam)
#   'PV -> DEG -> BESS'  (DEG naik sebelum BESS)  -> kode 0
#   'DEG -> PV -> BESS'  (DEG lebih dulu)         -> kode 1
# Dua terakhir hanya relevan saat DEG boleh paralel grid (DEG Interlock with
# Grid nonaktif). Bila interlock grid aktif, ketiga rantai dasar sama-sama
# menjadi 'PV -> BESS -> DEG' saat padam, jadi hanya satu opsi ditampilkan.
OFF_CHAINS = {
    2.0: 'PV -> BESS -> DEG',
    0.0: 'PV -> DEG -> BESS',
    1.0: 'DEG -> PV -> BESS',
}


def load_priority_off_choices(cfg: dict) -> list:
    """Pilihan skenario prioritas beban saat GRID PADAM (status 0), diringkas
    ke strategi yang benar-benar berbeda (posisi 'Grid' tak berpengaruh)."""
    codes = (2.0, 0.0, 1.0) if _deg_parallel_grid(cfg) else (2.0,)
    return [OFF_CHAINS[c] for c in codes]


def _off_code(value, cfg: dict) -> float:
    """Kode engine untuk skenario grid-padam. Menerima label ringkas baru
    ('PV -> BESS -> DEG', dst.) MAUPUN label rantai penuh lama
    ('Grid -> PV -> BESS -> DEG', dst.) demi kompatibilitas berkas lama —
    setiap rantai penuh dipetakan ke perilaku grid-padam-nya."""
    s = ' '.join(str(value).upper().split())
    for code, lbl in OFF_CHAINS.items():
        if s == lbl.upper():
            return code
    # label lama (rantai penuh): pakai kode kontekstual lalu petakan ke
    # perilaku saat grid padam (grid = 0 kW).
    code = _prio_code({**cfg, 'load_priority': value})
    if not _deg_parallel_grid(cfg):
        return 2.0                       # semua -> PV -> BESS -> DEG saat padam
    return {0.0: 0.0, 1.0: 1.0, 2.0: 2.0,
            3.0: 2.0, 5.0: 2.0}.get(code, 2.0)


def load_priority_off_label(value, cfg: dict) -> str:
    """Label ringkas grid-padam untuk nilai tersimpan (baru atau lama)."""
    return OFF_CHAINS[_off_code(value, cfg)]


def load_priority_offgrid_choices(cfg: dict) -> list:
    """Pilihan Load Supply Priority untuk sistem TANPA grid (Any Grid
    Connection nonaktif). Grid tak ada, jadi rantai hanya menyangkut urutan
    PV/BESS/DEG. Bila ada genset, ketiga strategi ditawarkan (genset boleh
    naik sebelum BESS); tanpa genset hanya PV -> BESS."""
    if _n_deg(cfg) > 0:
        return [OFF_CHAINS[c] for c in (2.0, 0.0, 1.0)]
    return [OFF_CHAINS[2.0]]


def load_priority_groups(cfg: dict) -> list:
    """Susunan berkelompok untuk dropdown Load Supply Priority, dibagi menurut
    status grid: kelompok 'Grid Status 1' (grid sebagai sumber utama —
    rantai yang diawali Grid + mode adaptif) dan 'Grid Status 0'
    (PV/BESS diprioritaskan — rantai yang diawali PV).

    Mengembalikan [(judul_kelompok, [label, ...]), ...] mengikuti opsi yang
    berlaku pada konfigurasi saat ini (mis. kode 3/4/5 hanya saat DEG boleh
    paralel grid)."""
    parallel = _deg_parallel_grid(cfg)
    i = 1 if parallel else 0
    if parallel:
        g1_codes = (1.0, 3.0, 5.0, 4.0)      # Grid dahulu + adaptif
        g0_codes = (0.0, 2.0)                # PV dahulu
    else:
        g1_codes = (1.0,)
        g0_codes = (0.0, 2.0)
    g1 = [PRIORITY_CHAINS[c][i] for c in g1_codes]
    g0 = [PRIORITY_CHAINS[c][i] for c in g0_codes]
    return [('Grid Status 1 — grid tersedia', g1),
            ('Grid Status 0 — grid padam', g0)]



PRIORITY_HELP = {
    'PV -> Grid -> BESS -> DEG':
        'PV melayani beban lebih dulu (menyisakan minimum loading untuk '
        'grid); grid memikul sisanya; BESS hanya menutup kekurangan yang '
        'melebihi kapasitas grid; genset menjadi cadangan terakhir.',
    'PV -> Grid -> DEG -> BESS':
        'PV melayani beban lebih dulu; grid memikul sisanya sampai batas '
        'kapasitasnya; genset menutup kekurangan berikutnya (boleh paralel '
        'dengan grid); BESS menjadi cadangan terakhir.',
    'Grid -> PV -> BESS -> DEG':
        'Grid memikul beban lebih dulu hingga batas loading maksimumnya; '
        'PV lalu BESS menutup sisanya; genset menjadi cadangan terakhir.',
    'Grid -> DEG -> PV -> BESS':
        'Grid memikul beban lebih dulu; genset langsung menutup kekurangan '
        'yang tidak sanggup dipikul grid (boleh paralel); PV lalu BESS '
        'melayani sisanya.',
    'PV -> BESS -> Grid -> DEG':
        'PV lalu BESS melayani beban lebih dulu (menyisakan minimum loading '
        'untuk grid); grid mengambil sisanya; genset menjadi cadangan '
        'terakhir. Cocok untuk memaksimalkan pemakaian energi surya.',
}


def load_priority_help(value, cfg: dict) -> str:
    """Penjelasan rantai prioritas yang sedang dipilih."""
    if _prio_code({**cfg, 'load_priority': value}) == 4.0:
        return ('Strategi otomatis mengikuti status grid tiap jam. '
                'Grid TERSEDIA: beban dilayani Grid → DEG → PV → BESS '
                '(genset membantu bila beban melebihi grid), pengisian BESS '
                'Grid → PV (sisa kapasitas grid mengisi BESS hingga ambang '
                '"Charge from Grid below SOC"); grid, DEG, PV, dan BESS boleh '
                'paralel. Grid PADAM: beban dilayani PV → BESS → DEG dengan '
                'DEG interlock PV-BESS (saat genset menyala ia memikul '
                'seluruh beban, PV hanya mengisi BESS). Membutuhkan grid '
                'aktif, ada DEG, dan DEG tidak interlock dengan grid.')
    if _prio_code({**cfg, 'load_priority': value}) == 5.0:
        return ('Beban dilayani Grid → PV → BESS → DEG. Saat grid TERSEDIA: '
                'genset boleh menyala paralel dengan Grid maupun PV-BESS '
                '(hanya menutup kekurangan yang tak sanggup dipikul '
                'grid + PV + BESS). Saat grid PADAM: DEG interlock dengan '
                'PV-BESS — begitu genset menyala ia memikul SELURUH beban, '
                'PV hanya mengisi BESS, dan BESS tidak discharge. '
                'Membutuhkan grid aktif, ada DEG, dan DEG tidak interlock '
                'dengan grid.')
    if _prio_code({**cfg, 'load_priority': value}) == 3.0:
        return ('Grid memikul beban lebih dulu (hormati batas loading); PV '
                'lalu BESS menutup sisanya; genset menjadi cadangan TERAKHIR '
                'namun boleh menyala paralel dengan grid untuk menutup '
                'kekurangan yang tidak sanggup dipikul grid + PV + BESS.')
    # Kode 0/1/2: bantuan dipetakan berdasarkan KODE (label tampilan boleh
    # deskriptif) ke kunci PRIORITY_HELP yang punya terjemahan EN.
    code = _prio_code({**cfg, 'load_priority': value})
    idx = 1 if _deg_parallel_grid(cfg) else 0
    key = _HELP_KEY.get(code, _HELP_KEY[0.0])[idx]
    return PRIORITY_HELP.get(key, '')


# Kode prioritas -> kunci teks bantuan (varian interlock-grid, paralel-grid).
_HELP_KEY = {
    0.0: ('PV -> Grid -> BESS -> DEG', 'PV -> Grid -> DEG -> BESS'),
    1.0: ('Grid -> PV -> BESS -> DEG', 'Grid -> DEG -> PV -> BESS'),
    2.0: ('PV -> BESS -> Grid -> DEG', 'PV -> BESS -> Grid -> DEG'),
}


def opt_base_params(cfg: dict) -> dict:
    """Parameter dasar (non-sweep) untuk OptimizationEngine dari config GUI."""
    grid_on = bool(cfg.get('grid_enabled', True))
    lp_code = _prio_code(cfg) if grid_on else _off_code(
        cfg.get('load_priority', ''), cfg)
    # Genset dinolkan sesuai jumlah unit (deg_count) — identik dengan
    # to_system_params. Tanpa langkah ini, kapasitas default deg2/deg3 (atau
    # deg1 saat Total DEG = 0) tetap ikut disimulasikan sehingga muncul diesel
    # energy meski pengguna meniadakan genset.
    n = _n_deg(cfg)
    deg = [cfg['deg1_kw'], cfg['deg2_kw'], cfg['deg3_kw']]
    lmax = _deg_lmax(cfg)
    degmax = [lmax, lmax, lmax]
    for i in range(3):
        if i >= n:
            deg[i] = 0.0
            degmax[i] = 0.0
    return dict(
        pv_base_annual=cfg['pv_base_annual'],
        pv_module_wp=cfg.get('pv_module_wp', 0.0),
        soc_init=cfg['soc_init'],
        soc_min=cfg['soc_min'], soc_max=cfg['soc_max'], rte=rte_effective(cfg),
        bess_c_rate=cfg['max_charge_kw'] / max(cfg['bess_kwh'], 1e-9),
        charge_from_grid_below_soc=cfg['charge_from_grid_below_soc'],
        bess_self_cons_kw=_fnum(cfg, 'bess_self_cons_kw', 0.0),
        bess_sc_source=_sc_source_code(cfg),
        grid_charge_max_kw=grid_charge_cap_kw(cfg),
        grid_enabled=cfg['grid_enabled'], grid_kw=cfg['grid_kw'],
        grid_min_loading=cfg['grid_min_loading'],
        grid_max_loading=cfg['grid_max_loading'], interval_h=1.0,
        deg_kw=tuple(deg),
        deg_max_loading=(degmax[0], degmax[1]),
        deg_fuel_rate=deg_fuel_rates(cfg),
        deg_fuel_rate_eff=deg_fuel_rate_eff(cfg),
        allow_export=cfg['allow_export'],
        load_priority=lp_code,
        load_priority_split=bool(cfg.get('load_priority_split', False)) and grid_on,
        load_priority_on=_prio_code(
            {**cfg, 'load_priority': cfg.get('load_priority_on',
                                             'Grid -> PV -> BESS -> DEG')}),
        load_priority_off=_off_code(
            cfg.get('load_priority_off', 'PV -> BESS -> DEG'), cfg),
        charge_priority=_prio(cfg['charge_priority']),
        strict_charge_priority=bool(cfg.get('strict_charge_priority', False)),
        grid_charge_enabled=grid_charge_allowed(cfg),
        deg_charge_enabled=bool(cfg['deg_charge_enabled'])
            and not bool(cfg['deg_interlock']),
        deg_interlock=bool(cfg['deg_interlock']),
        deg_sync=bool(cfg.get('deg_sync', True)),
        deg_always=bool(cfg.get('deg_always', False)),
        deg_grid_former=_deg_gridformer_code(cfg),
        deg_options_split=bool(cfg.get('deg_options_split', False)) and grid_on,
        deg_interlock_on=bool(cfg.get('deg_interlock_on', True)),
        deg_interlock_off=bool(cfg.get('deg_interlock_off', True)),
        deg_charge_on=bool(cfg.get('deg_charge_on', False)),
        deg_charge_off=bool(cfg.get('deg_charge_off', False)),
        grid_interlock=grid_interlock_active(cfg),
        deg_grid_interlock=bool(cfg.get('deg_grid_interlock', True)) and grid_on,
        deg_min_loading=float(cfg.get('deg_min_loading', 0.0)),
        **_bess_adv(cfg),
        pv_degradation=cfg['pv_degradation'])


def cost_config(cfg: dict) -> dict:
    return dict(
        pv_cost_per_kwp=cfg['pv_cost_per_kwp'],
        inverter_cost_per_kw=cfg['inverter_cost_per_kw'],
        bess_cost_per_kwh=cfg['bess_cost_per_kwh'],
        deg_cost_per_kw=cfg['deg_cost_per_kw'],
        accessories_cost=cfg.get('accessories_cost', 0.0),
        logistic_cost=cfg.get('logistic_cost', 0.0),
        epc_cost_per_kwp=cfg.get('epc_cost_per_kwp', 0.0),
        om_fraction=cfg['om_fraction'],
        diesel_price_per_l=cfg['diesel_price_per_l'],
        grid_tariff_per_kwh=cfg['grid_tariff_per_kwh'],
        export_tariff_per_kwh=cfg['export_tariff_per_kwh'],
        tariff_offpeak_per_kwh=cfg.get('tariff_offpeak_per_kwh',
                                       cfg['grid_tariff_per_kwh']),
        discount_rate=cfg['discount_rate'], inflation=cfg['inflation'],
        project_lifetime_y=cfg['project_lifetime_y'],
        baseline_mode=cfg['baseline_mode'],
        finance_scope=cfg.get('finance_scope', 'PV-BESS-DEG'),
        deg_fuel_rate=deg_fuel_rates(cfg),
        deg_fuel_rate_eff=deg_fuel_rate_eff(cfg),
        # v162 — WTG & STG
        wtg_kw=(_fnum(cfg, 'wtg_count', 0) * _fnum(cfg, 'wtg_unit_kw', 0)
                if wtg_active(cfg) else 0.0),
        wtg_cost_per_kw=_fnum(cfg, 'wtg_cost_per_kw', 0.0),
        stg_kw=(_fnum(cfg, 'stg_kw', 0) if stg_active(cfg) else 0.0),
        stg_cost_per_kw=_fnum(cfg, 'stg_cost_per_kw', 0.0),
        stg_fuel_cost_per_kwh=_fnum(cfg, 'stg_fuel_cost_per_kwh', 0.0),
        # v163 — GTG: biaya gas per kWh = heat rate (kJ/kWh) / 1 055 056 × harga
        gtg_kw=(_fnum(cfg, 'gtg_kw', 0) if gtg_active(cfg) else 0.0),
        gtg_cost_per_kw=_fnum(cfg, 'gtg_cost_per_kw', 0.0),
        gtg_fuel_cost_per_kwh=(_fnum(cfg, 'gtg_heat_rate', 12000.0) / 1055056.0
                               * _fnum(cfg, 'gas_price_per_mmbtu', 0.0)))


def _n_deg(cfg) -> int:
    try:
        return int(str(cfg.get('deg_count', '1')))
    except Exception:
        return 1


def _has(cfg, key, default=0.0) -> bool:
    try:
        return float(cfg.get(key, default)) > 0
    except Exception:
        return True


def _adv_bess(cfg) -> bool:
    """True bila ada baterai & mode BESS = Advanced (untuk visibilitas mode)."""
    return _has(cfg, 'bess_kwh') and cfg.get('bess_mode') == 'Advanced'


def _rank_vis(list_id, src=None):
    def f(c):
        if not rank_list_visible(c, list_id):
            return False
        g = rank_groups(c, list_id)
        return bool(g) if src is None else any(src in x for x in g)
    return f


def _has_pqa_load(c) -> bool:
    q = c.get('tr_pqa')
    return isinstance(q, dict) and 'p_max' in q


VISIBILITY = {
    # v168 — dengan data PQA, beban sistem seluruhnya dari PQA
    'tr_load_kw': lambda c: not _has_pqa_load(c),
    'tr_load_source': lambda c: _has_pqa_load(c),
    'tr_load_pf': lambda c: not (_has_pqa_load(c) and (c.get('tr_pqa') or {})
                                 .get('pf')),
    **{'__hdr_' + _l: _rank_vis(_l) for _l in RANK_LISTS},
    **{f'{_l}_{_s}': _rank_vis(_l, _s) for _l in RANK_LISTS for _s in RANK_SRC},
    # ---- Grid: semuanya bergantung ada/tidaknya sambungan grid ----
    'grid_kw':               lambda c: c.get('grid_enabled', True),
    'grid_min_loading':      lambda c: c.get('grid_enabled', True),
    'grid_max_loading':      lambda c: c.get('grid_enabled', True),
    'grid_tariff_per_kwh':   lambda c: c.get('grid_enabled', True),
    'allow_export':          lambda c: c.get('grid_enabled', True),
    'export_tariff_per_kwh': lambda c: c.get('grid_enabled', True)
                                        and c.get('allow_export', False),
    # ---- Dispatch Strategy: mode BESS lanjutan (Advanced) ----
    # Mode, fungsi & target BESS hanya relevan bila ada baterai. Fungsi &
    # target tampil saat mode Advanced; parameter tiap fungsi tampil saat
    # fungsi itu terpilih. Target (Grid/DEG) berlaku untuk keempat fungsi.
    'bess_mode':     lambda c: _has(c, 'bess_kwh'),
    # Judul "BESS Role Function" hanya tampil pada mode Advanced (di atas 8 mode).
    '__hdr_bess_role': lambda c: _adv_bess(c),
    'adv_target': lambda c: _adv_bess(c),
    # Mode BESS = checkbox (tampil bila Advanced & ada baterai); parameter tiap
    # mode tampil hanya saat modenya dicentang.
    'm_pv_smooth':   lambda c: _adv_bess(c),
    'prio_pv_smooth': lambda c: _adv_bess(c) and c.get('m_pv_smooth'),
    'm_firming':     lambda c: _adv_bess(c),
    'prio_firming':  lambda c: _adv_bess(c) and c.get('m_firming'),
    'm_load_shift':  lambda c: _adv_bess(c),
    'prio_load_shift': lambda c: _adv_bess(c) and c.get('m_load_shift'),
    'm_peak_shave':  lambda c: _adv_bess(c),
    'prio_peak_shave': lambda c: _adv_bess(c) and c.get('m_peak_shave'),
    'm_dg_minload':  lambda c: _adv_bess(c) and _n_deg(c) > 0,
    'prio_dg_minload': lambda c: _adv_bess(c) and _n_deg(c) > 0
                                  and c.get('m_dg_minload'),
    'm_reserve':     lambda c: _adv_bess(c),
    'prio_reserve':  lambda c: _adv_bess(c) and c.get('m_reserve'),
    'm_backup':      lambda c: _adv_bess(c),
    'prio_backup':   lambda c: _adv_bess(c) and c.get('m_backup'),
    'pv_ramp_up_kwmin': lambda c: _adv_bess(c) and c.get('m_pv_smooth'),
    'pv_ramp_dn_kwmin': lambda c: _adv_bess(c) and c.get('m_pv_smooth'),
    'smoothing_window': lambda c: _adv_bess(c) and c.get('m_pv_smooth'),
    'firming_kw':     lambda c: _adv_bess(c) and c.get('m_firming'),
    'firming_trigger': lambda c: _adv_bess(c) and c.get('m_firming'),
    'firming_pv_start': lambda c: _adv_bess(c) and c.get('m_firming')
        and not str(c.get('firming_trigger', 'PV Power')).strip().lower().startswith('time'),
    'firming_pv_end': lambda c: _adv_bess(c) and c.get('m_firming')
        and not str(c.get('firming_trigger', 'PV Power')).strip().lower().startswith('time'),
    'firming_time_start': lambda c: _adv_bess(c) and c.get('m_firming')
        and str(c.get('firming_trigger', 'PV Power')).strip().lower().startswith('time'),
    'firming_time_end': lambda c: _adv_bess(c) and c.get('m_firming')
        and str(c.get('firming_trigger', 'PV Power')).strip().lower().startswith('time'),
    'arb_peak_start':      lambda c: _adv_bess(c) and c.get('m_load_shift'),
    'arb_peak_end':        lambda c: _adv_bess(c) and c.get('m_load_shift'),
    'tariff_offpeak_per_kwh': lambda c: _adv_bess(c) and c.get('m_load_shift')
                                         and c.get('grid_enabled', True),
    'peak_shave_kw':  lambda c: _adv_bess(c) and c.get('m_peak_shave'),
    'reserve_frac':   lambda c: _adv_bess(c) and c.get('m_reserve'),
    'reserve_kw':     lambda c: _adv_bess(c) and c.get('m_reserve'),
    # Satu skenario tunggal (saat split nonaktif) ATAU dua skenario per
    # status grid (saat split aktif).
    # Load Supply Priority selalu relevan (urutan PV/BESS/DEG) — termasuk saat
    # TANPA grid. Hanya disembunyikan bila split per-status-grid sedang aktif
    # (yang hanya mungkin ketika grid ada).
    'load_priority':       lambda c: not (c.get('grid_enabled', True)
                                          and c.get('load_priority_split', False)),
    'load_priority_split': lambda c: c.get('grid_enabled', True),
    'load_priority_on':    lambda c: c.get('grid_enabled', True)
                                      and c.get('load_priority_split', False),
    'load_priority_off':   lambda c: c.get('grid_enabled', True)
                                      and c.get('load_priority_split', False),
    'grid_charge_enabled': lambda c: c.get('grid_enabled', True)
                                      and _has(c, 'bess_kwh')
                                      and not grid_interlock_active(c),
    'grid_charge_mode':    lambda c: c.get('grid_enabled', True)
                                      and _has(c, 'bess_kwh')
                                      and grid_charge_allowed(c),
    'grid_charge_max_kw':  lambda c: c.get('grid_enabled', True)
                                      and _has(c, 'bess_kwh')
                                      and grid_charge_allowed(c)
                                      and str(c.get('grid_charge_mode', 'Auto'))
                                      .strip().lower() == 'manual',
    # Mode 'Auto by Grid Status' (kode 4) mengatur sendiri charge priority &
    # interlock per jam, jadi opsi-opsi ini disembunyikan saat mode itu aktif.
    'charge_priority':     lambda c: c.get('grid_enabled', True)
                                      and _has(c, 'bess_kwh')
                                      and c.get('grid_charge_enabled', True)
                                      and _prio_code(c) != 4.0,
    'strict_charge_priority': lambda c: c.get('grid_enabled', True)
                                         and _has(c, 'bess_kwh')
                                         and c.get('grid_charge_enabled', True)
                                         and _prio_code(c) != 4.0,
    # Opsi DEG tunggal (saat split nonaktif) ATAU per status grid (saat aktif).
    # Split hanya "aktif" bila grid ada; tanpa grid, opsi tunggal selalu tampil
    # (mengabaikan nilai split lama yang mungkin tertinggal True).
    'deg_charge_enabled':  lambda c: _n_deg(c) > 0 and _has(c, 'bess_kwh')
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and not (c.get('grid_enabled', True)
                                               and c.get('deg_options_split', False)),
    'deg_interlock':       lambda c: _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and not (c.get('grid_enabled', True)
                                               and c.get('deg_options_split', False)),
    'deg_sync':            lambda c: _n_deg(c) > 1,
    'deg_always':          lambda c: _n_deg(c) > 0,
    'deg_grid_former':     lambda c: bool(c.get('deg_always')) and _n_deg(c) > 1,
    'deg_options_split':   lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0),
    'deg_interlock_on':    lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and c.get('deg_options_split', False),
    'deg_interlock_off':   lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and c.get('deg_options_split', False),
    'deg_charge_on':       lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _has(c, 'bess_kwh')
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and c.get('deg_options_split', False),
    'deg_charge_off':      lambda c: c.get('grid_enabled', True) and _n_deg(c) > 0
                                      and _has(c, 'bess_kwh')
                                      and _prio_code(c) not in (4.0, 5.0)
                                      and c.get('deg_options_split', False),
    'deg_grid_interlock':  lambda c: c.get('grid_enabled', True)
                                      and _n_deg(c) > 0
                                      and _prio_code(c) not in (4.0, 5.0),
    'grid_interlock':      lambda c: c.get('grid_enabled', True)
                                      and (_has(c, 'pv_kwp')
                                           or _has(c, 'bess_kwh'))
                                      and _prio_code(c) not in (0.0, 4.0),
    # ---- Diesel: jumlah unit menentukan field kapasitas ----
    'deg1_kw':            lambda c: _n_deg(c) >= 1,
    'deg2_kw':            lambda c: _n_deg(c) >= 2,
    'deg3_kw':            lambda c: _n_deg(c) >= 3,
    'diesel_price_per_l': lambda c: _n_deg(c) > 0,
    'deg_min_loading':    lambda c: _n_deg(c) > 0,
    'deg_max_loading':    lambda c: _n_deg(c) > 0,
    'deg1_fuel_rate':     lambda c: _n_deg(c) >= 1,
    'deg2_fuel_rate':     lambda c: _n_deg(c) >= 2,
    'deg3_fuel_rate':     lambda c: _n_deg(c) >= 3,
    'deg_cost_per_kw':    lambda c: _n_deg(c) > 0,
    # ---- Battery: kapasitas 0 = tanpa BESS ----
    'soc_init':          lambda c: _has(c, 'bess_kwh'),
    'soc_min':           lambda c: _has(c, 'bess_kwh'),
    'soc_max':           lambda c: _has(c, 'bess_kwh'),
    'rte':               lambda c: _has(c, 'bess_kwh'),
    'max_charge_kw':     lambda c: _has(c, 'bess_kwh'),
    'max_discharge_kw':  lambda c: _has(c, 'bess_kwh'),
    'bess_degradation':  lambda c: _has(c, 'bess_kwh') and not str(
        c.get('bess_soh_source', '')).lower().startswith('soh'),
    'bess_soh_source':   lambda c: _has(c, 'bess_kwh'),
    'rte_source':        lambda c: _has(c, 'bess_kwh'),
    'rte_degradation':   lambda c: _has(c, 'bess_kwh') and not str(
        c.get('rte_source', '')).lower().startswith('rte'),
    'rte_curve':         lambda c: _has(c, 'bess_kwh') and str(
        c.get('rte_source', '')).lower().startswith('rte'),
    'bess_soh_curve':    lambda c: _has(c, 'bess_kwh') and str(
        c.get('bess_soh_source', '')).lower().startswith('soh'),
    'bess_self_cons_kw': lambda c: _has(c, 'bess_kwh'),
    'bess_sc_source':    lambda c: _has(c, 'bess_kwh')
                                   and _fnum(c, 'bess_self_cons_kw', 0.0) > 0,
    'bess_lifetime_y':   lambda c: _has(c, 'bess_kwh'),
    'bess_soh_threshold': lambda c: _has(c, 'bess_kwh'),
    'bess_cost_per_kwh': lambda c: _has(c, 'bess_kwh'),
    'charge_from_grid_below_soc': lambda c: _has(c, 'bess_kwh')
                                             and c.get('grid_enabled', True)
                                             and c.get('grid_charge_enabled', True),
    # ---- v162: strategi BESS tambahan ----
    'm_load_follow':    lambda c: _adv_bess(c),
    'prio_load_follow': lambda c: _adv_bess(c) and c.get('m_load_follow'),
    'lf_set_kw':        lambda c: _adv_bess(c) and c.get('m_load_follow'),
    'lf_charge':        lambda c: _adv_bess(c) and c.get('m_load_follow'),
    'm_freq_reg':       lambda c: _adv_bess(c),
    'fr_kw':            lambda c: _adv_bess(c) and c.get('m_freq_reg'),
    'fr_min':           lambda c: _adv_bess(c) and c.get('m_freq_reg'),
    'm_qv':             lambda c: _adv_bess(c),
    'pcs_kva':          lambda c: _adv_bess(c) and c.get('m_qv'),
    'qv_kvar':          lambda c: _adv_bess(c) and c.get('m_qv'),
    'm_black_start':    lambda c: _adv_bess(c),
    'bs_kw':            lambda c: _adv_bess(c) and c.get('m_black_start'),
    'bs_min':           lambda c: _adv_bess(c) and c.get('m_black_start'),
    # ---- v162: WTG & STG ----
    **{k: (lambda c: bool(c.get('wtg_enabled', False))) for k in (
        'wtg_count', 'wtg_unit_kw', 'wtg_type',
        'wtg_cost_per_kw', 'wtg_loss')},
    'wtg_base_kw': lambda c: str(
        c.get('wtg_input', '')).lower().startswith('power'),
    'wtg_meas_h': lambda c: not str(
        c.get('wtg_input', '')).lower().startswith('power'),
    **{k: (lambda c: bool(c.get('wtg_enabled', False)) and (
        str(c.get('wind_source', 'excel')) == 'era5' or not str(
            c.get('wtg_input', '')).lower().startswith('power'))) for k in (
        'wtg_hub_h', 'wtg_shear', 'wtg_vci', 'wtg_vr',
        'wtg_vco', 'wtg_elev_m', 'wtg_temp_c')},
    **{k: (lambda c: bool(c.get('gtg_enabled', False))) for k in (
        'gtg_kw', 'gtg_commit', 'gtg_min_loading', 'gtg_max_loading',
        'gtg_charge', 'gtg_ramp_kwmin', 'gtg_sched_start', 'gtg_sched_end',
        'gtg_heat_rate', 'gas_price_per_mmbtu', 'gtg_cost_per_kw',
        'gtg_priority')},
    'wtg_priority': lambda c: bool(c.get('wtg_enabled', False))
                              and _has(c, 'pv_kwp'),
    **{k: (lambda c: not str(c.get('tr_pcs_mode', '')).lower()
           .startswith('grid-form')) for k in (
        'tr_gfl_ref', 'tr_gfl_loss', 'tr_gfl_detect_ms')},
    **{k: (lambda c: bool(c.get('stg_enabled', False))) for k in (
        'stg_kw', 'stg_min_loading', 'stg_max_loading', 'stg_priority',
        'stg_charge', 'stg_ramp_kwmin', 'stg_sched_start', 'stg_sched_end',
        'stg_renewable', 'stg_fuel_cost_per_kwh', 'stg_cost_per_kw')},
    # ---- PV: kapasitas 0 = tanpa PV ----
    'pv_module_wp':         lambda c: _has(c, 'pv_kwp'),
    'pv_inv_kw':            lambda c: _has(c, 'pv_kwp'),
    'pv_degradation':       lambda c: _has(c, 'pv_kwp'),
    'pv_base_annual':       lambda c: _has(c, 'pv_kwp'),
    'pv_cost_per_kwp':      lambda c: _has(c, 'pv_kwp'),
    'inverter_cost_per_kw': lambda c: _has(c, 'pv_kwp'),
}


# --- "Base Parameters" (dulu "Base Dispatch & Sources") SELALU tampil, baik
#     mode Standard MAUPUN Advanced -- ini parameter dasar (Load Supply
#     Priority, interlock DEG/Grid, DEG Must Always Run, Charging Priority,
#     dst.) yg jadi FONDASI dispatch fisik utk KEDUA mode; mode Advanced
#     (BESS Role Function/EMS) bekerja DI ATAS fondasi ini, bukan
#     menggantikannya. SEBELUMNYA section ini secara keliru disembunyikan
#     total saat Advanced aktif (lihat riwayat) -- pengguna jadi tak bisa
#     melihat/mengubah mis. DEG Interlock with PV-BESS sama sekali ketika di
#     mode Advanced, padahal parameter itu tetap dipakai mesin dispatch dgn
#     nilai (default/tersimpan) apa adanya secara diam-diam. Sudah dibetulkan:
#     TIDAK ADA lagi pembungkusan visibilitas berbasis _adv_bess di sini --
#     tiap kunci di section ini memakai aturan visibilitasnya sendiri saja
#     (mis. _n_deg(c)>0, grid_enabled, dst., didefinisikan di atas), yg
#     berlaku SAMA di mode Standard maupun Advanced.
