"""Numune listesi ve numune detay/değerlendirme penceresi."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSizePolicy, QSplitter, QTableWidget,
                               QTableWidgetItem,
                               QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from ..db import SAMPLE_TYPES, Sample
from ..evaluation import STATUS_TEXT
from ..parts import diagnose
from ..textnorm import fmt_num, format_date
from . import theme
from .common import (AppState, FilterBar, KpiCard, button, hint, paint_status, ro_item,
                     style_table)
from .param_picker import ParamPicker

# SGS teşhis rengi -> tablo renklendirmesi (yalnızca görsel; değerlendirmeye katılmaz)
SGS_STATUS = {"Yeşil": 0, "Sarı": 1, "Turuncu": 1, "Kırmızı": 2}

BASE_COLUMNS = ["Durum", "Analiz No", "Motor"]
TAIL_COLUMNS = ["Numune Tarihi", "Motor sa", "Yağ sa", "Platform", "Grup", "Numune Tipi", "Yağ",
                "SGS Teşhisi", "Dikkat Gerektirenler", "İst.", "Değerlendirme Yorumu"]
SHOW_MODES = ["Tüm numuneler", "Seçili parametrelerde uyarı veya alarm olanlar",
              "Seçili parametrelerde alarm olanlar"]
MAX_PARAM_COLS = 30


class SamplesTab(QWidget):
    title = "Numuneler"
    subtitle = "Tüm analizler, değerlendirme durumu ve yorumlar"
    icon = "samples"

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)

        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        self.k_total = KpiCard("Numune", "info")
        self.k_motor = KpiCard("Motor", "info")
        self.k_ok = KpiCard("Normal", "ok")
        self.k_warn = KpiCard("Uyarı", "warn")
        self.k_alarm = KpiCard("Alarm", "alarm")
        for k in (self.k_total, self.k_motor, self.k_ok, self.k_warn, self.k_alarm):
            kpis.addWidget(k, 1)
        lay.addLayout(kpis)

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        self.filters = FilterBar(state, with_motor=True, with_fresh=True)
        self.filters.changed.connect(self.refresh)
        cl.addWidget(self.filters)

        # parametre odaklı görünüm
        prow = QHBoxLayout()
        prow.setSpacing(8)
        self.picker = ParamPicker(state, allow_auto=True, default_auto=True)
        self.picker.changed.connect(self.refresh)
        prow.addWidget(self.picker)
        prow.addSpacing(6)
        prow.addWidget(QLabel("Göster:"))
        self.show_mode = QComboBox()
        self.show_mode.addItems(SHOW_MODES)
        self.show_mode.currentIndexChanged.connect(self.refresh)
        prow.addWidget(self.show_mode)
        self.c_cols = QCheckBox("Parametre değerlerini sütun olarak göster")
        self.c_cols.setChecked(True)
        self.c_cols.toggled.connect(self.refresh)
        prow.addWidget(self.c_cols)
        prow.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Ara: analiz no, motor, yorum…")
        self.search.addAction(theme.icon("search"), QLineEdit.LeadingPosition)
        self.search.setMinimumWidth(280)
        self.search.textChanged.connect(self.refresh)
        prow.addWidget(self.search)
        cl.addLayout(prow)

        # en sık uyarı/alarm veren parametreler: tek tık filtre
        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(6)
        cl.addLayout(self.chips_row)

        self.table = QTableWidget(0, 0)
        style_table(self.table)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.open_selected)
        cl.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.info = hint("")
        bottom.addWidget(self.info, 1)
        b_open = button("Detay / Değerlendir", "samples", "primary")
        b_open.clicked.connect(self.open_selected)
        b_del = button("Sil", "trash", "danger")
        b_del.clicked.connect(self.delete_selected)
        bottom.addWidget(b_open)
        bottom.addWidget(b_del)
        cl.addLayout(bottom)
        lay.addWidget(card, 1)
        state.changed.connect(self.on_state_changed)
        self.refresh()

    def on_state_changed(self):
        self.filters.refresh_options()
        self.picker.reload()
        self.refresh()

    # ------------------------------------------------------------ yardımcı
    def _flagged(self, s, thr=1):
        """Numunede durumu >= thr olan parametre anahtarları."""
        return [k for k, e in self.state.evaluator.evaluate(s).items() if e.status is not None and e.status >= thr]

    def _rebuild_chips(self, rows):
        while self.chips_row.count():
            it = self.chips_row.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().setParent(None)
                it.widget().deleteLater()
        counts = {}
        for s in rows:
            if s.is_fresh:
                continue
            for k in self._flagged(s):
                counts[k] = counts.get(k, 0) + 1
        if not counts:
            return
        lab = QLabel("Sık uyarı/alarm:")
        lab.setObjectName("Hint")
        self.chips_row.addWidget(lab)
        sel = set(self.picker.keys) if not self.picker.auto else set()
        for k, n in sorted(counts.items(), key=lambda t: -t[1])[:10]:
            name = self.state.pmap[k].name.split(" (")[0] if k in self.state.pmap else k
            b = QPushButton(f"{name}  {n}")
            b.setProperty("variant", "chip")
            b.setCheckable(True)
            b.setChecked(sel == {k})
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.setMinimumWidth(b.sizeHint().width() + 8)
            b.setToolTip(f"Yalnızca {name} için uyarı/alarm veren numuneleri göster (tekrar tıklayınca kaldırılır)")
            b.clicked.connect(lambda _c=False, key=k: self._chip(key))
            self.chips_row.addWidget(b)
        self.chips_row.addStretch(1)

    def _chip(self, key):
        if not self.picker.auto and self.picker.keys == [key]:
            self.show_mode.blockSignals(True)
            self.show_mode.setCurrentIndex(0)
            self.show_mode.blockSignals(False)
            self.picker.set_auto()
            return
        self.show_mode.blockSignals(True)
        if self.show_mode.currentIndex() == 0:
            self.show_mode.setCurrentIndex(1)
        self.show_mode.blockSignals(False)
        self.picker.set_keys([key])

    # -------------------------------------------------------------- tablo
    def refresh(self):
        st = self.state
        ev = st.evaluator
        q = self.search.text().strip().lower()
        rows = self.filters.apply(st.samples)
        if q:
            rows = [s for s in rows if q in " ".join(
                str(x or "") for x in (s.sample_no, s.motor_no, s.user_comment, s.lab_comment,
                                        s.platform_code)).lower()]
        # KPI'lar ve çipler: durum filtresinden önceki küme
        counts = {0: 0, 1: 0, 2: 0}
        for s in rows:
            stt, _f = ev.overall(s)
            if stt in counts and not s.is_fresh:
                counts[stt] += 1
        self.k_total.set(sum(1 for s in rows if not s.is_fresh))
        self.k_motor.set(len({s.motor_no for s in rows if s.motor_no}))
        self.k_ok.set(counts[0])
        self.k_warn.set(counts[1])
        self.k_alarm.set(counts[2])
        self._rebuild_chips(rows)

        mode = self.show_mode.currentIndex()
        if mode:
            thr = mode  # 1: uyarı+alarm, 2: alarm
            if self.picker.auto:
                rows = [s for s in rows if not s.is_fresh and (ev.overall(s)[0] or 0) >= thr]
            else:
                keys = set(self.picker.keys)
                rows = [s for s in rows if keys & set(self._flagged(s, thr))]

        if self.picker.auto:
            flagged = set()
            for s in rows:
                flagged.update(self._flagged(s))
            pkeys = [p.key for p in st.params if p.key in flagged]
        else:
            pkeys = [k for k in (p.key for p in st.params) if k in set(self.picker.keys)]
        if not self.c_cols.isChecked():
            pkeys = []
        pkeys = pkeys[:MAX_PARAM_COLS]
        heads = BASE_COLUMNS + [self._short(k) for k in pkeys] + TAIL_COLUMNS
        nb = len(BASE_COLUMNS)

        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        for j, k in enumerate(pkeys):
            hi = self.table.horizontalHeaderItem(nb + j)
            hi.setToolTip(st.param_label(k))
        self.table.setRowCount(len(rows))
        for i, s in enumerate(reversed(rows)):
            status, flagged_names = ev.overall(s)
            evs = ev.evaluate(s)
            if s.stats_excluded:
                excl, excl_tip = "⊘ tümü", "Numune istatistiklerden tamamen hariç" + (
                    f": {s.stats_note}" if s.stats_note else "")
            elif s.excluded:
                excl = f"⊘ {len(s.excluded)}"
                excl_tip = "İstatistik dışı: " + ", ".join(
                    st.pmap[k].name.split(" (")[0] if k in st.pmap else k for k in s.excluded)
            else:
                excl, excl_tip = "", None
            head = [
                ro_item("Sıfır Yağ" if s.is_fresh else STATUS_TEXT[status],
                        -1 if status is None else status, None if s.is_fresh else status),
                ro_item(s.sample_no),
                ro_item(s.motor_no or ""),
            ]
            pcells = []
            for k in pkeys:
                v = s.values.get(k)
                e = evs.get(k)
                if v is None:
                    pcells.append(ro_item("", None))
                    continue
                txt = fmt_num(v) + (" ⊘" if s.is_excluded(k) else "")
                tip = [st.param_label(k) + f": {fmt_num(v, 3)}"]
                if e is not None:
                    tip.append("Durum: " + STATUS_TEXT.get(e.status, "—"))
                    tip.extend(e.reasons)
                pcells.append(ro_item(txt, v, None if s.is_fresh or e is None else
                                      (e.status if e.status in (1, 2) else None), tooltip="\n".join(tip)))
            tail = [
                ro_item(format_date(s.date_taken), s.date_taken or ""),
                ro_item(fmt_num(s.motor_hours), s.motor_hours),
                ro_item(fmt_num(s.oil_hours), s.oil_hours),
                ro_item(s.platform_code or ""),
                ro_item(s.platform_group if s.platform_code else ""),
                ro_item(s.sample_type),
                ro_item(s.oil_type or ""),
                ro_item(s.lab_diagnosis or s.lab_diag_letter or "",
                        status=SGS_STATUS.get(s.lab_diagnosis),
                        tooltip=("SGS (analiz firması) teşhisi:\n" + (s.lab_comment or ""))
                        if (s.lab_comment or s.lab_diagnosis) else None),
                ro_item(", ".join(flagged_names), len(flagged_names), tooltip="\n".join(flagged_names) or None),
                ro_item(excl, len(s.excluded) + (100 if s.stats_excluded else 0), tooltip=excl_tip),
                ro_item((s.user_comment or "").replace("\n", " ")),
            ]
            for c, it in enumerate(head + pcells + tail):
                if c == 0:
                    it.setData(Qt.UserRole, s.id)
                    it.setTextAlignment(Qt.AlignCenter)
                elif nb <= c < nb + len(pkeys):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, c, it)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(80, self.table.columnWidth(0)))
        dcol = nb + len(pkeys) + TAIL_COLUMNS.index("Dikkat Gerektirenler")
        self.table.setColumnWidth(dcol, min(self.table.columnWidth(dcol), 260))
        for j in range(len(pkeys)):
            self.table.setColumnWidth(nb + j, max(62, self.table.columnWidth(nb + j)))
        extra = (f" • {len(pkeys)} parametre sütunu (renk: hücredeki parametrenin durumu; üzerine gelince neden)"
                 if pkeys else "")
        self.info.setText(f"{len(rows)} kayıt listeleniyor{extra}. Çift tıklayarak detay ve parça tahminini açın.")

    def _short(self, key):
        p = self.state.pmap.get(key)
        if p is None:
            return key
        if "(" in p.name and p.unit == "ppm":
            return p.name.split(" (")[0]  # element sembolü
        return p.name.replace("Viskozite ", "Visk. ").replace(" İndeksi", " İnd.")

    def _selected_ids(self):
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            it = self.table.item(idx.row(), 0)
            if it is not None:
                ids.append(it.data(Qt.UserRole))
        return ids

    def open_selected(self, *_):
        ids = self._selected_ids()
        if not ids:
            return
        s = next((x for x in self.state.samples if x.id == ids[0]), None)
        if s is not None:
            SampleDialog(self.state, s, self).exec()

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        if QMessageBox.question(self, "Sil", f"{len(ids)} numune silinsin mi?") != QMessageBox.Yes:
            return
        for sid in ids:
            self.state.db.delete_sample(sid)
        self.state.reload()


class SampleDialog(QDialog):
    """Numune bilgileri, ölçümler, limitler, parça tahmini, SGS yorumu ve kullanıcı değerlendirmesi."""

    EXCL_COL = 1

    def __init__(self, state: AppState, s: Sample, parent=None):
        super().__init__(parent)
        self.state, self.s = state, s
        self.setWindowTitle(f"Numune {s.sample_no}")
        self.resize(1320, 820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split, 1)

        # ----- sol: bilgiler ve yorumlar
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        g = QGroupBox("Numune Bilgileri")
        form = QFormLayout(g)
        self.e_motor = QLineEdit(s.motor_no or "")
        self.e_platform = QComboBox()
        self.e_platform.setEditable(True)
        self.e_platform.addItems([""] + sorted(state.platforms))
        self.e_platform.setCurrentText(s.platform_code or "")
        self.e_type = QComboBox()
        self.e_type.addItems(SAMPLE_TYPES)
        self.e_type.setCurrentText(s.sample_type)
        self.e_oil = QComboBox()
        self.e_oil.setEditable(True)
        self.e_oil.addItems([""] + state.oil_types())
        self.e_oil.setCurrentText(s.oil_type or "")
        self.e_date = QLineEdit(format_date(s.date_taken))
        self.e_mh = QLineEdit(fmt_num(s.motor_hours))
        self.e_oh = QLineEdit(fmt_num(s.oil_hours))
        form.addRow("Analiz No:", QLabel(f"<b>{s.sample_no}</b>  <span style='color:gray'>"
                                         f"{s.origin or ''}</span>"))
        form.addRow("Motor No:", self.e_motor)
        form.addRow("Platform:", self.e_platform)
        grp = state.platforms.get(s.platform_code or "", "") if s.platform_code else ""
        form.addRow("Platform grubu:", QLabel(grp or "— (Ayarlar > Platformlar)"))
        form.addRow("Numune tipi:", self.e_type)
        form.addRow("Yağ tipi:", self.e_oil)
        form.addRow("Numune tarihi:", self.e_date)
        form.addRow("Motor çalışma (sa):", self.e_mh)
        form.addRow("Yağ çalışma (sa):", self.e_oh)
        if s.lubricant:
            form.addRow("Yağ:", QLabel(s.lubricant))
        self.c_sample_excl = QCheckBox("Bu numuneyi istatistiklerden tamamen hariç tut")
        self.c_sample_excl.setChecked(s.stats_excluded)
        self.c_sample_excl.setToolTip("Ortalama, min/max ve limit hesaplarına katılmaz; "
                                      "kendisi yine değerlendirilir.")
        form.addRow(self.c_sample_excl)
        self.e_sample_note = QLineEdit(s.stats_note or "")
        self.e_sample_note.setPlaceholderText("Hariç tutma nedeni (ör. numune kontamine)")
        form.addRow("Neden:", self.e_sample_note)
        ll.addWidget(g)

        sg = QGroupBox("SGS (Analiz Firması) Değerlendirmesi — bilgi amaçlı")
        sl = QVBoxLayout(sg)
        diag = s.lab_diagnosis or "-"
        if s.lab_diag_letter:
            diag += f"  (SGS kodu: {s.lab_diag_letter})"
        sl.addWidget(QLabel(f"SGS teşhisi: <b>{diag}</b>"))
        lab = QTextEdit(s.lab_comment or "")
        lab.setReadOnly(True)
        lab.setMaximumHeight(100)
        sl.addWidget(lab)
        if s.lab_info:
            info = hint("; ".join(f"{k}: {v}" for k, v in s.lab_info.items()))
            sl.addWidget(info)
        ll.addWidget(sg)

        ug = QGroupBox("Değerlendirme Yorumu (kullanıcı)")
        ul = QVBoxLayout(ug)
        self.e_comment = QTextEdit(s.user_comment or "")
        ul.addWidget(self.e_comment)
        ll.addWidget(ug, 1)
        split.addWidget(left)

        # ----- sağ: ölçümler + parça tahmini
        tabs = QTabWidget()
        tabs.addTab(self._values_page(), theme.icon("stats"), "Ölçümler ve Limitler")
        tabs.addTab(self._parts_page(), theme.icon("parts"), "Parça Tahmini")
        split.addWidget(tabs)
        split.setSizes([400, 920])

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Save).setText("Kaydet")
        bb.button(QDialogButtonBox.Save).setProperty("variant", "primary")
        bb.button(QDialogButtonBox.Close).setText("Kapat")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    # ------------------------------------------------------------ ölçümler
    def _values_page(self):
        st, s = self.state, self.s
        w = QWidget()
        rl = QVBoxLayout(w)
        rl.setContentsMargins(10, 10, 10, 10)
        _pop, desc = st.evaluator.ref_population(s)
        status, _ = st.evaluator.overall(s)
        rl.addWidget(QLabel(f"Genel durum: <b>{STATUS_TEXT[status]}</b>   •   Referans grubu: {desc}"
                            f"   •   Hız: ppm / 100 sa yağ çalışması"))
        heads = ["Parametre", "İst. hariç", "Değer", "Durum", "Uyarı limiti", "Alarm limiti",
                 "Sıfır yağ", "Değişim %", "Artış hızı", "Hız uyarı/alarm", "Açıklama"]
        self.table = QTableWidget(0, len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        style_table(self.table)
        self.table.horizontalHeader().setStretchLastSection(True)
        rl.addWidget(self.table, 1)
        rl.addWidget(hint("'Değer' düzenlenebilir (okuma hatası düzeltmek için; boş bırakılan değer silinir). "
                          "'İst. hariç' işaretli değerler ortalama, min/max ve limit "
                          "hesaplarına katılmaz; numunenin kendi değerlendirmesi yine yapılır."))
        self._fill_values()
        return w

    def _fill_values(self):
        st, s = self.state, self.s
        ev = st.evaluator.evaluate(s)
        keys = [p.key for p in st.params if p.key in s.values or p.key in s.raws]
        self.table.setRowCount(len(keys))
        self._row_keys = keys
        for i, key in enumerate(keys):
            e = ev.get(key)
            raw = s.raws.get(key)
            v = s.values.get(key)
            name = ro_item(st.param_label(key))
            excl = QTableWidgetItem(s.excluded.get(key, "") if key in s.excluded else "")
            excl.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
            excl.setCheckState(Qt.Checked if key in s.excluded else Qt.Unchecked)
            excl.setToolTip("İşaretleyin ve isterseniz hücreye neden yazın")
            val = QTableWidgetItem(fmt_num(v, 3) if v is not None else (raw or ""))
            stt = e.status if e else None
            lim = e.limits if e else None
            rl = e.rate_limits if e else None

            def lim_txt(lo, hi):
                parts = []
                if lo is not None:
                    parts.append(f"< {fmt_num(lo)}")
                if hi is not None:
                    parts.append(f"> {fmt_num(hi)}")
                return "  ".join(parts)

            items = [
                name, excl, val,
                ro_item(STATUS_TEXT.get(stt, "—"), status=stt),
                ro_item(lim_txt(lim.lo_warn, lim.hi_warn) if lim else "",
                        tooltip=lim.note if lim else None),
                ro_item(lim_txt(lim.lo_alarm, lim.hi_alarm) if lim else "",
                        tooltip=lim.note if lim else None),
                ro_item(fmt_num(e.fresh) if e else ""),
                ro_item(f"{e.change_pct:+.0f}" if e and e.change_pct is not None else ""),
                ro_item(fmt_num(e.rate) if e and e.rate is not None else ""),
                ro_item(f"{fmt_num(rl.hi_warn)} / {fmt_num(rl.hi_alarm)}" if rl and rl.valid else "",
                        tooltip=rl.note if rl else None),
                ro_item("; ".join(e.reasons) if e else "",
                        tooltip="\n".join(e.reasons) if e and e.reasons else None),
            ]
            if stt in (1, 2):
                paint_status(val, stt)
            if key in s.excluded or s.stats_excluded:
                name.setForeground(QColor(theme.token("status_excluded_fg", "#94a3b8")))
                name.setText(name.text() + "  ⊘")
                name.setToolTip("İstatistik hesaplarına katılmıyor")
            for c, it in enumerate(items):
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()

    # ------------------------------------------------------- parça tahmini
    def _parts_page(self):
        st, s = self.state, self.s
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        changes, ranked = diagnose(s, st.evaluator, st.db.part_sources(), st.settings)
        prev = st.evaluator.previous_sample(s)
        lay.addWidget(hint(
            f"Önceki numune: <b>{prev.sample_no if prev else '—'}</b>"
            f"{' (' + format_date(prev.date_taken) + ')' if prev and prev.date_taken else ''}. "
            f"Anlamlı değişim: önceki numuneye göre ≥ %{st.settings.get('change_rel', 50):g} ve "
            f"≥ {st.settings.get('change_abs', 2):g} birim artış, veya uyarı/alarm. "
            "Kaynak parçalar 'Malzeme Kaynakları' sayfasında tanımlanır."))

        t1 = QLabel("Miktarı değişen / dikkat gerektiren malzemeler")
        t1.setObjectName("SectionTitle")
        lay.addWidget(t1)
        ct = QTableWidget(len(changes), 7)
        ct.setHorizontalHeaderLabels(["Malzeme", "Önceki", "Şimdi", "Δ", "Δ %", "Durum", "Olası kaynak parçalar"])
        style_table(ct)
        ct.horizontalHeader().setStretchLastSection(True)
        for i, c in enumerate(changes):
            parts = ", ".join(p["part"] for p in c.parts) or "— tanımlı kaynak yok"
            cells = [ro_item(st.param_label(c.key), tooltip=c.reason), ro_item(fmt_num(c.prev)),
                     ro_item(fmt_num(c.value)), ro_item(fmt_num(c.delta) if c.delta is not None else ""),
                     ro_item(f"{c.pct:+.0f}" if c.pct is not None else ""),
                     ro_item(STATUS_TEXT.get(c.status, "—"), status=c.status),
                     ro_item(parts, tooltip="\n".join(f"{p['part']}: {p['note']}" if p["note"] else p["part"]
                                                      for p in c.parts) or c.reason)]
            for j, it in enumerate(cells):
                ct.setItem(i, j, it)
        ct.resizeColumnsToContents()
        lay.addWidget(ct, 1)

        t2 = QLabel("En olası kaynak parçalar (birden çok malzemenin işaret ettiği parça üstte)")
        t2.setObjectName("SectionTitle")
        lay.addWidget(t2)
        pt = QTableWidget(len(ranked), 4)
        pt.setHorizontalHeaderLabels(["Parça", "Puan", "İşaret eden malzemeler", "Notlar"])
        style_table(pt)
        pt.horizontalHeader().setStretchLastSection(True)
        top = ranked[0].score if ranked else 1
        for i, p in enumerate(ranked):
            stt = 2 if p.score >= top and len(p.elements) > 1 else (1 if p.score >= 0.6 * top else None)
            cells = [ro_item(p.part, status=stt), ro_item(f"{p.score:g}", p.score),
                     ro_item(", ".join(p.elements)), ro_item("; ".join(dict.fromkeys(p.notes)))]
            for j, it in enumerate(cells):
                pt.setItem(i, j, it)
        pt.resizeColumnsToContents()
        lay.addWidget(pt, 1)
        lay.addWidget(hint("Puan: alarm 3, uyarı 2, yalnızca artış 1 — malzeme başına toplanır. "
                           "Bu bir ön tahmindir; kesin teşhis için muayene gerekir."))
        if not changes:
            lay.addWidget(hint("Bu numunede anlamlı değişim veya uyarı yok."))
        return w

    def save(self):
        values = {}
        excl_changes = []
        for i, key in enumerate(self._row_keys):
            new = self.table.item(i, 2).text().strip()
            old = self.s.values.get(key)
            old_txt = fmt_num(old, 3) if old is not None else (self.s.raws.get(key) or "")
            if new != old_txt:
                values[key] = new
            it = self.table.item(i, self.EXCL_COL)
            want = it.checkState() == Qt.Checked
            note = it.text().strip()
            if want != (key in self.s.excluded) or (want and note != self.s.excluded.get(key, "")):
                excl_changes.append((key, want, note))
        meta = {
            "platform_code": self.e_platform.currentText(),
            "sample_type": self.e_type.currentText(),
            "oil_type": self.e_oil.currentText(),
            "date_taken": self.e_date.text(),
            "motor_hours": self.e_mh.text(),
            "oil_hours": self.e_oh.text(),
            "user_comment": self.e_comment.toPlainText().strip() or None,
        }
        db = self.state.db
        db.update_sample(self.s.id, self.e_motor.text(), meta, values)
        for key, want, note in excl_changes:
            db.set_excluded(self.s.id, key, want, note, commit=False)
        db.commit()
        db.set_sample_excluded(self.s.id, self.c_sample_excl.isChecked(), self.e_sample_note.text().strip())
        self.state.reload()
        self.accept()
