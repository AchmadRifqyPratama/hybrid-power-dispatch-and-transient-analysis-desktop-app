"""Utilitas bersama untuk seluruh grafik pyqtgraph.

* ``no_wheel_zoom``  — mematikan zoom via scroll mouse (sering tak sengaja
  terpicu saat menggulir halaman).
* ``CursorReadout``  — menampilkan nilai seri pada posisi kursor.
* ``fit_table_columns`` — melebarkan kolom tabel agar memenuhi lebar yang
  tersedia di layar, tanpa memaksa scroll horizontal bila muat.
"""
from __future__ import annotations

import os
import sys

import pyqtgraph as pg
from PySide6.QtCore import Qt, QObject, QEvent, QRect, QSize, QPoint, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QHeaderView, QTableWidget, QApplication,
                               QAbstractItemView, QFrame, QScrollArea,
                               QLayout, QWidget, QPushButton, QDialog,
                               QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy)


# --------------------------------------------------------------- grafik
def no_wheel_zoom(plot) -> None:
    """Matikan zoom roda mouse pada sebuah PlotWidget/ViewBox."""
    try:
        vb = plot.getViewBox() if hasattr(plot, 'getViewBox') else plot
    except Exception:
        return
    if vb is None:
        return

    def _ignore(ev, axis=None):
        try:
            ev.ignore()
        except Exception:
            pass

    vb.wheelEvent = _ignore


def rect_zoom(plots, on_reset=None) -> None:
    """Interaksi grafik seragam: roda mouse TIDAK men-zoom (diteruskan ke
    scroll halaman), zoom = seret kotak di dalam grafik, klik-ganda =
    kembali ke tampilan penuh."""
    plots = list(plots)

    def reset():
        for p in plots:
            p.enableAutoRange()
            p.autoRange()
        if on_reset is not None:
            on_reset()
    for p in plots:
        vb = p.getViewBox()
        no_wheel_zoom(p)
        vb.setMouseMode(vb.RectMode)
        vb.setMouseEnabled(x=True, y=True)
        orig = vb.mouseClickEvent

        def click(ev, _orig=orig):
            if ev.button() == Qt.LeftButton and ev.double():
                ev.accept()
                reset()
            else:
                _orig(ev)
        vb.mouseClickEvent = click


def link_x(plots) -> None:
    """Samakan rentang sumbu-x beberapa PlotItem. Berbeda dengan setXLink
    (yang menyelaraskan menurut posisi layar), rentang disalin apa adanya —
    tetap benar saat panel disusun berdampingan."""
    plots = list(plots)
    busy = [False]

    def sync(vb, rng):
        if busy[0]:
            return
        busy[0] = True
        try:
            for p in plots:
                if p.vb is not vb:
                    p.vb.setXRange(rng[0], rng[1], padding=0)
        finally:
            busy[0] = False
    for p in plots:
        p.vb.sigXRangeChanged.connect(sync)


class LeaveWatcher(QObject):
    """Panggil ``callback`` saat kursor meninggalkan widget (sinyal
    sigMouseMoved tidak terpancar ketika kursor keluar dari widget)."""

    def __init__(self, widget, callback):
        super().__init__(widget)
        self._cb = callback
        widget.installEventFilter(self)
        try:
            widget.viewport().installEventFilter(self)
        except Exception:
            pass

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Leave:
            try:
                self._cb()
            except Exception:
                pass
        return False


class WheelToScroll(QObject):
    """Roda mouse di atas grafik menggulir halaman (QScrollArea terdekat)
    alih-alih ditelan grafik."""

    def __init__(self, view):
        super().__init__(view)
        self._v = view
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Wheel:
            return False
        w = self._v.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        if w is not None:
            sb = w.verticalScrollBar()
            sb.setValue(sb.value() - int(ev.angleDelta().y() / 120.0
                                         * max(40, sb.singleStep() * 3)))
        return True


class FlowLayout(QLayout):
    """Tata letak mengalir: item berjajar ke kanan dan turun baris bila
    lebar habis (dipakai LegendBar)."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._sp
            line = max(line, hint.height())
        return y + line - rect.y()


class LegendBar(QWidget):
    """Legenda TERKUMPUL di atas grafik: satu tombol per entri (titik warna +
    nama). Klik = sembunyikan/tampilkan semua kurva berentri itu di seluruh
    panel. Beberapa panel berbagi entri yang sama."""
    toggled = Signal(str, bool)

    def __init__(self):
        super().__init__()
        self._lay = FlowLayout(self, spacing=6)
        self._btn = {}
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def set_items(self, items):
        """items = [(key, label, color, dashed)]; kunci unik per entri.
        Kunci None = judul kelompok (teks saja)."""
        while self._lay.count():
            it = self._lay.takeAt(0)
            if it is not None and it.widget() is not None:
                w_ = it.widget()
                w_.hide(); w_.setParent(None)     # segera lepas dari tampilan
                w_.deleteLater()
        self._btn = {}
        for key, label, color, dashed in items:
            if key is None:
                lb = QLabel(label)
                lb.setStyleSheet('font-weight:600; padding:2px 2px 2px 8px;')
                self._lay.addWidget(lb)
                continue
            mark = '┄' if dashed else '●'
            b = QPushButton(f'{mark} {label}')
            b.setCheckable(True); b.setChecked(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(
                'QPushButton{border:1px solid rgba(138,148,160,90);'
                'border-radius:9px;padding:1px 8px;font-size:11px;'
                f'color:{color};background:transparent;}}'
                'QPushButton:!checked{color:rgba(138,148,160,130);'
                'border-style:dashed;}')

            def _tog(on, _k=key, _b=b, _m=mark, _l=label):
                _b.setText(f"{_m if on else '○'} {_l}")   # ○ = disembunyikan
                self.toggled.emit(_k, on)
            b.toggled.connect(_tog)
            self._lay.addWidget(b)
            self._btn[key] = b
        self.updateGeometry()

    def is_on(self, key) -> bool:
        b = self._btn.get(key)
        return True if b is None else b.isChecked()


class PopOut(QObject):
    """Tampilkan sebuah widget (blok grafik + pembacaan kursor) LAYAR PENUH
    lalu kembalikan ke tempat semula. Widget yang sama dipindahkan, sehingga
    kursor data, zoom dan legenda tetap bekerja."""

    def __init__(self, widget, title: str = '', on_open=None, on_close=None,
                 scroll=None):
        super().__init__(widget)
        self._w, self._title = widget, title
        # `scroll` = widget di dalam `widget` yang digulir; bagian lain
        # (judul, pemilih, legenda, pembacaan kursor) tetap terlihat (freeze)
        self._scroll = scroll
        self._on_open, self._on_close = on_open, on_close
        self._dlg = None
        self._home = None                 # (layout, indeks, stretch)

    def button(self, text='⛶') -> QPushButton:
        b = QPushButton(text)
        b.setProperty('flat', True)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(self.toggle)
        self._b = b
        return b

    def is_open(self) -> bool:
        return self._dlg is not None

    def toggle(self):
        if self._dlg is not None:
            self._dlg.close()
            return
        par = self._w.parentWidget()
        lay = par.layout() if par is not None else None
        if lay is None:
            return
        idx = lay.indexOf(self._w)
        st = lay.stretch(idx) if hasattr(lay, 'stretch') else 0
        self._home = (lay, idx, st)
        dlg = QDialog(self._w.window())
        dlg.setWindowTitle(self._title)
        dlg.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        v = QVBoxLayout(dlg); v.setContentsMargins(10, 8, 10, 8)
        top = QHBoxLayout()
        t = QLabel(self._title); t.setStyleSheet('font-weight:700;font-size:14px;')
        top.addWidget(t); top.addStretch(1)
        c = QPushButton('✕  Esc'); c.setProperty('flat', True)
        c.clicked.connect(dlg.close)
        top.addWidget(c)
        v.addLayout(top)
        lay.removeWidget(self._w)
        sa = QScrollArea(); sa.setWidgetResizable(True)    # boleh gulir vertikal
        sa.setFrameShape(QScrollArea.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._inner = None
        tgt = self._scroll
        tl = tgt.parentWidget().layout() if (
            tgt is not None and tgt.parentWidget() is not None) else None
        if tl is not None and tl.indexOf(tgt) >= 0:
            # hanya grafik yang digulir; bagian atas blok tetap di tempatnya
            ti = tl.indexOf(tgt)
            ts = tl.stretch(ti) if hasattr(tl, 'stretch') else 0
            tl.removeWidget(tgt)
            sa.setWidget(tgt)
            tl.insertWidget(ti, sa, 1)
            self._inner = (tl, ti, ts)
            v.addWidget(self._w, 1)
        else:
            sa.setWidget(self._w)
            v.addWidget(sa, 1)
        self._sa = sa
        b = getattr(self, '_b', None)
        if b is not None:                   # tak perlu tombol layar penuh
            b.setVisible(False)             # di dalam mode layar penuh
        if self._on_open is not None:
            self._on_open()
        dlg.finished.connect(self._restore)
        self._dlg = dlg
        try:
            from .theme import apply_titlebar_theme, CURRENT_DARK
            apply_titlebar_theme(dlg, dark=CURRENT_DARK)
        except Exception:
            pass
        dlg.showFullScreen()

    def _restore(self, *_):
        dlg, self._dlg = self._dlg, None
        sa = getattr(self, '_sa', None)
        if sa is not None:
            w_ = sa.takeWidget()            # lepas dari area gulir dialog
            inner = getattr(self, '_inner', None)
            if inner is not None and w_ is not None:
                tl, ti, ts = inner
                tl.removeWidget(sa)
                sa.setParent(None); sa.deleteLater()
                tl.insertWidget(ti, w_, ts)
                w_.show()
                self._inner = None
            self._sa = None
        b = getattr(self, '_b', None)
        if b is not None:
            b.setVisible(True)
        if self._on_close is not None:
            self._on_close()
        if self._home is not None:
            lay, idx, st = self._home
            try:
                lay.insertWidget(idx, self._w, st)
            except Exception:
                lay.addWidget(self._w)
            self._w.show()
        if dlg is not None:
            dlg.deleteLater()


class _GridOverlay(QWidget):
    """Lapisan transparan di atas viewport: garis grid & kotak target saat
    menyeret, serta tanda pegangan ubah-ukuran di sudut kanan-bawah panel."""

    def __init__(self, arr, parent):
        super().__init__(parent)
        self._arr = arr
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.hide()

    def paintEvent(self, _ev):
        from PySide6.QtGui import QPainter, QPen, QColor, QBrush
        a = self._arr
        if not a.active():
            return
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing, False)
        acc = QColor('#2563EB')
        mut = QColor(156, 163, 175)
        if a._drag is not None:
            # garis grid (sel) sampai sedikit di bawah panel terbawah
            rows = max(a.rows(), a._drag['cand'][0] + a._drag['cand'][2]) + 2
            g = QColor(mut); g.setAlpha(70)
            qp.setPen(QPen(g, 1, Qt.DotLine))
            for c in range(a.COLS + 1):
                x = a.vx(a.col_x(c))
                qp.drawLine(x, a.vy(a.row_y(0)), x, a.vy(a.row_y(rows)))
            for r in range(rows + 1):
                y = a.vy(a.row_y(r))
                qp.drawLine(a.vx(a.col_x(0)), y, a.vx(a.col_x(a.COLS)), y)
            rr = a.vrect(*a._drag['cand'])
            fill = QColor(acc); fill.setAlpha(45)
            qp.setPen(QPen(acc, 2)); qp.setBrush(QBrush(fill))
            qp.drawRect(rr)
        # tanda pegangan ubah-ukuran (kanan-bawah) tiap panel
        m = QColor(mut); m.setAlpha(170)
        qp.setPen(QPen(m, 1.4)); qp.setBrush(Qt.NoBrush)
        for k in a._items:
            r = a.vrect(*a.rects[k])
            x, y = r.right() - 3, r.bottom() - 3
            for d in (5, 9, 13):
                qp.drawLine(x - d, y, x, y - d)
        qp.end()


class GridArranger(QObject):
    """v181 — tata letak GRID bebas untuk panel grafik layar penuh.

    Area grafik dibagi COLS kolom × baris ber-tinggi UNIT px. Tiap panel
    menempati persegi [baris, kolom, rentang baris, rentang kolom]:
      * seret JUDUL panel (⠿) -> pindah ke sel mana pun (posisi bebas,
        boleh menyisakan ruang kosong);
      * seret SUDUT kanan-bawah / tepi kanan / tepi bawah -> ubah ukuran
        (dikunci ke grid).
    Panel lain yang tertimpa didorong ke bawah. Seret di area plot tetap =
    zoom kotak. Panel dikelola manual (di luar QGraphicsGridLayout) sehingga
    sel kosong benar-benar kosong. Sinyal `changed(dict)` -> simpan ke cfg."""

    changed = Signal(dict)
    COLS, UNIT, MARGIN, GAP = 12, 50, 6, 8
    HEAD, GRIP, EDGE = 24, 16, 6
    MIN_RS, MIN_CS = 2, 2

    def __init__(self, glw, enabled=lambda: True):
        super().__init__(glw)
        self._glw, self._enabled = glw, enabled
        self._items = {}               # key -> PlotItem (dikelola manual)
        self.rects = {}                # key -> [r, c, rs, cs]
        self.fit = False
        self._drag = None
        self._cur = None
        self._ov = _GridOverlay(self, glw.viewport())
        self._tip = QLabel(glw.viewport())
        self._tip.setObjectName('CursorCard')
        self._tip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._tip.hide()
        glw.viewport().installEventFilter(self)
        glw.installEventFilter(self)

    # ------------------------------------------------------------ data
    def active(self) -> bool:
        return bool(self._items)

    def rows(self) -> int:
        return max([r + rs for r, _c, rs, _cs in self.rects.values()] or [0])

    @classmethod
    def valid(cls, v) -> bool:
        try:
            r, c, rs, cs = (int(x) for x in v)
        except Exception:
            return False
        return (r >= 0 and c >= 0 and rs >= 1 and cs >= 1
                and c + cs <= cls.COLS and rs <= 400)

    @classmethod
    def merge(cls, keys, saved, preset):
        """Tata letak tersimpan (bila valid) + panel baru dari pola bawaan,
        diletakkan di bawah panel tersimpan; tumpang-tindih diselesaikan."""
        out = {}
        for k in keys:
            v = (saved or {}).get(k)
            if cls.valid(v):
                out[k] = [int(x) for x in v]
        if not out:
            return {k: list(preset[k]) for k in keys}
        base = max(r + rs for r, _c, rs, _cs in out.values())
        top = min([preset[k][0] for k in keys if k not in out] or [0])
        for k in keys:
            if k not in out:
                r, c, rs, cs = preset[k]
                out[k] = [r - top + base, c, rs, cs]
        return cls.resolve(out, None, keys)

    @staticmethod
    def resolve(rects, fixed, keys=None):
        """Dorong panel yang bertumpuk ke bawah. `fixed` = panel yang baru
        dipindah/diubah (tetap di tempatnya)."""
        ks = list(keys or rects)
        order = ([fixed] if fixed in rects else []) + sorted(
            [k for k in ks if k != fixed], key=lambda k: (rects[k][0], rects[k][1]))
        placed = {}
        for k in order:
            r, c, rs, cs = rects[k]
            moved = True
            while moved:
                moved = False
                for r2, c2, rs2, cs2 in placed.values():
                    if c < c2 + cs2 and c2 < c + cs and r < r2 + rs2 and r2 < r + rs:
                        r = r2 + rs2
                        moved = True
            placed[k] = [r, c, rs, cs]
        return {k: placed[k] for k in ks if k in placed}

    @classmethod
    def preset(cls, slots, C, rs):
        """Pola bawaan dari slot (baris, kolom, rentang kolom) grid C-kolom."""
        w = cls.COLS // max(1, C)
        return {k: [r * rs, c * w, rs, min(cls.COLS - c * w, sp * w)]
                for k, (r, c, sp) in slots.items()}

    # ------------------------------------------------------------ geometri
    def _area(self):
        ci = self._glw.ci
        return ci.rect()

    def _unit(self):
        if not self.fit:
            return float(self.UNIT)
        h = self._glw.viewport().height()
        R = max(1, self.rows())
        return max(6.0, (h - 2 * self.MARGIN + self.GAP) / R)

    def _cw(self):
        w = self._area().width()
        return max(10.0, (w - 2 * self.MARGIN + self.GAP) / self.COLS)

    def col_x(self, c):
        return self._area().left() + self.MARGIN + c * self._cw()

    def row_y(self, r):
        return self._area().top() + self.MARGIN + r * self._unit()

    def ci_rect(self, r, c, rs, cs):
        from PySide6.QtCore import QRectF
        return QRectF(self.col_x(c), self.row_y(r),
                      cs * self._cw() - self.GAP, rs * self._unit() - self.GAP)

    def vx(self, x):
        from PySide6.QtCore import QPointF
        return self._glw.mapFromScene(self._glw.ci.mapToScene(QPointF(x, 0))).x()

    def vy(self, y):
        from PySide6.QtCore import QPointF
        return self._glw.mapFromScene(self._glw.ci.mapToScene(QPointF(0, y))).y()

    def vrect(self, r, c, rs, cs):
        rr = self.ci_rect(r, c, rs, cs)
        x0, y0 = self.vx(rr.left()), self.vy(rr.top())
        return QRect(x0, y0, self.vx(rr.right()) - x0, self.vy(rr.bottom()) - y0)

    # ------------------------------------------------------------ kelola
    def place(self, items, rects, fit=False):
        """Ambil alih `items` [(key, PlotItem)] (sudah dikeluarkan dari
        layout) dan tempatkan menurut `rects`."""
        ci = self._glw.ci
        self.detach(keep=[p for _k, p in items])
        self._items = dict(items)
        self.rects = {k: list(rects[k]) for k, _p in items}
        self.fit = bool(fit)
        for _k, p in items:
            if p.parentItem() is not ci:
                p.setParentItem(ci)
            p.setVisible(True)
        self._apply_height()
        self.relayout()
        self._ov.show()

    def detach(self, keep=()):
        """Lepas semua panel yang dikelola (dikeluarkan dari scene) agar
        dapat dikembalikan ke layout biasa / dihapus."""
        keep = set(id(p) for p in keep)
        for p in list(self._items.values()):
            if id(p) in keep:
                continue
            try:
                sc = p.scene()
                p.setParentItem(None)
                if sc is not None:
                    sc.removeItem(p)
            except Exception:
                pass
        self._items, self.rects = {}, {}
        self._drag = None
        self._ov.hide(); self._tip.hide()
        self._set_cursor(None)

    def _apply_height(self):
        if self.fit:
            self._glw.setMinimumHeight(200)
        else:
            self._glw.setMinimumHeight(int(2 * self.MARGIN
                                           + (self.rows() + 1) * self.UNIT))

    def relayout(self):
        if not self._items:
            return
        for k, p in self._items.items():
            p.setGeometry(self.ci_rect(*self.rects[k]))
        self._ov.setGeometry(self._glw.viewport().rect())
        self._ov.raise_()
        self._ov.update()

    # ------------------------------------------------------------ interaksi
    def _hit(self, pos):
        """-> (key, mode) mode: 'move' | 'se' | 'e' | 's'."""
        for k in self._items:
            r = self.vrect(*self.rects[k])
            if not r.adjusted(-2, -2, 3, 3).contains(pos):
                continue
            right = pos.x() >= r.right() - self.EDGE
            bottom = pos.y() >= r.bottom() - self.EDGE
            if pos.x() >= r.right() - self.GRIP and pos.y() >= r.bottom() - self.GRIP:
                return k, 'se'
            if right:
                return k, 'e'
            if bottom:
                return k, 's'
            if pos.y() <= r.top() + self.HEAD:
                return k, 'move'
        return None

    _CURSORS = {'move': Qt.OpenHandCursor, 'se': Qt.SizeFDiagCursor,
                'e': Qt.SizeHorCursor, 's': Qt.SizeVerCursor,
                'grab': Qt.ClosedHandCursor}

    def _set_cursor(self, mode):
        if mode == self._cur:
            return
        vp = self._glw.viewport()
        if mode is None:
            vp.unsetCursor()
        else:
            vp.setCursor(self._CURSORS[mode])
        self._cur = mode

    def _cell(self, pos):
        """Posisi viewport -> (baris, kolom) pecahan pada grid."""
        x0, y0 = self.vx(self.col_x(0)), self.vy(self.row_y(0))
        cw = self.vx(self.col_x(1)) - x0
        u = self.vy(self.row_y(1)) - y0
        return (pos.y() - y0) / max(u, 1e-6), (pos.x() - x0) / max(cw, 1e-6)

    def _candidate(self, pos):
        d = self._drag
        r0, c0, rs, cs = d['start']
        fr, fc = self._cell(pos)
        if d['mode'] == 'move':
            r = int(round(fr - d['off'][0]))
            c = int(round(fc - d['off'][1]))
            r = max(0, r)
            c = min(max(0, c), self.COLS - cs)
            return [r, c, rs, cs]
        nrs, ncs = rs, cs
        if d['mode'] in ('se', 's'):
            nrs = max(self.MIN_RS, int(round(fr - r0)))
        if d['mode'] in ('se', 'e'):
            ncs = min(self.COLS - c0, max(self.MIN_CS, int(round(fc - c0))))
        return [r0, c0, nrs, ncs]

    def _tip_text(self, cand):
        r, c, rs, cs = cand
        return (f"{_tr('Kolom')} {c + 1}–{c + cs} / {self.COLS} · "
                f"{_tr('Baris')} {r + 1}–{r + rs} · {cs} × {rs}")

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self._glw:
            if t == QEvent.Resize and self._items:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self.relayout)
            return False
        if not self._items or not self._enabled():
            return False
        if t == QEvent.MouseMove:
            pos = ev.position().toPoint()
            if self._drag is None:
                hit = self._hit(pos)
                self._set_cursor(hit[1] if hit else None)
                return False
            cand = self._candidate(pos)
            self._drag['cand'] = cand
            self._tip.setText(self._tip_text(cand))
            self._tip.adjustSize()
            self._tip.move(pos + QPoint(14, 14)); self._tip.show()
            self._tip.raise_()
            self._ov.update()
            return True
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            pos = ev.position().toPoint()
            hit = self._hit(pos)
            if hit is None:
                return False
            k, mode = hit
            st = list(self.rects[k])
            fr, fc = self._cell(pos)
            self._drag = dict(key=k, mode=mode, start=st, cand=list(st),
                              off=(fr - st[0], fc - st[1]))
            if mode == 'move':
                self._set_cursor('grab')
            self._ov.update()
            return True                  # bukan zoom / klik grafik
        if t == QEvent.MouseButtonRelease and self._drag is not None:
            d, self._drag = self._drag, None
            self._tip.hide()
            if d['cand'] != d['start']:
                rects = dict(self.rects)
                rects[d['key']] = list(d['cand'])
                self.rects = self.resolve(rects, d['key'], list(self._items))
                self._apply_height()
                self.relayout()
                self.changed.emit({k: list(v) for k, v in self.rects.items()})
            self._ov.update()
            hit = self._hit(ev.position().toPoint())
            self._set_cursor(hit[1] if hit else None)
            return True
        if t == QEvent.MouseButtonDblClick and self._hit(
                ev.position().toPoint()) is not None:
            return True                  # klik-ganda judul/tepi bukan reset zoom
        if t == QEvent.KeyPress and self._drag is not None and \
                ev.key() == Qt.Key_Escape:
            self._drag = None; self._tip.hide(); self._ov.update()
            return True
        if t == QEvent.Leave and self._drag is None:
            self._set_cursor(None)
        return False


def _tr(s):
    try:
        from ..config.i18n import tr
        return tr(s)
    except Exception:
        return s


class HeightGrip(QFrame):
    """Pegangan tipis di bawah sebuah widget: seret naik/turun untuk mengubah
    TINGGI widget itu. Dipakai di dalam area gulir vertikal — tabel dapat
    dipanjangkan, isi di bawahnya terdorong dan tetap terjangkau scroll bar."""

    def __init__(self, target, min_h: int = 140, max_h: int = 3000):
        super().__init__()
        self._t, self._min, self._max = target, min_h, max_h
        self._y0 = self._h0 = None
        self.setFixedHeight(9)
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip('⇕')
        self.setStyleSheet('QFrame{background:rgba(138,148,160,70);'
                           'border-radius:3px;margin:2px 40%;}')

    def mousePressEvent(self, ev):
        self._y0 = ev.globalPosition().y()
        self._h0 = self._t.height()

    def mouseMoveEvent(self, ev):
        if self._y0 is None:
            return
        h = int(self._h0 + ev.globalPosition().y() - self._y0)
        self._t.setFixedHeight(max(self._min, min(self._max, h)))

    def mouseReleaseEvent(self, ev):
        self._y0 = None


class CursorReadout:
    """Tampilkan nilai seri di posisi kursor pada sebuah plot.

    ``formatter(x)`` mengembalikan teks yang ditampilkan pada ``label``;
    kembalikan string kosong bila tidak ada data pada posisi tersebut.
    """

    def __init__(self, plot, label, formatter, vline: bool = True):
        self.plot, self.label, self.fmt = plot, label, formatter
        self.line = None
        if vline:
            self.line = pg.InfiniteLine(angle=90, movable=False,
                                        pen=pg.mkPen((150, 150, 150, 110),
                                                     width=1))
            self.line.setZValue(-10)
            plot.addItem(self.line, ignoreBounds=True)
            self.line.hide()
        self._proxy = pg.SignalProxy(plot.scene().sigMouseMoved,
                                     rateLimit=45, slot=self._moved)

    def _moved(self, evt):
        pos = evt[0]
        try:
            inside = self.plot.sceneBoundingRect().contains(pos)
        except Exception:
            inside = False
        if not inside:
            if self.line is not None:
                self.line.hide()
            return
        x = self.plot.getViewBox().mapSceneToView(pos).x()
        try:
            text = self.fmt(float(x))
        except Exception:
            text = ''
        if self.line is not None:
            if text:
                self.line.setPos(x)
                self.line.show()
            else:
                self.line.hide()
        if self.label is not None:
            self.label.setText(text)


# --------------------------------------------------------------- tabel
def fit_table_columns(table, min_w: int = 84, pad: int = 18,
                      max_w: int = 320, fill: bool = True) -> None:
    """Lebarkan kolom mengikuti isi.

    ``fill=True``  : bila total kolom lebih sempit dari area tampil, sisa ruang
                     dibagi proporsional sehingga tabel memenuhi lebar.
    ``fill=False`` : kolom dirapatkan sesuai isi saja (tanpa diregangkan) —
                     tidak ada ruang kosong berlebih di dalam sel.
    Bila total kolom lebih lebar dari area tampil, kolom dibatasi ``max_w`` dan
    scroll horizontal tetap tersedia.
    """
    n = table.columnCount()
    if n <= 0:
        return
    table.resizeColumnsToContents()
    widths = [min(max(table.columnWidth(c) + pad, min_w), max_w)
              for c in range(n)]
    total = sum(widths)
    avail = table.viewport().width()
    if fill and avail > 0 and total > 0 and avail > total:
        extra = avail - total
        for c in range(n):
            widths[c] += int(extra * widths[c] / total)
        # sisa pembulatan diberikan ke kolom terakhir
        widths[-1] += avail - sum(widths)
    for c, w in enumerate(widths):
        table.setColumnWidth(c, max(w, min_w))
    hh = table.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.Interactive)


class CopyTableWidget(QTableWidget):
    """QTableWidget dengan seleksi blok (drag) + salin ke clipboard (Ctrl+C)
    dalam format TSV, siap ditempel ke sel Excel/Sheets.

    Nilai mentah (tanpa pemisah ribuan) disimpan di ``Qt.UserRole`` bila ada,
    sehingga tersalin sebagai angka yang bersih untuk Excel; jika tidak ada,
    teks yang tampil yang disalin.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setCornerButtonEnabled(True)   # klik pojok = pilih semua

    def keyPressEvent(self, ev):
        if ev.matches(QKeySequence.Copy):
            self.copy_selection()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _cell_text(self, row, col):
        it = self.item(row, col)
        if it is None:
            return ''
        raw = it.data(Qt.UserRole)
        if raw is not None and str(raw) != '':
            return str(raw)
        return it.text()

    def copy_selection(self):
        ranges = self.selectedRanges()
        if not ranges:
            return
        rows = sorted({r for rng in ranges
                       for r in range(rng.topRow(), rng.bottomRow() + 1)
                       if not self.isRowHidden(r)})
        cols_logical = {c for rng in ranges
                        for c in range(rng.leftColumn(), rng.rightColumn() + 1)
                        if not self.isColumnHidden(c)}
        # Salin mengikuti urutan TAMPILAN kolom (visual), sehingga bila kolom
        # digeser-geser, hasil salin ke Excel tetap sesuai yang terlihat.
        hh = self.horizontalHeader()
        cols = sorted(cols_logical, key=lambda c: hh.visualIndex(c))
        lines = ['\t'.join(self._cell_text(r, c) for c in cols) for r in rows]
        QApplication.clipboard().setText('\n'.join(lines))


# --------------------------------------------------------------- aset
def asset_path(name: str) -> str:
    """Lokasi berkas di folder assets, baik saat dijalankan dari sumber
    maupun dari hasil bundel PyInstaller."""
    base = getattr(sys, '_MEIPASS', None)
    if base:
        p = os.path.join(base, 'assets', name)
        if os.path.exists(p):
            return p
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, '..', '..'))
    return os.path.join(root, 'assets', name)
