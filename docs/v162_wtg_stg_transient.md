# HPP Studio v162 — WTG, STG, Utility Grid, strategi BESS & Transient Analysis

Dokumen desain & dasar engineering untuk perubahan v161 → v162.

## 1. Ringkasan perubahan

| Area | Isi |
|---|---|
| Sumber baru (dispatch energi) | Wind Turbine Generator (WTG), Steam Turbine Generator (STG) |
| Istilah | "Grid" → "Utility Grid" di seluruh tampilan (kunci config & berkas lama tidak berubah) |
| Strategi BESS | 10 fungsi hasil rasionalisasi 12 permintaan + DG Minimum Loading (lama) |
| Transient Analysis | Halaman baru: simulator RMS satu-bus, 9 kelompok kasus + hubung singkat & proteksi, ekspor Excel/Word |
| Audit | `audit_dispatch_ext.py` (8 invarian); jalur lama byte-identik terhadap v161 |

## 2. Rasionalisasi strategi BESS

Dari 12 strategi yang diminta, dua dihapus karena secara engineering sama dengan strategi lain; sisanya dipetakan sebagai berikut.

| Diminta | Keputusan | Alasan engineering | Model di engine |
|---|---|---|---|
| Frequency regulation | Dipertahankan (baru) | Respons kontinu dua arah; butuh pita daya & energi simetris | ±P_fr ditahan dari PCS, P_fr·t ditahan di kedua sisi SOC |
| Spinning reserve | Dipertahankan (= Operating Reserve lama, ganti nama) | Cadangan kontinjensi satu arah (discharge) | Fraksi SOC + daya PCS ditahan |
| Reactive power & voltage control | Dipertahankan (baru) | Membatasi P lewat kurva kapabilitas PQ | P_maks = √(S² − Q²) |
| **Power quality** | **Dihapus** | Bukan fungsi dispatch tersendiri: komponen tegangan = Q/V control, flicker = renewable smoothing, frekuensi = frequency regulation; harmonik berada di luar model RMS/energi (butuh EMT). Menjadikannya mode sendiri menghitung ganda kapasitas PCS yang sama | Dilaporkan sebagai indeks hasil di Transient Analysis (dip tegangan, RoCoF, nadir) |
| Load follower | Dipertahankan (baru) | Menahan sumber dispatchable di set-point, dua arah; beda dari peak shaving (ambang atas, satu arah) | Discharge di atas P_set, charge (opsional) di bawahnya |
| Backup power | Dipertahankan (lama) | Ambil alih penuh saat outage total | Tidak berubah |
| Firming capacity | Dipertahankan (= Firming lama) | Daya konstan PV+WTG+BESS | Tidak berubah; kini mencakup WTG |
| Black start | Dipertahankan (baru) | Energi dasar SOC untuk restart; **tidak dijumlahkan** dengan spinning reserve (kejadian N-1 tidak bersamaan → lantai efektif = maksimum, bukan jumlah) | Lantai SOC P_bs·t; urutan diuji di Transient |
| Peak shaving | Dipertahankan (lama) | — | Tidak berubah |
| **Energy arbitrage** + energy time-shifting | **Dilebur menjadi satu** ("Energy Time-Shifting / Arbitrage") | Dispatch fisiknya identik (charge saat murah/surplus, discharge saat mahal/puncak); bedanya hanya sinyal pemicu (harga vs waktu). Dua mode = energi yang sama dihitung dua kali | = Load Shifting lama + tarif ToU |
| Renewable smoothing | Dipertahankan (= Smoothing lama) | Kini menghaluskan PV + WTG | Basis MA = PV + WTG |

Catatan tumpang-tindih yang sengaja dibiarkan: Load Follower dengan P_set = minimum loading genset setara DG Minimum Loading pada sisi charge; keduanya tetap ada karena referensinya berbeda (titik kerja ekonomis vs batas teknis mesin).

## 3. Kajian standar — WTG

| Standar | Isi yang dipakai | Implementasi di HPP Studio |
|---|---|---|
| IEC 61400-1:2019 (design requirements) | Kelas turbin I–III/S, model angin normal: profil hukum pangkat V(z) = V_hub·(z/z_hub)^α dengan α = 0,2; model turbulensi NTM; kejadian ekstrem termasuk Extreme Operating Gust (bentuk "Mexican hat", durasi 10,5 s) | Koreksi ketinggian data angin (eksponen dapat diubah; 0,14 lepas pantai per IEC 61400-3-1); kasus C3 Transient memakai bentuk EOG |
| IEC 61400-12-1:2022 (power performance) | Kurva daya berbasis rata-rata 10 menit; normalisasi kerapatan udara — untuk turbin pitch-regulated kecepatan dinormalisasi V_n = V·(ρ/ρ0)^(1/3), ρ0 = 1,225 kg/m³; AEP dari kurva daya × distribusi angin | Kerapatan site dari elevasi & suhu (atmosfer standar), lalu normalisasi kecepatan; kurva daya tiga-wilayah (cut-in, rated, cut-out) |
| IEC 61400-27-1:2020 (generic electrical simulation models) | Model generik urutan-positif domain waktu untuk studi stabilitas jangka pendek; Type 1–4; struktur modular (aerodinamik, mekanik, generator/konverter, kontrol P/Q, pembatas arus, proteksi); bukan untuk harmonik/EMT | WTG Type 3/4 disederhanakan menjadi sumber arus terkendali: prioritas arus reaktif saat tegangan turun (gain K), batas arus, laju pemulihan daya aktif, proteksi ride-through |
| IEC 61400-21-1:2019 (electrical characteristics) | Pengukuran flicker, harmonik, respons terhadap dip tegangan, kontrol P/Q | Dasar parameter LVRT & laju pemulihan; flicker/harmonik di luar model RMS |
| IEEE Std 2800-2022 (IBR interconnection) | Ride-through tegangan & frekuensi, injeksi arus reaktif saat gangguan, primary/fast frequency response, kapabilitas daya reaktif | Ambang trip konverter (V < 0,10 pu > 0,32 s; V < 0,50 pu > 1,2 s; |Δf| > 6 % > 0,3 s) sebagai nilai awal yang dapat disesuaikan dengan grid code setempat |
| IEC 60909-0:2016 (short circuit) | Kontribusi wind power station: DFIG (crowbar) vs full converter (sumber arus) | Type 3 ≈ 3 pu awal; Type 4 = batas arus konverter |

Implikasi desain yang diturunkan:

1. Data angin per jam meremehkan energi karena hubungan kubik (E[v³] > E[v]³); untuk studi bankable gunakan data 10 menit, yang juga merupakan basis IEC 61400-12-1. Aplikasi menerima data resolusi tinggi lewat mekanisme interval yang sudah ada.
2. WTG Type 3/4 tidak menyumbang inersia; pada sistem pulau, seluruh ketidakseimbangan sesaat dipikul sumber pembentuk tegangan (VSG atau mesin sinkron). Kasus C2/C3 mengukur ini langsung.
3. Arus hubung singkat WTG kecil dan terbatas — pada konfigurasi BESS + WTG saja, proteksi arus lebih konvensional tidak bekerja (lihat tabel Feeder Clearing).

## 4. Kajian standar — STG

| Standar | Isi yang dipakai | Implementasi |
|---|---|---|
| IEEE PES-TR1 (2013), Dynamic Models for Turbine-Governors | TGOV1 (governor droop + lag katup + lag steam chest, batas katup) dan IEEEG1 (multi-tahap HP/IP/LP, reheater, batas laju katup); pedoman pemilihan model | STG industri tanpa reheat → struktur TGOV1: droop R, Tg (aktuator/katup), Tt (steam chest), plafon daya; ditambah kompensasi droop transien (governor mekanik-hidraulik) |
| IEEE Std 122-1991 (speed governing of steam turbine-generators) | Regulasi kecepatan tunak, dead band, respons terhadap load rejection | Rentang droop & laju pembebanan sebagai nilai awal |
| IEC 60045-1:2020 (steam turbines — specifications) | Batas operasi: variasi kecepatan/frekuensi yang diizinkan, beban minimum stabil, laju perubahan beban | Minimum Stable Load & Loading Rate Limit pada dispatch |
| IEEE Std 1110-2019 (synchronous generator modeling) | Hierarki model; model 1.0/1.1 (satu-sumbu dengan peluruhan fluks) memadai untuk stabilitas transien mesin kecil | E′q di belakang X′d, T′d0; X″d untuk siklus pertama |
| IEEE Std 421.5-2016 (excitation system models) | Struktur AVR, pembatas V/Hz, kompensasi arus reaktif | AVR PI + lag eksiter + droop reaktif + pembatas V/Hz |
| ISO 8528-5:2022 (genset) | Kelas performa G1–G3: deviasi frekuensi/tegangan transien pada step load | Acuan penilaian kasus DEG (step load, motor start) |
| IEC 60034-1 / -3 | Rating & kapabilitas mesin sinkron | kVA = kW/PF; kurva kapabilitas disederhanakan |

Implikasi desain yang diturunkan:

1. STG adalah unit must-run dengan beban minimum stabil; di bawahnya operasi tidak stabil dan berisiko reverse power (ANSI 32). Dispatch menahan STG di minimum lewat charging BESS bila diizinkan, dan melaporkan jam operasi di bawah minimum.
2. Kemampuan STG dibatasi uap, bukan rating generator. Penurunan tekanan boiler = plafon daya turun; governor tidak dapat mengompensasi → frekuensi jatuh sampai beban berkurang. Kasus D1/D2 dan B2/B3 memodelkan ini.
3. Inersia STG industri kecil (H ≈ 1–2 s) dan loop governor droop murni nyaris tak teredam pada sistem pulau; kompensasi droop transien wajib dimodelkan. Tanpa itu simulasi menunjukkan osilasi yang tidak ada di lapangan.
4. Penutupan STG ke bus yang dipegang VSG kaku jauh lebih sensitif terhadap sudut dibanding ke bus genset: sync-check ANSI 25 hard-wired menjadi persyaratan, bukan opsi.

## 5. Model dispatch energi

**WTG.** v_hub = v_meas·(h_hub/h_meas)^α → v_eq = v_hub·(ρ/ρ0)^(1/3) → kurva daya → rugi plant. Masukan: kolom `Wind` (m/s) atau profil daya plant acuan (kW). Bila profil angin belum ada, WS10m hasil unduhan PVGIS dipakai otomatis.

**STG.** Unit must-run: saat tersedia (kolom `STG Status` dan/atau jendela jam operasi) memikul beban dalam pita [P_min, P_max]. Prioritas `STG -> PV/WTG` (baseload) atau `PV/WTG -> STG`. Charging BESS: tidak / surplus minimum-loading / kapasitas cadangan.

**Integrasi.** PV (setelah inverter) + WTG + surplus STG diperlakukan sebagai satu bus must-take oleh rantai keputusan engine yang sudah teraudit; hasil dipecah kembali per sumber di akhir tiap langkah. Dengan ekstensi mati, seluruh blok dilewati (byte-identik v161).

**Keterbatasan yang perlu diketahui.**
- WTG tidak ikut disapu pada optimasi sizing (kapasitas tetap dari Parameters).
- Baseline finansial (diesel-only / grid+diesel) belum memisahkan STG eksisting; penghematan terhadap baseline mencakup kontribusi STG.
- Pada konfigurasi interlock bus (DEG/Grid ⟂ PV-BESS), STG diasumsikan berada di bus utama paralel dengan semuanya.

## 6. Model Transient Analysis

Simulator RMS (fasor) satu-bus, langkah 1 ms, per-unit pada 1.000 kVA. Validitas ~10 ms sampai beberapa menit. Di luar lingkup: gejala sub-siklus (offset DC, inrush, harmonik) → studi EMT dengan model vendor.

| Elemen | Representasi |
|---|---|
| STG, DEG | Mesin sinkron satu-sumbu (E′q, X′d, T′d0; X″d untuk siklus pertama), AVR PI + droop reaktif + V/Hz, governor droop + kompensasi transien, lag katup & turbin, plafon daya |
| BESS PCS | VSG: rotor virtual (H, droop P-f), reaktansi virtual, loop tegangan droop Q-V, batas arus bergantung waktu, proteksi tegangan-rendah saat di batas arus. Opsi grid-following + FFR |
| PV, WTG | Sumber arus: prioritas arus reaktif LVRT, batas arus, pemulihan daya aktif, trip ride-through |
| Utility Grid | Thevenin (S″k, X/R) |
| Beban | Statis P ∝ V^kpv·(1 + kpf·Δf/f), Q ∝ V²; motor induksi deep-bar dengan dinamika mekanik |

Kelompok kasus: A loss of generation · B loss of the BESS (dengan/tanpa UFLS, STG steam-limited) · C variabilitas PV/WTG · D steam shortfall · E load step & damping · F motor starting · G sinkronisasi · H gangguan feeder · I black start · J hubung singkat & pemutusan feeder.

### Validasi terhadap proposal BPM

Model dijalankan dengan parameter proposal (STG 1.400 kVA, H 1,5 s, X′d 0,22; VSG 1.296 kVA, H_v 3 s, droop 0,5 %, X_v 0,10).

| Kasus | Besaran | Proposal | HPP Studio |
|---|---|---|---|
| STG trip 1.000 kW | Δf / RoCoF / PCS | −0,19 Hz / −1,8 Hz/s / 0,84 pu | −0,19 Hz / −1,85 Hz/s / 0,85 pu |
| STG trip 1.192 kW | Δf / RoCoF / V min | −0,23 Hz / −2,1 Hz/s / 0,97 pu | −0,23 Hz / −2,2 Hz/s / 0,98 pu |
| Motor 185 kW DOL, BESS saja | V min / V 1 s / PCS / arus puncak | 0,90 / 0,96 / 1,18 pu / 2.046 A | 0,90 / 0,96 / 1,20 pu / 2.086 A |
| STG closing 10°, 3 % | Arus STG / ayunan / PCS | 1.533 A / 1.060 kW / 0,74 pu | 1.529 A / 1.058 kW / 0,73 pu |
| STG closing 65°, 15 % | Arus STG / PCS di batas | 2.781 A / 1,30 pu selama 0,65 s | 2.701 A / 1,30 pu selama 0,62 s |
| Load step 200 kW | Mode / dip | 3,1 Hz / 0,04 Hz | 3,1 Hz / 0,045 Hz |
| Fault feeder, BESS saja | Arus / tegangan | 2,3 kA / 0,09 pu | 2,4 kA / 0,10 pu |

Selisih yang tersisa: rasio redaman mode VSG–STG (0,11 vs 0,19) dan lompatan fasa (±1°) — keduanya bergantung detail governor/kontrol yang di proposal dikalibrasi terhadap rekaman PQA. Kedalaman frekuensi pada kasus tanpa BESS bergantung kuat pada parameter beban (kpv, kpf, porsi motor) yang harus dikalibrasi dari pengukuran site.

## 7. Berkas

Baru: `app/engine/wtg.py`, `extsrc.py`, `transient.py`, `transient_cases.py`, `app/gui/pages/transient_page.py`, `app/reports/transient_report.py`, `audit_dispatch_ext.py`, `docs/v162_wtg_stg_transient.md`.

Diubah: `app/engine/dispatch.py`, `bess_modes.py`, `kpi.py`, `finance.py`, `simulation.py`, `optimization.py`; `app/config/parameters.py`, `intervals.py`, `i18n.py`; `app/data/importer.py`, `exporter.py`, `project.py`; `app/reports/common.py`; `app/gui/state.py`, `bgproc.py`, `widgets.py`, `icons.py`, `main_window.py`; halaman `parameters`, `data`, `dashboard`, `results`, `home`, `optimization`, `multi_year`.

## 8. Temuan pada v161 (tidak diubah)

Pada mode Smoothing/Firming/Backup, discharge shaping dapat melebihi beban yang benar-benar dilayani (set-point MA > beban, atau DEG mengambil alih seluruh beban karena interlock): energi tetap dikurangkan dari SOC tetapi tidak punya penerima, sehingga neraca daya bus per langkah tidak menutup (contoh uji: beban 27 kW, discharge 79 kW). Neraca beban tetap benar. Perlu keputusan apakah discharge shaping harus dibatasi beban sisa.

## 9. Tambahan v163

### 9.1 Gas Turbine Generator (GTG)

**Dispatch.** GTG memakai jalur pra-dispatch termal yang sama dengan STG (diproses setelah STG, melihat beban sisanya). Parameter: rating pada kondisi site, minimum stable load, prioritas (`GTG -> PV/WTG` atau `PV/WTG -> GTG`), charging BESS, jendela operasi / kolom `GTG Status`, heat rate (kJ/kWh, LHV) dan harga gas (Rp/MMBTU).

Komitmen GTG ada dua:
- **Must-Run** — selalu menyala saat tersedia, minimal di minimum stable load.
- **On Demand** (default) — menyala hanya bila beban yang harus dipikulnya ≥ minimum stable load; di bawah itu GTG mati dan beban diteruskan ke BESS / Utility Grid / DEG. Konsekuensi: dalam urutan efektif GTG berada **sebelum** BESS discharge.

KPI: energi, jam operasi, jam di bawah minimum, konsumsi gas (MMBTU = kWh × heat rate / 1.055.056). GTG tidak dihitung terbarukan.

**Transient.** Mesin sinkron dengan governor struktur IEEE GAST (lag sistem bahan bakar T1 = 0,4 s, lag pembakaran/turbin T2 = 0,1 s, droop 4 %). Kasus baru: A5 GTG trip, sinkronisasi GTG ke bus BESS, konfigurasi hubung singkat GTG + BESS.

### 9.2 Penataan section Parameters

| Parameter | Section |
|---|---|
| WTG / STG / GTG Dispatch Priority | Dispatch Strategy |
| Allow DEG Charging to BESS, DEG Must Always Run, Grid-Forming DEG Priority | Diesel |
| Allow Grid Charging to BESS, mode & batas dayanya | Utility Grid |
| Seluruh interlock, Load Supply Priority, BESS Charging Priority | Dispatch Strategy (tetap) |

Dispatch Strategy kini menampilkan dua baris informasi yang dihitung dari seluruh pembangkit aktif: **urutan suplai beban efektif** dan **urutan charging BESS efektif** (juga ditulis ke lembar Info ekspor). WTG Dispatch Priority menentukan mana yang dipakai dulu / di-curtail dulu antara PV dan WTG (pro-rata, PV dulu, atau WTG dulu).

### 9.3 PCS Grid-Following: sumber acuan

Mode Grid-Following kini punya **Grid-Following Reference Source** (Auto / Utility Grid / STG / GTG / DEG): sumber yang dianggap "grid" oleh PCS. Bila sumber itu lepas — walau sumber lain masih memegang bus — PCS bertindak menurut **On Loss of Reference**: trip (anti-islanding) atau beralih ke grid-forming setelah waktu deteksi. Selama jeda deteksi tanpa pembentuk tegangan, bus ditopang sumber-sumber arus. PCS grid-following juga memberi dukungan tegangan droop Q-V.

### 9.4 Data beban aktual dari PQA

Halaman Transient mengimpor rekaman PQA (Excel/CSV; kolom waktu, P, opsional Q/PF/S, f, V; kolom min/max dikenali). Bila **Study Load Source** = PQA:
- beban studi = maksimum / persentil-95 / rata-rata terukur; faktor daya beban = terukur;
- kasus load step memakai kenaikan & penurunan beban terbesar antar-sampel;
- kasus baru **K1 Measured load replay**: 16 level beban terukur di sekitar step terbesar diterapkan berurutan (4 s per level).

Keterbatasan: rekaman rata-rata 1 menit menyamarkan step yang lebih cepat; gunakan kolom min/max atau rekaman ≤ 1 s bila ada. Kalibrasi parameter beban (kpv, kpf, porsi motor) terhadap event PQA masih manual.

### 9.5 Default parameter & dasar standar

Tiap parameter Transient kini membawa dasar standar nilai default-nya (tooltip, tab "Dasar Parameter", sheet "Parameter Basis", dan laporan Word). Bila IEC tidak menetapkan angka (mis. eksponen beban, inersia, konstanta waktu governor), hal itu dinyatakan dan sumber nilai tipikalnya disebut (IEEE PES-TR1, ISO 8528-5, ISO 3977-2). Perubahan nilai default: Frequency Maximum 52,0 → 51,5 Hz (IEC 60034-1 Zona B, +3 %).

### 9.6 Grafik & tabel

Grafik menambah panel daya reaktif (kvar) per sumber + beban, dan metrik waktu respons daya reaktif (t90, puncak). Kursor menampilkan garis, penanda titik, dan nilai semua kurva pada waktu tersebut. Lebar kolom tabel dapat digeser dan teks membungkus ke bawah.

### 9.7 Perubahan model lain

Mesin sinkron mendapat torsi peredam (belitan damper) default 1,0 pu — tanpa itu mode lokal terhadap grid kaku nyaris tak teredam. Dampak pada validasi BPM: penutupan STG 65° di batas arus 0,55 s (sebelumnya 0,62 s; proposal 0,65 s); besaran lain tidak berubah berarti.

## 10. v164 — sumber data (PVGIS / ERA5) di halaman Data, satu istilah urutan suplai beban

### 10.1 Unduhan data pindah ke halaman Data
* **Home → Select on map** kini hanya memilih lokasi (lat/lon/alamat). Opsi PVGIS
  dikeluarkan dari dialog peta menjadi `map_picker.PvgisOptionsPanel`.
* **Data → PV ENetAC Source → Download from PVGIS…** membuka opsi PVGIS yang sama
  (orientasi, loss, PVSyst-like, bifacial, tahun) dan mengunduh untuk koordinat
  proyek. Setelan tersimpan di `cfg['pvgis_opts']`. Seluruh mesin unduh
  (`_download_pvgis`, `_on_pvgis_ok`, `_export_pvgis`, …) pindah dari `HomePage`
  ke `DataPage`.
* Adopsi otomatis WS10m PVGIS sebagai profil angin (v162) **dihapus** — sumber
  angin kini eksplisit.

### 10.2 Data angin: ERA5 atau Excel
* Modul baru `app/data/era5.py` (murni data): `fetch_wind(lat, lon, year,
  provider, api_key)`; penyedia `open-meteo` (Open-Meteo Historical Weather API,
  `models=era5`; API key opsional → server `customer-archive-api`) dan `cds`
  (Copernicus CDS `reanalysis-era5-single-levels-timeseries`, butuh token +
  paket opsional `cdsapi`). Dipakai **kecepatan angin 100 m**; waktu UTC digeser
  ke waktu lokal (bujur/15°) seperti PVGIS. Parser (`parse_open_meteo`,
  `parse_cds_csv`) terpisah dari jaringan agar dapat diuji dengan respons tiruan.
* State: `wind_excel`, `wind_era5` (profil DB & .hpps bernama sama),
  `cfg['wind_source']` = `'excel'|'era5'`, `state.wind` = sumber aktif
  (`set_wind_data`, `use_wind_source`). Kolom `Wind` pada impor Excel → sumber
  Excel. Proyek v162/v163 (hanya `wind`) dibaca sebagai sumber Excel.
* Deret ERA5 per-jam disejajarkan ke sumbu waktu beban (`DataPage.fit_hourly`:
  tahan nilai untuk resolusi lebih halus, rata-rata blok untuk lebih kasar).
* Metadata: `wind_era5_year`, `wind_era5_provider`, `wind_era5_api`,
  `wind_era5_height` (100). Key/token **tidak** disimpan.
* Atribusi wajib: "Contains modified Copernicus Climate Change Service
  information"; jalur Open-Meteo: data CC BY 4.0, pemakaian komersial perlu API key.

### 10.3 Tanpa isian ganda di Parameters → WTG
* `wtg_input`, `wtg_meas_h`, `wtg_base_kw` (deskripsi DATA) pindah ke grup skema
  `'Data — Wind'` — tidak dirender di halaman Parameters, melainkan di kartu
  "Wind Data Source" halaman Data, dan hanya tampil untuk sumber Excel.
* Sumber ERA5: `ext_vals` memaksa `wtg_mode = 0` (kecepatan angin) dan
  `wtg_meas_h = 100`. Section WTG tinggal memuat data TURBIN.

### 10.4 Satu istilah: Load Supply Order
"Load Supply Priority" dan "WTG/STG/GTG Dispatch Priority" (v163) adalah konsep
yang sama — urutan sumber memasok beban — dan semua pembangkit memasok beban.
* Label: `WTG / STG / GTG Position in Load Supply`; pilihan WTG `Shared with PV
  (pro-rata) | After PV | Before PV`; STG/GTG `Before PV/WTG (baseload) | After
  PV/WTG (follows load)`. Baris info: "Resulting Load Supply Order" + penjelasan.
* `migrate_cfg` memetakan nilai lama; `_is_re_first` / `_wtg_pos_code` menerima
  nilai lama maupun baru. Engine tidak berubah (kode numerik sama).

## 11. v165 — prioritas bernomor (suplai beban & charging BESS)

### 11.1 Tampilan
Section Dispatch Strategy kini memakai **nomor prioritas per sumber** (1 = pertama):
* **Load Supply Priority** — PV, WTG, STG, GTG, Utility Grid, BESS, DEG (yang aktif).
  Saat "Load Priority Follows Grid Status" aktif: dua daftar (Grid Available /
  Grid Unavailable).
* **BESS Charging Priority** — PV, WTG, STG, GTG (bila Charging to BESS = Spare
  Capacity), Utility Grid (bila charging grid diizinkan), DEG (bila charging DEG aktif).
* PV dan WTG boleh bernomor sama = berbagi pro-rata.
* Dropdown rantai lama (`load_priority`, `load_priority_on/off`, `wtg/stg/gtg_priority`,
  `charge_priority`) tidak ditampilkan lagi (`HIDDEN_KEYS`), tetapi TETAP menjadi kunci
  yang dibaca engine; baris bernomor adalah penyunting di atasnya, tidak disimpan di cfg.

### 11.2 Pemetaan nomor → engine (`parameters.apply_rank`)
`_rank_options()` mengenumerasi semua urutan yang didukung engine (rantai Load Supply ×
posisi WTG × posisi STG/GTG × urutan termal; untuk charging: semua permutasi sumber bus
× Grid di depan/belakang). Permintaan pengguna dicocokkan ke urutan didukung TERDEKAT
(sumber lain dijaga urutannya; opsi yang tidak mendekatkan sumber ke nomor yang diminta
diabaikan). Bila tidak persis, baris ringkasan menampilkan catatan.

Batasan engine (dijelaskan di tooltip):
* STG/GTG selalu sebelum Utility Grid / BESS / DEG (pra-dispatch termal);
* BESS selalu setelah PV/WTG; urutan Grid/BESS/DEG mengikuti rantai yang didukung
  (bergantung opsi interlock DEG);
* charging: Utility Grid hanya sebelum atau sesudah SELURUH sumber bus; DEG selalu
  terakhir (surplus minimum loading); surplus minimum-loading STG/GTG selalu lebih dulu.
* Ringkasan urutan kini menempatkan unit termal "follows load" SEBELUM Utility Grid juga
  pada rantai yang diawali Grid/DEG (sesuai perilaku engine; v163/v164 menampilkannya
  setelah PV).

### 11.3 Kunci cfg & engine baru
* `thermal_order` (`'stg,gtg'|'gtg,stg'`) → `ext['thermal_gtg_first']`. `extsrc.prepare`
  memproses unit baseload lebih dulu, lalu unit pengikut (di tiap sisi menurut
  `thermal_order`). **Perubahan perilaku**: kombinasi STG "follows load" + GTG "baseload"
  dulu diproses STG→GTG (GTG baseload melihat beban yang sudah dikurangi STG pengikut);
  kini GTG→STG, sesuai urutan yang ditampilkan. Kombinasi lain identik dengan v164.
* `charge_bus_order` (mis. `'stg>pv=wtg>gtg'`) → `ext['chg_rank_pv|wtg|stg|gtg']`. Tanpa
  kunci ini engine memakai urutan bawaan v163 (cadangan unit baseload → PV/WTG →
  cadangan unit pengikut). Atribusi bus di `dispatch` kini: porsi beban PV/WTG menurut
  kebijakan suplai beban, lalu charging menurut peringkat charging (`_X['chg_groups']`);
  PV vs WTG untuk charging dapat berbeda dari untuk beban.
* Regresi: urutan bawaan identik dengan v164 (selisih relatif ≤ 1e-15, 120 kasus acak).

### 11.4 Parameter WTG
Semua isian section Wind Turbine (WTG) dipakai dalam perhitungan: jumlah × daya unit
(kapasitas), hub height + shear (ekstrapolasi kecepatan angin ke hub), cut-in / rated /
cut-out (kurva daya), elevasi + suhu (koreksi densitas udara), plant losses, WTG Type
(model transient IEC 61400-27-1 Type 3/4), CAPEX (finansial). Tidak ada yang dihapus.

## 12. v166 — impor PQA berformat template + lima analisis pengukuran

### 12.1 Kolom template (`app/data/pqa.py: GROUPS`, 44 kolom)
Identification (`Date`, `Time`); Half-Cycle RMS `U/I{1..3}_rms1/2_MAX|MIN`; `Freq_wav_MAX`,
`Freq_wav_MIN`, `Freq_AVG`; `U/I{1..3}_rms_AVG`; `Uunb_AVG`, `Iunb_AVG`, `U{1..3}_thd-f_AVG`;
`U/I{1..3}_H5|H7_AVG`; `P_sum_AVG`, `PF_sum_AVG`, `WP+`, `Dem_P+`.
Nama kolom dicocokkan tanpa membedakan huruf besar/kecil, spasi, `_`, `-`, dan akhiran
satuan dalam kurung. `write_template()` menghasilkan template Excel (sheet `PQA Data`,
`Columns`, `Notes`). Berkas tanpa satu pun kolom template masih dibaca parser longgar v163.

### 12.2 Analisis (dilewati bila kolomnya tidak ada; `status` = done / partial / skipped)
| Analisis | Kolom | Keluaran utama |
|---|---|---|
| Half-Cycle Transient & Sag/Swell | `*_rms1/2_MAX|MIN` | min/maks per fasa (pu thd. median RMS), jumlah interval dip (<90 %), swell (>110 %), interupsi (<10 %), faktor lonjakan arus, 10 kejadian terburuk |
| Frequency Stability & RoCoF | `Freq_*` | rentang, % waktu dalam ±1 %, simpangan baku, RoCoF antar-interval, ekskursi MAX−MIN |
| Load Flow, P & Q Profiling | `P_sum_AVG`, `PF_sum_AVG`, `WP+`, `Dem_P+`, RMS rata-rata | P maks/P95/mean/min, load factor, Q & S (dari PF), PF, step beban, jam puncak, energi, demand, basis tegangan |
| Voltage & Current Unbalance | `Uunb_AVG`, `Iunb_AVG` | mean/P95/maks, % waktu > 2 % (tegangan); tanpa kolom → pendekatan NEMA dari RMS tiga fasa |
| THD & Dominant Harmonics | `U*_thd-f_AVG`, `*_H5|H7_AVG` | mean/P95/maks vs batas, harmonisa dominan |

Batas acuan (`LIM`): THD-U 8 %, H5 6 %, H7 5 %, unbalance tegangan 2 %, frekuensi ±1 %
(EN 50160 / IEC 61000-2-2, dinilai pada persentil-95); dip/swell/interupsi 90/110/10 %
(IEC 61000-4-30 / IEEE 1159). Harmonisa arus tidak dinilai (IEEE 519 perlu Isc/IL).

Keterbatasan yang dicantumkan pada hasil: data teragregasi per interval → durasi kejadian
tidak tersedia; RoCoF adalah rata-rata interval (batas bawah); Q diturunkan dari P & PF
(tanda tidak diketahui, dianggap lagging); `P_sum_AVG` dalam W dideteksi dari Σ U·I.

### 12.3 Integrasi
* Ringkasan lama (`p_max`, `p_p95`, `pf`, `step_up_kw`, `window_kw`, …) tetap dihasilkan dari
  `P_sum_AVG`/`PF_sum_AVG` → Study Load Source = PQA dan kasus E1/E2/K1 tetap berjalan. Tanpa
  `P_sum_AVG`, beban studi kembali ke Manual / Profile Peak.
* `cfg['tr_pqa']` kini memuat `analysis` (baris tabel) dan `series` (≤ 600 titik per grafik).
* Halaman Transient: tombol **Template PQA…**, tab **Analisis PQA** (status, tabel, grafik,
  ekspor Excel tersendiri). Ekspor studi: sheet `PQA Analysis` + deret; Word: bab 7.

### 12.4 Penyesuaian terhadap ekspor PQA nyata (contoh 25–27 Mei 2026, 1 menit)
* CSV ekspor langsung dapat diimpor apa adanya: BOM UTF-8, tanggal `dd/mm/yyyy`, angka
  `+230.48E+00`, kolom tambahan (`Status1`, `Status2`) diabaikan.
* Satuan dideteksi: `P_sum_AVG`/`Dem_P+` W→kW dan `WP+` Wh→kWh (banding Σ U·I); harmonisa
  H5/H7 RMS absolut (V/A) → % terhadap RMS rata-rata fasa (dalam %, √(H5²+H7²) tak mungkin
  melebihi THD).
* Interval padam / transisi (ada fasa < 85 % tegangan acuan) dikeluarkan dari statistik
  frekuensi, unbalance, harmonisa dan PF minimum; frekuensi ≤ 40 Hz dianggap tidak valid.
* Kejadian dikelompokkan: interupsi = interval berurutan (awal–akhir, jumlah interval);
  dip di luar interupsi dan interval tepinya; lonjakan arus hanya bila arus rata-rata
  interval ≥ 10 % median.

## 13. v167 — interaksi grafik halaman Transient
* Kursor di luar area grafik (atau meninggalkan widget) → garis kursor & titik data
  disembunyikan dan teks pembacaan kembali ke petunjuk (`_cursor_off`, `LeaveWatcher`).
* Tab Analisis PQA: pembacaan kursor (waktu rekaman + nilai tiap deret) dengan titik data.
* `plotutil.rect_zoom`: roda mouse tidak men-zoom; zoom = seret kotak; klik-ganda = reset.
  `WheelToScroll` meneruskan roda mouse di atas grafik ke scroll halaman.
* Tab Kasus & Analisis PQA berada dalam area gulir vertikal; tinggi tabel diubah dengan
  menyeret pegangan di bawah tabel (`HeightGrip`), grafik tetap terjangkau scroll bar.

## 14. v168 — sistem existing / baru dan pemakaian penuh data PQA

### 14.1 Definisi sistem (halaman Transient → "Definisi Sistem")
* `cfg['tr_existing']` ⊆ {stg, grid, gtg, wtg, deg}; `cfg['tr_new']` ⊆ {pv, bess, stg, gtg, wtg}
  (satu pembangkit hanya boleh di satu sisi). Ukuran tetap dari halaman Parameters; pilihan
  yang belum punya ukuran diberi peringatan dan diabaikan.
* `transient_cases.run_scenarios()` menjalankan `run_study(include=…)` untuk **Existing**,
  **New**, dan **Existing + New**. Tanpa pilihan → satu studi seluruh sumber terkonfigurasi.
* Sistem tanpa sumber pembentuk tegangan (mis. PV saja, atau BESS grid-following saja) tidak
  disimulasikan: `not_viable` berisi alasannya.
* Bentuk hasil: tingkat atas = studi sistem utama (Existing + New bila ada) + `scenarios`
  (studi sistem lain), `comparison`, `assessment`, `version = 3`. `scenario_studies(study)`
  mengembalikan `[(nama, studi)]`; hasil format lama tetap terbaca.

### 14.2 Beban seluruhnya dari PQA
`pqa.study_load()`: bila PQA memuat `P_sum_AVG`, beban studi, faktor daya dan step beban
selalu dari PQA; "Study Load Source" hanya memilih statistik (Maximum / P95 / Mean). Isian
Study Load dan Load Power Factor disembunyikan. Motor DOL terbesar (bila 0): dari lonjakan
arus setengah-siklus, kW ≈ ΣU·ΔI ÷ LRC × 0,8; `study['motor_basis']` mencatat dasarnya.

### 14.3 Penilaian tiap sistem terhadap seluruh kolom PQA (`pqa_assessment`)
| Baris | Kolom PQA | Cara dipakai |
|---|---|---|
| Study load & PF | `P_sum_AVG`, `PF_sum_AVG` | beban & titik operasi semua kasus |
| Kapasitas vs demand | `Dem_P+`, `WP+` | kapasitas firm (generator + Utility Grid) N dan N-1 |
| Step beban terukur | ΔP antar-interval | kasus E1/E2 tiap sistem |
| Lonjakan arus | `I*_rms1/2_MAX|MIN`, `I*_rms_AVG` | ukuran motor DOL kasus F; ΔV ≈ S_surge / S″k |
| Dip & interupsi | `U*_rms1/2_MIN|MAX` | banding V min simulasi; interupsi → peran BESS grid-forming |
| Frekuensi & RoCoF | `Freq_*` | banding rentang simulasi vs terukur dan kriteria |
| Unbalance tegangan | `Uunb_AVG` | diskalakan S″k acuan / S″k sistem, batas 2 % |
| Unbalance arus | `Iunb_AVG`, `I*_rms_AVG` | arus urutan negatif thd. rating mesin sinkron, batas 8 % (IEC 60034-1) |
| THD & H5/H7 tegangan | `U*_thd-f_AVG`, `U*_H5|H7_AVG` | diskalakan S″k, batas 8 / 6 / 5 % |
| H5/H7 arus | `I*_H5|H7_AVG` | beban harmonisa pada mesin / konverter (tanpa batas tetap) |

Penskalaan dengan tingkat hubung singkat adalah perkiraan orde pertama (tegangan
harmonisa/unbalance ∝ impedansi sumber) dan menganggap pengukuran dilakukan pada sistem
Existing; tanpa sistem Existing nilai terukur ditampilkan apa adanya.

### 14.4 Tampilan & ekspor
Pemilih "Sistem yang ditampilkan" di atas tab mengganti isi tab Kasus / Ringkasan / Hubung
Singkat / Model; tab baru **Perbandingan Sistem** memuat tabel perbandingan dan penilaian
PQA. Excel: sheet `Systems`, `PQA Assessment`, `Cases/Requirements/Short Circuit <sistem>`;
Word: "Systems analysed", "Assessment against the measured data (PQA)", "Other analysed systems".

## 15. v169 — grafik perbandingan kasus antar-sistem
* `_scen()`: BESS yang online selalu ditulis pada titik operasi, juga saat 0 kW
  ("BESS 0 kW (online, standby)") — sebelumnya sumber < 0,5 kW disembunyikan sehingga BESS
  tampak tidak ikut dianalisis. Baris perbandingan baru: pembangkit yang dipilih tetapi
  belum dikonfigurasi (`study['missing_sources']`).
* Tab Perbandingan Sistem: pemilih kasus (gabungan ID seluruh sistem; ID sama = kejadian
  sama), tabel metrik kasus per sistem, dan grafik: frekuensi, tegangan bus, arus PCS
  (ditumpuk antar-sistem) + daya aktif dan reaktif per sumber untuk tiap sistem
  (berdampingan, skala-y sama). Sumbu waktu disinkronkan manual (`sigXRangeChanged`) karena
  `setXLink` menyelaraskan menurut posisi layar. Pembacaan kursor, zoom kotak, klik-ganda
  reset, dan roda mouse = scroll halaman berlaku juga di sini.

## 16. v170 — cuplikan PQA per kasus, legenda terkumpul, layar penuh, pemisahan sumber data

### 16.1 Cuplikan kejadian PQA (`pqa['events']`)
Saat impor, jendela data mentah (15 rekaman sebelum … 30 sesudah) disimpan untuk tiap kejadian:
`step_up`, `step_dn` (hanya antar interval bertegangan), `peak`, `surge`, `f_low`, `f_high`,
`dip`, `interruption`, `restore`. Isi: `label`, `at`, `t_from`, `t_to`, `dt_s`, `t` (relatif
kejadian) dan deret P, f avg/min/max, U min/max (pu, fasa terburuk), I ½-siklus maks, I rata-rata.
`transient_cases.pqa_event_for(case, pqa)` memetakan kasus → cuplikan:
A/B/D → `f_low`; C dan E (naik) → `step_up`; E (turun) → `step_dn`; F → `surge`; G/I → `restore`;
H → `dip`; K → `step_up`. Bila kejadian tak ada pada rekaman, cuplikan terdekat dipakai dan
dinyatakan. Data PQA yang diimpor sebelum v170 perlu diimpor ulang.

### 16.2 Tab Perbandingan Sistem
* Label "CUPLIKAN PQA": nama kejadian, waktu kejadian, jendela cuplikan (awal … akhir, jumlah
  rekaman, interval) dan kaitannya dengan kasus; baris "PQA / Pengukuran" pada tabel metrik.
* Baris grafik tambahan "Pengukuran PQA" (frekuensi, tegangan ½-siklus, daya aktif, arus) dengan
  sumbu waktu sendiri (relatif kejadian); kursor & sinkron sumbu-x per kelompok (simulasi / PQA).
* Legenda dikumpulkan di atas grafik (`plotutil.LegendBar`, `FlowLayout`): entri Sistem, Sumber,
  PQA dipakai bersama semua panel; klik = sembunyikan/tampilkan kurvanya di semua panel. Kurva
  tersembunyi tidak ikut pembacaan kursor maupun skala-y bersama.

### 16.3 Layar penuh & menu utama
* `plotutil.PopOut`: blok grafik (pemilih, legenda, pembacaan kursor, grafik) dipindahkan ke
  dialog layar penuh dan dikembalikan saat ditutup (Esc) — widget yang sama, jadi kursor data,
  zoom dan legenda tetap bekerja. Tombol "⛶ Layar penuh" pada grafik Kasus, Perbandingan, PQA.
* `MainWindow.toggle_sidebar()`: tombol ☰ di status bar dan Ctrl+B menyembunyikan menu utama.

### 16.4 Pemisahan menurut sumber data
Tab luar (`top_tabs`): **Perbandingan Sistem** (SIMULASI + PQA), **Simulasi (Parameter & Standar)**
(berisi Kasus, Ringkasan dan Persyaratan, Hubung Singkat dan Proteksi, Model dan Data, Dasar
Parameter), **Pengukuran (Data PQA)** (Analisis PQA). Tiap kelompok dan tiap bagian tab
perbandingan diberi lencana sumber data.

## 17. v171 — layar penuh 2 kolom, judul sumber data netral, grafik mengikuti tema
* `PopOut`: tombol "Layar penuh" disembunyikan selama mode layar penuh; blok grafik ditaruh
  di `QScrollArea` (boleh gulir vertikal) lalu dikembalikan utuh saat ditutup.
* Layar penuh 2 kolom: grafik Kasus 2 × 2 (`_layout_case`: panel yang sama dipindah di
  `GraphicsLayout`); Perbandingan Sistem f | V, arus PCS (lebar penuh, hanya bila ada BESS),
  P | Q per sistem, cuplikan PQA 2 × 2 — tinggi ± 300 px per baris. Tab Pengukuran tetap
  1 kolom. Sumbu-x disinkronkan dengan `plotutil.link_x` (menyalin rentang; `setXLink`
  menyelaraskan menurut posisi layar sehingga salah pada panel berdampingan). Entri legenda
  yang disembunyikan tetap tersembunyi saat tata letak berganti.
* Judul sumber data tanpa lencana berwarna: satu baris "Sumber data: …" per tab utama, dan
  bagian bernomor di tab Perbandingan Sistem — 1. Perbandingan sistem (simulasi model),
  2. Penilaian terhadap data PQA (hasil simulasi dibandingkan dengan pengukuran PQA),
  3. Grafik kasus (simulasi model di panel atas, cuplikan PQA di panel bawah).
* Tema: `theme.style_layout()` menerapkan latar, sumbu, label dan judul tema aktif ke
  `GraphicsLayoutWidget` (termasuk sub-layout); `apply_theme` kini juga memprosesnya —
  sebelumnya hanya `PlotWidget`, sehingga kanvas multi-panel tetap gelap pada mode terang.

## 18. v172 — layar penuh: header tetap, 1/2/3 kolom, muat 1 layar; tanpa kedip
* `PopOut(scroll=…)`: saat layar penuh hanya kanvas grafik yang masuk `QScrollArea`; judul,
  pemilih kasus, keterangan cuplikan PQA, legenda dan pembacaan kursor tetap di atas (freeze).
* Kontrol tata letak kecil di kanan pemilih kasus (dan di baris judul grafik Kasus), hanya
  tampil saat layar penuh: **1 / 2 / 3 kolom** dan **Gulir / Muat 1 layar**. Kedua grafik
  memakai pilihan yang sama (tersinkron) dan diingat di `cfg['tr_fs_cols']`, `cfg['tr_fs_fit']`.
  Grid: tiap kelompok panel mulai di baris baru; panel terakhir kelompok mengisi sisa kolom;
  P/Q sistem disusun per baris jenis (P semua sistem, lalu Q) bila kolom ≥ jumlah sistem,
  selain itu P | Q per sistem. Gulir = ± 300 px per baris; Muat 1 layar = 110 px minimum per
  baris dan label sumbu waktu dihemat.
* Kedip saat **buka proyek**: `MainWindow.freeze_for_load()` menutup jendela dengan foto dan
  mematikan penggambaran selama state diisi; halaman dibangun ulang sekali di balik foto
  (`_rebuild` memakai foto yang sudah ada), foto dipudarkan, lalu pesan "Proyek dimuat"
  muncul. Sebelumnya setiap sinyal perubahan menggambar ulang halaman, lalu bangun ulang
  kedua terjadi setelah pesan ditutup.
* Kedip setelah **login**: jendela utama dibuat transparan, dimaksimalkan dan bilah judulnya
  diwarnai sebelum dipudarkan masuk (160 ms). `apply_titlebar_theme` hanya memaksa bingkai
  digambar ulang (SWP_FRAMECHANGED) bila warnanya berubah per jendela — fungsi ini terpanggil
  pada setiap Show/aktivasi jendela, termasuk setelah dialog ditutup.

## 19. v173 — tanpa tooltip di atas grafik
Tooltip "Zoom: seret kotak … · Reset: klik-ganda" pada kanvas grafik Kasus, Perbandingan
Sistem dan Analisis PQA dihapus karena menutupi kurva saat kursor diam di atas grafik.
Petunjuk yang sama kini ada di baris pembacaan kursor (`_hint()`), yang tampil saat kursor
berada di luar grafik.

## 20. v174 — jendela kecil kosong ("H..") saat aplikasi dibuka / proyek dimuat
Penyebab: sejak v170 (`toggle_sidebar`), `_build_ui` memanggil `side.setVisible(True)` SEBELUM
sidebar dimasukkan ke layout. Pada widget tanpa induk, `setVisible(True)` membuatnya menjadi
jendela top-level tersendiri — sidebar (lebar 184 px, tinggi penuh) sempat tampil sebagai
jendela sempit kosong berikon HPP Studio setiap kali UI dibangun: setelah login, saat buka
proyek, dan saat ganti bahasa. Perbaikan: sidebar dimasukkan ke layout dulu, lalu hanya
`setVisible(False)` bila pengguna menyembunyikannya. Diverifikasi dengan pemantau event
(Show / WinIdChange / PlatformSurface pada widget top-level): tidak ada lagi jendela selain
MainWindow selama startup, bangun ulang (sidebar tampil/tersembunyi), buka proyek, ganti
bahasa, dan navigasi semua halaman.

## 21. v175 — legenda terkumpul di semua grafik halaman Transient
* Grafik **Kasus**: legenda pyqtgraph di dalam panel P/Q dihapus; diganti `LegendBar`
  (`leg_case`) di atas grafik — kelompok Bus (Frekuensi, Tegangan) dan Sumber (tiap sumber +
  Beban). Satu entri berlaku untuk panel P dan Q sekaligus; warna sumber sama di kedua panel;
  daya aktif beban (p_load) kini ikut digambar (garis putus-putus) seperti di Perbandingan.
  `_curves` = (plot, t, y, label, color, unit, key, item).
* Grafik **Analisis PQA**: `leg_pqa` (satu entri per deret + "Batas acuan" untuk garis batas).
* Entri yang disembunyikan tetap tersembunyi saat berganti kasus / grafik; kurva tersembunyi
  tidak ikut pembacaan kursor. Pada layar penuh legenda berada di bagian atas yang tetap.

## 22. v176 — nama tab Simulasi dan pemilih kasus pada layar penuh
* Tab "Simulasi (Parameter & Standar)" → **Simulasi (Parameter Standar)** / EN **Simulation
  (Parameters Standard)**. Di Qt, '&' pada label tab adalah penanda mnemonic sehingga tampil
  sebagai garis bawah, bukan karakter '&'.
* Grafik Kasus layar penuh: baris "Grafik kasus" (pemilih kasus + pilihan kolom / Gulir-Muat)
  di bagian atas yang tetap, seperti Perbandingan Sistem. Pemilih kasus (`cb_case`) dan tabel
  kasus saling tersinkron; baris ini disembunyikan di luar layar penuh (tabel sudah tersedia).

## 23. v177 — bukti & penjelasan hasil Pass/Fail tiap kasus; kebocoran bahasa Indonesia di mode EN
* `transient_cases.case_evidence(case, crit)` menghitung ulang setiap kriteria penerimaan dari
  metrik yang tersimpan (aturan yang sama dengan `_verdict`): bus tetap bertegangan, PCS tetap
  terhubung, PV/WTG ride-through, frekuensi min/maks, tegangan bus min, pemulihan tegangan
  ≤ 1,0 s (gangguan), RoCoF (trip/dinamis), arus PCS pasca-kejadian ≤ ilim_cont. Tiap baris:
  kriteria, nilai terukur, batas, status (Pass/Fail/Not assessed), dasar standar, margin.
* Penjelasan otomatis: Fail → kriteria yang dilanggar + nilai vs batas; Pass → semua kriteria
  terpenuhi + kriteria yang paling dekat batasnya; Ref → tidak dinilai, kriteria yang akan gagal.
* GUI: label kasus menampilkan "Dasar hasil"; tabel baru **Bukti penilaian** (dapat diubah
  tingginya) di bawah tabel kasus; tabel kasus Perbandingan Sistem ditambah kolom
  'Basis of the result'. Laporan: kolom 'Basis of the result' di sheet Cases, sheet Excel baru
  **Evidence**, dan paragraf penjelasan per kasus di Word.
* Mode English: teks dasar arus hubung singkat (engine) kini berbahasa Inggris; status bar
  langsung diperbarui setelah ganti bahasa (sebelumnya "Belum disimulasi" sempat tampil).

## 24. v178 — kerapian kartu Status Data (halaman Data)
* Kartu Status Data memakai grid 2 kolom (pengganti QFormLayout): label & nilai rata atas pada
  baris yang sama, tinggi baris minimum seragam (24 px, jarak 8 px). Sisa tinggi kartu (yang
  mengikuti tinggi kolom kanan) ditaruh di bawah baris terakhir, tidak lagi dibagi tak merata
  ke tiap baris sehingga label dan nilai sebelumnya tampak tidak sejajar.

## 25. v179 — Case Analysis Mode (Dashboard → Time Series) mengikuti pembangkit yang tersedia
* `engine/cases.py`: `CaseScheme(dims, bess)` + `scheme_from(params, cfg, series)`. Dimensi hanya
  untuk aset yang terpasang — urutan signifikansi DEG · GTG · STG · Grid · WTG · PV, lalu BESS
  (4 keadaan) bila ada. Nomor case = 1 + Σ bit_OFF·bobot + idx_BESS; jumlah case = 2^dims × (4|1).
  Deteksi: Grid = `grid_enabled`; PV = pv_kwp > 0; DEG = Σ deg_kw > 0; WTG/STG/GTG = `params.ext`
  (`*_on`); BESS = bess_kwh > 0. Status per langkah: Grid status, PV/WTG/STG/GTG/DEG > 0.
* Sistem PV + BESS + Grid + DEG → skema lama 32 kasus (nomor, teks, warna identik — diuji).
  Tanpa BESS setiap langkah mendapat case; dengan BESS "idle & energi cukup" tetap tanpa case.
* Dashboard: duplikasi klasifikasi dihapus (memakai engine). Menu "Pilih Case" menampilkan baris
  "Pembangkit: …", kolom = status pembangkit paling signifikan (mis. DEG ON | DEG OFF; tanpa DEG →
  GTG/STG/Grid/...), label & tooltip hanya memuat pembangkit yang ada. Filter case direset bila
  skema berubah (nomor case berubah arti).
* Laporan (Analisis Mode Operasi & Metodologi): jumlah mode, dimensi, deskripsi & warna mengikuti
  skema yang sama.

## 26. v180 — layar penuh Transient: atur posisi grafik dengan menyeret
* `plotutil.PanelMover(glw, panels, on_swap, enabled)`: event filter pada viewport
  GraphicsLayoutWidget. Strip judul tiap panel (judul diawali "⠿", kursor tangan) menjadi pegangan
  seret; lepas di atas panel lain → kedua panel **bertukar posisi** (kotak sorot pada panel tujuan +
  label "Tukar posisi panel"). Seret di area plot tetap = zoom kotak; klik-ganda judul diabaikan.
  Aktif hanya saat layar penuh.
* Posisi disimpan sebagai permutasi slot `{key panel: key slot}` (`apply_perm` / `swap_perm`) di
  cfg proyek: `tr_fs_perm_case` (Kasus: f, v, p, q) dan `tr_fs_perm_cmp` (Perbandingan Sistem:
  f, v, i, P:<sistem>, Q:<sistem>, PQA:<kolom>). Tetap berlaku saat jumlah kolom diubah, kasus
  diganti, atau layar penuh dibuka lagi; pasangan yang panelnya tidak ada diabaikan.
* Tombol **↺ Tata letak awal** di baris kontrol layar penuh mengembalikan urutan bawaan. Di luar
  layar penuh tata letak halaman tidak berubah (judul pegangan disembunyikan).

## 27. v181 — layar penuh Transient: GRID bebas (posisi & ukuran tiap grafik)
* Menggantikan tukar-posisi v180 (`PanelMover`, `tr_fs_perm_*` tidak dipakai lagi).
  `plotutil.GridArranger(glw, enabled)`: area grafik = **12 kolom** × baris **50 px** (mode
  Gulir) atau baris yang menyesuaikan tinggi layar (mode Muat 1 layar). Tiap panel = persegi
  `[baris, kolom, rentang baris, rentang kolom]`; panel dikeluarkan dari QGraphicsGridLayout dan
  diberi geometri manual sehingga sel kosong benar-benar kosong (panel boleh di mana saja).
* Interaksi (hanya layar penuh): seret **judul panel (⠿)** → pindah (dikunci ke grid); seret
  **sudut kanan-bawah** (tanda ⟋) / **tepi kanan** / **tepi bawah** → ubah ukuran (min 2×2 sel).
  Saat menyeret tampil garis grid + kotak target + label "Kolom a–b / 12 · Baris c–d · w × h".
  Panel yang tertimpa didorong ke bawah. Seret di area plot tetap = zoom kotak; Esc membatalkan.
* Tersimpan di proyek: `tr_fs_grid_case` (f, v, p, q) dan `tr_fs_grid_cmp` (f, v, i,
  P:<sistem>, Q:<sistem>, PQA:<kolom>); panel tanpa posisi tersimpan diletakkan di bawah dengan pola
  bawaan. Pilihan **jumlah kolom 1/2/3** kini = pola bawaan (memilih ulang menyusun ulang panel);
  **↺ Tata letak awal** mengembalikan pola bawaan. Di luar layar penuh tata letak halaman tetap.

## 28. v182 — Analisis PQA (tab Pengukuran) layar penuh: beberapa grafik + grid bebas
* Di halaman tetap 1 grafik (pemilih combo). Di layar penuh, combo diganti tombol **"n dari N grafik ▾"**
  (daftar centang; minimal 1, "Tampilkan semua") — tiap analisis terpilih (Sag/Swell, Frequency &
  RoCoF, Load Flow P/Q, Unbalance, THD/Harmonics) tampil sebagai panel sendiri pada `glw_pqa`.
* Tata letak memakai `GridArranger` (v181): seret judul = pindah, sudut/tepi kanan-bawah = ubah
  ukuran; pilihan 1/2/3 kolom = pola bawaan, Gulir / Muat 1 layar, ↺ Tata letak awal. Tersimpan di
  proyek: `tr_pqa_fs_charts` (grafik terpilih) dan `tr_fs_grid_pqa` (posisi/ukuran per id analisis).
* Sumbu waktu antar panel disamakan (`link_x`); kursor: garis waktu di semua panel, nilai kurva pada
  panel yang ditunjuk + judul analisisnya. Legenda dikelompokkan per grafik (kunci `pqafs:<id>:<kurva>`).
* `theme.style_layout` kini juga mewarnai panel yang ditempatkan manual (grid bebas), sehingga ganti
  tema terang/gelap saat layar penuh ikut diterapkan (berlaku juga untuk Kasus & Perbandingan Sistem).
