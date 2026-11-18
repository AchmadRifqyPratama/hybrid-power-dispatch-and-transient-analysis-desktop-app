"""Halaman Transient — studi dinamik/transien & hubung singkat.

Kiri : parameter studi (grup 'Transient — …' dari SCHEMA, tersimpan otomatis)
       + impor data beban aktual dari Power Quality Analyzer (PQA).
Kanan: tabel kasus (lebar kolom dapat diatur, teks membungkus), grafik
       frekuensi / tegangan / daya aktif / daya reaktif dengan pembacaan nilai
       di posisi kursor, tabel hubung singkat & pemutusan feeder, ringkasan
       persyaratan, data model, dan dasar standar tiap parameter.
Perhitungan berjalan di proses latar (ProcWorker) agar UI tetap responsif.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QCheckBox, QGridLayout, QToolButton, QMenu,
                               QWidgetAction,
                               QComboBox,
                               QPushButton, QScrollArea, QSplitter, QTabWidget,
                               QTableWidgetItem, QFileDialog, QMessageBox,
                               QProgressBar, QHeaderView, QAbstractItemView,
                               QGroupBox)

from ...config.i18n import tr
from ...config.parameters import SCHEMA, VISIBILITY
from ..bgproc import ProcWorker
from ..widgets import ParamGroupBox
from ..plotutil import (CopyTableWidget, rect_zoom, LeaveWatcher,
                        HeightGrip, WheelToScroll, LegendBar, PopOut,
                        link_x, GridArranger)
from ..theme import style_layout

_STATUS_COL = {'Pass': '#16A34A', 'Fail': '#DC2626', 'Ref': '#6B7280',
               'Skipped': '#D97706',
               'Error': '#DC2626'}
_PAL = ['#B45309', '#DC2626', '#7C3AED', '#0EA5E9', '#84CC16', '#06B6D4',
        '#2563EB', '#DB2777', '#F59E0B', '#10B981']
# lebar awal kolom (px) menurut judul; kolom lain = 92
_COL_W = {'ID': 44, 'Group': 150, 'Case': 300, 'Pre-event operating point': 230,
          'Result': 60, 'Remarks': 320, 'Basis of the result': 440,
          'Criterion': 230, 'Measured': 130, 'Limit': 170, 'Status': 70,
          'Basis / reason': 420, 'Event': 190, 'Result ': 320,
          'Requirement that follows': 520, 'Representation': 420,
          'Parameters': 420, 'Element': 170, 'Basis': 300,
          'Operating configuration': 240, 'Source': 190, 'Parameter': 230,
          'Standard basis of the default': 520}


_MUTED = '#7C8794'          # abu-abu netral, terbaca di tema gelap & terang


def _src_head(source: str, text: str = '') -> str:
    """Baris 'Sumber data' di bawah tab — tanpa lencana berwarna."""
    s = (f'<span style="color:{_MUTED};">{tr("Sumber data")}:</span> '
         f'<b>{source}</b>')
    return s + (f'<span style="color:{_MUTED};"> — {text}</span>' if text else '')


def _section(num, title: str, source: str, text: str = '') -> str:
    """Judul bagian bernomor + sumber datanya (satu gaya di seluruh tab)."""
    s = (f'<span style="font-weight:600;font-size:13px;">{num}. {title}</span>'
         f'&nbsp;&nbsp;<span style="color:{_MUTED};">{tr("Sumber data")}: '
         f'{source}</span>')
    return s + (f'<br><span style="color:{_MUTED};">{text}</span>' if text else '')


def _hint(fs: bool = False) -> str:
    """Teks pembacaan kursor saat kursor di luar grafik (menggantikan
    tooltip di atas grafik, yang menutupi kurva). `fs` = layar penuh:
    tambah petunjuk menyeret judul panel (v180)."""
    t = (tr('Arahkan kursor ke grafik untuk membaca nilai.') + ' · '
         + tr('Zoom: seret kotak di dalam grafik · Reset: klik-ganda'))
    if fs:
        t += ' · ' + tr('Tata letak: seret judul panel untuk memindah, '
                        'sudut/tepi kanan-bawah untuk mengubah ukuran')
    return t


_CASE_KEYS = ('f', 'v', 'p', 'q')        # panel grafik Kasus (urutan kanonik)


def _name(k: str) -> str:
    return k.replace('GRID', 'Utility Grid')


class _StudyWorker(ProcWorker):
    finished_ok = Signal(object)
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self, state):
        super().__init__()
        self.state = state

    def run(self):
        try:
            from ...engine.transient_cases import run_scenarios
            st = self.state
            peak = None
            if getattr(st, 'load', None) is not None and len(st.load):
                peak = float(np.max(st.load))

            def _cb(done, total, _t=''):
                self.progress.emit(int(done * 100 / max(total, 1)))
            self.finished_ok.emit(run_scenarios(dict(st.cfg), load_peak_kw=peak,
                                                progress=_cb))
        except Exception as e:  # pragma: no cover
            import traceback
            self.failed.emit(f'{e}\n{traceback.format_exc()}')


class TransientPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self._worker = None
        self._curves = []            # [(plot, x, y, label, color, unit)]
        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        t = QLabel(tr('Transient Analysis')); t.setObjectName('PageTitle')
        head.addWidget(t); head.addStretch(1)
        self.bar = QProgressBar(); self.bar.setFixedWidth(160)
        self.bar.setVisible(False)
        self.btn_run = QPushButton(tr('Run Transient Study'))
        self.btn_run.clicked.connect(self._run)
        self.btn_xlsx = QPushButton(tr('Export Excel'))
        self.btn_xlsx.setProperty('flat', True)
        self.btn_xlsx.clicked.connect(lambda: self._export('xlsx'))
        self.btn_docx = QPushButton(tr('Export Report (Word)'))
        self.btn_docx.setProperty('flat', True)
        self.btn_docx.clicked.connect(lambda: self._export('docx'))
        for w in (self.bar, self.btn_docx, self.btn_xlsx, self.btn_run):
            head.addWidget(w)
        lay.addLayout(head)
        self.sub = QLabel(tr(
            'Model RMS (fasor) satu-bus, langkah 1 ms: trip pembangkit, loss of '
            'BESS, variabilitas PV/WTG, steam shortfall, load step, motor '
            'starting, sinkronisasi, gangguan feeder, black start, dan hubung '
            'singkat. Titik operasi diturunkan dari halaman Parameters.'))
        self.sub.setObjectName('PageSub'); self.sub.setWordWrap(True)
        lay.addWidget(self.sub)

        split = QSplitter(Qt.Horizontal)
        # ---- kiri: PQA + parameter ----
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); iv = QVBoxLayout(inner); iv.setSpacing(8)
        pq = QGroupBox(tr('Data Beban Aktual (PQA)'))
        pl = QVBoxLayout(pq)
        row = QHBoxLayout()
        self.btn_pqa = QPushButton(tr('Impor Data PQA…'))
        self.btn_pqa.setToolTip(tr(
            'Impor rekaman Power Quality Analyzer (Excel/CSV) dengan kolom '
            'sesuai Template PQA: Date, Time, RMS setengah-siklus U/I '
            '(MAX/MIN), frekuensi, RMS rata-rata per fasa, unbalance, THD, '
            'harmonisa H5/H7, P, PF, WP+, Dem_P+. Kolom yang tidak tersedia '
            'boleh dikosongkan — analisis yang membutuhkannya dilewati. '
            'Beban studi, faktor daya, dan step beban terbesar diambil dari '
            'data ini saat "Study Load Source" = PQA.'))
        self.btn_pqa.clicked.connect(self._import_pqa)
        self.btn_pqa_tpl = QPushButton(tr('Template PQA…'))
        self.btn_pqa_tpl.setProperty('flat', True)
        self.btn_pqa_tpl.setToolTip(tr(
            'Simpan template Excel berisi kolom data PQA yang diminta, '
            'satuannya, dan analisis yang memakai tiap kolom.'))
        self.btn_pqa_tpl.clicked.connect(self._pqa_template)
        self.btn_pqa_clr = QPushButton(tr('Hapus'))
        self.btn_pqa_clr.setProperty('flat', True)
        self.btn_pqa_clr.clicked.connect(self._clear_pqa)
        row.addWidget(self.btn_pqa); row.addWidget(self.btn_pqa_tpl)
        row.addWidget(self.btn_pqa_clr)
        row.addStretch(1)
        pl.addLayout(row)
        self.lbl_pqa = QLabel(''); self.lbl_pqa.setWordWrap(True)
        self.lbl_pqa.setObjectName('PageSub')
        pl.addWidget(self.lbl_pqa)
        iv.addWidget(pq)

        # ---- v168: definisi sistem (existing / baru) ----
        from ...engine.transient_cases import (EXISTING_CHOICES, NEW_CHOICES,
                                               SRC_LABEL)
        sd = QGroupBox(tr('Definisi Sistem'))
        sg = QGridLayout(sd)
        sg.setHorizontalSpacing(10); sg.setVerticalSpacing(4)
        self._sys_chk = {'tr_existing': {}, 'tr_new': {}}
        for r_, (key, title, opts) in enumerate((
                ('tr_existing', tr('Sistem existing'), EXISTING_CHOICES),
                ('tr_new', tr('Sistem baru'), NEW_CHOICES))):
            lb = QLabel(title); lb.setStyleSheet('font-weight:600;')
            sg.addWidget(lb, 2 * r_, 0, 1, 5)
            for c_, k in enumerate(opts):
                cb = QCheckBox(SRC_LABEL[k])
                cb.setChecked(k in (state.cfg.get(key) or []))
                cb.toggled.connect(
                    lambda on, _key=key, _k=k: self._on_sys_toggle(_key, _k, on))
                sg.addWidget(cb, 2 * r_ + 1, c_)
                self._sys_chk[key][k] = cb
        self.lbl_sys = QLabel(''); self.lbl_sys.setWordWrap(True)
        self.lbl_sys.setObjectName('PageSub')
        self.lbl_sys.setTextFormat(Qt.RichText)
        sg.addWidget(self.lbl_sys, 4, 0, 1, 5)
        sd.setToolTip(tr(
            'Pilih pembangkit sistem existing dan sistem baru (boleh lebih '
            'dari satu). Studi dijalankan untuk: sistem existing, sistem '
            'baru, dan existing + baru. Ukuran tiap pembangkit diambil dari '
            'halaman Parameters. Tanpa pilihan, seluruh pembangkit yang '
            'dikonfigurasi dianalisis sebagai satu sistem.'))
        iv.addWidget(sd)
        self.groups = []
        for name, params in SCHEMA.items():
            if not name.startswith('Transient'):
                continue
            g = ParamGroupBox(name, params)
            g.set_values(state.cfg)
            g.changed.connect(self._on_change)
            iv.addWidget(g)
            self.groups.append(g)
        iv.addStretch(1)
        scroll.setWidget(inner)
        scroll.setMinimumWidth(380)
        split.addWidget(scroll)

        # ---- kanan: hasil ----
        self.tabs = QTabWidget()
        rw = QWidget(); rv = QVBoxLayout(rw); rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(4)
        sr = QHBoxLayout()
        sr.addWidget(QLabel(tr('Sistem yang ditampilkan')))
        self.cb_sys = QComboBox()
        self.cb_sys.setMinimumWidth(220)
        self.cb_sys.currentIndexChanged.connect(self._on_sys_view)
        sr.addWidget(self.cb_sys)
        self.lbl_sys_view = QLabel(''); self.lbl_sys_view.setObjectName('PageSub')
        sr.addWidget(self.lbl_sys_view, 1)
        rv.addLayout(sr)
        # v170 — tab LUAR memisahkan hasil menurut SUMBER DATA-nya
        self.top_tabs = QTabWidget()
        rv.addWidget(self.top_tabs, 1)
        split.addWidget(rw)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1)
        split.setSizes([430, 900])
        lay.addWidget(split, 1)

        cw = QWidget(); cv = QVBoxLayout(cw); cv.setContentsMargins(4, 4, 4, 4)
        self.lbl_sum = QLabel(tr('Belum ada hasil — tekan "Run Transient Study".'))
        self.lbl_sum.setObjectName('PageSub'); self.lbl_sum.setWordWrap(True)
        cv.addWidget(self.lbl_sum)
        # v167 — isi tab dapat digulir vertikal: tabel bisa dipanjangkan
        # (seret pegangan di bawahnya), grafik tetap terjangkau scroll bar.
        self.tbl = self._mk_table()
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.itemSelectionChanged.connect(self._plot_selected)
        self.tbl.setFixedHeight(250)
        cv.addWidget(self.tbl)
        cv.addWidget(HeightGrip(self.tbl))
        # v177 — bukti penilaian kasus terpilih: tiap kriteria, nilai hasil
        # simulasi, batas, status, dan dasar batasnya
        self.lbl_ev = QLabel(''); self.lbl_ev.setWordWrap(True)
        self.lbl_ev.setTextFormat(Qt.RichText); self.lbl_ev.setObjectName('PageSub')
        cv.addWidget(self.lbl_ev)
        self.tbl_ev = self._mk_table(); self.tbl_ev.setFixedHeight(200)
        cv.addWidget(self.tbl_ev)
        cv.addWidget(HeightGrip(self.tbl_ev, min_h=90))
        pw = QWidget(); pv = QVBoxLayout(pw); pv.setContentsMargins(0, 0, 0, 0)
        self.lbl_case = QLabel(''); self.lbl_case.setWordWrap(True)
        self.lbl_case.setObjectName('PageSub')
        # v176 — baris pemilih kasus (tampil saat layar penuh, bagian atas
        # yang tetap): pilih kasus tanpa keluar dari layar penuh
        self._case_sel = QWidget()
        _cs = QHBoxLayout(self._case_sel); _cs.setContentsMargins(0, 0, 0, 0)
        _l = QLabel(tr('Grafik kasus')); _l.setStyleSheet('font-weight:600;')
        _cs.addWidget(_l)
        self.cb_case = QComboBox()
        self.cb_case.currentIndexChanged.connect(self._on_case_combo)
        _cs.addWidget(self.cb_case, 1)
        self._fs_cols = int(state.cfg.get('tr_fs_cols', 2) or 2)
        self._fs_fit = bool(state.cfg.get('tr_fs_fit', False))
        # v181 — tata letak grid bebas layar penuh {key: [r, c, rs, cs]}
        self._case_grid = dict(state.cfg.get('tr_fs_grid_case') or {})
        self._cmp_grid = dict(state.cfg.get('tr_fs_grid_cmp') or {})
        self._fs_case = self._fs_controls(
            lambda: self._layout_case(getattr(self, '_case_fs', False)),
            on_reset=self._reset_case_layout)
        _cs.addWidget(self._fs_case)
        self._case_sel.setVisible(False)
        pv.addWidget(self._case_sel)
        _hr = QHBoxLayout()
        _hr.addWidget(self.lbl_case, 1)

        def _case_full(on):
            self._fs_case.setVisible(on)
            self._case_sel.setVisible(on)
            self._layout_case(on)
        self._pop_case = PopOut(
            pw, tr('Kasus — grafik'),
            on_open=lambda: _case_full(True),
            on_close=lambda: _case_full(False))
        _b = self._pop_case.button(tr('⛶ Layar penuh'))
        _b.setToolTip(tr('Tampilkan grafik ini layar penuh (Esc untuk kembali)'))
        _hr.addWidget(_b, 0, Qt.AlignTop)
        pv.addLayout(_hr)
        self.lbl_cur = QLabel(_hint())
        self.lbl_cur.setWordWrap(True); self.lbl_cur.setTextFormat(Qt.RichText)
        self.lbl_cur.setObjectName('PageSub')
        self.lbl_cur.setMinimumHeight(34)
        # v175 — legenda terkumpul di atas grafik (tidak menutupi kurva);
        # satu entri berlaku untuk semua panel
        self.leg_case = LegendBar()
        self.leg_case.setToolTip(tr('Klik entri legenda untuk menyembunyikan / '
                                    'menampilkan kurvanya di semua panel'))
        self.leg_case.toggled.connect(self._on_case_legend)
        pv.addWidget(self.leg_case)
        pv.addWidget(self.lbl_cur)
        self.glw = pg.GraphicsLayoutWidget()
        self._pop_case._scroll = self.glw        # layar penuh: hanya grafik digulir
        self.p_f = self.glw.addPlot(row=0, col=0)
        self.p_v = self.glw.addPlot(row=1, col=0)
        self.p_p = self.glw.addPlot(row=2, col=0)
        self.p_q = self.glw.addPlot(row=3, col=0)
        self._plots = (self.p_f, self.p_v, self.p_p, self.p_q)
        for p, lab in ((self.p_f, tr('Frekuensi (Hz)')),
                       (self.p_v, tr('Tegangan bus (pu)')),
                       (self.p_p, tr('Daya aktif (kW)')),
                       (self.p_q, tr('Daya reaktif (kvar)'))):
            p.showGrid(x=True, y=True, alpha=0.2)
            p.setLabel('left', lab)
            p.getAxis('left').setWidth(64)
        link_x(self._plots)
        self.p_q.setLabel('bottom', tr('Waktu (s)'))
        self.glw.setMinimumHeight(560)
        # roda mouse tidak men-zoom; zoom = seret kotak; klik-ganda = reset
        rect_zoom(self._plots)
        # v181 — layar penuh: grid bebas (seret judul = pindah, sudut/tepi =
        # ubah ukuran)
        self._case_arr = GridArranger(
            self.glw, lambda: bool(getattr(self, '_case_fs', False)))
        self._case_arr.changed.connect(self._on_case_grid)
        # garis kursor + penanda titik data di tiap panel
        self._vlines, self._dots = [], []
        for p in self._plots:
            ln = pg.InfiniteLine(angle=90, movable=False,
                                 pen=pg.mkPen('#9CA3AF', width=1))
            ln.setZValue(50); ln.setVisible(False)
            p.addItem(ln, ignoreBounds=True)
            sc = pg.ScatterPlotItem(size=8, pen=pg.mkPen('#111827', width=1))
            sc.setZValue(60)
            p.addItem(sc, ignoreBounds=True)
            self._vlines.append(ln); self._dots.append(sc)
        self._proxy = pg.SignalProxy(self.glw.scene().sigMouseMoved,
                                     rateLimit=50, slot=self._on_mouse)
        self._leave = LeaveWatcher(self.glw, self._cursor_off)
        self._wheel = WheelToScroll(self.glw)
        pv.addWidget(self.glw, 1)
        cv.addWidget(pw, 1)
        csc = QScrollArea(); csc.setWidgetResizable(True)
        csc.setFrameShape(QScrollArea.NoFrame)
        csc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        csc.setWidget(cw)
        self.tabs.addTab(csc, tr('Kasus'))

        self.tbl_req = self._mk_table()
        self.tabs.addTab(self.tbl_req, tr('Ringkasan dan Persyaratan'))
        scw = QWidget(); sv = QVBoxLayout(scw); sv.setContentsMargins(4, 4, 4, 4)
        self.lbl_sc = QLabel(''); self.lbl_sc.setWordWrap(True)
        self.lbl_sc.setObjectName('PageSub')
        self.tbl_sc = self._mk_table(); self.tbl_src = self._mk_table()
        self.tbl_prot = self._mk_table()
        for w in (self.lbl_sc, self.tbl_src, self.tbl_sc, self.tbl_prot):
            sv.addWidget(w)
        self.tabs.addTab(scw, tr('Hubung Singkat dan Proteksi'))
        self.tbl_model = self._mk_table()
        self.tabs.addTab(self.tbl_model, tr('Model dan Data'))
        self.tbl_basis = self._mk_table()
        self.tabs.addTab(self.tbl_basis, tr('Dasar Parameter'))

        # ---- v168: perbandingan sistem + penilaian thd. data PQA ----
        xw_ = QWidget(); xv = QVBoxLayout(xw_); xv.setContentsMargins(4, 4, 4, 4)
        self.lbl_cmp = QLabel(_section(1, tr('Perbandingan sistem'),
                                       tr('simulasi model'), tr(
            'Belum ada hasil. Tentukan sistem existing dan sistem baru di '
            'panel kiri, lalu jalankan studi.')))
        self.lbl_cmp.setWordWrap(True); self.lbl_cmp.setObjectName('PageSub')
        self.lbl_cmp.setTextFormat(Qt.RichText)
        xv.addWidget(self.lbl_cmp)
        self.tbl_cmp = self._mk_table(); self.tbl_cmp.setFixedHeight(330)
        xv.addWidget(self.tbl_cmp); xv.addWidget(HeightGrip(self.tbl_cmp))
        self.lbl_asm = QLabel(''); self.lbl_asm.setWordWrap(True)
        self.lbl_asm.setObjectName('PageSub')
        self.lbl_asm.setTextFormat(Qt.RichText)
        xv.addWidget(self.lbl_asm)
        self.tbl_asm = self._mk_table(); self.tbl_asm.setFixedHeight(420)
        xv.addWidget(self.tbl_asm); xv.addWidget(HeightGrip(self.tbl_asm))
        # ---- v169/v170: grafik perbandingan per kasus (semua sistem) +
        #      cuplikan PQA terkait; legenda terkumpul; layar penuh ----
        _s3 = QLabel(_section(3, tr('Grafik kasus'), tr(
            'simulasi model (panel atas) dan cuplikan pengukuran PQA (panel '
            'bawah)')))
        _s3.setTextFormat(Qt.RichText); _s3.setWordWrap(True)
        _s3.setObjectName('PageSub')
        xv.addSpacing(6); xv.addWidget(_s3)
        blk = QWidget(); bl = QVBoxLayout(blk); bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        cr = QHBoxLayout()
        _l = QLabel(tr('Grafik kasus')); _l.setStyleSheet('font-weight:600;')
        cr.addWidget(_l)
        self.cb_cmp_case = QComboBox()
        self.cb_cmp_case.currentIndexChanged.connect(
            lambda *_: self._plot_cmp_case())
        cr.addWidget(self.cb_cmp_case, 1)
        # layar penuh: tabel metrik disembunyikan & grafik mengikuti tinggi layar
        self._fs_cmp = self._fs_controls(lambda: self._plot_cmp_case(),
                                         on_reset=self._reset_cmp_layout)
        cr.addWidget(self._fs_cmp)

        def _cmp_full(on):
            self.tbl_cmp_case.setVisible(not on)
            self._cmp_grip.setVisible(not on)
            self._fs_cmp.setVisible(on)
            self._cmp_fs = bool(on)
            self._plot_cmp_case()           # susun ulang menurut pilihan
        self._pop_cmp = PopOut(blk, tr('Perbandingan Sistem — grafik kasus'),
                               on_open=lambda: _cmp_full(True),
                               on_close=lambda: _cmp_full(False))
        _b = self._pop_cmp.button(tr('⛶ Layar penuh'))
        _b.setToolTip(tr('Tampilkan grafik ini layar penuh (Esc untuk kembali)'))
        cr.addWidget(_b)
        bl.addLayout(cr)
        self.tbl_cmp_case = self._mk_table(); self.tbl_cmp_case.setFixedHeight(170)
        bl.addWidget(self.tbl_cmp_case)
        self._cmp_grip = HeightGrip(self.tbl_cmp_case, min_h=90)
        bl.addWidget(self._cmp_grip)
        self.lbl_cmp_pqa = QLabel(''); self.lbl_cmp_pqa.setWordWrap(True)
        self.lbl_cmp_pqa.setTextFormat(Qt.RichText)
        self.lbl_cmp_pqa.setObjectName('PageSub')
        bl.addWidget(self.lbl_cmp_pqa)
        self.leg_cmp = LegendBar()
        self.leg_cmp.setToolTip(tr('Klik entri legenda untuk menyembunyikan / '
                                   'menampilkan kurvanya di semua panel'))
        self.leg_cmp.toggled.connect(self._on_cmp_legend)
        bl.addWidget(self.leg_cmp)
        self.lbl_cmp_cur = QLabel(_hint())
        self.lbl_cmp_cur.setWordWrap(True)
        self.lbl_cmp_cur.setTextFormat(Qt.RichText)
        self.lbl_cmp_cur.setObjectName('PageSub')
        self.lbl_cmp_cur.setMinimumHeight(52)
        bl.addWidget(self.lbl_cmp_cur)
        self.glw_cmp = pg.GraphicsLayoutWidget()
        self._pop_cmp._scroll = self.glw_cmp     # layar penuh: hanya grafik digulir
        self.glw_cmp.setMinimumHeight(1040)
        self._cmp_plots, self._cmp_curves = [], []
        self._cmp_vlines, self._cmp_dots = [], []
        self._cmp_proxy = pg.SignalProxy(self.glw_cmp.scene().sigMouseMoved,
                                         rateLimit=50, slot=self._on_cmp_mouse)
        self._cmp_leave = LeaveWatcher(self.glw_cmp, self._cmp_cursor_off)
        self._cmp_wheel = WheelToScroll(self.glw_cmp)
        self._cmp_arr = GridArranger(
            self.glw_cmp, lambda: bool(getattr(self, '_cmp_fs', False)))
        self._cmp_arr.changed.connect(self._on_cmp_grid)
        bl.addWidget(self.glw_cmp, 1)
        xv.addWidget(blk, 1)
        xsc = QScrollArea(); xsc.setWidgetResizable(True)
        xsc.setFrameShape(QScrollArea.NoFrame)
        xsc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        xsc.setWidget(xw_)
        self.tab_cmp = xsc

        # ---- v166: Analisis PQA (pengukuran) ----
        qw = QWidget(); qv = QVBoxLayout(qw); qv.setContentsMargins(4, 4, 4, 4)
        self.lbl_pqa_an = QLabel(''); self.lbl_pqa_an.setWordWrap(True)
        self.lbl_pqa_an.setObjectName('PageSub')
        self.lbl_pqa_an.setTextFormat(Qt.RichText)
        qv.addWidget(self.lbl_pqa_an)
        self.tbl_pqa = self._mk_table()
        self.tbl_pqa.setFixedHeight(330)
        qv.addWidget(self.tbl_pqa)
        qv.addWidget(HeightGrip(self.tbl_pqa))
        qp = QWidget(); qpl = QVBoxLayout(qp); qpl.setContentsMargins(0, 0, 0, 0)
        qr = QHBoxLayout()
        qr.addWidget(QLabel(tr('Grafik')))
        self.cb_pqa = QComboBox()
        self.cb_pqa.currentIndexChanged.connect(lambda *_: self._plot_pqa())
        qr.addWidget(self.cb_pqa, 1)
        # v182 — layar penuh: pilih BEBERAPA grafik + tata letak grid bebas
        self.btn_pqa_sel = QToolButton()
        self.btn_pqa_sel.setPopupMode(QToolButton.InstantPopup)
        self.btn_pqa_sel.setToolTip(tr('Pilih grafik analisis PQA yang ditampilkan '
                                       'pada layar penuh'))
        self._pqa_sel_wrap = QWidget()          # tombol rata kiri + sisa ruang
        _sw = QHBoxLayout(self._pqa_sel_wrap); _sw.setContentsMargins(0, 0, 0, 0)
        _sw.addWidget(self.btn_pqa_sel); _sw.addStretch(1)
        self._pqa_sel_wrap.setVisible(False)
        qr.addWidget(self._pqa_sel_wrap, 1)
        self._pqa_grid = dict(state.cfg.get('tr_fs_grid_pqa') or {})
        self._fs_pqa = self._fs_controls(lambda: self._plot_pqa_fs(),
                                         on_reset=self._reset_pqa_layout)
        qr.addWidget(self._fs_pqa)
        self.btn_pqa_x = QPushButton(tr('Ekspor Analisis PQA (Excel)'))
        self.btn_pqa_x.setProperty('flat', True)
        self.btn_pqa_x.clicked.connect(self._export_pqa)
        qr.addWidget(self.btn_pqa_x)
        self._pop_pqa = PopOut(qp, tr('Analisis PQA — grafik'),
                               on_open=lambda: self._pqa_full(True),
                               on_close=lambda: self._pqa_full(False))
        _b = self._pop_pqa.button(tr('⛶ Layar penuh'))
        _b.setToolTip(tr('Tampilkan grafik ini layar penuh (Esc untuk kembali)'))
        qr.addWidget(_b)
        qpl.addLayout(qr)
        self.plot_pqa = pg.PlotWidget()
        # wadah grafik: halaman = 1 grafik (plot_pqa); layar penuh = beberapa
        # grafik pada kanvas grid (glw_pqa). Hanya wadah ini yang digulir.
        self._pqa_box = QWidget()
        _pb = QVBoxLayout(self._pqa_box); _pb.setContentsMargins(0, 0, 0, 0)
        _pb.addWidget(self.plot_pqa, 1)
        self.glw_pqa = pg.GraphicsLayoutWidget()
        self.glw_pqa.setVisible(False)
        _pb.addWidget(self.glw_pqa, 1)
        self._pop_pqa._scroll = self._pqa_box   # layar penuh: legenda tetap di atas
        self._pqa_fs = False
        self._pqa_fs_plots = []          # [(id, PlotItem)]
        self._pqa_fs_curves = []         # [(plot, t, y, label, color, item)]
        self._pqa_fs_cur = []            # [(plot, vline, dots)]
        self._pqa_arr = GridArranger(self.glw_pqa, lambda: self._pqa_fs)
        self._pqa_arr.changed.connect(self._on_pqa_grid)
        self._pqa_fs_proxy = pg.SignalProxy(self.glw_pqa.scene().sigMouseMoved,
                                            rateLimit=50,
                                            slot=self._on_pqa_fs_mouse)
        self._pqa_fs_leave = LeaveWatcher(self.glw_pqa, self._pqa_cursor_off)
        self._pqa_fs_wheel = WheelToScroll(self.glw_pqa)
        self.plot_pqa.setBackground(None)
        self.plot_pqa.showGrid(x=True, y=True, alpha=0.2)
        self.plot_pqa.setMinimumHeight(380)
        self.lbl_pqa_cur = QLabel(_hint())
        self.lbl_pqa_cur.setWordWrap(True)
        self.lbl_pqa_cur.setTextFormat(Qt.RichText)
        self.lbl_pqa_cur.setObjectName('PageSub')
        self.lbl_pqa_cur.setMinimumHeight(34)
        self.leg_pqa = LegendBar()
        self.leg_pqa.setToolTip(tr('Klik entri legenda untuk menyembunyikan / '
                                   'menampilkan kurvanya'))
        self.leg_pqa.toggled.connect(self._on_pqa_legend)
        self._pqa_items = []
        qpl.addWidget(self.leg_pqa)
        qpl.addWidget(self.lbl_pqa_cur)
        qpl.addWidget(self._pqa_box, 1)
        rect_zoom([self.plot_pqa.getPlotItem()])
        self._pqa_curves = []            # [(t, y, label, color)]
        self._pqa_vline = pg.InfiniteLine(angle=90, movable=False,
                                          pen=pg.mkPen('#9CA3AF', width=1))
        self._pqa_vline.setZValue(50)
        self._pqa_dots = pg.ScatterPlotItem(size=8,
                                            pen=pg.mkPen('#111827', width=1))
        self._pqa_dots.setZValue(60)
        self._pqa_proxy = pg.SignalProxy(self.plot_pqa.scene().sigMouseMoved,
                                         rateLimit=50, slot=self._on_pqa_mouse)
        self._pqa_leave = LeaveWatcher(self.plot_pqa, self._pqa_cursor_off)
        self._pqa_wheel = WheelToScroll(self.plot_pqa)
        qv.addWidget(qp, 1)
        qsc = QScrollArea(); qsc.setWidgetResizable(True)
        qsc.setFrameShape(QScrollArea.NoFrame)
        qsc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        qsc.setWidget(qw)
        self.tab_pqa = qsc

        def _origin(source, text):
            lb = QLabel(_src_head(source, text))
            lb.setTextFormat(Qt.RichText); lb.setWordWrap(True)
            lb.setObjectName('PageSub')
            return lb

        def _wrap(head, body):
            w_ = QWidget(); l_ = QVBoxLayout(w_)
            l_.setContentsMargins(4, 6, 4, 0); l_.setSpacing(4)
            l_.addWidget(head); l_.addWidget(body, 1)
            return w_
        self.tab_sim = _wrap(_origin(tr('simulasi model'), tr(
            'parameter yang Anda isi (halaman Parameters dan panel kiri); '
            'nilai bawaan mengikuti standar IEC/IEEE (lihat tab "Dasar '
            'Parameter"). Bila data PQA diimpor, hanya beban (kW, faktor '
            'daya, step beban, ukuran motor) yang diambil dari PQA.')),
            self.tabs)
        self.tab_meas = _wrap(_origin(tr('pengukuran PQA'), tr(
            'seluruhnya dari berkas PQA yang diimpor (pengukuran sistem yang '
            'ada); tidak memakai parameter model maupun nilai bawaan.')),
            self.tab_pqa)
        self.tab_mix = _wrap(_origin(tr('simulasi model dan pengukuran PQA'), tr(
            'hasil simulasi tiap sistem disandingkan dengan pengukuran PQA; '
            'sumber data tiap bagian disebut pada judul bagian.')), self.tab_cmp)
        self.top_tabs.addTab(self.tab_mix, tr('Perbandingan Sistem'))
        self.top_tabs.addTab(self.tab_sim, tr('Simulasi (Parameter Standar)'))
        self.top_tabs.addTab(self.tab_meas, tr('Pengukuran (Data PQA)'))

        self._apply_visibility()
        self._show_pqa()
        self._show_basis()
        self._sync_sys()
        state.config_changed.connect(self._refresh_params)
        st = getattr(state, 'transient_result', None)
        if st:
            try:
                self._show(st)
            except Exception:
                pass

    # ------------------------------------------------------------ tabel
    def _mk_table(self):
        """Tabel: lebar kolom dapat DIGESER pengguna (Interactive), teks
        membungkus ke bawah, tinggi baris mengikuti isi setiap kali lebar
        kolom berubah."""
        t = CopyTableWidget(0, 0)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setWordWrap(True)
        t.setTextElideMode(Qt.ElideNone)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        t.verticalHeader().setVisible(False)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(36)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        tm = QTimer(t); tm.setSingleShot(True); tm.setInterval(60)
        tm.timeout.connect(t.resizeRowsToContents)
        hh.sectionResized.connect(lambda *_: tm.start())
        return t

    @staticmethod
    def _fill(tbl, head, rows, status_col=None, widths=None):
        tbl.clear()
        tbl.setColumnCount(len(head)); tbl.setRowCount(len(rows))
        tbl.setHorizontalHeaderLabels([str(h) for h in head])
        for i, r in enumerate(rows):
            for j, v in enumerate(r):
                if isinstance(v, float):
                    txt = f'{v:,.3f}'.rstrip('0').rstrip('.') if v == v else ''
                else:
                    txt = '' if v is None else str(v)
                it = QTableWidgetItem(txt)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignTop)
                else:
                    it.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
                if status_col is not None and j == status_col:
                    it.setForeground(QBrush(QColor(_STATUS_COL.get(txt, '#6B7280'))))
                    f = it.font(); f.setBold(True); it.setFont(f)
                tbl.setItem(i, j, it)
        for j, h in enumerate(head):
            w = (widths or {}).get(str(h), _COL_W.get(str(h), 92))
            tbl.setColumnWidth(j, int(w))
        tbl.resizeRowsToContents()

    # ------------------------------------------------------------ parameter
    def _values(self):
        v = dict(self.state.cfg)
        for g in self.groups:
            v.update(g.values())
        return v

    def _apply_visibility(self):
        v = self._values()
        for g in self.groups:
            g.apply_visibility(v, VISIBILITY)
            f = g.fields.get('tr_load_source')
            if f is not None:               # dengan PQA: hanya statistik PQA
                q = self.state.cfg.get('tr_pqa')
                has = isinstance(q, dict) and 'p_max' in q
                opts = (['PQA — Maximum', 'PQA — 95th Percentile', 'PQA — Mean']
                        if has else ['Manual / Profile Peak'])
                cur = str(self.state.cfg.get('tr_load_source', ''))
                f.set_choices(opts, keep=cur if cur in opts else opts[0])

    def _on_change(self):
        v = {}
        for g in self.groups:
            v.update(g.values())
        self._apply_visibility()
        self.state.update_cfg(v)
        self._show_basis()

    def _refresh_params(self):
        for g in self.groups:
            g.set_values(self.state.cfg)
        self._apply_visibility()
        self._show_pqa()
        self._sync_sys()

    # ------------------------------------------------------ definisi sistem
    def _on_sys_toggle(self, key, k, on):
        if getattr(self, '_sys_busy', False):
            return
        cfg = self.state.cfg
        cur = {kk: [x for x in (cfg.get(kk) or [])] for kk in self._sys_chk}
        if on and k not in cur[key]:
            cur[key].append(k)
            other = 'tr_new' if key == 'tr_existing' else 'tr_existing'
            if k in cur[other]:             # satu pembangkit: existing ATAU baru
                cur[other].remove(k)
        elif not on and k in cur[key]:
            cur[key].remove(k)
        self.state.update_cfg(cur)          # config_changed -> _sync_sys

    def _sync_sys(self):
        from ...engine.transient_cases import (configured_sources, SRC_LABEL,
                                               system_scenarios)
        cfg = self.state.cfg
        self._sys_busy = True
        for key, d in self._sys_chk.items():
            sel = cfg.get(key) or []
            for k, cb in d.items():
                cb.setChecked(k in sel)
        self._sys_busy = False
        try:
            conf = configured_sources(cfg)
        except Exception:
            conf = set()
        sel = set(cfg.get('tr_existing') or []) | set(cfg.get('tr_new') or [])
        sc = system_scenarios(cfg)
        if not sel:
            txt = tr('Tanpa pilihan: seluruh pembangkit yang dikonfigurasi '
                     'dianalisis sebagai satu sistem.')
        else:
            txt = tr('Dianalisis') + ': <b>' + ' · '.join(
                f"{n} ({', '.join(SRC_LABEL[x] for x in SRC_LABEL if x in inc)})"
                for _k, n, inc in sc) + '</b>'
            miss = [SRC_LABEL[x] for x in SRC_LABEL if x in sel and x not in conf]
            if miss:
                txt += ('<br><span style="color:#D97706">'
                        + tr('Belum dikonfigurasi di halaman Parameters '
                             '(diabaikan sampai diberi ukuran)') + ': '
                        + ', '.join(miss) + '</span>')
        self.lbl_sys.setText(txt)

    def _on_sys_view(self, *_):
        if getattr(self, '_sys_view_busy', False):
            return
        st = getattr(self, '_study_all', None)
        if not st:
            return
        from ...engine.transient_cases import scenario_studies
        items = scenario_studies(st)
        i = max(0, min(self.cb_sys.currentIndex(), len(items) - 1))
        self._show_one(items[i][1])

    def _show_basis(self):
        try:
            from ...engine.transient_cases import parameter_basis
            rows = parameter_basis(self._values())
        except Exception:
            rows = []
        self._fill(self.tbl_basis,
                   ['Parameter', 'Value', 'Unit', 'Standard basis of the default'],
                   rows, widths={'Value': 110, 'Unit': 70})

    # ------------------------------------------------------------ PQA
    def _show_pqa(self):
        p = self.state.cfg.get('tr_pqa')
        self._show_pqa_analysis(p if isinstance(p, dict) else None)
        if not isinstance(p, dict):
            self.lbl_pqa.setText(tr(
                'Belum ada data PQA. Tanpa PQA, beban studi memakai nilai '
                'Study Load (atau puncak profil beban).'))
            self.btn_pqa_clr.setEnabled(False)
            return
        self.btn_pqa_clr.setEnabled(True)
        parts = [f"<b>{p.get('source', '')}</b> — {p.get('n', 0):,} "
                 + tr('sampel')
                 + (f" @ {p['dt_s']:g} s" if p.get('dt_s') else '')]
        if 'p_max' in p:
            parts.append(f"P: max {p['p_max']:,.0f} · P95 {p['p_p95']:,.0f} · "
                         f"mean {p['p_mean']:,.0f} · min {p['p_min']:,.0f} kW")
        else:
            parts.append(tr('P_sum_AVG tidak tersedia — beban studi tidak '
                            'diambil dari PQA'))
        if p.get('pf'):
            parts.append(f"PF {p['pf']:.3f}")
        if 'step_up_kw' in p:
            parts.append(tr('step terbesar') + f": +{p['step_up_kw']:,.0f} / "
                         f"{p['step_dn_kw']:,.0f} kW")
        if 'f_min' in p:
            parts.append(f"f {p['f_min']:.2f}–{p['f_max']:.2f} Hz")
        if 'v_min' in p:
            parts.append(f"V {p['v_min']:,.1f}–{p['v_max']:,.1f}")
        an = p.get('analysis') or []
        if an:
            done = sum(1 for a in an if a['status'] != 'skipped')
            parts.append(tr('analisis PQA: {d} dari {n} dijalankan').format(
                d=done, n=len(an)))
        self.lbl_pqa.setText(' · '.join(parts))

    def _show_pqa_analysis(self, p):
        """Tab 'Analisis PQA': status tiap analisis, tabel hasil, grafik."""
        from ...data.pqa import analysis_rows
        an = (p or {}).get('analysis') or []
        self.cb_pqa.blockSignals(True)
        self.cb_pqa.clear()
        if not an:
            self.lbl_pqa_an.setText(tr(
                'Belum ada analisis PQA. Impor data PQA dengan kolom sesuai '
                'Template PQA (panel kiri) untuk menjalankan: Half-Cycle '
                'Transient & Sag/Swell, Frequency Stability & RoCoF, Load '
                'Flow & P/Q Profiling, Voltage & Current Unbalance, THD & '
                'Dominant Harmonics.'))
            self._fill(self.tbl_pqa, ['Analysis', 'Item', 'Value', 'Unit',
                                      'Reference / limit', 'Result'], [])
            self.plot_pqa.clear()
            self._pqa_curves = []
            self._pqa_cursor_off()
            self.cb_pqa.blockSignals(False)
            return
        col = {'done': '#16A34A', 'partial': '#D97706', 'skipped': '#6B7280'}
        lab = {'done': tr('dijalankan'), 'partial': tr('sebagian'),
               'skipped': tr('dilewati')}
        bits = []
        for a in an:
            t = (f'<span style="color:{col[a["status"]]}">&#9679;</span> '
                 f'<b>{a["title"]}</b>: {lab[a["status"]]}')
            if a['missing']:
                t += (' <span style="color:#8A94A0">('
                      + tr('kolom tidak tersedia') + ': '
                      + ', '.join(a['missing']) + ')</span>')
            bits.append(t)
        self.lbl_pqa_an.setText(
            f"<b>{p.get('source', '')}</b> — {p.get('n', 0):,} " + tr('sampel')
            + (f" @ {p['dt_s']:g} s" if p.get('dt_s') else '')
            + (f" · {p['t_start']} … {p['t_end']}" if p.get('t_start') else '')
            + '<br>' + '<br>'.join(bits))
        self._fill(self.tbl_pqa, ['Analysis', 'Item', 'Value', 'Unit',
                                  'Reference / limit', 'Result'],
                   analysis_rows(p), status_col=5,
                   widths={'Analysis': 150, 'Item': 270, 'Value': 180,
                           'Unit': 64, 'Reference / limit': 290, 'Result': 64})
        ser = p.get('series') or {}
        for a in an:
            if a['id'] in ser:
                self.cb_pqa.addItem(a['title'], a['id'])
        self.cb_pqa.blockSignals(False)
        self._plot_pqa()
        if self._pqa_fs:
            self._plot_pqa_fs()

    # ------------------------- v182: Analisis PQA layar penuh — multi-grafik
    def _pqa_available(self):
        """[(id, judul)] grafik analisis yang tersedia (urutan combo)."""
        return [(self.cb_pqa.itemData(i), self.cb_pqa.itemText(i))
                for i in range(self.cb_pqa.count())]

    def _pqa_selected(self):
        avail = [k for k, _t in self._pqa_available()]
        sel = self.state.cfg.get('tr_pqa_fs_charts')
        if not isinstance(sel, (list, tuple)):
            return avail                      # bawaan: semua grafik
        out = [k for k in avail if k in sel]
        return out or avail[:1]

    def _rebuild_pqa_sel_menu(self):
        avail = self._pqa_available()
        sel = set(self._pqa_selected())
        menu = QMenu(self.btn_pqa_sel)
        a_all = menu.addAction(tr('Tampilkan semua'))
        a_all.triggered.connect(lambda: self._set_pqa_sel([k for k, _t in avail]))
        menu.addSeparator()
        cont = QWidget(); v = QVBoxLayout(cont)
        v.setContentsMargins(8, 4, 8, 6); v.setSpacing(2)
        self._pqa_sel_boxes = {}
        for k, t in avail:
            cb = QCheckBox(t); cb.setChecked(k in sel)
            cb.toggled.connect(lambda on_, kk=k: self._on_pqa_sel_box(kk, on_))
            v.addWidget(cb)
            self._pqa_sel_boxes[k] = cb
        wa = QWidgetAction(menu); wa.setDefaultWidget(cont); menu.addAction(wa)
        self.btn_pqa_sel.setMenu(menu)
        self.btn_pqa_sel.setText(tr('{n} dari {N} grafik').format(
            n=len(sel), N=len(avail)) + '  ▾')

    def _on_pqa_sel_box(self, k, on):
        cur = [kk for kk, cb in self._pqa_sel_boxes.items() if cb.isChecked()]
        if not cur:                          # minimal satu grafik
            cb = self._pqa_sel_boxes[k]
            cb.blockSignals(True); cb.setChecked(True); cb.blockSignals(False)
            return
        self._set_pqa_sel(cur, rebuild_menu=False)

    def _set_pqa_sel(self, keys, rebuild_menu=True):
        self.state.cfg['tr_pqa_fs_charts'] = list(keys)
        if rebuild_menu:
            for k, cb in getattr(self, '_pqa_sel_boxes', {}).items():
                cb.blockSignals(True); cb.setChecked(k in keys); cb.blockSignals(False)
        avail = self._pqa_available()
        self.btn_pqa_sel.setText(tr('{n} dari {N} grafik').format(
            n=len(keys), N=len(avail)) + '  ▾')
        self._plot_pqa_fs()

    def _pqa_full(self, on):
        self._pqa_fs = bool(on)
        self.cb_pqa.setVisible(not on)
        self._pqa_sel_wrap.setVisible(on)
        self._fs_pqa.setVisible(on)
        self.plot_pqa.setVisible(not on)
        self.glw_pqa.setVisible(on)
        if on:
            self._rebuild_pqa_sel_menu()
            self._plot_pqa_fs()
        else:
            self._pqa_arr.detach()
            self._pqa_fs_plots, self._pqa_fs_curves, self._pqa_fs_cur = [], [], []
            self._plot_pqa()                 # legenda kembali ke grafik tunggal
        self._pqa_cursor_off()

    def _on_pqa_grid(self, rects):
        g = dict(self._pqa_grid); g.update(rects)
        self._pqa_grid = g
        self.state.cfg['tr_fs_grid_pqa'] = dict(g)

    def _reset_pqa_layout(self):
        self._pqa_grid = {}
        self.state.cfg['tr_fs_grid_pqa'] = {}
        self._plot_pqa_fs()

    def _plot_pqa_fs(self):
        """Layar penuh: grafik-grafik analisis PQA terpilih, masing-masing
        satu panel pada grid bebas (pindah: seret judul; ukuran: seret
        sudut/tepi kanan-bawah). Sumbu waktu disamakan antar panel."""
        if not self._pqa_fs:
            return
        from ..theme import _style_plotitem, TOKENS
        from .. import theme as _th
        self._pqa_arr.detach()
        self._pqa_fs_plots, self._pqa_fs_curves, self._pqa_fs_cur = [], [], []
        self._pqa_items = []
        p = self.state.cfg.get('tr_pqa')
        ser = ((p or {}).get('series') or {}) if isinstance(p, dict) else {}
        titles = dict(self._pqa_available())
        keys = [k for k in self._pqa_selected() if ser.get(k)]
        xlab = (tr('Waktu (jam sejak awal rekaman)')
                if (p or {}).get('t_unit') == 'h' else tr('Sampel'))
        legend, plots = [], []
        tok = TOKENS['dark' if _th.CURRENT_DARK else 'light']
        for k in keys:
            s = ser[k]
            pl = pg.PlotItem()
            pl.showGrid(x=True, y=True, alpha=0.2)
            pl.setTitle('⠿ ' + titles.get(k, k), size='9pt')
            pl.setLabel('left', s.get('ylabel', ''))
            pl.setLabel('bottom', xlab)
            pl.getAxis('left').setWidth(64)
            t = np.asarray(s['t'], float)
            legend.append((None, titles.get(k, k) + ':', '', False))
            for i, (name, y) in enumerate(s['y'].items()):
                yy = np.asarray([np.nan if v is None else v for v in y], float)
                col = _PAL[i % len(_PAL)]
                it = pl.plot(t, yy, pen=pg.mkPen(col, width=1.3), connect='finite')
                key = f'pqafs:{k}:{name}'
                self._pqa_fs_curves.append((pl, t, yy, name, col, it))
                self._pqa_items.append((key, it))
                legend.append((key, name, col, False))
            hl = s.get('hlines') or []
            for h in hl:
                ln = pg.InfiniteLine(pos=float(h), angle=0, movable=False,
                                     pen=pg.mkPen('#DC2626', width=1,
                                                  style=Qt.DashLine))
                pl.addItem(ln)
                self._pqa_items.append((f'pqafs:{k}:limit', ln))
            if hl:
                legend.append((f'pqafs:{k}:limit', tr('Batas acuan'),
                               '#DC2626', True))
            vl = pg.InfiniteLine(angle=90, movable=False,
                                 pen=pg.mkPen('#9CA3AF', width=1))
            vl.setZValue(50); vl.setVisible(False)
            pl.addItem(vl, ignoreBounds=True)
            dots = pg.ScatterPlotItem(size=8, pen=pg.mkPen('#111827', width=1))
            dots.setZValue(60)
            pl.addItem(dots, ignoreBounds=True)
            self._pqa_fs_cur.append((pl, vl, dots))
            try:
                _style_plotitem(pl, tok)
            except Exception:
                pass
            plots.append((k, pl))
        self._pqa_fs_plots = plots
        self.leg_pqa.set_items(legend)
        for k_ in list(getattr(self, '_pqa_hidden', set())):
            b_ = self.leg_pqa._btn.get(k_)
            if b_ is not None and b_.isChecked():
                b_.setChecked(False)
        if not plots:
            self._pqa_cursor_off()
            return
        rect_zoom([pl for _k, pl in plots])
        link_x([pl for _k, pl in plots])
        C = int(getattr(self, '_fs_cols', 2))
        n = len(plots)
        slots = {k: (i // C, i % C, (C - i % C) if i == n - 1 else 1)
                 for i, (k, _pl) in enumerate(plots)}
        pre = GridArranger.preset(slots, C, 6 if C == 1 else 7)
        rects = GridArranger.merge([k for k, _pl in plots], self._pqa_grid, pre)
        self._pqa_arr.place(plots, rects, fit=getattr(self, '_fs_fit', False))
        self.glw_pqa.setBackground(tok['plot_bg'])
        self._pqa_cursor_off()

    def _on_pqa_fs_mouse(self, evt):
        pos = evt[0]
        hit = next((c for c in self._pqa_fs_cur
                    if c[0].vb.sceneBoundingRect().contains(pos)), None)
        if hit is None:
            self._pqa_cursor_off()
            return
        pl = hit[0]
        curves = [c for c in self._pqa_fs_curves if c[0] is pl]
        if not curves or curves[0][1].size == 0:
            return
        x = pl.vb.mapSceneToView(pos).x()
        t = curves[0][1]
        i = int(np.clip(np.searchsorted(t, x), 0, t.size - 1))
        if i > 0 and abs(t[i - 1] - x) < abs(t[i] - x):
            i -= 1
        xi = float(t[i])
        head = self._pqa_time_head(xi)
        title = next((tt for k, tt in self._pqa_available()
                      if dict(self._pqa_fs_plots).get(k) is pl), '')
        txt, spots = [f'<b>{head}</b> · {title}'], []
        for _pl, _t, y, label, color, item in curves:
            if not item.isVisible() or i >= y.size or not np.isfinite(y[i]):
                continue
            v = float(y[i])
            spots.append({'pos': (xi, v), 'brush': pg.mkBrush(color)})
            txt.append(f"<span style='color:{color}'>●</span> {label} "
                       + (f'{v:,.3f}' if abs(v) < 100 else f'{v:,.1f}'))
        for p_, vl, dots in self._pqa_fs_cur:   # garis waktu di semua panel
            vl.setPos(xi); vl.setVisible(True)
            dots.setData(spots if p_ is pl else [])
        self.lbl_pqa_cur.setText(' &nbsp; '.join(txt))

    def _pqa_time_head(self, xi):
        p = self.state.cfg.get('tr_pqa') or {}
        if p.get('t_unit') == 'h':
            head = f'{xi:,.2f} h'
            try:
                import pandas as pd
                head = (str(pd.Timestamp(p['t_start'])
                            + pd.Timedelta(hours=xi))[:19] + f' ({head})')
            except Exception:
                pass
            return head
        return tr('Sampel') + f' {xi:,.0f}'

    def _plot_pqa(self):
        if getattr(self, '_pqa_fs', False):
            return                      # layar penuh: _plot_pqa_fs
        self.plot_pqa.clear()
        self._pqa_curves = []
        self._pqa_items = []
        self.leg_pqa.set_items([])
        self.plot_pqa.addItem(self._pqa_vline, ignoreBounds=True)
        self.plot_pqa.addItem(self._pqa_dots, ignoreBounds=True)
        self._pqa_cursor_off()
        p = self.state.cfg.get('tr_pqa')
        key = self.cb_pqa.currentData()
        s = ((p or {}).get('series') or {}).get(key) if isinstance(p, dict) else None
        if not s:
            return
        t = np.asarray(s['t'], float)
        legend = []
        for i, (name, y) in enumerate(s['y'].items()):
            yy = np.asarray([np.nan if v is None else v for v in y], float)
            col = _PAL[i % len(_PAL)]
            it = self.plot_pqa.plot(t, yy, pen=pg.mkPen(col, width=1.3),
                                    connect='finite')
            self._pqa_curves.append((t, yy, name, col, it))
            self._pqa_items.append(('pqa:' + name, it))
            legend.append(('pqa:' + name, name, col, False))
        hl = s.get('hlines') or []
        for h in hl:
            ln = pg.InfiniteLine(pos=float(h), angle=0, movable=False,
                                 pen=pg.mkPen('#DC2626', width=1, style=Qt.DashLine))
            self.plot_pqa.addItem(ln)
            self._pqa_items.append(('pqa:limit', ln))
        if hl:
            legend.append(('pqa:limit', tr('Batas acuan'), '#DC2626', True))
        self.leg_pqa.set_items(legend)
        for k in list(getattr(self, '_pqa_hidden', set())):
            b_ = self.leg_pqa._btn.get(k)
            if b_ is not None and b_.isChecked():
                b_.setChecked(False)
        self.plot_pqa.setLabel('left', s.get('ylabel', ''))
        self.plot_pqa.setLabel('bottom', tr('Waktu (jam sejak awal rekaman)')
                               if (p or {}).get('t_unit') == 'h'
                               else tr('Sampel'))
        self.plot_pqa.enableAutoRange()

    def _export_pqa(self):
        p = self.state.cfg.get('tr_pqa')
        if not isinstance(p, dict) or not p.get('analysis'):
            QMessageBox.information(self, tr('Analisis PQA'),
                                    tr('Impor data PQA terlebih dahulu.'))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Simpan'), 'PQA_Analysis.xlsx', 'Excel (*.xlsx)')
        if not path:
            return
        try:
            from ...reports.transient_report import export_pqa_xlsx
            export_pqa_xlsx(path, p)
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))
            return
        QMessageBox.information(self, tr('Sukses'), tr('Tersimpan:') + f'\n{path}')

    def _pqa_template(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr('Template PQA…'), 'pqa_template.xlsx', 'Excel (*.xlsx)')
        if not path:
            return
        try:
            from ...data.pqa import write_template
            write_template(path)
        except Exception as e:
            QMessageBox.warning(self, tr('Gagal'), str(e))
            return
        QMessageBox.information(
            self, tr('Template PQA…'),
            tr('Template tersimpan di\n{path}').format(path=path))

    def _import_pqa(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr('Impor Data PQA…'), '', 'Data (*.xlsx *.xlsm *.xls *.csv *.txt)')
        if not path:
            return
        try:
            from ...data.pqa import read_pqa_file
            p = read_pqa_file(path)
        except Exception as e:
            QMessageBox.warning(self, tr('Import gagal'), str(e))
            return
        self._apply_pqa(p)

    def _apply_pqa(self, p):
        upd = {'tr_pqa': p}
        src = str(self.state.cfg.get('tr_load_source', ''))
        if 'p_max' in p:
            if not src.startswith('PQA'):
                upd['tr_load_source'] = 'PQA — Maximum'
        elif src.startswith('PQA'):
            upd['tr_load_source'] = 'Manual / Profile Peak'
        self.state.update_cfg(upd)
        self._refresh_params()
        self._show_basis()
        an = p.get('analysis') or []
        if an:
            self.top_tabs.setCurrentWidget(self.tab_meas)
            skipped = [a for a in an if a['status'] == 'skipped']
            if skipped:
                QMessageBox.information(
                    self, tr('Impor Data PQA…'),
                    tr('Analisis berikut tidak dijalankan karena kolomnya '
                       'tidak tersedia:') + '\n\n' + '\n'.join(
                        f"• {a['title']}  ({', '.join(a['missing'][:6])}"
                        + ('…' if len(a['missing']) > 6 else '') + ')'
                        for a in skipped))

    def _clear_pqa(self):
        self.state.update_cfg({'tr_pqa': None,
                               'tr_load_source': 'Manual / Profile Peak'})
        self._refresh_params()

    # ------------------------------------------------------------ run
    def _run(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.btn_run.setEnabled(False)
        self.bar.setValue(0); self.bar.setVisible(True)
        w = _StudyWorker(self.state)
        w.progress.connect(self.bar.setValue)
        w.finished_ok.connect(self._done)
        w.failed.connect(self._failed)
        self._worker = w
        w.start()

    def _failed(self, msg):
        self.btn_run.setEnabled(True); self.bar.setVisible(False)
        QMessageBox.critical(self, tr('Transient Analysis'), str(msg)[:1500])

    def _done(self, study):
        self.btn_run.setEnabled(True); self.bar.setVisible(False)
        self.state.transient_result = study
        self._show(study)

    # ------------------------------------------------------------ tampil
    def _show(self, study):
        """Tampilkan hasil run_scenarios: pemilih sistem, tab perbandingan,
        lalu rincian sistem utama."""
        from ...engine.transient_cases import scenario_studies
        self._study_all = study
        items = scenario_studies(study)
        self._sys_view_busy = True
        self.cb_sys.clear()
        for n, _s in items:
            self.cb_sys.addItem(n)
        pi = next((i for i, (_n, s) in enumerate(items) if s is study), 0)
        self.cb_sys.setCurrentIndex(pi)
        self._sys_view_busy = False
        self.lbl_sys_view.setText(' · '.join(
            f"{n}: " + (tr('tidak dianalisis') if s.get('not_viable') else
                        f"{sum(c['status'] == 'Pass' for c in s['cases'])}/"
                        f"{len(s['cases'])} " + tr('lulus'))
            for n, s in items))
        cmp_ = study.get('comparison')
        if cmp_:
            self.lbl_cmp.setText(_section(
                1, tr('Perbandingan sistem'), tr('simulasi model'), tr(
                    'Pilih "Sistem yang ditampilkan" di atas untuk melihat '
                    'kasus, hubung singkat, dan persyaratan tiap sistem.')))
            self._fill(self.tbl_cmp, cmp_['head'], cmp_['rows'],
                       widths={'Item': 250, **{h: 300 for h in cmp_['head'][1:]}})
        asm = study.get('assessment')
        if asm:
            self.lbl_asm.setText(_section(
                2, tr('Penilaian terhadap data PQA'),
                tr('hasil simulasi dibandingkan dengan pengukuran PQA')
                + f" ({asm.get('source', '')})", asm.get('note', '')))
            self._fill(self.tbl_asm, asm['head'], asm['rows'],
                       widths={'Item': 170, 'PQA columns used': 170,
                               'Measured': 200, 'Criterion': 220,
                               **{h: 280 for h in asm['head'][3:-1]}})
        else:
            self.lbl_asm.setText(_section(
                2, tr('Penilaian terhadap data PQA'),
                tr('hasil simulasi dibandingkan dengan pengukuran PQA'),
                tr('Impor data PQA (panel kiri) lalu jalankan studi.')))
            self._fill(self.tbl_asm, ['Item'], [])
        self._fill_cmp_cases(items)
        self._show_one(study)

    def _fs_controls(self, on_change, on_reset=None):
        """Pilihan tata letak layar penuh: jumlah kolom (1/2/3) dan
        'Gulir' / 'Muat 1 layar'. Kecil; hanya tampil saat layar penuh.
        v180: tombol 'Atur ulang tata letak' (posisi panel hasil seret)."""
        w = QWidget(); h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        cb_c = QComboBox()
        for n in (1, 2, 3):
            cb_c.addItem(f'{n} ' + tr('kolom'), n)
        cb_c.setCurrentIndex(int(getattr(self, '_fs_cols', 2)) - 1)
        cb_c.setToolTip(tr('Jumlah kolom grafik pada layar penuh — memilih '
                           'ulang menyusun panel ke pola bawaan kolom ini'))
        cb_f = QComboBox()
        cb_f.addItem(tr('Gulir'), False)
        cb_f.addItem(tr('Muat 1 layar'), True)
        cb_f.setCurrentIndex(1 if getattr(self, '_fs_fit', False) else 0)
        cb_f.setToolTip(tr('Gulir: panel berukuran tetap, halaman dapat '
                           'digulir vertikal. Muat 1 layar: semua panel '
                           'dipadatkan dalam satu layar.'))
        for cb in (cb_c, cb_f):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            h.addWidget(cb)

        def changed(*_):
            if int(cb_c.currentData()) != int(getattr(self, '_fs_cols', 2)):
                # v181: jumlah kolom = pola bawaan -> susun ulang semua panel
                self._case_grid, self._cmp_grid = {}, {}
                self._pqa_grid = {}
                self.state.cfg['tr_fs_grid_case'] = {}
                self.state.cfg['tr_fs_grid_cmp'] = {}
                self.state.cfg['tr_fs_grid_pqa'] = {}
            self._fs_cols = int(cb_c.currentData())
            self._fs_fit = bool(cb_f.currentData())
            self.state.cfg['tr_fs_cols'] = self._fs_cols    # diingat proyek
            self.state.cfg['tr_fs_fit'] = self._fs_fit
            for other in getattr(self, '_fs_widgets', []):  # samakan semua
                if other is not w:
                    a_, b_ = other._cbs
                    for cb_, v_ in ((a_, self._fs_cols - 1),
                                    (b_, 1 if self._fs_fit else 0)):
                        cb_.blockSignals(True); cb_.setCurrentIndex(v_)
                        cb_.blockSignals(False)
            on_change()
        cb_c.currentIndexChanged.connect(changed)
        cb_f.currentIndexChanged.connect(changed)
        if on_reset is not None:
            b_r = QPushButton('↺ ' + tr('Tata letak awal'))
            b_r.setProperty('flat', True)
            b_r.setToolTip(tr('Kembalikan posisi & ukuran panel ke pola bawaan '
                              '(seret judul panel untuk memindah; seret sudut/tepi '
                              'kanan-bawah untuk mengubah ukuran)'))
            b_r.clicked.connect(on_reset)
            h.addWidget(b_r)
            w._reset = b_r
        w._cbs = (cb_c, cb_f)
        w.setVisible(False)
        self._fs_widgets = getattr(self, '_fs_widgets', []) + [w]
        return w

    def _layout_case(self, two: bool):
        """Susun 4 panel grafik Kasus: 1 kolom (halaman) atau GRID bebas
        (layar penuh, v181 — posisi & ukuran tiap panel diatur pengguna).
        Panel yang sama dipindahkan — kursor & zoom tetap."""
        self._case_fs = bool(two)
        ci = self.glw.ci
        for p in self._plots:
            if p in ci.items:
                ci.removeItem(p)
        names = dict(zip(self._plots, (tr('Frekuensi (Hz)'),
                                       tr('Tegangan bus (pu)'),
                                       tr('Daya aktif (kW)'),
                                       tr('Daya reaktif (kvar)'))))
        for p in self._plots:
            show = two or p is self.p_q
            p.setLabel('bottom', tr('Waktu (s)') if show else '')
            p.getAxis('bottom').showLabel(show)
            # judul panel = pegangan seret (hanya layar penuh)
            p.setTitle(('⠿ ' + names[p]) if two else None, size='9pt')
        self.lbl_cur.setText(_hint(two))
        if two:
            C = int(getattr(self, '_fs_cols', 2))
            n = len(self._plots)
            slots = {k: (i // C, i % C, (C - i % C) if i == n - 1 else 1)
                     for i, k in enumerate(_CASE_KEYS)}
            pre = GridArranger.preset(slots, C, 5 if C == 1 else 8)
            rects = GridArranger.merge(_CASE_KEYS, self._case_grid, pre)
            self._case_arr.place(list(zip(_CASE_KEYS, self._plots)), rects,
                                 fit=getattr(self, '_fs_fit', False))
        else:
            self._case_arr.detach()
            for i, p in enumerate(self._plots):
                ci.addItem(p, row=i, col=0, rowspan=1, colspan=1)
            self.glw.setMinimumHeight(560)
        style_layout(self.glw)

    # ----------------------------- v181: tata letak grid bebas layar penuh
    def _on_case_grid(self, rects):
        self._case_grid = dict(rects)
        self.state.cfg['tr_fs_grid_case'] = dict(rects)    # diingat proyek

    def _reset_case_layout(self):
        self._case_grid = {}
        self.state.cfg['tr_fs_grid_case'] = {}
        self._layout_case(getattr(self, '_case_fs', False))

    def _on_cmp_grid(self, rects):
        # gabung: kunci panel yang tak tampil pada kasus ini tetap diingat
        g = dict(self._cmp_grid); g.update(rects)
        self._cmp_grid = g
        self.state.cfg['tr_fs_grid_cmp'] = dict(g)

    def _reset_cmp_layout(self):
        self._cmp_grid = {}
        self.state.cfg['tr_fs_grid_cmp'] = {}
        self._plot_cmp_case()

    # ------------------------------------------- grafik perbandingan kasus
    def _fill_cmp_cases(self, items):
        """Daftar kasus (gabungan ID seluruh sistem) untuk grafik
        perbandingan. ID kasus sama di tiap sistem untuk kejadian yang sama."""
        self._cmp_items = items
        seen, order = {}, []
        for n, s in items:
            for c in s['cases']:
                if 't' not in (c.get('series') or {}):
                    continue
                if c['id'] not in seen:
                    seen[c['id']] = [c['title'], []]
                    order.append(c['id'])
                seen[c['id']][1].append(n)
        order.sort(key=lambda i: (i[0], int(i[1:]) if i[1:].isdigit() else 0))
        self.cb_cmp_case.blockSignals(True)
        self.cb_cmp_case.clear()
        for cid in order:
            title, names = seen[cid]
            self.cb_cmp_case.addItem(
                f"{cid} — {_name(title)}   [{' · '.join(names)}]", cid)
        self.cb_cmp_case.blockSignals(False)
        self._plot_cmp_case()

    def _plot_cmp_case(self):
        from ...reports.transient_report import _num
        from ...engine.transient_cases import pqa_event_for
        self._cmp_arr.detach()               # panel grid lama (layar penuh)
        self.glw_cmp.clear()
        self._cmp_keyed, self._cmp_slot = [], {}
        self._cmp_plots, self._cmp_curves = [], []
        self._cmp_vlines, self._cmp_dots = [], []
        self._cmp_grp = {}
        self._cmp_cursor_off()
        cid = self.cb_cmp_case.currentData()
        items = getattr(self, '_cmp_items', None) or []
        found = []
        for n, s in items:
            c = next((c for c in s['cases'] if c['id'] == cid
                      and 't' in (c.get('series') or {})), None)
            if c is not None:
                found.append((n, c))
        if not found:
            self._fill(self.tbl_cmp_case, ['System'], [])
            self.lbl_cmp_pqa.setText('')
            self.leg_cmp.set_items([])
            return
        ev, ev_key, ev_why = pqa_event_for(found[0][1], self.state.cfg.get('tr_pqa'))
        # ---- tabel metrik kasus per sistem (+ baris pengukuran PQA) ----
        mcols = [('f_min', 'f min (Hz)', 2), ('f_max', 'f max (Hz)', 2),
                 ('f_end', 'f end (Hz)', 2), ('rocof', 'RoCoF (Hz/s)', 2),
                 ('v_min', 'V min (pu)', 3), ('v_end', 'V end (pu)', 3),
                 ('pcs_ipk', 'PCS peak (pu)', 2), ('q_peak_kvar', 'Q peak (kvar)', 0)]
        from ...engine.transient_cases import case_evidence
        crit_of = {n_: s_.get('crit') or {} for n_, s_ in items}
        rows = [[n, tr('Simulasi'), _name(c['title']), _name(c['scenario']),
                 c['status']]
                + [_num(c['metrics'].get(k), d) for k, _h, d in mcols]
                + [_name(case_evidence(c, crit_of.get(n, {}))[1])]
                for n, c in found]

        def _rng(key, fn):
            v = [x for x in (ev['series'].get(key) or []) if x is not None]
            return fn(v) if v else None
        if ev:
            lo = _rng('f min (Hz)', min)
            lo = lo if lo is not None else _rng('f avg (Hz)', min)
            hi = _rng('f max (Hz)', max)
            hi = hi if hi is not None else _rng('f avg (Hz)', max)
            pk = ev['series'].get('P (kW)') or []
            pk = [x for x in pk if x is not None]
            rows.append(
                ['PQA', tr('Pengukuran'), ev['label'],
                 f"{ev['t_from']} … {ev['t_to']}", 'Ref',
                 _num(lo, 2), _num(hi, 2), '', '', _num(_rng('U min (pu)', min), 3),
                 '', '', '',
                 (f"P {min(pk):,.0f}–{max(pk):,.0f} kW; " if pk else '')
                 + tr('kejadian pada') + f" {ev['at']}"])
        self._fill(self.tbl_cmp_case,
                   ['System', 'Data', 'Case / event',
                    'Pre-event operating point / window', 'Result']
                   + [h for _k, h, _d in mcols] + ['Basis of the result'], rows,
                   status_col=4, widths={'System': 110, 'Data': 90,
                                         'Case / event': 230,
                                         'Pre-event operating point / window': 250,
                                         'Basis of the result': 440})
        if ev:
            step = ev.get('dt_s')
            self.lbl_cmp_pqa.setText(
                f'<span style="color:{_MUTED};">' + tr('Cuplikan PQA')
                + ':</span> <b>' + ev['label'] + '</b> — ' + tr('kejadian pada') + f" <b>{ev['at']}</b>; "
                + tr('jendela cuplikan') + f" <b>{ev['t_from']} … {ev['t_to']}</b>"
                + (f" ({len(ev['t'])} " + tr('rekaman') + f" @ {step:g} s)"
                   if step else '') + '. ' + tr('Kaitan dengan kasus') + ': '
                + ev_why + '. ' + tr(
                    'Pengukuran berinterval jauh lebih kasar daripada simulasi '
                    '(detik vs milidetik), sehingga sumbu waktunya terpisah.'))
        elif isinstance(self.state.cfg.get('tr_pqa'), dict):
            self.lbl_cmp_pqa.setText(tr(
                'Cuplikan PQA tidak tersedia — impor ulang data PQA agar '
                'jendela kejadian ikut tersimpan.'))
        else:
            self.lbl_cmp_pqa.setText(tr(
                'Tanpa data PQA: hanya hasil simulasi yang ditampilkan.'))
        # ---- grafik: f & V ditumpuk antar-sistem; P & Q per sistem;
        #      baris terakhir = cuplikan PQA ----
        ncol = len(found)
        syscol = {'Existing': '#9CA3AF', 'New': '#2563EB',
                  'Existing + New': '#DC2626'}
        srccol = {}
        legend = []            # (key, label, color, dashed)
        seen = set()

        def leg(key, label, color, dashed=False):
            if key is None:                       # judul kelompok
                legend.append((None, label, color, dashed))
            elif key not in seen:
                seen.add(key)
                legend.append((key, label, color, dashed))

        def scol(name):
            if name not in srccol:
                srccol[name] = _PAL[len(srccol) % len(_PAL)]
            return srccol[name]

        def mk(layout, row, col, colspan, label, title=None, grp='sim',
               key=None):
            p = layout.addPlot(row=row, col=col, colspan=colspan)
            p.showGrid(x=True, y=True, alpha=0.2)
            p.setLabel('left', label)
            p.getAxis('left').setWidth(64)
            p.getAxis('left').enableAutoSIPrefix(False)
            if fs:                      # v180: judul = pegangan seret
                title = '⠿ ' + (title or label)
            if title:
                p.setTitle(title, size='9pt')
            self._cmp_plots.append(p)
            self._cmp_grp[id(p)] = grp
            if key is not None:
                self._cmp_keyed.append((key, p))
                self._cmp_slot[key] = (layout, row, col, colspan)
            return p
        G = self.glw_cmp
        # Tata letak: halaman = sistem berdampingan (seperti sebelumnya);
        # layar penuh = grid C kolom pilihan pengguna (1/2/3), tiap kelompok
        # panel mulai di baris baru.
        fs = bool(getattr(self, '_cmp_fs', False))
        C = int(getattr(self, '_fs_cols', 2)) if fs else None
        has_i = any('i_BESS' in c['series'] and np.any(np.abs(np.asarray(
            c['series']['i_BESS'], float)) > 1e-6) for _n, c in found)
        self._cmp_pq = {'kW': [], 'kvar': []}
        all_ttl = tr('Simulasi') + ' — ' + tr('semua sistem')
        top = [(tr('Frekuensi (Hz)'), 'f'), (tr('Tegangan bus (pu)'), 'v')]
        if has_i:
            top.append((tr('Arus PCS (pu)'), 'i'))
        tp = {}
        if not fs:
            for r_, (lab, k) in enumerate(top):
                tp[k] = mk(G, r_, 0, ncol, lab, all_ttl if r_ == 0 else None)
            row = len(top)
        else:
            fit = bool(getattr(self, '_fs_fit', False))
            for jj, (lab, k) in enumerate(top):
                rr, cc = divmod(jj, C)
                # panel terakhir kelompok mengisi sisa kolom (tanpa celah)
                span = C - cc if jj == len(top) - 1 else 1
                tp[k] = mk(G, rr, cc, span, lab, all_ttl if rr == 0 else None,
                           key=k)
                if not fit:                 # 'Muat 1 layar': hemat tempat
                    tp[k].setLabel('bottom', tr('Waktu (s)'))
            row = -(-len(top) // C)
        p_f, p_v, p_i = tp['f'], tp['v'], tp.get('i')
        # posisi panel P / Q tiap sistem
        if not fs or (C > 1 and C >= ncol):
            sys_pos = [((row, j), (row + 1, j)) for j in range(ncol)]
            sys_rows = 2
            q_title = False                 # judul cukup di panel P
        elif C > 1:
            sys_pos = [((row + j, 0), (row + j, 1)) for j in range(ncol)]
            sys_rows = ncol
            q_title = True
        else:
            sys_pos = [((row + 2 * j, 0), (row + 2 * j + 1, 0))
                       for j in range(ncol)]
            sys_rows = 2 * ncol
            q_title = False

        def add(plot, t_, y, key, label, color, unit, sysname, width=1.5,
                dash=False, grp='sim'):
            pen = pg.mkPen(color, width=width,
                           style=Qt.DashLine if dash else Qt.SolidLine)
            it = plot.plot(t_, y, pen=pen, connect='finite')
            self._cmp_curves.append(dict(plot=plot, t=t_, y=y, label=label,
                                         color=color, unit=unit, sys=sysname,
                                         key=key, item=it, grp=grp))
        leg(None, tr('Sistem') + ':', '', False)
        for j, (n, c) in enumerate(found):
            leg('sys:' + n, n, syscol.get(n, _PAL[j % len(_PAL)]))
        src_names = []
        for j, (n, c) in enumerate(found):
            s = c['series']
            t_ = np.asarray(s['t'], float)
            col = syscol.get(n, _PAL[j % len(_PAL)])
            add(p_f, t_, np.asarray(s['f'], float), 'sys:' + n, n, col, 'Hz', n, 1.7)
            add(p_v, t_, np.asarray(s['v'], float), 'sys:' + n, n, col, 'pu', n, 1.7)
            if p_i is not None and 'i_BESS' in s and np.any(
                    np.abs(np.asarray(s['i_BESS'], float)) > 1e-6):
                add(p_i, t_, np.asarray(s['i_BESS'], float), 'sys:' + n, n, col,
                    'pu PCS', n, 1.5)
            ttl = tr('Simulasi') + f" — {n} — {c['status']}"
            (rp, cp), (rq, cq) = sys_pos[j]
            pp = mk(G, rp, cp, 1, tr('Daya aktif (kW)'), ttl, key='P:' + n)
            pq_ = mk(G, rq, cq, 1, tr('Daya reaktif (kvar)'),
                     ttl if q_title or fs else None, key='Q:' + n)
            if fs and not getattr(self, '_fs_fit', False):
                pp.setLabel('bottom', tr('Waktu (s)'))
            self._cmp_pq['kW'].append(pp); self._cmp_pq['kvar'].append(pq_)
            for k in s:
                if k.startswith(('p_', 'q_')) and k not in ('p_load', 'q_load'):
                    nm = k[2:]
                    if nm not in src_names:
                        src_names.append(nm)
                    add(pp if k[0] == 'p' else pq_, t_, np.asarray(s[k], float),
                        'src:' + nm, _name(nm), scol(nm),
                        'kW' if k[0] == 'p' else 'kvar', n)
            if 'p_load' in s:
                add(pp, t_, np.asarray(s['p_load'], float), 'src:load',
                    tr('Beban'), '#6B7280', 'kW', n, 1.0, True)
            if 'q_load' in s:
                add(pq_, t_, np.asarray(s['q_load'], float), 'src:load',
                    tr('Beban'), '#6B7280', 'kvar', n, 1.0, True)
            if not (fs and getattr(self, '_fs_fit', False)):
                pq_.setLabel('bottom', tr('Waktu (s)'))
        leg(None, tr('Sumber') + ':', '', False)
        for nm in src_names:
            leg('src:' + nm, _name(nm), scol(nm))
        leg('src:load', tr('Beban'), '#6B7280', True)
        row_pqa = row + sys_rows
        n_rows = row_pqa
        # ---- cuplikan PQA (sumbu waktu sendiri) ----
        if ev:
            span = C if fs else ncol
            sub = G.addLayout(row=row_pqa, col=0, colspan=span)
            sub.setContentsMargins(0, 8, 0, 0)
            per_min = bool(ev.get('dt_s')) and ev['dt_s'] >= 30
            k_t = 1.0 / 60.0 if per_min else 1.0
            tq = np.asarray(ev['t'], float) * k_t
            xlab = (tr('Waktu relatif terhadap kejadian (menit)') if per_min else
                    tr('Waktu relatif terhadap kejadian (s)')
                    if ev.get('dt_s') else tr('Sampel'))
            head = tr('Pengukuran PQA') + f" — {ev['at']}"
            panels = [(tr('Frekuensi (Hz)'), ('f avg (Hz)', 'f min (Hz)', 'f max (Hz)'), 'Hz'),
                      (tr('Tegangan ½-siklus (pu)'), ('U min (pu)', 'U max (pu)'), 'pu'),
                      (tr('Daya aktif (kW)'), ('P (kW)',), 'kW'),
                      (tr('Arus (A)'), ('I half-cycle max (A)', 'I avg (A)'), 'A')]
            panels = [(lab, [k for k in keys if k in ev['series']], unit)
                      for lab, keys, unit in panels]
            panels = [x for x in panels if x[1]]
            pc = C if fs else max(1, len(panels))    # kolom grid PQA
            leg(None, 'PQA:', '', False)
            short = {'f avg (Hz)': 'avg', 'f min (Hz)': 'min', 'f max (Hz)': 'max',
                     'U min (pu)': 'min', 'U max (pu)': 'max', 'P (kW)': 'P',
                     'I half-cycle max (A)': '½-cycle max', 'I avg (A)': 'avg'}
            for jj, (lab, ks, unit) in enumerate(panels):
                rr, cc = divmod(jj, pc)
                span = pc - cc if jj == len(panels) - 1 else 1
                pp = mk(sub, rr, cc, span, lab, head if rr == 0 else None,
                        grp='pqa', key='PQA:' + ks[0])
                for k in ks:
                    y = np.asarray([np.nan if v is None else v
                                    for v in ev['series'][k]], float)
                    lkey = 'pqa:' + short[k]
                    lcol = {'avg': '#10B981', 'min': '#0EA5E9', 'max': '#DB2777',
                            '½-cycle max': '#DB2777', 'P': '#F59E0B'}[short[k]]
                    add(pp, tq, y, lkey, short[k], lcol, unit, 'PQA', 1.4,
                        grp='pqa')
                    leg(lkey, short[k], lcol)
                pp.setLabel('bottom', xlab)
                pp.addItem(pg.InfiniteLine(0.0, angle=90, pen=pg.mkPen(
                    '#16A34A', style=Qt.DotLine)), ignoreBounds=True)
            n_rows += -(-len(panels) // pc)
        self.leg_cmp.set_items(legend)
        # tinggi kanvas (halaman); layar penuh = GRID bebas (v181): panel
        # dikeluarkan dari layout & ditempatkan menurut tata letak pengguna
        if not fs:
            self.glw_cmp.setMinimumHeight(1040)
        elif self._cmp_keyed:
            keys = [k for k, _p in self._cmp_keyed]
            slots = {}
            for k, p_ in self._cmp_keyed:
                lay_, r_, c_, sp_ = self._cmp_slot[k]
                slots[k] = ((r_ + row_pqa) if lay_ is not G else r_, c_, sp_)
                lay_.removeItem(p_)
            for it in list(G.ci.items):        # sub-layout PQA (kini kosong)
                G.removeItem(it)
            pre = GridArranger.preset(slots, C, 5 if C == 1 else 6)
            rects = GridArranger.merge(keys, self._cmp_grid, pre)
            self._cmp_arr.place(self._cmp_keyed, rects,
                                fit=getattr(self, '_fs_fit', False))
        t_ev = found[0][1].get('t_ev', 1.0)
        # Sumbu waktu disamakan MANUAL per kelompok (simulasi / PQA): setXLink
        # menyelaraskan menurut posisi layar, sehingga panel yang berdampingan
        # akan bergeser satu sama lain.
        self._cmp_sync = False

        def _sync_x(vb, rng):
            if self._cmp_sync:
                return
            self._cmp_sync = True
            try:
                grp = next((self._cmp_grp[id(q_)] for q_ in self._cmp_plots
                            if q_.vb is vb), 'sim')
                for q_ in self._cmp_plots:
                    if q_.vb is not vb and self._cmp_grp[id(q_)] == grp:
                        q_.vb.setXRange(rng[0], rng[1], padding=0)
            finally:
                self._cmp_sync = False
        for p in self._cmp_plots:
            p.vb.sigXRangeChanged.connect(_sync_x)
            if self._cmp_grp[id(p)] == 'sim':
                p.addItem(pg.InfiniteLine(t_ev, angle=90, pen=pg.mkPen(
                    '#9CA3AF', style=Qt.DotLine)), ignoreBounds=True)
            ln = pg.InfiniteLine(angle=90, movable=False,
                                 pen=pg.mkPen('#9CA3AF', width=1))
            ln.setZValue(50); ln.setVisible(False)
            p.addItem(ln, ignoreBounds=True)
            sc = pg.ScatterPlotItem(size=7, pen=pg.mkPen('#111827', width=1))
            sc.setZValue(60)
            p.addItem(sc, ignoreBounds=True)
            self._cmp_vlines.append(ln); self._cmp_dots.append(sc)
            p.enableAutoRange()

        # P dan Q antar-sistem memakai skala-y yang SAMA agar dapat dibandingkan
        def _common_y():
            for unit, plots_ in self._cmp_pq.items():
                ys = [c_['y'][np.isfinite(c_['y'])] for c_ in self._cmp_curves
                      if c_['unit'] == unit and c_['grp'] == 'sim'
                      and c_['item'].isVisible()]
                ys = [y for y in ys if y.size]
                if not ys:
                    continue
                lo = min(float(y.min()) for y in ys)
                hi = max(float(y.max()) for y in ys)
                pad = 0.06 * max(hi - lo, 1.0)
                for it in plots_:
                    it.vb.setYRange(lo - pad, hi + pad, padding=0)
        self._cmp_common_y = _common_y
        rect_zoom(self._cmp_plots, on_reset=_common_y)
        _common_y()
        style_layout(self.glw_cmp)          # warna mengikuti tema aktif
        # entri legenda yang disembunyikan pengguna tetap tersembunyi
        for k in list(getattr(self, '_cmp_hidden', set())):
            b_ = self.leg_cmp._btn.get(k)
            if b_ is not None and b_.isChecked():
                b_.setChecked(False)

    def _on_cmp_legend(self, key, on):
        """Legenda bersama: sembunyikan / tampilkan semua kurva berentri
        `key` di seluruh panel."""
        hid = getattr(self, '_cmp_hidden', None)
        if hid is None:
            hid = self._cmp_hidden = set()
        (hid.discard if on else hid.add)(key)
        for c_ in self._cmp_curves:
            if c_['key'] == key:
                c_['item'].setVisible(bool(on))
        for p in self._cmp_plots:
            p.enableAutoRange(); p.autoRange()
        fn = getattr(self, '_cmp_common_y', None)
        if fn is not None:
            fn()
        self._cmp_cursor_off()

    def _cmp_cursor_off(self):
        for ln, sc in zip(self._cmp_vlines, self._cmp_dots):
            ln.setVisible(False)
            sc.setData([])
        self.lbl_cmp_cur.setText(
            _hint(bool(getattr(self, '_cmp_fs', False))))

    def _on_cmp_mouse(self, evt):
        pos = evt[0]
        x = grp = None
        for p in self._cmp_plots:
            if p.vb.sceneBoundingRect().contains(pos):
                x = p.vb.mapSceneToView(pos).x()
                grp = self._cmp_grp.get(id(p), 'sim')
                break
        if x is None or not self._cmp_curves:
            self._cmp_cursor_off()
            return
        spots = {id(p): [] for p in self._cmp_plots}
        per = {}
        for c_ in self._cmp_curves:
            t_, y = c_['t'], c_['y']
            if c_['grp'] != grp or not c_['item'].isVisible() or t_.size == 0:
                continue
            i = int(np.clip(np.searchsorted(t_, x), 0, t_.size - 1))
            if i > 0 and abs(t_[i - 1] - x) < abs(t_[i] - x):
                i -= 1
            if i >= y.size or not np.isfinite(y[i]):
                continue
            v = float(y[i])
            unit = c_['unit']
            spots[id(c_['plot'])].append({'pos': (float(t_[i]), v),
                                          'brush': pg.mkBrush(c_['color'])})
            fmt = (f'{v:.3f}' if unit in ('Hz', 'pu', 'pu PCS') else f'{v:,.0f}')
            if grp == 'pqa':
                nm = {'Hz': 'f', 'pu': 'U', 'kW': '', 'A': 'I'}[unit] \
                    + ' ' + c_['label']
            else:
                nm = {'Hz': 'f', 'pu': 'V', 'pu PCS': 'I PCS'}.get(
                    unit, f"{'P' if unit == 'kW' else 'Q'} {c_['label']}")
            per.setdefault(c_['sys'], []).append(
                f"<span style='color:{c_['color']}'>●</span> {nm.strip()} {fmt}")
        for p, ln, sc in zip(self._cmp_plots, self._cmp_vlines, self._cmp_dots):
            same = self._cmp_grp.get(id(p)) == grp
            ln.setPos(x); ln.setVisible(same)
            sc.setData(spots[id(p)] if same else [])
        if grp == 'pqa':
            head = tr('Pengukuran PQA') + f': <b>{x:+.2f}</b> ' + tr(
                'dari kejadian')
        else:
            head = tr('Simulasi') + f': <b>t = {x:.3f} s</b>'
        self.lbl_cmp_cur.setText(head + '<br>' + '<br>'.join(
            f'<b>{n}</b>: ' + ' &nbsp; '.join(v) for n, v in per.items()))

    def _show_one(self, study):
        from ...reports.transient_report import case_rows
        self._study = study
        cs = study['cases']
        n_pass = sum(c['status'] == 'Pass' for c in cs)
        n_fail = sum(c['status'] in ('Fail', 'Error') for c in cs)
        self.lbl_sum.setText(tr(
            '{n} kasus · {p} lulus · {f} gagal · beban studi {l} kW · titik '
            'operasi dasar: {b}').format(
                n=len(cs), p=n_pass, f=n_fail, l=f"{study['load_kw']:,.0f}",
                b=_name(study['base_scenario']))
            + (' · ' + tr('motor DOL') + f" {study['motor_kw']:,.0f} kW "
               f"[{study['motor_basis']}]" if study.get('motor_basis') else '')
            + ('\n' + study['not_viable'] if study.get('not_viable') else ''))
        head, rows = case_rows(study)
        self._fill(self.tbl, head, rows, status_col=4)
        self.cb_case.blockSignals(True)
        self.cb_case.clear()
        for c in cs:
            self.cb_case.addItem(f"{c['id']} — {_name(c['title'])} · {c['status']}")
        self.cb_case.blockSignals(False)
        self._fill(self.tbl_req, ['Event', 'Result ', 'Requirement that follows'],
                   [list(r) for r in study['requirements']])
        self._fill(self.tbl_src,
                   ['Source', 'Rated current (A)', 'Basis', 'Initial (kA)',
                    'Sustained / transient (kA)'],
                   [[s['name'], (round(s['ir_a']) if s['ir_a'] == s['ir_a'] else ''),
                     s['basis'], round(s['ik_sub'], 2), round(s['ik_tr'], 2)]
                    for s in study['sc_sources']],
                   widths={'Rated current (A)': 120, 'Initial (kA)': 100,
                           'Sustained / transient (kA)': 170})
        self._fill(self.tbl_sc,
                   ['Operating configuration', 'Max initial fault I″k (kA)',
                    'Peak ip (kA)', 'Minimum fault (kA)'],
                   [[s['config'], round(s['ik_max'], 2), round(s['ip'], 2),
                     round(s['ik_min'], 2)] for s in study['sc']],
                   widths={'Max initial fault I″k (kA)': 170, 'Peak ip (kA)': 110,
                           'Minimum fault (kA)': 140})
        lab = {'yes': 'Yes', 'partial': 'Only at low pickup setting', 'no': 'No'}
        self._fill(self.tbl_prot,
                   ['Feeder rating (A)', 'Instantaneous pickup 5–10 × In (kA)',
                    'Clears instantaneously at minimum fault?'],
                   [[p['rating'], f"{p['lo']:.2f} – {p['hi']:.2f}",
                     lab[p['verdict']]] for p in study['protection']],
                   widths={'Feeder rating (A)': 120,
                           'Instantaneous pickup 5–10 × In (kA)': 240,
                           'Clears instantaneously at minimum fault?': 280})
        self.lbl_sc.setText(tr(
            'Metode IEC 60909 (sumber setara) + konverter sebagai sumber '
            'arus-terbatas. Maksimum {a} kA (rating switchgear {i} kA) · '
            'minimum {b} kA pada konfigurasi "{c}".').format(
                a=f"{study['ik_all']:.1f}", i=f"{study['icu_ka']:.0f}",
                b=f"{study['ik_weak']:.2f}", c=study['weak_config']))
        self._fill(self.tbl_model,
                   ['Element', 'Rating', 'Rated current', 'Representation',
                    'Parameters'], study['sources'],
                   widths={'Rating': 110, 'Rated current': 120})
        if study.get('basis'):
            self._fill(self.tbl_basis,
                       ['Parameter', 'Value', 'Unit',
                        'Standard basis of the default'], study['basis'],
                       widths={'Value': 110, 'Unit': 70})
        if cs:
            self.tbl.selectRow(0)
        else:
            for p in self._plots:
                p.clear()
            self._curves = []
            self.lbl_case.setText('')

    def _plot_selected(self):
        st = getattr(self, '_study', None)
        if not st:
            return
        r = self.tbl.currentRow()
        if r < 0 or r >= len(st['cases']):
            return
        c = st['cases'][r]
        s = c.get('series') or {}
        if self.cb_case.currentIndex() != r:          # sinkron dgn pemilih kasus
            self.cb_case.blockSignals(True)
            self.cb_case.setCurrentIndex(r)
            self.cb_case.blockSignals(False)
        for p in self._plots:
            for it in list(p.listDataItems()):
                if it not in self._dots:
                    p.removeItem(it)
            for it in [x for x in p.items if isinstance(x, pg.InfiniteLine)
                       and x not in self._vlines]:
                p.removeItem(it)
            if p.legend is not None:            # legenda lama di dalam grafik
                p.legend.scene() and p.legend.scene().removeItem(p.legend)
                p.legend = None
        self._curves = []
        from ...engine.transient_cases import case_evidence
        checks, expl = case_evidence(c, st.get('crit') or {})
        col = {'Pass': '#16A34A', 'Fail': '#DC2626'}.get(c['status'], _MUTED)
        txt = (f"<b>{c['id']} — {c['title']}</b> · "
               f"<b style='color:{col}'>{c['status']}</b>")
        if c.get('scenario'):
            txt += f"<br>{tr('Titik operasi')}: {_name(c['scenario'])}"
        txt += f"<br><b>{tr('Dasar hasil')}:</b> {_name(expl)}"
        if c.get('log'):
            txt += '<br>' + ' · '.join(c['log'][:5])
        m = c.get('metrics') or {}
        if m.get('q_unit'):
            t90 = m.get('q_t90')
            txt += ('<br>' + tr('Respons daya reaktif') + f": {_name(m['q_unit'])} — "
                    + tr('puncak') + f" {m.get('q_peak_kvar', 0):,.0f} kvar"
                    + (f", t90 {t90:.3f} s" if t90 is not None and t90 == t90
                       else ''))
        self.lbl_case.setText(txt)
        self.lbl_ev.setText(
            f"<b>{tr('Bukti penilaian')} — {c['id']}</b> "
            f"<span style='color:{_MUTED};'>· " + tr(
                'kriteria penerimaan dari panel kiri (Transient — Converters → '
                'Acceptance Criteria); dasar standar tiap batas pada kolom '
                'Basis') + '</span>')
        self._fill(self.tbl_ev, ['Criterion', 'Measured', 'Limit', 'Status',
                                 'Basis / reason'],
                   [[x['criterion'], x['measured'], x['limit'], x['status'],
                     x['basis']] for x in checks], status_col=3)
        if 't' not in s:
            self.leg_case.set_items([])
            return
        t = np.asarray(s['t'], float)
        legend, seen = [], set()

        def leg(key, label, color, dashed=False):
            if key is None:
                legend.append((None, label, color, dashed))
            elif key not in seen:
                seen.add(key); legend.append((key, label, color, dashed))

        def add(plot, key, color, label, unit, lkey, width=1.6, dash=False):
            y = np.asarray(s[key], float)
            it = plot.plot(t, y, pen=pg.mkPen(
                color, width=width, style=Qt.DashLine if dash else Qt.SolidLine),
                connect='finite')
            self._curves.append((plot, t, y, label, color, unit, lkey, it))
        leg(None, 'Bus:', '', False)
        add(self.p_f, 'f', '#2563EB', 'f', 'Hz', 'bus:f')
        leg('bus:f', tr('Frekuensi'), '#2563EB')
        add(self.p_v, 'v', '#DC2626', 'V', 'pu', 'bus:v')
        leg('bus:v', tr('Tegangan'), '#DC2626')
        # warna per SUMBER (sama di panel P dan Q)
        srcs = []
        for k in s:
            if k[:2] in ('p_', 'q_') and k not in ('p_load', 'q_load') \
                    and k[2:] not in srcs:
                srcs.append(k[2:])
        scol = {nm: _PAL[i % len(_PAL)] for i, nm in enumerate(srcs)}
        leg(None, tr('Sumber') + ':', '', False)
        for nm in srcs:
            for plot, pre, unit in ((self.p_p, 'p_', 'kW'), (self.p_q, 'q_', 'kvar')):
                if pre + nm in s:
                    add(plot, pre + nm, scol[nm], _name(nm), unit, 'src:' + nm, 1.5)
            leg('src:' + nm, _name(nm), scol[nm])
        for plot, k, unit in ((self.p_p, 'p_load', 'kW'), (self.p_q, 'q_load', 'kvar')):
            if k in s:
                add(plot, k, '#6B7280', tr('Beban'), unit, 'src:load', 1.0, True)
                leg('src:load', tr('Beban'), '#6B7280', True)
        self.leg_case.set_items(legend)
        for k in list(getattr(self, '_case_hidden', set())):   # tetap tersembunyi
            b_ = self.leg_case._btn.get(k)
            if b_ is not None and b_.isChecked():
                b_.setChecked(False)
        for p in self._plots:
            p.addItem(pg.InfiniteLine(c.get('t_ev', 1.0), angle=90,
                                      pen=pg.mkPen('#9CA3AF', style=Qt.DotLine)),
                      ignoreBounds=True)
            p.enableAutoRange()
        self.lbl_cur.setText(_hint(bool(getattr(self, '_case_fs', False))))

    # ------------------------------------------------------------ kursor
    def _on_mouse(self, evt):
        pos = evt[0]
        if not self._curves:
            return
        x = None
        for p in self._plots:
            if p.vb.sceneBoundingRect().contains(pos):
                x = p.vb.mapSceneToView(pos).x()
                break
        if x is None:
            self._cursor_off()          # di luar area grafik: tidak men-trace
            return
        t = self._curves[0][1]
        if t.size == 0:
            return
        i = int(np.clip(np.searchsorted(t, x), 0, t.size - 1))
        if i > 0 and abs(t[i - 1] - x) < abs(t[i] - x):
            i -= 1
        xi = float(t[i])
        spots = {id(p): [] for p in self._plots}
        txt = [f"<b>t = {xi:.3f} s</b>"]
        groups = {}
        for plot, tt, y, label, color, unit, _k, item in self._curves:
            if not item.isVisible() or i >= y.size or not np.isfinite(y[i]):
                continue
            v = float(y[i])
            spots[id(plot)].append({'pos': (xi, v), 'brush': pg.mkBrush(color)})
            fmt = (f'{v:.3f}' if unit in ('Hz', 'pu') else f'{v:,.1f}')
            groups.setdefault(unit, []).append(
                f"<span style='color:{color}'>●</span> {label} {fmt}")
        for unit in ('Hz', 'pu', 'kW', 'kvar'):
            if unit in groups:
                txt.append(f"<b>{unit}</b>: " + ' &nbsp; '.join(groups[unit]))
        for p, ln, sc in zip(self._plots, self._vlines, self._dots):
            ln.setPos(xi); ln.setVisible(True)
            sc.setData(spots[id(p)])
        self.lbl_cur.setText(' &nbsp;|&nbsp; '.join(txt))

    def _on_case_combo(self, i):
        """Pemilih kasus (layar penuh) -> pilih baris tabel kasus yang sama
        (memicu _plot_selected)."""
        if 0 <= i < self.tbl.rowCount() and self.tbl.currentRow() != i:
            self.tbl.selectRow(i)

    def _on_case_legend(self, key, on):
        """Legenda bersama grafik Kasus: sembunyikan / tampilkan semua kurva
        berentri `key` di seluruh panel."""
        hid = getattr(self, '_case_hidden', None)
        if hid is None:
            hid = self._case_hidden = set()
        (hid.discard if on else hid.add)(key)
        for c_ in self._curves:
            if c_[6] == key:
                c_[7].setVisible(bool(on))
        for p in self._plots:
            p.enableAutoRange(); p.autoRange()
        self._cursor_off()

    def _on_pqa_legend(self, key, on):
        hid = getattr(self, '_pqa_hidden', None)
        if hid is None:
            hid = self._pqa_hidden = set()
        (hid.discard if on else hid.add)(key)
        for c_ in self._pqa_items:
            if c_[0] == key:
                c_[1].setVisible(bool(on))
        if self._pqa_fs:
            for _k, pl in self._pqa_fs_plots:
                pl.enableAutoRange(); pl.autoRange()
        else:
            self.plot_pqa.enableAutoRange(); self.plot_pqa.autoRange()
        self._pqa_cursor_off()

    def _cursor_off(self):
        """Kursor di luar grafik: sembunyikan garis & titik data."""
        for ln, sc in zip(self._vlines, self._dots):
            ln.setVisible(False)
            sc.setData([])
        self.lbl_cur.setText(_hint(bool(getattr(self, '_case_fs', False))))

    def _pqa_cursor_off(self):
        self._pqa_vline.setVisible(False)
        self._pqa_dots.setData([])
        for _p, vl, dots in getattr(self, '_pqa_fs_cur', []):
            vl.setVisible(False); dots.setData([])
        self.lbl_pqa_cur.setText(
            _hint(bool(getattr(self, '_pqa_fs', False))))

    def _on_pqa_mouse(self, evt):
        pos = evt[0]
        vb = self.plot_pqa.getPlotItem().vb
        if not self._pqa_curves or not vb.sceneBoundingRect().contains(pos):
            self._pqa_cursor_off()
            return
        x = vb.mapSceneToView(pos).x()
        t = self._pqa_curves[0][0]
        if t.size == 0:
            return
        i = int(np.clip(np.searchsorted(t, x), 0, t.size - 1))
        if i > 0 and abs(t[i - 1] - x) < abs(t[i] - x):
            i -= 1
        xi = float(t[i])
        p = self.state.cfg.get('tr_pqa') or {}
        if p.get('t_unit') == 'h':
            head = f'{xi:,.2f} h'
            try:
                import pandas as pd
                head = (str(pd.Timestamp(p['t_start'])
                            + pd.Timedelta(hours=xi))[:19] + f' ({head})')
            except Exception:
                pass
        else:
            head = tr('Sampel') + f' {xi:,.0f}'
        txt, spots = [f'<b>{head}</b>'], []
        for tt, y, label, color, item in self._pqa_curves:
            if not item.isVisible() or i >= y.size or not np.isfinite(y[i]):
                continue
            v = float(y[i])
            spots.append({'pos': (xi, v), 'brush': pg.mkBrush(color)})
            txt.append(f"<span style='color:{color}'>●</span> {label} "
                       + (f'{v:,.3f}' if abs(v) < 100 else f'{v:,.1f}'))
        self._pqa_vline.setPos(xi); self._pqa_vline.setVisible(True)
        self._pqa_dots.setData(spots)
        self.lbl_pqa_cur.setText(' &nbsp; '.join(txt))

    # ------------------------------------------------------------ ekspor
    def _export(self, kind):
        st = getattr(self, '_study_all', None) or getattr(
            self.state, 'transient_result', None)
        if not st:
            QMessageBox.information(self, tr('Transient Analysis'),
                                    tr('Jalankan studi terlebih dahulu.'))
            return
        from ...data.exporter import export_filename
        try:
            default = export_filename(self.state.cfg, 'Transient', kind)
        except Exception:
            default = f'Transient_Study.{kind}'
        flt = 'Excel (*.xlsx)' if kind == 'xlsx' else 'Word (*.docx)'
        path, _ = QFileDialog.getSaveFileName(self, tr('Simpan'), default, flt)
        if not path:
            return
        try:
            from ...reports import transient_report as tr_rep
            if kind == 'xlsx':
                tr_rep.export_xlsx(path, st, dict(self.state.cfg))
            else:
                tr_rep.export_docx(path, st, dict(self.state.cfg))
        except Exception as e:
            QMessageBox.critical(self, tr('Gagal'), str(e))
            return
        QMessageBox.information(self, tr('Sukses'), tr('Tersimpan:') + f'\n{path}')
