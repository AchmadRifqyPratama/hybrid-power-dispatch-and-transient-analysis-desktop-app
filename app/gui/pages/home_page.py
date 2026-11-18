"""Halaman Home — identitas proyek & ringkasan status."""
from __future__ import annotations
from datetime import datetime

from ...config.i18n import tr
from PySide6.QtCore import Qt, QTimer, QLocale, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
                               QGroupBox, QPushButton, QFileDialog, QMessageBox,
                               QDialog)

from ...data.project import (save_project, load_project, default_name,
                             FILE_FILTER, ProjectError)

from ..widgets import KPICard, kpi_grid


class HomePage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        lay = QVBoxLayout(self)
        t = QLabel(tr('Home')); t.setObjectName('PageTitle')
        s = QLabel(tr('Identitas proyek dan status data')); s.setObjectName('PageSub')
        head = QHBoxLayout()
        head.addWidget(t); head.addStretch(1)
        b_open = QPushButton(tr('Buka Proyek…'))
        b_open.setProperty('flat', True)
        b_open.setCursor(Qt.PointingHandCursor)
        b_open.setToolTip(tr('Buka berkas proyek HPP Studio (.hpps)'))
        b_open.clicked.connect(self.open_project)
        b_saveas = QPushButton(tr('Simpan Sebagai…'))
        b_saveas.setProperty('flat', True)
        b_saveas.setCursor(Qt.PointingHandCursor)
        b_saveas.setToolTip(tr('Simpan ke berkas .hpps baru (Ctrl+Shift+S)'))
        b_saveas.clicked.connect(self.save_project_as)
        b_save = QPushButton(tr('Simpan'))
        b_save.setProperty('flat', True)
        b_save.setCursor(Qt.PointingHandCursor)
        b_save.setToolTip(tr('Simpan ke berkas yang sedang dibuka (Ctrl+S)'))
        b_save.clicked.connect(self.save_project)
        head.addWidget(b_open); head.addWidget(b_saveas)
        head.addWidget(b_save)
        lay.addLayout(head); lay.addWidget(s)
        self.lbl_file = QLabel('')
        self.lbl_file.setObjectName('PageSub')
        lay.addWidget(self.lbl_file)

        box = QGroupBox(tr('Project'))
        form = QFormLayout(box)
        self.name = QLineEdit(state.cfg.get('project_name', ''))
        self.customer = QLineEdit(state.cfg.get('customer', ''))
        self.site = QLineEdit(state.cfg.get('site_name', ''))
        self.location = QLineEdit(state.cfg.get('location', ''))
        self.year = QSpinBox(); self.year.setRange(2000, 2100)
        self.year.setValue(int(state.cfg.get('simulation_year', 2025)))
        created = state.created or datetime.now().strftime('%Y-%m-%d %H:%M')
        form.addRow(tr('Project Name'), self.name)
        form.addRow(tr('Customer'), self.customer)
        form.addRow(tr('Site Name'), self.site)
        form.addRow(tr('Location'), self.location)

        # --- Koordinat + pemilih peta ---------------------------------------
        # Label "Lat"/"Lon" berada DI DALAM kotak (prefix) agar baris rapi &
        # sejajar baris lain; locale titik-desimal agar mudah di-copy-paste.
        _usloc = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        self.lat = QDoubleSpinBox(); self.lat.setDecimals(6)
        self.lat.setRange(-90.0, 90.0); self.lat.setSingleStep(0.001)
        self.lat.setLocale(_usloc); self.lat.setPrefix('Lat  ')
        self.lat.setValue(float(state.cfg.get('latitude', 0.0) or 0.0))
        self.lat.setToolTip(tr('Latitude (−90…90)'))
        self.lon = QDoubleSpinBox(); self.lon.setDecimals(6)
        self.lon.setRange(-180.0, 180.0); self.lon.setSingleStep(0.001)
        self.lon.setLocale(_usloc); self.lon.setPrefix('Lon  ')
        self.lon.setValue(float(state.cfg.get('longitude', 0.0) or 0.0))
        self.lon.setToolTip(tr('Longitude (−180…180)'))
        self.btn_map = QPushButton(tr('Select on Map'))
        self.btn_map.setCursor(Qt.PointingHandCursor)
        self.btn_map.setToolTip(tr('Pick the project location on an '
                                   'interactive map (search by lat/lon or '
                                   'place name).'))
        self.btn_map.clicked.connect(self._open_map)
        coord = QWidget(); ch = QHBoxLayout(coord)
        ch.setContentsMargins(0, 0, 0, 0); ch.setSpacing(8)
        ch.addWidget(self.lat, 1); ch.addWidget(self.lon, 1)
        ch.addWidget(self.btn_map, 0)
        form.addRow(tr('Coordinates'), coord)

        form.addRow(tr('Created Date'), QLabel(created))
        form.addRow(tr('Simulation Year'), self.year)
        for w in (self.name, self.customer, self.site, self.location):
            w.editingFinished.connect(self._save)
        self.lat.editingFinished.connect(self._save)
        self.lon.editingFinished.connect(self._save)
        self.year.valueChanged.connect(self._save)
        lay.addWidget(box)

        self.c_load = KPICard(tr('Load Profile'), '—')
        self.c_pv = KPICard(tr('PV ENetAC Profile'), '—')
        self.c_grid = KPICard(tr('Grid Availability'), '—')
        self.c_sim = KPICard(tr('Simulasi Terakhir'), '—')
        lay.addWidget(kpi_grid([self.c_load, self.c_pv, self.c_grid, self.c_sim]))
        lay.addStretch(1)
        state.profiles_changed.connect(self.refresh)
        state.simulation_done.connect(self._on_simulation)
        state.config_changed.connect(self._sync_cfg_fields)
        self._sync_file_label()
        self.refresh()

    def _save(self):
        self.state.update_cfg(dict(
            project_name=self.name.text(), customer=self.customer.text(),
            site_name=self.site.text(), location=self.location.text(),
            latitude=round(self.lat.value(), 6),
            longitude=round(self.lon.value(), 6),
            simulation_year=self.year.value()))

    def _sync_cfg_fields(self):
        """Perbarui kolom yang bisa berubah dari luar (mis. tahun simulasi
        ikut berubah saat memakai data PVGIS; Site Name & koordinat ikut saat
        'Apply site' dari halaman Optimization / Multi-Year)."""
        try:
            self.year.blockSignals(True)
            self.year.setValue(int(self.state.cfg.get(
                'simulation_year', self.year.value())))
            self.year.blockSignals(False)
        except Exception:
            pass
        cfg = self.state.cfg
        for w, key in ((self.site, 'site_name'), (self.location, 'location')):
            try:
                v = cfg.get(key)
                if v is not None and w.text() != str(v):
                    w.blockSignals(True); w.setText(str(v))
                    w.blockSignals(False)
            except Exception:
                pass
        for sb, key in ((self.lat, 'latitude'), (self.lon, 'longitude')):
            try:
                v = cfg.get(key)
                if v is not None and abs(sb.value() - float(v)) > 1e-9:
                    sb.blockSignals(True); sb.setValue(float(v))
                    sb.blockSignals(False)
            except Exception:
                pass

    def _open_map(self):
        """Buka dialog peta untuk memilih lokasi (lat/lon)."""
        from ..map_picker import MapPickerDialog, webengine_available
        if not webengine_available():
            QMessageBox.warning(
                self, tr('Map unavailable'),
                tr('The map component is not available in this build. '
                   'You can still type latitude and longitude manually.'))
            return
        saved = dict(self.state.cfg.get('pvgis_opts') or {})
        try:
            dlg = MapPickerDialog(self.lat.value(), self.lon.value(),
                                  options=saved, parent=self)
        except Exception as e:
            QMessageBox.critical(self, tr('Map unavailable'), str(e))
            return
        # Bilah judul dialog diwarnai sendiri oleh MapPickerDialog (showEvent),
        # termasuk setelah WebEngine selesai memuat, agar tidak kembali putih.
        if dlg.exec() != QDialog.Accepted:
            return
        lat, lon = dlg.result_latlon()
        for sb, val in ((self.lat, lat), (self.lon, lon)):
            sb.blockSignals(True); sb.setValue(val); sb.blockSignals(False)
        addr = dlg.result_address()
        if addr:                                     # Location mengikuti peta
            self.location.setText(addr)
        self._save()
        # v164 — unduhan PVGIS (PV) & ERA5 (angin) dilakukan dari halaman Data
        # memakai koordinat yang baru dipilih ini.

    # ------------------------------------------------------------------
    def save_project(self):
        """Ctrl+S — timpa berkas yang sedang dibuka (bila ada)."""
        if not self.state.project_path:
            return self.save_project_as()
        return self._write(self.state.project_path, quiet=True)

    def save_project_as(self):
        """Ctrl+Shift+S — selalu menanyakan berkas tujuan baru."""
        st = self.state
        start = st.project_path or default_name(st.cfg)
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Simpan Sebagai'), start, FILE_FILTER)
        if not path:
            return
        return self._write(path)

    def _write(self, path, quiet=False):
        st = self.state
        try:
            sim = st.last_result
            # Kunci hasil simulasi yang disimpan agar GRAFIK Dashboard pulih
            # UTUH saat proyek dibuka lagi: selain data seri (series) & KPI,
            # SERTAKAN metadata render (interval, jendela, mode shaping, langkah
            # ramp) yang dipakai Dashboard menggambar sumbu-X, jendela tampil,
            # & overlay Smoothing/Firming. Tanpa ini grafik dulu pulih dgn
            # sumbu/jendela salah (interval balik ke 1 jam, window_h=0, dsb.).
            # 'params' (dataclass SystemParams) SENGAJA tak disimpan (tak perlu
            # utk grafik & bukan JSON).
            _SIM_KEYS = ('kpi', 'finance', 'series', 'monthly',
                         'sim_interval', 'window_start_h', 'window_h',
                         'adv_pv_smooth', 'adv_firming',
                         'ma_window', 'ramp_up_step', 'ramp_dn_step',
                         'pv_smooth_on')
            results = {
                'simulation': ({k: sim[k] for k in _SIM_KEYS
                                if sim.get(k) is not None}
                               if sim else None),
                'optimization': getattr(st, 'last_opt', None),
                'multiyear': getattr(st, 'multi_result', None),
                'transient': getattr(st, 'transient_result', None),
                'batch': (getattr(st, 'batch_rows', None) or None),
                # hasil batch multi-site multi-year (halaman Results)
                'multi_year_batch': (getattr(st, 'my_batch_rows', None)
                                     or None),
                # INPUT batch multi-site: sizing per-site & Base Profile Plant
                'multi_year_batch_inputs': {
                    'sizing': (getattr(st, 'my_batch_sizing', None) or None),
                    'base_mode': getattr(st, 'myb_base_mode', None),
                    'base_custom': getattr(st, 'myb_base_custom', None),
                    'col_order': (getattr(st, 'myb_col_order', None) or None),
                },
            }
            out = save_project(path, dict(st.cfg), load=st.load,
                               pv=st.pv_norm, grid=st.grid_status,
                               datetimes=st.datetimes,
                               results=results,
                               pv_excel=st.pv_excel, pv_pvgis=st.pv_pvgis,
                               wind=getattr(st, 'wind', None),
                               wind_excel=getattr(st, 'wind_excel', None),
                               wind_era5=getattr(st, 'wind_era5', None),
                               stg=getattr(st, 'stg_status', None),
                               gtg=getattr(st, 'gtg_status', None))
            import os
            size = os.path.getsize(out) / 1024.0
            st.project_path = out
            self._sync_file_label()
            if quiet:
                self.lbl_file.setText(
                    tr('Tersimpan:') + f' {os.path.basename(out)} '
                    f'({size:,.0f} KB) · {out}')
            else:
                QMessageBox.information(
                    self, tr('Sukses'),
                    tr('Proyek tersimpan:') + f'\n{out}\n({size:,.0f} KB)')
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr('Buka Proyek'), '', FILE_FILTER)
        if not path:
            return
        try:
            doc = load_project(path)
        except ProjectError as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))
            return
        win = self.window()
        # v172 — tampilan DIBEKUKAN (foto + updates off) selama state diisi
        # dan halaman dibangun ulang: tanpa ini setiap sinyal perubahan
        # menggambar ulang halaman satu per satu (berkedip).
        frozen = bool(getattr(win, 'freeze_for_load', None)) and \
            win.freeze_for_load()
        try:
            self._load_doc(doc, path)
        except Exception:
            if frozen:
                win.unfreeze()
            raise
        if frozen:
            win._rebuild()                  # di balik foto, lalu pudar halus
        msg = (tr('Proyek dimuat:') + f'\n{path}'
               + (('\n' + tr('Disimpan pada') + f": {doc['saved_at']}")
                  if doc.get('saved_at') else ''))
        if frozen:
            # pesan ditampilkan SETELAH UI baru siap (halaman ini sudah
            # diganti; induk pesan = jendela utama)
            QTimer.singleShot(260, lambda: QMessageBox.information(
                win, tr('Sukses'), msg))
            return
        QMessageBox.information(win, tr('Sukses'), msg)
        if hasattr(win, '_rebuild'):
            QTimer.singleShot(0, win._rebuild)

    def _load_doc(self, doc, path):
        """Isi AppState dari dokumen proyek (tanpa dialog)."""
        st = self.state
        from ...config.parameters import migrate_cfg
        cfg = dict(st.cfg)
        cfg.update(migrate_cfg(dict(doc['config'])))   # naikkan proyek lama
        res = doc.get('results') or {}
        sim = res.get('simulation')
        st.last_result = dict(sim) if sim else None
        st.multi_result = res.get('multiyear')
        st.transient_result = res.get('transient')
        st.last_opt = res.get('optimization')
        batch = res.get('batch')
        st.batch_rows = list(batch) if batch else []
        st.batch_paths = [r.get('path', '') for r in st.batch_rows]
        myb = res.get('multi_year_batch')
        st.my_batch_rows = list(myb) if myb else []
        st.my_batch_paths = [r.get('path', '') for r in st.my_batch_rows]
        inp = res.get('multi_year_batch_inputs') or {}
        st.my_batch_sizing = list(inp.get('sizing') or [])
        if inp.get('base_mode'):
            st.myb_base_mode = inp['base_mode']
        if inp.get('base_custom') is not None:
            try:
                st.myb_base_custom = float(inp['base_custom'])
            except (ValueError, TypeError):
                pass
        st.myb_col_order = list(inp.get('col_order') or [])
        prof = doc['profiles']
        if prof:
            st.set_profiles(prof['datetimes'], prof['load'], prof['pv'],
                            prof['grid'])
            # Pulihkan dua sumber PV (Excel/PVGIS) bila tersimpan.
            st.set_pv_excel(prof.get('pv_excel'))
            st.set_pv_pvgis(prof.get('pv_pvgis'))
            # v162 — profil Wind & STG Status (None = berkas tak memuatnya)
            st.set_aux_profiles(wind=prof.get('wind'), stg=prof.get('stg'),
                                gtg=prof.get('gtg'))
            # v164 — dua sumber angin; berkas v162/v163 hanya punya 'wind'
            # (dianggap impor Excel).
            _wx, _we = prof.get('wind_excel'), prof.get('wind_era5')
            if _wx is None and _we is None:
                _wx = prof.get('wind')
            st.set_wind_data('excel', _wx)
            st.set_wind_data('era5', _we)
            # Berkas lama tanpa kedua sumber: isi sumber aktif dari profil PV.
            if st.pv_excel is None and st.pv_pvgis is None \
                    and st.pv_norm is not None:
                if str(cfg.get('pv_source')) == 'pvgis':
                    st.set_pv_pvgis(st.pv_norm)
                else:
                    st.set_pv_excel(st.pv_norm)
        st.project_path = path
        st.update_cfg(cfg)
        self.refresh()
        self._sync_file_label()

    def _sync_file_label(self):
        import os
        p = self.state.project_path
        self.lbl_file.setText(
            (tr('Berkas proyek:') + f' {os.path.basename(p)} · {p}')
            if p else tr('Proyek belum tersimpan ke berkas .hpps'))
        win = self.window()
        if hasattr(win, 'set_project_title'):
            win.set_project_title(p)

    def _on_simulation(self, *_):
        self.refresh()

    def refresh(self):
        st = self.state
        # Interval NATIVE data: energi = daya × dt, jumlah baris BUKAN jam.
        # Data per-jam -> dt=1 (kartu lama utuh).
        from ...config import intervals as ivals
        n = len(st.load) if st.load is not None else (
            len(st.pv_norm) if st.pv_norm is not None else 0)
        iv = ivals.detect_interval_label(n, st.datetimes) or '1 hour'
        dt = ivals.interval_dt_h(iv)
        if st.load is not None:
            self.c_load.set_value(f'{st.load.sum() * dt:,.0f} kWh/yr')
        if st.pv_norm is not None:
            # Energi PV ENetAC TERKIRIM per tahun = profil basis × skala
            # (pv_kwp / pv_base_annual) × dt.
            scale = st.cfg.get('pv_kwp', 1) / \
                max(st.cfg.get('pv_base_annual', 1), 1e-9)
            self.c_pv.set_value(f'{st.pv_norm.sum() * scale * dt:,.0f} kWh/yr')
        if st.grid_status is not None:
            off_h = float((st.grid_status == 0).sum()) * dt
            oh = f'{off_h:,.0f}' if abs(off_h - round(off_h)) < 0.05 \
                else f'{off_h:,.1f}'
            self.c_grid.set_value(f'{oh} ' + tr('jam padam'))
        if st.last_result:
            rf = st.last_result['kpi']['renewable_fraction']
            self.c_sim.set_value(f'RF {rf*100:.1f}%')
