# ⚡ HPP Studio

Aplikasi desktop untuk **simulasi operasi & optimasi sizing Hybrid Power Plant**
(PV + BESS + Diesel Generator + Grid). Pengganti workbook Excel
`sizing_analysis_Villa_Bali` — logika dispatch **identik** dengan Excel
(tervalidasi hingga deviasi 1e-13 pada seluruh 8760 jam), namun ratusan kali
lebih cepat dan tidak membutuhkan Microsoft Excel.

## Fitur

- Simulasi operasi per jam selama 1 tahun (8760/8784 jam)
- Optimasi sizing PV / Inverter / BESS: sweep seluruh kombinasi range dengan
  **NumPy tervektorisasi + multiprocessing** (ratusan–ribuan simulasi/detik)
- 9 objective function (Min LCOE, Max NPV, Min CAPEX, Min Payback, Max RF,
  Min Fuel, Min Grid Import, Min PV Excess, Min Unserved) + optimization
  constraints
- KPI teknis & finansial lengkap: RF, cycles, throughput, curtailment, fuel,
  LCOE, CAPEX, OPEX, NPV, IRR, ROI, payback, cashflow
- Dashboard interaktif: time series (zoom/pan + overview region), pie energy
  mix, bar bulanan, heatmap harian (SOC / Diesel / Excess)
- Laporan HTML mandiri (bisa dibuka browser apa pun, siap kirim ke customer)
  dan export Excel
- Dark / Light mode, parameter tersimpan otomatis (SQLite + JSON)

## Baru di v162

- **Sumber tambahan**: Wind Turbine Generator (WTG) & Steam Turbine Generator
  (STG) pada dispatch energi; istilah "Grid" menjadi **Utility Grid**.
  Kolom data baru (opsional): `Wind` (m/s atau kW) dan `STG Status` (1/0).
- **Strategi BESS** (mode Advanced): Frequency Regulation, Spinning Reserve,
  Reactive Power & Voltage Control, Load Follower, Backup Power, Firming
  Capacity, Black Start, Peak Shaving, Energy Time-Shifting / Arbitrage,
  Renewable Smoothing, DG Minimum Loading.
- **Halaman Transient**: studi dinamik RMS satu-bus (trip pembangkit, loss of
  BESS, variabilitas PV/WTG, steam shortfall, load step & damping, motor
  starting, sinkronisasi, gangguan feeder, black start) + hubung singkat &
  proteksi; ekspor Excel dan laporan Word.
- **v181**: layar penuh Transient — grid bebas: grafik dapat dipindah ke sel mana pun dan diubah ukurannya (seret judul / sudut kanan-bawah).
- **v180**: layar penuh Transient — posisi grafik dapat diatur dengan menyeret judul panel (tukar posisi; tombol Tata letak awal).
- **v179**: Case Analysis Mode (Dashboard) mengikuti pembangkit yang tersedia (Grid/PV/WTG/STG/GTG/DEG/BESS).
- **v178**: kartu Status Data di halaman Data dirapikan (label & nilai sejajar, jarak baris seragam).
- **v177**: bukti & penjelasan Pass/Fail tiap kasus Transient (tabel Bukti penilaian, sheet
  Excel Evidence); perbaikan teks Indonesia yang muncul di mode English.
- **v176**: nama tab "Simulation (Parameters Standard)"; pemilih kasus pada grafik Kasus layar
  penuh (bagian atas yang tetap).
- **v175**: legenda grafik Kasus dan Analisis PQA dikumpulkan di atas grafik (satu entri untuk
  semua panel, dapat disembunyikan bersama), sama seperti Perbandingan Sistem.
- **v174**: perbaikan jendela kecil kosong yang sempat muncul (berkedip) setelah login, saat buka
  proyek, dan saat ganti bahasa.
- **v173**: tooltip petunjuk zoom di atas grafik halaman Transient dihapus (dipindah ke baris
  pembacaan kursor).
- **v172**: layar penuh halaman Transient — bagian atas tetap terlihat saat digulir, pilihan
  1/2/3 kolom dan Gulir / Muat 1 layar; kedip saat buka proyek dan setelah login dihilangkan.
- **v171**: halaman Transient — layar penuh tanpa tombol ganda dan tersusun 2 kolom (boleh
  gulir), judul sumber data yang netral dan tidak berulang, grafik multi-panel mengikuti tema
  terang/gelap.
- **v170**: halaman Transient — cuplikan data PQA kejadian terkait pada tiap kasus (dengan waktu
  cuplikan), legenda terkumpul di atas grafik, grafik layar penuh, tab dipisah menurut sumber data
  (simulasi / pengukuran PQA / gabungan); menu utama dapat disembunyikan (☰ atau Ctrl+B).
- **v169**: tab Perbandingan Sistem — grafik tiap kasus untuk semua sistem (frekuensi, tegangan,
  arus PCS, daya aktif/reaktif per sumber); BESS siaga 0 kW kini ditulis pada titik operasi.
- **v168**: halaman Transient — pilih pembangkit sistem existing dan sistem baru; studi dijalankan
  untuk Existing, New, dan Existing + New, dengan tab Perbandingan Sistem. Dengan data PQA, beban
  sistem seluruhnya dari PQA dan tiap sistem dinilai terhadap seluruh kelompok kolom PQA.
- **v167**: grafik halaman Transient — kursor di luar grafik tidak men-trace, pembacaan kursor
  di tab Analisis PQA, zoom dengan menyeret kotak (klik-ganda = reset, roda mouse menggulir
  halaman), tab dapat digulir vertikal dan tinggi tabel dapat diubah.
- **v166**: impor PQA di halaman Transient memakai kolom template (tombol "Template PQA…")
  dan menjalankan lima analisis pengukuran (sag/swell setengah-siklus, frekuensi & RoCoF,
  profil beban P/Q, unbalance, THD & harmonisa H5/H7); analisis yang kolomnya tidak ada dilewati.
- **v165**: Load Supply Priority dan BESS Charging Priority memakai nomor prioritas per
  sumber (1 = pertama) untuk seluruh pembangkit aktif; urutan charging WTG/STG/GTG dapat
  diatur; urutan STG/GTG dapat dibalik.
- **v164**: unduhan PVGIS pindah ke halaman Data (Home hanya memilih lokasi di peta);
  data angin dapat diunduh dari ERA5 (Open-Meteo / Copernicus CDS, angin 100 m) dan
  dipilih sebagai sumber aktif (ERA5 atau input Excel); deskripsi data angin pindah dari
  Parameters → WTG ke halaman Data; istilah prioritas disatukan menjadi
  "Load Supply Order" (posisi WTG/STG/GTG dalam urutan suplai beban).
- **v163**: Gas Turbine Generator (GTG) pada dispatch & transient; impor
  data beban aktual PQA di halaman Transient; sumber acuan PCS
  Grid-Following; panel daya reaktif + pembacaan kursor pada grafik; dasar
  standar tiap parameter transient; prioritas WTG/STG/GTG di Dispatch
  Strategy. Kolom data baru (opsional): `GTG Status` (1/0).
- Audit baru: `python audit_dispatch_ext.py`. Dasar engineering & kajian
  standar: `docs/v162_wtg_stg_transient.md`.

## Struktur Proyek

```
HPPStudio/
├── main.py                  # entry point
├── requirements.txt
├── hpp_studio.spec          # konfigurasi PyInstaller
├── build_windows.bat        # build .exe satu-klik
├── assets/
│   └── sample_input.xlsx    # contoh input (profil Villa Bali)
└── app/
    ├── config/parameters.py # skema parameter (mudah ditambah)
    ├── engine/
    │   ├── dispatch.py      # logika dispatch per jam (vektorisasi batch)
    │   ├── kpi.py           # KPI teknis + agregasi bulanan
    │   ├── finance.py       # CAPEX/OPEX/LCOE/NPV/IRR/ROI/payback
    │   ├── simulation.py    # fasad simulasi tunggal
    │   └── optimization.py  # sweep grid + ProcessPoolExecutor
    ├── data/
    │   ├── importer.py      # baca Excel Load/PV/Grid (nama kolom fleksibel)
    │   ├── exporter.py      # export hasil ke Excel
    │   └── database.py      # SQLite proyek & profil
    ├── reports/report_builder.py  # laporan HTML (chart SVG inline)
    └── gui/                 # PySide6: theme, widgets, halaman-halaman
```

## Menjalankan (mode pengembangan / VS Code)

Cara tercepat: double-click **`run_dev.bat`** — otomatis memilih Python
3.10–3.13 yang terpasang (PySide6 belum tersedia untuk Python 3.14),
membuat venv di `%LOCALAPPDATA%\\hppstudio-venv` (di luar OneDrive agar
terhindar dari batas panjang path), menginstal dependensi, lalu menjalankan
aplikasi. Untuk menguji engine tanpa GUI: **`selftest.bat`**.

Manual:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python selftest.py     :: verifikasi engine tanpa GUI (opsional)
python main.py         :: jalankan aplikasi
```

Folder `.vscode/` sudah disertakan: buka folder proyek di VS Code, pilih
interpreter `.venv\Scripts\python.exe`, lalu tekan **F5** untuk menjalankan
dengan debugger. `selftest.py` menguji seluruh rantai non-GUI (import →
simulasi → optimasi multiprocessing → export → laporan) dan mencetak ✔ bila
hasil simulasi identik dengan referensi Excel.

## Build .exe Windows

Cukup jalankan **`build_windows.bat`** (double-click). Hasil:
`dist\HPPStudio\HPPStudio.exe`. Salin seluruh folder `dist\HPPStudio`
untuk distribusi — tidak perlu Python maupun Excel di komputer tujuan.

> Mode default *onedir* (start-up cepat). Jika ingin satu file tunggal,
> jalankan `pyinstaller --onefile --windowed main.py` (start-up lebih lambat).

## Format Input

File Excel/CSV, satu sheet, baris pertama header. Kolom yang dikenali
(nama fleksibel, tidak case-sensitive):

| Kolom      | Alias yang dikenali                          | Wajib |
|------------|----------------------------------------------|-------|
| Datetime   | datetime, date, time, waktu, tanggal         | ya    |
| Load       | load, beban, load (kw), load_kw              | ya*   |
| PV ENetAC  | pv, earray, pv earray (kw), pv_kw            | ya*   |
| Grid Status| grid, pln, grid status (1/0)                 | tidak |

\* Load dan PV boleh di file terpisah (import dua kali) atau satu file.
Jumlah baris harus 8760 atau 8784 (tahun kabisat). `Grid Status` = 1 saat
PLN tersedia, 0 saat padam; jika tidak ada dianggap selalu tersedia.
Lihat `assets/sample_input.xlsx`. Tombol **Import dari Workbook Lama** di
halaman Data juga bisa membaca langsung workbook Excel Villa Bali.

## Berkas Proyek (.hpps)

Seluruh pekerjaan dapat disimpan ke satu berkas **`.hpps`** (HPP Studio
Project) lewat tombol **Simpan Proyek…** di halaman Home atau **Ctrl+S**;
membukanya kembali dengan **Buka Proyek…** atau **Ctrl+O**.

Isi berkas: identitas proyek, seluruh parameter (strategi dispatch,
finansial, multi-year, batasan optimasi), profil data 8760 jam (Load,
PV ENetAC, Grid Status), **dan seluruh hasil yang sudah dihitung** —
simulasi (Dashboard & Results), hasil optimasi, serta simulasi
multi-year. Membuka kembali berkas langsung menampilkan semuanya tanpa
perlu menghitung ulang. Formatnya JSON terkompresi gzip: tanpa hasil
hanya ±18 KB, lengkap dengan seluruh hasil ±0,2 MB.

## Alur Pakai

1. **Data** — import Load Profile & PV ENetAC (atau workbook lama / sample)
2. **Parameters** — atur grid, diesel, baterai, PV, finansial, constraints
3. **Dashboard** — *Run Simulation* → lihat time series, mix, bulanan, heatmap
4. **Optimization** — dua mode sizing (Manual Range / Auto Optimizer) dengan
   objective bertingkat. Bagian **Batch Multi-Site** di bawah tabel hasil
   memungkinkan menjalankan optimasi untuk beberapa berkas data sekaligus:
   pilih berkasnya, jalankan, dan tiap site (nama diambil dari nama berkas)
   dioptimasi memakai parameter & objective yang sama. Hasilnya dapat
   diekspor ke satu Excel berisi ringkasan per site plus satu sheet detail
   untuk masing-masing site.

   Alur lama tetap berlaku:
   4b. **Optimization** — isi range PV/INV/BESS + objective → *Run* →
   *Terapkan Terbaik* untuk memindah hasil ke Parameters
5. **Results** — KPI lengkap + cashflow → *Export Excel* / *Generate Report*

## Catatan Teknis

- Logika dispatch mengikuti urutan formula Excel: PV → BESS discharge →
  Diesel (saat grid padam) → Grid, charge dari PV surplus lalu dari
  grid saat SOC < ambang, dengan batas SOC min/max, RTE, dan C-rate.
- Pada optimasi, daya charge/discharge BESS mengikuti C-rate dari parameter
  (Max Charge ÷ Nominal Capacity) sehingga ikut terskala dengan kapasitas.
- Engine dipisah total dari GUI — bisa dipakai dari skrip Python biasa
  (`from app.engine.simulation import SimulationEngine`).
