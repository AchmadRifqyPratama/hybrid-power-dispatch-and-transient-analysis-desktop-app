"""Halaman Data — import Load Profile, PV ENetAC, Grid Status dari Excel/CSV."""
from __future__ import annotations
import numpy as np

from ...config.i18n import tr
from ..plotutil import no_wheel_zoom
from PySide6.QtCore import Qt, QLocale, QTimer, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QFileDialog, QMessageBox,
                               QGroupBox, QFormLayout, QGridLayout,
                               QDoubleSpinBox, QButtonGroup, QScrollArea,
                               QSizePolicy, QRadioButton, QDialog,
                               QDialogButtonBox, QComboBox, QSpinBox,
                               QLineEdit)
import pyqtgraph as pg

from ...data.importer import (read_profile_file, ImportError_,
                              deg_status_to_label, DEG_STATUS_AUTO)
from ..theme import SERIES_COLORS


class DataPage(QWidget):
    # Hasil unduhan PVGIS / ERA5 dari thread jaringan (queued lintas-thread).
    _pvgis_ok = Signal(object)
    _pvgis_err = Signal(str)
    _era5_ok = Signal(object)
    _era5_err = Signal(str)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self._pvgis_progress = None
        self._pvgis_cancelled = False
        self._last_pvgis = None            # (res, datetimes) unduhan terakhir
        self._pvgis_ok.connect(self._on_pvgis_ok)
        self._pvgis_err.connect(self._on_pvgis_err)
        self._era5_progress = None
        self._era5_cancelled = False
        self._era5_ok.connect(self._on_era5_ok)
        self._era5_err.connect(self._on_era5_err)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget(); scroll.setWidget(page)
        outer.addWidget(scroll)
        lay = QVBoxLayout(page)
        t = QLabel(tr('Input Data')); t.setObjectName('PageTitle')
        s = QLabel(tr('Format: kolom "Datetime" + "Load (kW)" / "PV ENetAC (kW)" '
                   '/ "Grid Status" / "DEG Status" (0/1/A). Per jam (8760/8784 '
                   'baris) atau resolusi tinggi dgn timestamp konsisten hingga '
                   '1 tahun (mis. 525.600 baris = 1 menit setahun). Interval '
                   'terdeteksi dari timestamp.'))
        s.setObjectName('PageSub')
        s.setWordWrap(True)              # bungkus → tak memaksa lebar halaman
        lay.addWidget(t); lay.addWidget(s)

        self.manual_box = None          # dibuat di bawah
        btns = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        specs = [(tr('Import Excel/CSV…'), self._import_file),
                 (tr('Buat Template Excel…'), self._template),
                 (tr('Input Load Manual (24 jam)…'), self._show_manual)]
        self.mode_btns = []
        for i, (text, slot) in enumerate(specs):
            b = QPushButton(text)
            b.setProperty('mode', True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c, s=slot: s())
            self.mode_group.addButton(b, i)
            self.mode_btns.append(b)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.manual_box = self._build_manual()
        if self.manual_box is not None:
            self.manual_box.setVisible(False)
        lay.addWidget(self.manual_box)

        info = QGroupBox(tr('Status Data'))
        # v178: grid 2 kolom (bukan QFormLayout) — label & nilai rata atas pada
        # baris yang sama, jarak antar baris tetap; sisa tinggi kartu (yang
        # mengikuti tinggi kolom kanan) ditaruh di bawah, tidak dibagi ke baris.
        f = QGridLayout(info)
        f.setContentsMargins(8, 8, 8, 6)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(8)
        f.setColumnStretch(1, 1)
        self.lbl_load = QLabel(tr('belum diimpor'))
        self.lbl_pv = QLabel(tr('belum diimpor'))
        self.lbl_grid = QLabel(tr('default: selalu tersedia'))
        self.lbl_deg = QLabel(tr('default: Auto (mengikuti dispatch normal)'))
        self.lbl_wind = QLabel(tr('belum diimpor'))
        self.lbl_stg = QLabel(tr('default: selalu tersedia'))
        self.lbl_gtg = QLabel(tr('default: selalu tersedia'))
        for _lb in (self.lbl_load, self.lbl_pv, self.lbl_grid, self.lbl_deg,
                    self.lbl_wind, self.lbl_stg, self.lbl_gtg):
            _lb.setWordWrap(True)            # bungkus baris → tak ada h-scroll
            _lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        _rows = [(tr('Load Profile'), self.lbl_load),
                 (tr('PV ENetAC'), self.lbl_pv),
                 (tr('Grid Status'), self.lbl_grid),
                 (tr('DEG Status'), self.lbl_deg),
                 (tr('Wind (WTG)'), self.lbl_wind),
                 (tr('STG Status'), self.lbl_stg),
                 (tr('GTG Status'), self.lbl_gtg)]
        _top = Qt.AlignLeft | Qt.AlignTop
        for _r, (_name, _val) in enumerate(_rows):
            _k = QLabel(_name)
            _k.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            _val.setAlignment(_top)
            _val.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            f.addWidget(_k, _r, 0, _top)
            f.addWidget(_val, _r, 1)
            f.setRowMinimumHeight(_r, 24)    # jarak baris seragam (~kartu kanan)
        f.setRowStretch(len(_rows), 1)       # sisa ruang di bawah baris terakhir

        # --- Sumber PV ENetAC: Input Excel vs PVGIS ---
        self._syncing_pvsrc = False
        pvsrc = QGroupBox(tr('PV ENetAC Source'))
        pv_f = QFormLayout(pvsrc)
        self._style_form(pv_f)
        # Baris 1 — sumber aktif (dua radio)
        self.pvsrc_group = QButtonGroup(self)
        self.rb_excel = QRadioButton(tr('From Excel input'))
        self.rb_pvgis = QRadioButton(tr('From PVGIS'))
        self.pvsrc_group.addButton(self.rb_excel, 0)
        self.pvsrc_group.addButton(self.rb_pvgis, 1)
        self.rb_excel.toggled.connect(self._on_pv_source_changed)
        self.rb_pvgis.toggled.connect(self._on_pv_source_changed)
        rb_row = QWidget()
        rbl = QHBoxLayout(rb_row)
        rbl.setContentsMargins(0, 0, 0, 0); rbl.setSpacing(18)
        rbl.addWidget(self.rb_excel)
        rbl.addWidget(self.rb_pvgis)
        rbl.addStretch(1)
        # Tombol unduh di sisi KANAN kartu (sebaris dengan pilihan sumber)
        self.btn_dl_input = QPushButton(tr('Download modified input Excel…'))
        self.btn_dl_input.setProperty('flat', True)
        self.btn_dl_input.setCursor(Qt.PointingHandCursor)
        self.btn_dl_input.setToolTip(tr(
            'Save an input Excel (Datetime, Load, active PV ENetAC, Grid '
            'Status) — e.g. with the PV column replaced by PVGIS data.'))
        self.btn_dl_input.clicked.connect(self._download_input_excel)
        rbl.addWidget(self.btn_dl_input, 0, Qt.AlignRight)
        pv_f.addRow(tr('Active source'), rb_row)
        # Baris 2 — ketersediaan tiap sumber (titik status berwarna)
        self.lbl_pvsrc = QLabel('')
        self.lbl_pvsrc.setTextFormat(Qt.RichText)
        self.lbl_pvsrc.setWordWrap(True)
        pv_f.addRow(tr('Availability'), self.lbl_pvsrc)
        # Baris 3 (v164) — unduh PVGIS dari halaman Data (lokasi dari Home)
        self.btn_pvgis = QPushButton(tr('Download from PVGIS…'))
        self.btn_pvgis.setProperty('flat', True)
        self.btn_pvgis.setCursor(Qt.PointingHandCursor)
        self.btn_pvgis.setToolTip(tr(
            'Download an hourly PV profile from PVGIS for the project '
            'location (set on the Home page).'))
        self.btn_pvgis.clicked.connect(self._open_pvgis_dialog)
        self.lbl_loc_pv = QLabel('')
        self.lbl_loc_pv.setObjectName('PageSub')
        _r = QWidget(); _rl = QHBoxLayout(_r)
        _rl.setContentsMargins(0, 0, 0, 0); _rl.setSpacing(12)
        _rl.addWidget(self.btn_pvgis); _rl.addWidget(self.lbl_loc_pv, 1)
        pv_f.addRow('PVGIS', _r)

        # --- Sumber data angin (v164): ERA5 vs Input Excel ---
        self._syncing_wsrc = False
        wsrc = QGroupBox(tr('Wind Data Source'))
        w_f = QFormLayout(wsrc)
        self._style_form(w_f)
        self.wsrc_group = QButtonGroup(self)
        self.rb_w_excel = QRadioButton(tr('From Excel input'))
        self.rb_w_era5 = QRadioButton(tr('From ERA5'))
        self.wsrc_group.addButton(self.rb_w_excel, 0)
        self.wsrc_group.addButton(self.rb_w_era5, 1)
        self.rb_w_excel.toggled.connect(self._on_wind_source_changed)
        self.rb_w_era5.toggled.connect(self._on_wind_source_changed)
        _r = QWidget(); _rl = QHBoxLayout(_r)
        _rl.setContentsMargins(0, 0, 0, 0); _rl.setSpacing(18)
        _rl.addWidget(self.rb_w_excel); _rl.addWidget(self.rb_w_era5)
        _rl.addStretch(1)
        w_f.addRow(tr('Active source'), _r)
        self.lbl_wsrc = QLabel('')
        self.lbl_wsrc.setTextFormat(Qt.RichText)
        self.lbl_wsrc.setWordWrap(True)
        w_f.addRow(tr('Availability'), self.lbl_wsrc)
        self.btn_era5 = QPushButton(tr('Download from ERA5…'))
        self.btn_era5.setProperty('flat', True)
        self.btn_era5.setCursor(Qt.PointingHandCursor)
        self.btn_era5.setToolTip(tr(
            'Download hourly 100 m wind speed (ERA5 reanalysis) for the '
            'project location (set on the Home page).'))
        self.btn_era5.clicked.connect(self._open_era5_dialog)
        self.lbl_era5 = QLabel('')
        self.lbl_era5.setObjectName('PageSub')
        self.lbl_era5.setWordWrap(True)
        _r = QWidget(); _rl = QHBoxLayout(_r)
        _rl.setContentsMargins(0, 0, 0, 0); _rl.setSpacing(12)
        _rl.addWidget(self.btn_era5); _rl.addWidget(self.lbl_era5, 1)
        w_f.addRow('ERA5', _r)
        # Deskripsi data angin Excel (dulu di Parameters > WTG): jenis data,
        # ketinggian ukur, kapasitas acuan — hanya untuk sumber Excel.
        from ...config.parameters import SCHEMA as _SC
        from ..widgets import ParamField, param_tooltip
        self._wind_fields = {}
        self._wind_rows = {}
        for _p in _SC.get('Data — Wind', []):
            _fld = ParamField(_p)
            _fld.set_value(state.cfg.get(_p.key, _p.default))
            _fld.changed.connect(self._on_wind_field)
            _lb = QLabel(tr(_p.label) + (f' ({_p.unit})' if _p.unit else ''))
            try:
                _tt = param_tooltip(_p)
                _lb.setToolTip(_tt); _fld.setToolTip(_tt)
            except Exception:
                pass
            w_f.addRow(_lb, _fld)
            self._wind_fields[_p.key] = _fld
            self._wind_rows[_p.key] = (_lb, _fld)

        # Dua kartu sebaris dengan LEBAR SAMA & TINGGI SAMA; isi rata atas,
        # pola label–nilai seragam di kedua kartu.
        cards = QHBoxLayout()
        cards.setSpacing(8)
        cards.addWidget(info, 1)
        _col = QVBoxLayout(); _col.setSpacing(8)
        _col.addWidget(pvsrc); _col.addWidget(wsrc); _col.addStretch(1)
        cards.addLayout(_col, 1)
        lay.addLayout(cards)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget(
            title=tr('Pratinjau Profil (7 hari pertama · rata-rata per jam)'))
        no_wheel_zoom(self.plot)
        self.plot.setBackground(None)
        self.plot.addLegend(offset=(10, 10))
        self.plot.setLabel('left', 'kW')
        lay.addWidget(self.plot, 1)
        state.profiles_changed.connect(self.refresh)
        state.config_changed.connect(self._sync_wind_source)
        self.refresh()

    @staticmethod
    def _style_form(f):
        """Pola form seragam utk kartu Status Data & PV ENetAC Source."""
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        f.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(7)
        f.setContentsMargins(8, 8, 8, 6)

    # ------------------------------------------------------------------
    def _import_file(self):
        if self.manual_box is not None:
            self.manual_box.setVisible(False)
        path, _ = QFileDialog.getOpenFileName(
            self, tr('Pilih file profil'), '',
            'Data (*.xlsx *.xlsm *.xls *.csv)')
        if not path:
            return
        # Indikator progres (file besar mis. 525.600 baris butuh beberapa detik).
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QCoreApplication
        dlg = QProgressDialog(tr('Membaca file…'), tr('Batal'), 0, 100, self)
        dlg.setWindowTitle(tr('Impor Data'))
        dlg.setMinimumDuration(0); dlg.setAutoClose(False); dlg.setAutoReset(False)

        def _step(pct, msg):
            dlg.setValue(int(pct)); dlg.setLabelText(tr(msg))
            QCoreApplication.processEvents()

        _step(5, 'Membaca file…')
        try:
            d = read_profile_file(path)
        except ImportError_ as e:
            dlg.close()
            QMessageBox.warning(self, tr('Import gagal'), str(e))
            return
        if dlg.wasCanceled():
            dlg.close(); return
        _step(70, 'Memuat & memvalidasi profil…')
        if any(k in d for k in ('load', 'pv', 'grid', 'deg')):
            self.state.set_profiles(d.get('datetimes'), d.get('load'),
                                    d.get('pv'), d.get('grid'), d.get('deg'))
        # v162 — profil Wind & STG Status (panjang harus sama dgn Load)
        if 'wind' in d or 'stg' in d or 'gtg' in d:
            _n = len(self.state.load) if self.state.load is not None else -1
            _bad = [k for k in ('wind', 'stg', 'gtg')
                    if k in d and len(d[k]) != _n]
            if _bad:
                dlg.close()
                QMessageBox.warning(
                    self, tr('Import gagal'),
                    tr('Kolom Wind / STG Status harus sepanjang profil Load '
                       '(impor Load lebih dulu atau dalam berkas yang sama).'))
                return
            self.state.set_aux_profiles(stg=d.get('stg', 'keep'),
                                        gtg=d.get('gtg', 'keep'))
            if 'wind' in d:
                # v164 — kolom Wind = sumber "Excel"; langsung diaktifkan
                self.state.set_wind_data('excel', d['wind'])
                self.state.use_wind_source('excel')
        _step(90, 'Menyiapkan tampilan…')
        # Tahun acuan Load/Grid = tahun kolom Datetime pada Excel.
        try:
            self.state.cfg['excel_year'] = int(d['datetimes'][0].year)
        except Exception:
            pass
        if d.get('pv') is not None:
            # Simpan sebagai sumber "Excel" dan jadikan aktif.
            self.state.set_pv_excel(d['pv'])
            self.state.use_pv_source('excel')
        else:
            self.state.remember_pv_source('excel')
        _step(100, 'Selesai')
        dlg.close()
        got = [k for k in ('load', 'pv', 'grid', 'deg', 'wind', 'stg', 'gtg')
               if k in d]
        QMessageBox.information(
            self, tr('Import berhasil'),
            tr('Kolom terbaca: {cols}').format(cols=", ".join(got)))

    def _template(self):
        if self.manual_box is not None:
            self.manual_box.setVisible(False)
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Simpan template'), 'input_template.xlsx', 'Excel (*.xlsx)')
        if not path:
            return
        import pandas as pd
        dts = pd.date_range('2025-01-01', periods=8760, freq='h')
        pd.DataFrame({'Datetime': dts, 'Load (kW)': 0.0,
                      'PV ENetAC (kW)': 0.0, tr('Grid Status'): 1,
                      tr('DEG Status'): 'A',
                      'Wind Speed (m/s)': 0.0, 'STG Status': 1,
                      'GTG Status': 1}) \
            .to_excel(path, index=False)
        QMessageBox.information(
            self, tr('Template'),
            tr('Template tersimpan di\n{path}').format(path=path))

    # ------------------------------------------------------------------
    def _build_manual(self):
        box = QGroupBox(tr('Input Load Manual — pola 24 jam (diulang tiap hari)'))
        v = QVBoxLayout(box)
        head = QHBoxLayout()
        head.addStretch(1)
        b_close = QPushButton(tr('✕  Tutup'))
        b_close.setProperty('flat', True)
        b_close.setCursor(Qt.PointingHandCursor)
        b_close.setToolTip(tr('Tutup panel input manual'))
        b_close.clicked.connect(self._close_manual)
        head.addWidget(b_close)
        v.addLayout(head)
        desc = QLabel(
            tr('Isi beban tiap jam (kW). Pola ini disalin ke seluruh hari dalam '
            'setahun. PV ENetAC memakai profil default bawaan; Grid Status '
            'mengikuti parameter Grid (1 penuh bila ada grid, 0 penuh bila '
            'off-grid).'))
        desc.setWordWrap(True)
        v.addWidget(desc)
        grid = QGridLayout()
        self.hour_spins = []
        for h in range(24):
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 1e6); sp.setDecimals(3)
            sp.setSingleStep(0.1); sp.setValue(0.0)
            sp.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
            sp.setKeyboardTracking(False)
            sp.setMinimumWidth(64)
            sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            lb = QLabel(f'{h:02d}:00')
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lb.setMinimumWidth(46)
            r, c = h % 6, h // 6
            grid.addWidget(lb, r, c * 2)
            grid.addWidget(sp, r, c * 2 + 1)
            self.hour_spins.append(sp)
        grid.setHorizontalSpacing(8)
        for c in range(4):                 # kolom spin melar seimbang
            grid.setColumnStretch(c * 2, 0)
            grid.setColumnStretch(c * 2 + 1, 1)
        v.addLayout(grid)
        row = QHBoxLayout()
        b_fill = QPushButton(tr('Isi dari Profil Saat Ini'))
        b_fill.setProperty('flat', True)
        b_fill.setCursor(Qt.PointingHandCursor)
        b_fill.clicked.connect(self._fill_from_current)
        b_flat = QPushButton(tr('Isi Rata…'))
        b_flat.setProperty('flat', True)
        b_flat.setCursor(Qt.PointingHandCursor)
        b_flat.clicked.connect(self._fill_flat)
        b_apply = QPushButton(tr('▶  Terapkan ke Setahun'))
        b_apply.setProperty('flat', True)
        b_apply.setCursor(Qt.PointingHandCursor)
        b_apply.clicked.connect(self._apply_manual)
        row.addWidget(b_fill); row.addWidget(b_flat)
        row.addStretch(1)
        row.addWidget(b_apply)
        row.addStretch(1)
        v.addLayout(row)
        self.lbl_manual = QLabel('')
        self.lbl_manual.setObjectName('PageSub')
        self.lbl_manual.setWordWrap(True)
        v.addWidget(self.lbl_manual)
        return box

    def _close_manual(self):
        if self.manual_box is not None:
            self.manual_box.setVisible(False)
        self.mode_group.setExclusive(False)
        for b in self.mode_btns:
            b.setChecked(False)
        self.mode_group.setExclusive(True)

    def _show_manual(self):
        if self.manual_box is None:
            return
        # klik ulang pada tombol mode = tutup panel
        if self.manual_box.isVisible():
            self._close_manual()
        else:
            self.manual_box.setVisible(True)

    def _fill_from_current(self):
        st = self.state
        if st.load is None:
            QMessageBox.information(self, tr('Belum ada data'),
                                    tr('Impor profil dahulu, atau isi manual.'))
            return
        n = len(st.load)
        prof = np.asarray(st.load, float)[:n // 24 * 24].reshape(-1, 24)
        avg = prof.mean(axis=0)
        for h, sp in enumerate(self.hour_spins):
            sp.setValue(float(avg[h]))
        self.lbl_manual.setText(tr('Terisi rata-rata profil saat ini.'))

    def _fill_flat(self):
        vals = [sp.value() for sp in self.hour_spins]
        base = max(vals) if max(vals) > 0 else 0.0
        for sp in self.hour_spins:
            sp.setValue(base)
        self.lbl_manual.setText(tr('Terisi rata sebesar nilai tertinggi.'))

    def _default_pv(self, n: int):
        """Profil PV ENetAC default dari assets/sample_input.xlsx."""
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.abspath(os.path.join(here, '..', '..', '..'))
        path = os.path.join(root, 'assets', 'sample_input.xlsx')
        if not os.path.exists(path):
            return None
        try:
            d = read_profile_file(path)
        except ImportError_:
            return None
        pv = d.get('pv')
        if pv is None:
            return None
        pv = np.asarray(pv, float)
        if len(pv) >= n:
            return pv[:n]
        return np.resize(pv, n)

    def _apply_manual(self):
        vals = np.array([sp.value() for sp in self.hour_spins], float)
        if vals.sum() <= 0:
            QMessageBox.warning(self, tr('Data kosong'),
                                tr('Isi setidaknya satu jam dengan nilai > 0.'))
            return
        year = int(self.state.cfg.get('simulation_year', 2025) or 2025)
        leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
        days = 366 if leap else 365
        load = np.tile(vals, days)
        n = len(load)
        pv = self.state.pv_norm
        src = tr('profil PV yang sudah dimuat')
        if pv is None or len(pv) != n:
            pv = self._default_pv(n)
            src = tr('profil PV default bawaan')
        if pv is None:
            QMessageBox.warning(
                self, tr('PV tidak tersedia'),
                tr('Profil PV default tidak ditemukan '
                   '(assets/sample_input.xlsx). Impor profil PV '
                   'terlebih dahulu.'))
            return
        on = bool(self.state.cfg.get('grid_enabled', True))
        grid = np.ones(n) if on else np.zeros(n)
        try:
            import pandas as pd
            dts = pd.date_range(f'{year}-01-01', periods=n, freq='h')
        except Exception:
            dts = None
        self.state.set_profiles(dts, load, pv, grid)
        gs = tr('1 (tersedia)') if on else tr('0 (off-grid)')
        self.lbl_manual.setText(
            tr('{n} jam dibuat dari pola 24 jam · {src} · Grid Status {g} '
               'penuh.').format(n=f'{n:,}', src=src, g=gs))
        QMessageBox.information(
            self, tr('Data dibuat'),
            tr('Load {e} kWh/tahun dari pola 24 jam (diulang {d} hari).')
            .format(e=f'{load.sum():,.0f}', d=days)
            + f'\nPV ENetAC: {src}.\n' + tr('Grid Status:') + ' '
            + (tr('selalu tersedia') if on else tr('off-grid penuh')) + '.')

    # ------------------------------------------------------------------
    # ---------------------- lokasi proyek (dari Home) ----------------------
    def _latlon(self):
        c = self.state.cfg
        try:
            return (float(c.get('latitude', 0.0) or 0.0),
                    float(c.get('longitude', 0.0) or 0.0))
        except (TypeError, ValueError):
            return 0.0, 0.0

    def _loc_text(self):
        lat, lon = self._latlon()
        if abs(lat) < 1e-9 and abs(lon) < 1e-9:
            return tr('Location not set — pick it on the Home page.')
        return tr('Location: {lat:.5f}, {lon:.5f}').format(lat=lat, lon=lon)

    def _need_location(self, title):
        lat, lon = self._latlon()
        if abs(lat) < 1e-9 and abs(lon) < 1e-9:
            QMessageBox.information(
                self, title,
                tr('Project location is not set. Open the Home page and use '
                   '"Select on map" (or type latitude/longitude) first.'))
            return None
        return lat, lon

    def _theme_dialog(self, dlg):
        try:
            from ..theme import apply_titlebar_theme, CURRENT_DARK
            QTimer.singleShot(0, lambda: apply_titlebar_theme(
                dlg, dark=CURRENT_DARK))
        except Exception:
            pass

    # ---------------------------- unduh PVGIS ------------------------------
    def _open_pvgis_dialog(self):
        """Opsi PVGIS (dulu di dialog peta Home) lalu unduh profil PV."""
        loc = self._need_location('PVGIS')
        if loc is None:
            return
        lat, lon = loc
        from ..map_picker import PvgisOptionsPanel
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('Download PV data from PVGIS'))
        v = QVBoxLayout(dlg)
        head = QLabel(self._loc_text())
        head.setObjectName('PageSub')
        v.addWidget(head)
        panel = PvgisOptionsPanel(
            options=dict(self.state.cfg.get('pvgis_opts') or {}), lat=lat,
            parent=dlg)
        v.addWidget(panel)
        bb = QDialogButtonBox()
        b_ok = bb.addButton(tr('Download'), QDialogButtonBox.AcceptRole)
        bb.addButton(tr('Cancel'), QDialogButtonBox.RejectRole)
        b_ok.setDefault(True)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        self._theme_dialog(dlg)
        if dlg.exec() != QDialog.Accepted:
            return
        opts = panel.pvgis_options()
        self.state.update_cfg({'pvgis_opts': opts})      # simpan setelan
        self._download_pvgis(lat, lon, opts)

    def _download_pvgis(self, lat, lon, opts=None):
        """Unduh profil PV per-jam dari PVGIS untuk (lat, lon) di thread
        terpisah, dengan dialog progres; hasilnya jadi profil PV ENetAC.
        `opts`: {optimal, tilt, azimuth, loss, year} dari dialog PVGIS."""
        import threading
        from ...data.pvgis import (fetch_pv_profile, year_for_length,
                                   combine_losses, PVGISError)
        from PySide6.QtWidgets import QProgressDialog
        opts = opts or {}
        optimal = bool(opts.get('optimal', True))
        tilt = float(opts.get('tilt', 0.0) or 0.0)
        azimuth = float(opts.get('azimuth', 0.0) or 0.0)
        loss = float(opts.get('loss', 14.0) if opts.get('loss') is not None
                     else 14.0)
        mounting = opts.get('mounting', 'free') or 'free'
        # Koreksi tipe-PVSyst (opsional): keluarkan inverter & kabel DC dari
        # loss datar PVGIS (agar tak dobel), lalu modelkan eksplisit.
        pvsyst = None
        if opts.get('pvsyst_match'):
            comps = opts.get('loss_components') or {}
            if comps:
                loss = combine_losses(comps, exclude=('inverter', 'cabling_dc'))
            pvsyst = {
                'dcac': float(opts.get('dcac', 1.2) or 1.2),
                'inv_eff': float(opts.get('inv_eff', 98.0) or 98.0),
                'dc_stc': float((comps.get('cabling_dc', 1.0) if comps else 1.0)
                                or 0.0),
            }
        # Modul bifacial (opsional): gain sisi belakang dari pantulan tanah.
        bifacial = None
        if opts.get('bifacial'):
            bifacial = {
                'albedo': float(opts.get('albedo', 0.20) or 0.0),
                'bifaciality': float(opts.get('bifaciality', 70.0) or 0.0),
                'rear_factor': float(opts.get('rear_factor', 65.0) or 0.0),
            }
        peak = float(self.state.cfg.get('pv_base_annual', 1103.76) or 0.0)
        if peak <= 0:
            peak = 1103.76
        n_exist = len(self.state.load) if self.state.load is not None else None
        yr = opts.get('year') or year_for_length(n_exist)

        prog = QProgressDialog(
            tr('Downloading PV data from PVGIS…'), tr('Cancel'), 0, 0, self)
        prog.setWindowTitle('PVGIS')
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        self._pvgis_progress = prog
        self._pvgis_cancelled = False
        prog.canceled.connect(
            lambda: setattr(self, '_pvgis_cancelled', True))
        try:
            from ..theme import apply_titlebar_theme
            from ..theme import CURRENT_DARK
            QTimer.singleShot(0, lambda: apply_titlebar_theme(
                prog, dark=CURRENT_DARK))
        except Exception:
            pass
        prog.show()

        def work():
            try:
                res = fetch_pv_profile(lat, lon, peak, loss=loss,
                                       optimal=optimal, tilt=tilt,
                                       azimuth=azimuth, mounting=mounting,
                                       year=yr, with_ghi=True, pvsyst=pvsyst,
                                       bifacial=bifacial)
                self._pvgis_ok.emit(res)
            except PVGISError as e:
                self._pvgis_err.emit(str(e))
            except Exception as e:                      # pengaman terakhir
                self._pvgis_err.emit(str(e))

        threading.Thread(target=work, daemon=True).start()

    def _close_pvgis_progress(self):
        """Tutup dialog progres tanpa memicu sinyal 'canceled'.

        closeEvent QProgressDialog memancarkan canceled() saat ditutup secara
        program — bila tidak diputus, itu disalah-artikan sebagai pembatalan
        oleh pengguna sehingga kotak konfirmasi tidak muncul."""
        prog = self._pvgis_progress
        self._pvgis_progress = None
        if prog is not None:
            try:
                prog.canceled.disconnect()
            except Exception:
                pass
            prog.close()

    def _on_pvgis_ok(self, res):
        import numpy as np
        import pandas as pd
        cancelled = self._pvgis_cancelled       # tangkap SEBELUM menutup
        self._close_pvgis_progress()
        if cancelled:
            return
        pv = np.asarray(res['pv'], float)
        # Selaraskan panjang dengan data lain bila sudah ada.
        if self.state.load is not None and len(self.state.load) != len(pv):
            n = len(self.state.load)
            pv = pv[:n] if len(pv) > n else np.resize(pv, n)
        # Simpan sebagai sumber "PVGIS", catat tahun datanya, lalu aktifkan.
        # use_pv_source() akan: mengeser Load & Grid (selaras hari-dalam-minggu)
        # ke tahun PVGIS, menata datetimes, dan menyetel tahun simulasi.
        self.state.set_pv_pvgis(pv)
        self.state.cfg['pvgis_year'] = int(res.get('year') or 2019)
        self.state.use_pv_source('pvgis')
        self._last_pvgis = (res, self.state.datetimes)   # untuk ekspor Excel
        self.refresh()
        if res.get('optimal'):
            orient = tr('orientation: optimal tilt/azimuth')
        else:
            orient = tr('orientation: tilt {t:.0f}° / azimuth {a:.0f}°').format(
                t=res.get('tilt', 0.0), a=res.get('azimuth', 0.0))
        note = ''
        bf = res.get('bifacial')
        if bf:
            gp = bf.get('gain_pct')
            if gp is not None:
                note += '\n' + tr(
                    'Bifacial gain +{g:.2f}% (albedo {a:.2f}, bifaciality '
                    '{b:.2f}%, rear factor {r:.2f}%).').format(
                        g=gp, a=bf.get('albedo', 0.0),
                        b=bf.get('bifaciality', 0.0), r=bf.get('rear_factor', 0.0))
            else:
                note += '\n' + tr('Bifacial requested but GHI unavailable — '
                                  'gain not applied.')
        ps = res.get('pvsyst')
        if ps:
            note += '\n' + tr(
                'PVSyst-like correction applied: clipping @ Pnom AC '
                '{pn:,.1f} kW (DC/AC {r:.2f}), inverter {e:.2f}%, '
                'DC cabling @STC {d:.2f}%.').format(
                    pn=ps.get('pnom_ac', 0.0), r=ps.get('dcac', 0.0),
                    e=ps.get('inv_eff', 0.0), d=ps.get('dc_stc', 0.0))
        if self.state.load is None:
            note += '\n\n' + tr('Note: load profile is still empty — import or '
                                'enter load data on the Data page.')
        msg = (tr('PV profile downloaded from PVGIS for {lat:.5f}, {lon:.5f}.')
               .format(lat=res['lat'], lon=res['lon']) + '\n'
               + tr('Reference size {p:,.1f} kWp · data year {y}.')
               .format(p=res['peakpower_kwp'], y=res['year']) + '\n'
               + orient + tr(' · loss {l:.1f}%.').format(l=res.get('loss', 14.0))
               + '\n'
               + tr('Annual PV energy {e:,.0f} kWh · specific yield '
                    '{sy:,.0f} kWh/kWp/yr.')
               .format(e=res['annual_kwh'], sy=res['specific_yield']) + note)
        box = QMessageBox(self)
        box.setWindowTitle('PVGIS')
        box.setIcon(QMessageBox.Information)
        box.setText(msg)
        save_btn = box.addButton(tr('Save to Excel…'), QMessageBox.AcceptRole)
        box.addButton(tr('Close'), QMessageBox.RejectRole)
        try:
            from ..theme import apply_titlebar_theme, CURRENT_DARK
            QTimer.singleShot(0, lambda: apply_titlebar_theme(
                box, dark=CURRENT_DARK))
        except Exception:
            pass
        box.exec()
        if box.clickedButton() is save_btn:
            self._export_pvgis(res, self.state.datetimes)

    def _export_pvgis(self, res, dts):
        """Simpan data PVGIS per-jam ke berkas Excel pilihan pengguna."""
        from PySide6.QtWidgets import QFileDialog
        from ...data.pvgis import export_pvgis_xlsx
        default = (f"PVGIS_{res.get('lat', 0):.4f}_{res.get('lon', 0):.4f}"
                   f"_{res.get('year', '')}.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Save PVGIS data to Excel'), default, 'Excel (*.xlsx)')
        if not path:
            return
        try:
            export_pvgis_xlsx(path, res, dts)
        except Exception as e:
            QMessageBox.critical(self, 'PVGIS',
                                 tr('Failed to save Excel:') + '\n' + str(e))
            return
        import os
        QMessageBox.information(
            self, 'PVGIS',
            tr('PVGIS data saved to Excel:') + f'\n{os.path.basename(path)}')

    def _on_pvgis_err(self, msg):
        cancelled = self._pvgis_cancelled       # tangkap SEBELUM menutup
        self._close_pvgis_progress()
        if cancelled:
            return
        QMessageBox.warning(
            self, 'PVGIS',
            tr('Could not download PV data from PVGIS:') + '\n' + msg)

    # ------------------------- sumber data angin --------------------------
    def _on_wind_source_changed(self, checked):
        if not checked or self._syncing_wsrc:
            return
        src = 'era5' if self.rb_w_era5.isChecked() else 'excel'
        if self.state.wind_source() == src and self.state.wind is not None:
            return
        if not self.state.use_wind_source(src):
            self._sync_wind_source()        # sumber belum ada → kembalikan

    def _on_wind_field(self):
        if self._syncing_wsrc:
            return
        vals = {k: f.value() for k, f in self._wind_fields.items()}
        self.state.update_cfg(vals)         # config_changed → _sync_wind_source
        self.refresh()

    def _sync_wind_source(self):
        st = self.state
        has_x = st.wind_excel is not None
        has_e = st.wind_era5 is not None
        src = st.wind_source()
        if src == 'era5' and not has_e and has_x:
            src = 'excel'
        elif src == 'excel' and not has_x and has_e:
            src = 'era5'
        self._syncing_wsrc = True
        self.rb_w_excel.setEnabled(has_x)
        self.rb_w_era5.setEnabled(has_e)
        self.rb_w_excel.setChecked(src == 'excel' and has_x)
        self.rb_w_era5.setChecked(src == 'era5' and has_e)
        from ...config.parameters import VISIBILITY
        for k, (lb, fld) in self._wind_rows.items():
            fld.set_value(st.cfg.get(k, fld.p.default))
            rule = VISIBILITY.get(k)
            vis = (src == 'excel') and (rule(st.cfg) if rule else True)
            lb.setVisible(vis); fld.setVisible(vis)
        self._syncing_wsrc = False
        from .. import theme as _thm

        def _item(name, ok):
            col = _thm.tok('ok') if ok else _thm.tok('faint')
            txt = tr('available') if ok else tr('not loaded')
            return (f'<span style="color:{col}">&#9679;</span>&nbsp;{name}: '
                    f'<span style="color:{_thm.tok("muted")}">{txt}</span>')
        self.lbl_wsrc.setText(_item('Excel', has_x) + '&nbsp;&nbsp;&nbsp;&nbsp;'
                              + _item('ERA5', has_e))
        self.lbl_loc_pv.setText(self._loc_text())
        if has_e and st.cfg.get('wind_era5_year'):
            self.lbl_era5.setText(tr(
                '{prov} · year {y} · wind speed at {h:.0f} m (fixed)').format(
                    prov=st.cfg.get('wind_era5_provider', 'ERA5'),
                    y=st.cfg.get('wind_era5_year'),
                    h=float(st.cfg.get('wind_era5_height', 100.0) or 100.0)))
        else:
            self.lbl_era5.setText(self._loc_text())

    # ----------------------------- unduh ERA5 ------------------------------
    def _open_era5_dialog(self):
        loc = self._need_location('ERA5')
        if loc is None:
            return
        st = self.state
        if st.load is None:
            QMessageBox.information(
                self, 'ERA5',
                tr('Import or enter the load profile first — the wind series '
                   'is aligned to the load time axis.'))
            return
        lat, lon = loc
        from datetime import datetime as _dt
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('Download wind data from ERA5'))
        v = QVBoxLayout(dlg)
        head = QLabel(self._loc_text()); head.setObjectName('PageSub')
        v.addWidget(head)
        f = QFormLayout()
        cb = QComboBox()
        cb.addItem('Open-Meteo (ERA5)', 'open-meteo')
        cb.addItem('Copernicus CDS (ERA5)', 'cds')
        if str(st.cfg.get('wind_era5_api', 'open-meteo')) == 'cds':
            cb.setCurrentIndex(1)
        f.addRow(tr('Data provider'), cb)
        yr = QSpinBox(); yr.setRange(1940, _dt.now().year - 1)
        try:
            y0 = int(st.cfg.get('wind_era5_year') or st.datetimes[0].year)
        except Exception:
            y0 = _dt.now().year - 1
        yr.setValue(min(max(y0, 1940), _dt.now().year - 1))
        yr.setToolTip(tr('ERA5 data year. Default: the year of the current '
                         'load data.'))
        f.addRow(tr('Data year'), yr)
        key = QLineEdit(); key.setEchoMode(QLineEdit.Password)
        lb_key = QLabel('')
        f.addRow(lb_key, key)
        v.addLayout(f)
        note = QLabel(''); note.setWordWrap(True); note.setObjectName('PageSub')
        note.setMinimumWidth(460)
        v.addWidget(note)

        def _sync():
            if cb.currentData() == 'cds':
                lb_key.setText(tr('CDS access token'))
                key.setPlaceholderText(tr('required'))
                note.setText(tr(
                    'Official Copernicus Climate Data Store. Requires a free '
                    'CDS account, its personal access token, accepted dataset '
                    'licence, and the Python package "cdsapi". Requests are '
                    'queued and can take several minutes.'))
            else:
                lb_key.setText(tr('API key'))
                key.setPlaceholderText(tr('optional — required for commercial use'))
                note.setText(tr(
                    'Open-Meteo Historical Weather API (ERA5 reanalysis). No '
                    'account needed for non-commercial use; commercial use '
                    'requires an Open-Meteo API key. Data licence CC BY 4.0.'))
        cb.currentIndexChanged.connect(lambda *_: _sync())
        _sync()
        v.addWidget(QLabel(tr('The key/token is used for this download only '
                              'and is not stored in the project.')))
        bb = QDialogButtonBox()
        b_ok = bb.addButton(tr('Download'), QDialogButtonBox.AcceptRole)
        bb.addButton(tr('Cancel'), QDialogButtonBox.RejectRole)
        b_ok.setDefault(True)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        self._theme_dialog(dlg)
        if dlg.exec() != QDialog.Accepted:
            return
        self._download_era5(lat, lon, int(yr.value()), cb.currentData(),
                            key.text().strip())

    def _download_era5(self, lat, lon, year, provider, api_key=''):
        import threading
        from ...data.era5 import fetch_wind
        from PySide6.QtWidgets import QProgressDialog
        prog = QProgressDialog(
            tr('Downloading wind data from ERA5…'), tr('Cancel'), 0, 0, self)
        prog.setWindowTitle('ERA5')
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        self._era5_progress = prog
        self._era5_cancelled = False
        self._era5_api = provider
        prog.canceled.connect(lambda: setattr(self, '_era5_cancelled', True))
        self._theme_dialog(prog)
        prog.show()

        def work():
            try:
                self._era5_ok.emit(fetch_wind(lat, lon, year, provider, api_key))
            except Exception as e:
                self._era5_err.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def _close_era5_progress(self):
        prog = self._era5_progress
        self._era5_progress = None
        if prog is not None:
            try:
                prog.canceled.disconnect()
            except Exception:
                pass
            prog.close()

    @staticmethod
    def fit_hourly(hourly, n, dt_h):
        """Sejajarkan deret per-jam 1 tahun ke sumbu waktu data (n langkah,
        dt_h jam/langkah): tahan nilai per-jam untuk resolusi lebih halus,
        rata-rata blok untuk resolusi lebih kasar, lalu potong / ulang."""
        a = np.asarray(hourly, float)
        if dt_h < 0.999:
            a = np.repeat(a, max(1, int(round(1.0 / dt_h))))
        elif dt_h > 1.001:
            k = max(1, int(round(dt_h)))
            m = (len(a) // k) * k
            a = a[:m].reshape(-1, k).mean(axis=1)
        if len(a) == n:
            return a
        return a[:n] if len(a) > n else np.resize(a, n)

    def _on_era5_ok(self, res):
        cancelled = self._era5_cancelled
        self._close_era5_progress()
        if cancelled:
            return
        st = self.state
        if st.load is None:
            return
        from ...config import intervals as ivals
        n = len(st.load)
        iv = ivals.detect_interval_label(n, st.datetimes) or '1 hour'
        ws = self.fit_hourly(res['ws100'], n, ivals.interval_dt_h(iv))
        st.set_wind_data('era5', ws)
        st.cfg.update({'wind_era5_year': int(res['year']),
                       'wind_era5_provider': res.get('provider', 'ERA5'),
                       'wind_era5_api': getattr(self, '_era5_api', 'open-meteo'),
                       'wind_era5_height': float(res.get('height_m', 100.0))})
        st.use_wind_source('era5')
        self.refresh()
        msg = (tr('Wind data downloaded from ERA5 for {lat:.5f}, {lon:.5f}.')
               .format(lat=res['lat'], lon=res['lon']) + '\n'
               + tr('Source {p} · data year {y} · local time.')
               .format(p=res.get('provider', 'ERA5'), y=res['year']) + '\n'
               + tr('Mean wind speed at 100 m: {a:.2f} m/s · max {m:.1f} m/s.')
               .format(a=res['mean_ws100'], m=res['max_ws100']))
        if res.get('shear_10_100') is not None:
            msg += '\n' + tr('Mean 10 m: {a:.2f} m/s · effective shear exponent '
                             '10→100 m: {s:.3f} (compare with Wind Shear '
                             'Exponent in Parameters).').format(
                                 a=res['mean_ws10'], s=res['shear_10_100'])
        try:
            data_y = int(st.datetimes[0].year)
            if data_y != int(res['year']):
                msg += '\n\n' + tr(
                    'Note: ERA5 year {y} differs from the load data year '
                    '{d}; the series is aligned by hour of year.').format(
                        y=res['year'], d=data_y)
        except Exception:
            pass
        msg += '\n\n' + res.get('attribution', '')
        box = QMessageBox(self)
        box.setWindowTitle('ERA5')
        box.setIcon(QMessageBox.Information)
        box.setText(msg)
        save_btn = box.addButton(tr('Save to Excel…'), QMessageBox.AcceptRole)
        box.addButton(tr('Close'), QMessageBox.RejectRole)
        self._theme_dialog(box)
        box.exec()
        if box.clickedButton() is save_btn:
            from ...data.era5 import export_era5_xlsx
            default = (f"ERA5_{res['lat']:.4f}_{res['lon']:.4f}"
                       f"_{res['year']}.xlsx")
            path, _ = QFileDialog.getSaveFileName(
                self, tr('Save ERA5 data to Excel'), default, 'Excel (*.xlsx)')
            if path:
                try:
                    export_era5_xlsx(path, res)
                except Exception as e:
                    QMessageBox.critical(
                        self, 'ERA5', tr('Failed to save Excel:') + '\n' + str(e))

    def _on_era5_err(self, msg):
        cancelled = self._era5_cancelled
        self._close_era5_progress()
        if cancelled:
            return
        QMessageBox.warning(
            self, 'ERA5',
            tr('Could not download wind data from ERA5:') + '\n' + msg)

    # -------------------------- sumber PV ENetAC --------------------------
    def _on_pv_source_changed(self, checked):
        if not checked or self._syncing_pvsrc:
            return
        src = 'pvgis' if self.rb_pvgis.isChecked() else 'excel'
        if self.state.pv_source() == src:
            return
        if not self.state.apply_pv_source(src):
            self._sync_pv_source()          # sumber belum ada → kembalikan
            return
        # profil aktif berubah → profiles_changed memicu refresh()

    def _sync_pv_source(self):
        st = self.state
        has_x = st.pv_excel is not None
        has_g = st.pv_pvgis is not None
        src = st.pv_source()
        if src == 'pvgis' and not has_g and has_x:
            src = 'excel'
        elif src == 'excel' and not has_x and has_g:
            src = 'pvgis'
        self._syncing_pvsrc = True
        self.rb_excel.setEnabled(has_x)
        self.rb_pvgis.setEnabled(has_g)
        self.rb_excel.setChecked(src == 'excel' and has_x)
        self.rb_pvgis.setChecked(src == 'pvgis' and has_g)
        self._syncing_pvsrc = False
        self.btn_dl_input.setEnabled(
            st.load is not None and st.pv_norm is not None)
        from .. import theme as _thm

        def _item(name, ok):
            col = _thm.tok('ok') if ok else _thm.tok('faint')
            txt = tr('available') if ok else tr('not loaded')
            return (f'<span style="color:{col}">&#9679;</span>&nbsp;{name}: '
                    f'<span style="color:{_thm.tok("muted")}">{txt}</span>')
        self.lbl_pvsrc.setText(_item('Excel', has_x) + '&nbsp;&nbsp;&nbsp;&nbsp;'
                               + _item('PVGIS', has_g))

    def _download_input_excel(self):
        st = self.state
        if st.load is None or st.pv_norm is None:
            QMessageBox.information(
                self, tr('Belum ada data'),
                tr('Load and PV ENetAC profiles are required first.'))
            return
        import os
        import pandas as pd
        base = (self.state.cfg.get('site_name')
                or self.state.cfg.get('project_name') or 'input')
        suffix = 'PVGIS' if st.pv_source() == 'pvgis' else 'Excel'
        default = f'input_{base}_{suffix}.xlsx'.replace(' ', '_')
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Download Input Excel'), default, 'Excel (*.xlsx)')
        if not path:
            return
        try:
            n = len(st.load)
            if st.datetimes is not None and len(st.datetimes) == n:
                dts = pd.DatetimeIndex(st.datetimes)
            else:
                dts = pd.date_range('2025-01-01', periods=n, freq='h')
            grid = (st.grid_status if st.grid_status is not None
                    and len(st.grid_status) == n else np.ones(n))
            deg = (st.deg_status if st.deg_status is not None
                   and len(st.deg_status) == n else np.full(n, DEG_STATUS_AUTO))
            df = pd.DataFrame({
                'Datetime': dts,
                'Load (kW)': np.asarray(st.load, float),
                'PV ENetAC (kW)': np.asarray(st.pv_norm, float),
                'Grid Status': np.asarray(grid, float).round().astype(int),
                'DEG Status': [deg_status_to_label(c) for c in np.asarray(deg, float)],
            })
            if getattr(st, 'wind', None) is not None and len(st.wind) == n:
                df['Wind Speed (m/s)'] = np.asarray(st.wind, float)
            if getattr(st, 'stg_status', None) is not None \
                    and len(st.stg_status) == n:
                df['STG Status'] = np.asarray(st.stg_status, float).round().astype(int)
            if getattr(st, 'gtg_status', None) is not None \
                    and len(st.gtg_status) == n:
                df['GTG Status'] = np.asarray(st.gtg_status, float).round().astype(int)
            df.to_excel(path, index=False)
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))
            return
        QMessageBox.information(
            self, tr('Sukses'),
            tr('Input Excel saved:') + f'\n{os.path.basename(path)}')

    def refresh(self):
        st = self.state
        self._sync_pv_source()
        self._sync_wind_source()
        # Interval NATIVE data (dari timestamp / jumlah baris). Energi = daya ×
        # dt; jumlah baris BUKAN jam. Data per-jam -> dt=1 (tampilan lama utuh).
        from ...config import intervals as ivals
        n = len(st.load) if st.load is not None else 0
        iv = ivals.detect_interval_label(n, st.datetimes) or '1 hour'
        dt = ivals.interval_dt_h(iv)
        if st.load is not None:
            self.lbl_load.setText(
                tr('{n} baris · total {e} kWh · puncak {p} kW').format(
                    n=f'{len(st.load):,}',
                    e=f'{st.load.sum() * dt:,.0f}', p=f'{st.load.max():,.1f}'))
        if st.pv_norm is not None:
            self.lbl_pv.setText(
                tr('{n} baris · profil basis {e} (skala kWp/basis)'
                   ).format(n=f'{len(st.pv_norm):,}',
                            e=f'{st.pv_norm.sum() * dt:,.0f}'))
        if st.grid_status is not None:
            off_h = float((st.grid_status == 0).sum()) * dt
            oh = f'{off_h:,.0f}' if abs(off_h - round(off_h)) < 0.05 \
                else f'{off_h:,.1f}'
            self.lbl_grid.setText(tr('{n} jam padam / tahun').format(n=oh))
        if st.deg_status is not None:
            off_h = float((st.deg_status == 0.0).sum()) * dt
            on_h = float((st.deg_status == 1.0).sum()) * dt
            auto_h = float((st.deg_status == DEG_STATUS_AUTO).sum()) * dt
            self.lbl_deg.setText(
                tr('{off} jam DEG dipaksa OFF · {on} jam dipaksa ON · '
                   '{auto} jam Auto').format(
                    off=f'{off_h:,.0f}', on=f'{on_h:,.0f}',
                    auto=f'{auto_h:,.0f}'))
        else:
            self.lbl_deg.setText(tr('default: Auto (mengikuti dispatch normal)'))
        # v162 — Wind & STG Status
        _w = getattr(st, 'wind', None)
        if _w is not None and len(_w):
            _txt = tr('{n} baris · rata-rata {a} · maks {m}').format(
                n=f'{len(_w):,}', a=f'{float(np.mean(_w)):,.2f}',
                m=f'{float(np.max(_w)):,.1f}')
            try:
                from ...config.parameters import ext_vals, wtg_active
                if wtg_active(st.cfg):
                    from ...engine.extsrc import wtg_series
                    _p = wtg_series(ext_vals(st.cfg), _w, len(_w))
                    _cap = float(st.cfg.get('wtg_count', 0)) * float(
                        st.cfg.get('wtg_unit_kw', 0))
                    _txt += ' · ' + tr('produksi {e} kWh · CF {c} %').format(
                        e=f'{float(_p.sum()) * dt:,.0f}',
                        c=f'{100.0 * float(_p.mean()) / max(_cap, 1e-9):,.1f}')
            except Exception:
                pass
            self.lbl_wind.setText(
                ('ERA5 100 m · ' if st.wind_source() == 'era5' else 'Excel · ')
                + _txt)
        else:
            self.lbl_wind.setText(tr('belum diimpor'))
        _s = getattr(st, 'stg_status', None)
        if _s is not None and len(_s):
            self.lbl_stg.setText(tr('{on} jam tersedia · {off} jam tak tersedia').format(
                on=f'{float((_s != 0).sum()) * dt:,.0f}',
                off=f'{float((_s == 0).sum()) * dt:,.0f}'))
        else:
            self.lbl_stg.setText(tr('default: selalu tersedia'))
        _g = getattr(st, 'gtg_status', None)
        if _g is not None and len(_g):
            self.lbl_gtg.setText(tr('{on} jam tersedia · {off} jam tak tersedia').format(
                on=f'{float((_g != 0).sum()) * dt:,.0f}',
                off=f'{float((_g == 0).sum()) * dt:,.0f}'))
        else:
            self.lbl_gtg.setText(tr('default: selalu tersedia'))
        self.plot.clear()
        # Pratinjau: ratakan ke basis PER JAM lalu tampilkan hingga 7 hari
        # pertama (pola harian jelas) — bukan 720 langkah mentah (utk data 1
        # menit hanya 12 menit & tak terbaca).
        if st.load is not None:
            lh = ivals.to_hourly(st.load, iv)
            m = int(min(len(lh), 168))
            xh = np.arange(m)
            self.plot.plot(xh, np.asarray(lh[:m], float),
                           pen=pg.mkPen(SERIES_COLORS['load'], width=1.4),
                           name=tr('Load'))
            if st.pv_norm is not None:
                ph = ivals.to_hourly(st.pv_norm, iv)
                scale = self.state.cfg.get('pv_kwp', 1) / \
                    max(self.state.cfg.get('pv_base_annual', 1), 1e-9)
                self.plot.plot(xh, np.asarray(ph[:m], float) * scale,
                               pen=pg.mkPen(SERIES_COLORS['pv'], width=1.2),
                               name=tr('PV ENetAC'))
        self.plot.setLabel('bottom', tr('Jam pertama (pratinjau · rata-rata per jam)'))
