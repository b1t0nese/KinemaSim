"""Интерфейс главного окна: панель настроек, график траектории с проигрыванием
полёта, панели телеметрии и итогов, история запусков, графики анализа и таблица
данных. Логика симуляции живёт в physics/, оркестрация — в main.py."""

import csv
from contextlib import contextmanager
from dataclasses import dataclass
from math import hypot

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QShortcut, QKeySequence
from PySide6.QtWidgets import (QMainWindow, QWidget, QHeaderView, QFileDialog,
                               QAbstractItemView, QMessageBox, QTableWidgetItem)

from ui_loader import loadUi, resource_path
from physics.config import SimulationConfig, INTEGRATORS, INTEGRATOR_NAMES, SOUND_SPEED
from physics.presets import PROJECTILE_PRESETS, ENVIRONMENT_PRESETS
from .chart import ChartWidget

RUN_COLORS = ["#5b8cff", "#ff6b6b", "#3ecf8e", "#ffd166", "#c792ea", "#4dd0e1",
              "#ff9f43", "#7bed9f", "#ff7ab6", "#95de64", "#64b5f6", "#f06292"]
MAX_TABLE_ROWS = 3000
CUSTOM_PRESET = "— вручную —"


@contextmanager
def block_signals(*widgets):
    """Временно глушит сигналы виджетов (чтобы программная установка значений
    не сбрасывала пресеты и не порождала каскадов)."""
    states = [w.blockSignals(True) for w in widgets]
    try:
        yield
    finally:
        for w, state in zip(widgets, states):
            w.blockSignals(state)


# ─── Форматирование чисел ────────────────────────────────────────────

def fmt_num(value: float, unit: str="") -> str:
    """Число с адаптивной точностью и пробелом-разделителем тысяч."""
    negative = value < 0
    value = abs(value)
    if value >= 100:
        text = f"{value:,.1f}"
    elif value >= 1:
        text = f"{value:,.2f}"
    elif value >= 0.01:
        text = f"{value:.3f}"
    else:
        text = f"{value:.5f}"
    text = text.replace(",", " ")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "":
        text = "0"
    return ("-" if negative else "") + text + (f" {unit}" if unit else "")


def fmt_dist(meters: float) -> str:
    return (fmt_num(meters / 1000, "км") if abs(meters) >= 1000
            else fmt_num(meters, "м"))


def fmt_energy(joules: float) -> str:
    return (fmt_num(joules / 1000, "кДж") if abs(joules) >= 1000
            else fmt_num(joules, "Дж"))


def _table_item(text: str, dim: bool=False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if dim:
        item.setForeground(QColor("#98a2b3"))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


# ─── Панель настроек ─────────────────────────────────────────────────

class SettingsPanel(QWidget):
    """Все параметры симуляции + пресеты. Отдаёт/принимает SimulationConfig."""
    run_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        loadUi(resource_path("interface_module", "uis", "widgets", "settings_panel.ui"), self)

        self.combo_preset.addItems([CUSTOM_PRESET, *PROJECTILE_PRESETS.keys()])
        self.combo_environment.addItems([CUSTOM_PRESET, *ENVIRONMENT_PRESETS.keys()])
        self.combo_integrator.addItems([INTEGRATOR_NAMES[i] for i in INTEGRATORS])
        self.combo_integrator.setCurrentIndex(INTEGRATORS.index(SimulationConfig().integrator))

        self.combo_preset.currentTextChanged.connect(self._apply_projectile_preset)
        self.combo_environment.currentTextChanged.connect(self._apply_environment_preset)
        self.btn_run.clicked.connect(self.run_requested.emit)

        # ручное редактирование любого поля сбрасывает пресеты в «вручную»
        all_fields = (*self._all_spins(), self.cb_drag, self.cb_magnus, self.cb_buoyancy,
                      self.cb_bounces, self.cb_target)
        for field in all_fields:
            if isinstance(field, type(self.cb_drag)):  # QCheckBox
                field.toggled.connect(self._mark_custom)
            else:
                field.valueChanged.connect(self._mark_custom)
        self.cb_auto_dt.toggled.connect(
            lambda checked: self.spin_dt.setEnabled(not checked))

    def _all_spins(self) -> tuple:
        return (self.spin_speed, self.spin_angle, self.spin_height, self.spin_mass,
                self.spin_diameter, self.spin_drag, self.spin_spin_rpm, self.spin_gravity,
                self.spin_air_density, self.spin_scale_height, self.spin_wind, self.spin_dt,
                self.spin_max_time, self.spin_restitution, self.spin_target_distance,
                self.spin_target_height, self.spin_target_size)

    def _mark_custom(self, *_):
        for combo in (self.combo_preset, self.combo_environment):
            if combo.currentText() != CUSTOM_PRESET:
                with block_signals(combo):
                    combo.setCurrentText(CUSTOM_PRESET)

    def _apply_projectile_preset(self, name: str):
        preset = PROJECTILE_PRESETS.get(name)
        if preset is None:
            return
        with block_signals(self, *self._all_spins()):
            for field, value in preset.items():
                if hasattr(self, f"spin_{field}"):
                    getattr(self, f"spin_{field}").setValue(value)
                elif hasattr(self, f"cb_{field}"):
                    getattr(self, f"cb_{field}").setChecked(value)

    def _apply_environment_preset(self, name: str):
        preset = ENVIRONMENT_PRESETS.get(name)
        if preset is None:
            return
        with block_signals(self, self.spin_gravity, self.spin_air_density, self.spin_scale_height):
            self.spin_gravity.setValue(preset["gravity"])
            self.spin_air_density.setValue(preset["air_density"])
            self.spin_scale_height.setValue(preset["density_scale_height"] / 1000)

    def collect_config(self) -> SimulationConfig:
        """Собирает SimulationConfig из полей панели."""
        config = SimulationConfig(
            speed=self.spin_speed.value(), angle=self.spin_angle.value(),
            height=self.spin_height.value(),
            mass=self.spin_mass.value(), diameter=self.spin_diameter.value(),
            drag_coefficient=self.spin_drag.value(), spin_rpm=self.spin_spin_rpm.value(),
            gravity=self.spin_gravity.value(), air_density=self.spin_air_density.value(),
            density_scale_height=self.spin_scale_height.value() * 1000,
            wind_speed=self.spin_wind.value(),
            integrator=INTEGRATORS[self.combo_integrator.currentIndex()],
            dt=self.spin_dt.value(), auto_dt=self.cb_auto_dt.isChecked(),
            max_time=self.spin_max_time.value(),
            use_drag=self.cb_drag.isChecked(), use_magnus=self.cb_magnus.isChecked(),
            use_buoyancy=self.cb_buoyancy.isChecked(),
            use_bounces=self.cb_bounces.isChecked(),
            restitution=self.spin_restitution.value(),
            target_enabled=self.cb_target.isChecked(),
            target_distance=self.spin_target_distance.value(),
            target_height=self.spin_target_height.value(),
            target_size=self.spin_target_size.value(),
        )
        if config.auto_dt:
            with block_signals(self.spin_dt):
                self.spin_dt.setValue(config.suggest_dt())
        return config

    def apply_config(self, config: SimulationConfig):
        with block_signals(self, *self._all_spins(), self.combo_integrator, self.cb_auto_dt,
                           self.cb_drag, self.cb_magnus, self.cb_buoyancy, self.cb_bounces,
                           self.cb_target):
            self.spin_speed.setValue(config.speed); self.spin_angle.setValue(config.angle)
            self.spin_height.setValue(config.height); self.spin_mass.setValue(config.mass)
            self.spin_diameter.setValue(config.diameter)
            self.spin_drag.setValue(config.drag_coefficient)
            self.spin_spin_rpm.setValue(config.spin_rpm)
            self.spin_gravity.setValue(config.gravity)
            self.spin_air_density.setValue(config.air_density)
            self.spin_scale_height.setValue(config.density_scale_height / 1000)
            self.spin_wind.setValue(config.wind_speed)
            self.combo_integrator.setCurrentIndex(INTEGRATORS.index(config.integrator))
            self.cb_auto_dt.setChecked(config.auto_dt)
            self.spin_dt.setValue(config.suggest_dt() if config.auto_dt else config.dt)
            self.spin_dt.setEnabled(not config.auto_dt)
            self.spin_max_time.setValue(config.max_time)
            self.cb_drag.setChecked(config.use_drag); self.cb_magnus.setChecked(config.use_magnus)
            self.cb_buoyancy.setChecked(config.use_buoyancy)
            self.cb_bounces.setChecked(config.use_bounces)
            self.spin_restitution.setValue(config.restitution)
            self.cb_target.setChecked(config.target_enabled)
            self.spin_target_distance.setValue(config.target_distance)
            self.spin_target_height.setValue(config.target_height)
            self.spin_target_size.setValue(config.target_size)
            self.combo_preset.setCurrentText(CUSTOM_PRESET)
            self.combo_environment.setCurrentText(CUSTOM_PRESET)


# ─── Панель воспроизведения ──────────────────────────────────────────

class PlaybackBar(QWidget):
    """Транспорт: играть/пауза/стоп/шаг + прокрутка времени + скорость."""
    play_toggled = Signal(bool)
    stopped = Signal()
    stepped = Signal(float)
    time_scrubbed = Signal(float)
    speed_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        loadUi(resource_path("interface_module", "uis", "widgets", "playback_bar.ui"), self)

        self.slider_time.setRange(0, 1000)
        self.slider_time.valueChanged.connect(self._on_scrub)
        self.btn_play.clicked.connect(lambda: self.play_toggled.emit(not self._playing))
        self.btn_stop.clicked.connect(self.stopped.emit)
        self.btn_step.clicked.connect(lambda: self.stepped.emit(self.step_time()))
        self.btn_step_back.clicked.connect(lambda: self.stepped.emit(-self.step_time()))
        self.slider_speed.setValue(465)  # ≈×1.0 на логарифмической шкале
        self.slider_speed.valueChanged.connect(self._on_speed)
        self._flight_time = 0.0
        self._playing = False

    def step_time(self) -> float:
        """Длительность одного шага: 1/300 полёта (не меньше миллисекунды)."""
        return max(self._flight_time / 300, 0.001)

    def _on_scrub(self, value: int):
        self.time_scrubbed.emit(value / 1000 * self._flight_time)

    def _on_speed(self, value: int):
        """Логарифмическая шкала скорости 0.05× – 50×."""
        speed = 0.05 * (1000 ** (value / 1000))
        self.label_speed.setText(f"×{speed:.5g}")
        self.speed_changed.emit(speed)

    def set_playing(self, playing: bool):
        self._playing = playing
        self.btn_play.setText("⏸ Пауза" if playing else "▶ Играть")
        self.btn_play.setProperty("playing", playing)
        self.btn_play.style().unpolish(self.btn_play)
        self.btn_play.style().polish(self.btn_play)

    def set_flight_time(self, flight_time: float):
        self._flight_time = flight_time
        self.set_time(flight_time, flight_time)

    def set_time(self, time: float, flight_time: float):
        self.label_time.setText(f"t = {time:,.3f} / {flight_time:,.3f} с".replace(",", " "))
        fraction = time / flight_time if flight_time > 0 else 0.0
        with block_signals(self.slider_time):
            self.slider_time.setValue(int(fraction * 1000))


# ─── Панель итогов ───────────────────────────────────────────────────

class ResultsPanel(QWidget):
    """Телеметрия в реальном времени + таблица итогов полёта."""

    def __init__(self, parent=None):
        super().__init__(parent)
        loadUi(resource_path("interface_module", "uis", "widgets", "results_panel.ui"), self)
        self.table_results.setColumnCount(2)
        self.table_results.setHorizontalHeaderLabels(["Параметр", "Значение"])
        self.table_results.verticalHeader().setVisible(False)
        self.table_results.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_results.horizontalHeader().setStretchLastSection(True)
        self.table_results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_results.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table_results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table_results.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table_results.setRowCount(1)
        self.table_results.setItem(0, 0, _table_item("🚀"))
        self.table_results.setItem(0, 1, _table_item("запустите симуляцию", dim=True))

    def set_telemetry(self, index: int, result):
        """Значения величин в точке траектории с индексом index."""
        t, x, y = result.t[index], result.x[index], result.y[index]
        vx, vy = result.vx[index], result.vy[index]
        speed = hypot(vx, vy)
        energy = (result.config.mass * speed ** 2 / 2
                  + result.config.mass * result.config.gravity * y)
        mach = speed / SOUND_SPEED
        self.val_t.setText(fmt_num(t, "с")); self.val_x.setText(fmt_dist(x))
        self.val_y.setText(fmt_dist(y)); self.val_v.setText(fmt_num(speed, "м/с"))
        self.val_vx.setText(fmt_num(vx, "м/с")); self.val_vy.setText(fmt_num(vy, "м/с"))
        self.val_mach.setText(f"{mach:.2f}" + (" ⚡" if mach >= 1 else ""))
        self.val_energy.setText(fmt_energy(energy))

    def set_results(self, result):
        """Заполняет таблицу итогов полёта."""
        r = result.results
        rows = [
            ("Дальность", fmt_dist(r["range"])),
            ("Время полёта", fmt_num(r["flight_time"], "с")),
            ("Максимальная высота", fmt_dist(r["max_height"])),
            ("Апогей через", fmt_num(r["apogee_time"], "с")),
            ("Скорость падения", fmt_num(r["impact_speed"], "м/с")),
            ("Угол падения", fmt_num(r["impact_angle"], "°")),
            ("Энергия при ударе", fmt_energy(r["impact_energy"])),
            ("Дальность без воздуха", fmt_dist(r["vacuum_range"])),
            ("Потеря из-за воздуха", fmt_dist(r["drag_loss"])),
            ("Отскоков", str(r["bounces"])),
        ]
        if result.config.target_enabled:
            if r["target_hit"]:
                rows.append(("🎯 Цель", f"ПОПАДАНИЕ (откл. {fmt_num(r['target_deviation'], 'м')})"))
            elif r["target_deviation"] is None:
                rows.append(("🎯 Цель", "не долетел"))
            else:
                rows.append(("🎯 Цель", f"промах на {fmt_num(abs(r['target_deviation']), 'м')}"))
        rows.append(("Статус", result.status))
        table = self.table_results
        table.setRowCount(len(rows))
        for row, (name, value) in enumerate(rows):
            table.setItem(row, 0, _table_item(name))
            table.setItem(row, 1, _table_item(value))
        table.resizeRowsToContents()


# ─── История запусков ────────────────────────────────────────────────

@dataclass
class RunRecord:
    """Один запуск: результат, имя, цвет на графике и видимость."""
    name: str
    color: str
    result: object
    visible: bool = True


class RunsPanel(QWidget):
    """Таблица запусков: галочка слева — показывать траекторию, клик по строке —
    сделать запуск активным (графики, телеметрия, таблица данных)."""
    run_selected = Signal(int)
    runs_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        loadUi(resource_path("interface_module", "uis", "widgets", "runs_panel.ui"), self)
        self.table_runs.setColumnCount(5)
        self.table_runs.setHorizontalHeaderLabels(["", "Запуск", "Дальность", "Высота", "t полёта"])
        self.table_runs.verticalHeader().setVisible(False)
        self.table_runs.setSortingEnabled(False)  # порядок строк = порядок записей
        header = self.table_runs.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table_runs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table_runs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_runs.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_runs.cellClicked.connect(self._on_click)
        self.btn_delete_run.clicked.connect(self._delete_selected)
        self.btn_clear_runs.clicked.connect(self.clear)
        self.records: list[RunRecord] = []
        self.active_index = -1

    def add(self, record: RunRecord) -> int:
        self.records.append(record)
        self.active_index = len(self.records) - 1
        self._refresh()
        return self.active_index

    def _on_click(self, row: int, column: int):
        if not 0 <= row < len(self.records):
            return
        if column == 0:  # галочка видимости
            self.records[row].visible = not self.records[row].visible
        else:
            self.active_index = row
        self._refresh()
        self.runs_changed.emit()
        self.run_selected.emit(self.active_index)

    def _delete_selected(self):
        row = self.table_runs.currentRow()
        if 0 <= row < len(self.records):
            del self.records[row]
            self.active_index = min(self.active_index, len(self.records) - 1)
            self._refresh()
            self.runs_changed.emit()
            if self.records:
                self.run_selected.emit(self.active_index)

    def clear(self):
        self.records.clear()
        self.active_index = -1
        self._refresh()
        self.runs_changed.emit()

    def active(self) -> RunRecord | None:
        if 0 <= self.active_index < len(self.records):
            return self.records[self.active_index]
        return None

    def _refresh(self):
        table = self.table_runs
        table.setRowCount(len(self.records))
        for row, record in enumerate(self.records):
            visible_item = _table_item("●" if record.visible else "○")
            visible_item.setForeground(QColor(record.color))
            visible_item.setToolTip("Клик — показать/скрыть траекторию")
            name_item = _table_item(record.name)
            name_item.setForeground(QColor(record.color if record.visible else "#98a2b3"))
            if row == self.active_index:
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
            table.setItem(row, 0, visible_item)
            table.setItem(row, 1, name_item)
            for column, text in ((2, fmt_dist(record.result.results["range"])),
                                 (3, fmt_dist(record.result.results["max_height"])),
                                 (4, fmt_num(record.result.results["flight_time"], "с"))):
                table.setItem(row, column, _table_item(text, dim=True))


# ─── Главное окно ────────────────────────────────────────────────────

class MainWindowUI(QMainWindow):
    """Собирает всё вместе: настройки слева, вкладки справа, проигрывание снизу."""
    simulation_requested = Signal()

    def __init__(self):
        super().__init__()
        loadUi(resource_path("interface_module", "uis", "mainwindow.ui"), self)

        self.settings_panel = SettingsPanel()
        self.settings_scroll_content.layout().addWidget(self.settings_panel)

        self.playback_bar = PlaybackBar()
        self.playback_layout.addWidget(self.playback_bar)

        self.results_panel = ResultsPanel()
        self.results_layout.addWidget(self.results_panel)

        self.runs_panel = RunsPanel()
        self.runs_layout.addWidget(self.runs_panel)

        self.chart = ChartWidget()
        self.chart.ground_y = 0.0
        self.chart.x_label = "x, м"
        self.chart.y_label = "y, м"
        self.chart.setToolTip("Колесо — зум, ЛКМ — сдвиг, двойной клик — сброс вида.\nНаведите на траекторию, чтобы увидеть значения.")
        self.chart_layout.addWidget(self.chart)

        self.analysis_charts = {}
        for key, title, x_label, y_label in (
                ("h", "Высота — время", "t, с", "y, м"),
                ("v", "Скорость — время", "t, с", "|v|, м/с"),
                ("e", "Энергия — время", "t, с", "E, Дж"),
                ("a", "Ускорение — время", "t, с", "|a|, м/с²")):
            chart = ChartWidget()
            chart.x_label, chart.y_label = x_label, y_label
            chart.setToolTip(f"{title}: колесо — зум, ЛКМ — сдвиг, двойной клик — сброс")
            self.analysis_charts[key] = chart
            self.findChild(QWidget, f"chart_{key}_container").layout().addWidget(chart)

        self.splitter_main.setStretchFactor(0, 3)
        self.splitter_main.setStretchFactor(1, 1)
        self.splitter_main.setSizes([1000, 380])

        self.table_data.setColumnCount(7)
        self.table_data.setHorizontalHeaderLabels(
            ["t, с", "x, м", "y, м", "vx, м/с", "vy, м/с", "|v|, м/с", "|a|, м/с²"])
        self.table_data.verticalHeader().setVisible(False)
        self.table_data.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_data.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_data.setAlternatingRowColors(True)

        self._play_timer = QTimer(self, interval=16)
        self._play_timer.timeout.connect(self._tick)
        self._play_speed = 1.0
        self._play_time = 0.0

        self.settings_panel.run_requested.connect(self.simulation_requested.emit)
        self.playback_bar.play_toggled.connect(self.toggle_play)
        self.playback_bar.stopped.connect(self.stop_playback)
        self.playback_bar.stepped.connect(self.step_playback)
        self.playback_bar.time_scrubbed.connect(self.seek)
        self.playback_bar.speed_changed.connect(self.set_playback_speed)
        self.runs_panel.runs_changed.connect(self._update_all_charts)
        self.runs_panel.run_selected.connect(self._select_run)

        self.cb_equal_scale.toggled.connect(self._apply_chart_options)
        self.cb_show_vectors.toggled.connect(self._apply_chart_options)
        self.cb_show_grid.toggled.connect(self._apply_chart_options)
        self.btn_reset_view.clicked.connect(self._reset_views)
        self.btn_export_png.clicked.connect(self.export_png)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_play_shortcut)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.step_playback())
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.step_playback(back=True))

        self.statusBar().showMessage("Готово к запуску 🚀")
        self.chart.hoverMoved.connect(self._on_chart_hover)
        self._apply_chart_options()

    # ─── Симуляция и история ─────────────────────────────────────────

    def add_run(self, result, name: str) -> int:
        """Добавляет результат в историю, делает его активным и проигрывает полёт."""
        color = RUN_COLORS[len(self.runs_panel.records) % len(RUN_COLORS)]
        index = self.runs_panel.add(RunRecord(name=name, color=color, result=result))
        self._select_run(index)
        self._update_all_charts()
        self.playback_bar.set_flight_time(result.flight_time)
        self.stop_playback()
        self.fill_data_table(result)
        self.toggle_play(True)  # сразу показываем полёт
        return index

    def _select_run(self, index: int):
        record = self.runs_panel.active()
        if record:
            self.results_panel.set_results(record.result)
            self.fill_data_table(record.result)
            self.playback_bar.set_flight_time(record.result.flight_time)
            self.stop_playback()

    def _update_all_charts(self):
        self._update_trajectory_chart()
        self._update_analysis_charts()

    def _update_trajectory_chart(self):
        """Траектории всех видимых запусков + маркеры активного."""
        series, markers = [], []
        target_marker = None
        for record in self.runs_panel.records:
            if not record.visible:
                continue
            active = record is self.runs_panel.active()
            result = record.result
            series.append({
                "points": list(zip(result.x, result.y)),
                "color": record.color, "width": 2.6 if active else 1.8,
                "name": record.name, "pickable": active, "time": result.t,
            })
            if active:
                markers.append({"x": result.results["apogee_distance"],
                                "y": result.results["max_height"], "color": "#ffd166",
                                "label": f"апогей {fmt_num(result.results['max_height'], 'м')}"})
                markers.append({"x": result.x[-1], "y": result.y[-1],
                                "color": "#ff6b6b", "label": "падение"})
                for _, bounce_x, bounce_y in result.bounces:
                    markers.append({"x": bounce_x, "y": bounce_y, "color": "#ff9f43"})
                if result.config.target_enabled:
                    half = result.config.target_size / 2
                    d, h = result.config.target_distance, result.config.target_height
                    series.append({"points": [(d, h - half), (d, h + half)],
                                   "color": "#98a2b3", "width": 4, "name": "цель"})
                    if result.results["target_y"] is not None:
                        hit = result.results["target_hit"]
                        deviation = result.results["target_deviation"]
                        target_marker = {
                            "x": d, "y": result.results["target_y"],
                            "color": "#3ecf8e" if hit else "#ff6b6b",
                            "label": ("🎯 попадание" if hit else
                                      f"промах {fmt_num(abs(deviation), 'м')}")}
        if target_marker:
            markers.append(target_marker)
        self.chart.set_series(series)
        self.chart.set_markers(markers)
        self._update_cursor()

    def _update_analysis_charts(self):
        """Четыре графика: высота, скорость, энергия, ускорение — по времени."""
        chart_series = {}
        for record in self.runs_panel.records:
            if not record.visible:
                continue
            result = record.result
            t, y, vx, vy = result.t, result.y, result.vx, result.vy
            mass, g = result.config.mass, result.config.gravity
            speeds = [hypot(vx[i], vy[i]) for i in range(len(t))]
            accels = [hypot(result.ax[i], result.ay[i]) for i in range(len(t))]
            active = record is self.runs_panel.active()
            base = {"color": record.color, "width": 2.4 if active else 1.6, "name": record.name}
            chart_series.setdefault("h", []).append({**base, "points": list(zip(t, y))})
            chart_series.setdefault("v", []).append({**base, "points": list(zip(t, speeds))})
            chart_series.setdefault("e", []).append({**base, "points": list(zip(t, [
                mass * v * v / 2 for v in speeds]))})
            chart_series.setdefault("e", []).append({**base, "points": list(zip(t, [
                mass * g * h for h in y]))})
            chart_series.setdefault("a", []).append({**base, "points": list(zip(t, accels))})
        for key, chart in self.analysis_charts.items():
            chart.set_series(chart_series.get(key, []))

    # ─── Проигрывание полёта ─────────────────────────────────────────

    def toggle_play_shortcut(self):
        self.toggle_play(not self._play_timer.isActive())

    def toggle_play(self, want_play: bool):
        record = self.runs_panel.active()
        if not record:
            return
        if want_play == self._play_timer.isActive():
            return
        if want_play and self._play_time >= record.result.flight_time:
            self._play_time = 0.0
        self.playback_bar.set_playing(want_play)
        if want_play:
            self._play_timer.start()
        else:
            self._play_timer.stop()

    def stop_playback(self):
        self._play_timer.stop()
        self.playback_bar.set_playing(False)
        self.seek(0.0)

    def step_playback(self, delta: float=None, back: bool=False):
        record = self.runs_panel.active()
        if not record:
            return
        if delta is None:
            delta = self.playback_bar.step_time()
        if back:
            delta = -delta
        self.seek(self._play_time + delta)

    def seek(self, time: float):
        record = self.runs_panel.active()
        if not record:
            return
        self._play_time = min(max(time, 0.0), record.result.flight_time)
        self.playback_bar.set_time(self._play_time, record.result.flight_time)
        self._update_cursor()

    def set_playback_speed(self, speed: float):
        self._play_speed = speed

    def _tick(self):
        record = self.runs_panel.active()
        if not record:
            self._play_timer.stop()
            return
        self._play_time += 0.016 * self._play_speed
        if self._play_time >= record.result.flight_time:
            self._play_time = record.result.flight_time
            self.toggle_play(False)
        self.playback_bar.set_time(self._play_time, record.result.flight_time)
        self._update_cursor()

    def _update_cursor(self):
        """Снаряд на траектории + векторы скорости/ускорения + телеметрия."""
        record = self.runs_panel.active()
        if not record:
            self.chart.set_cursor(None)
            self.chart.set_vectors([])
            return
        result = record.result
        index = result.time_index(self._play_time)
        x, y = result.x[index], result.y[index]
        self.chart.set_cursor({"x": x, "y": y, "color": record.color})
        vectors = []
        if self.cb_show_vectors.isChecked() and index < len(result.vx):
            v0 = result.config.speed or 1.0
            a0 = max(result.config.gravity, 0.1)
            vectors.append({"x": x, "y": y, "dx": result.vx[index] / v0,
                            "dy": result.vy[index] / v0, "scale": 160, "max_px": 150,
                            "color": "#3ecf8e", "label": "v"})
            vectors.append({"x": x, "y": y, "dx": result.ax[index] / a0,
                            "dy": result.ay[index] / a0, "scale": 55, "max_px": 120,
                            "color": "#ff9f43", "label": "a"})
        self.chart.set_vectors(vectors)
        self.results_panel.set_telemetry(index, result)

    # ─── Таблица данных и экспорт ────────────────────────────────────

    def fill_data_table(self, result):
        stride = max(1, len(result.t) // MAX_TABLE_ROWS)
        self.table_data.setRowCount(0)
        rows = list(range(0, len(result.t), stride))
        dt_real = result.t[1] - result.t[0] if len(result.t) > 1 else 0
        self.label_points.setText(
            f"{len(result.t):,} точек, показана каждая {stride}-я (Δt = {dt_real:g} с)"
            .replace(",", " "))
        self.table_data.setRowCount(len(rows))
        for row, i in enumerate(rows):
            values = (result.t[i], result.x[i], result.y[i], result.vx[i], result.vy[i],
                      hypot(result.vx[i], result.vy[i]), hypot(result.ax[i], result.ay[i]))
            for column, value in enumerate(values):
                self.table_data.setItem(row, column, _table_item(fmt_num(value)))

    def export_csv(self, path: str):
        record = self.runs_panel.active()
        if not record:
            QMessageBox.information(self, "Экспорт CSV", "Сначала запустите симуляцию.")
            return
        result = record.result
        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow(["t, с", "x, м", "y, м", "vx, м/с", "vy, м/с", "|v|, м/с", "|a|, м/с²"])
            for i in range(len(result.t)):
                writer.writerow([f"{result.t[i]:.6f}", f"{result.x[i]:.4f}", f"{result.y[i]:.4f}",
                                 f"{result.vx[i]:.4f}", f"{result.vy[i]:.4f}",
                                 f"{hypot(result.vx[i], result.vy[i]):.4f}",
                                 f"{hypot(result.ax[i], result.ay[i]):.4f}"])

    def export_png(self):
        """PNG активной вкладки: график траектории или все графики анализа."""
        widget = self.chart if self.tabs_main.currentIndex() == 0 else self.tabs_main.currentWidget()
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт графика в PNG",
                                              "kinemasim_chart.png", "PNG (*.png)")
        if path:
            if not path.endswith(".png"):
                path += ".png"
            widget.grab().save(path)
            self.statusBar().showMessage(f"✓ График сохранён: {path}")

    # ─── Прочее ──────────────────────────────────────────────────────

    def _apply_chart_options(self):
        self.chart.equal_scale = self.cb_equal_scale.isChecked()
        self.chart.show_grid = self.cb_show_grid.isChecked()
        for chart in self.analysis_charts.values():
            chart.show_grid = self.cb_show_grid.isChecked()
        self.chart.fit_all()

    def _reset_views(self):
        self.chart.fit_all()
        for chart in self.analysis_charts.values():
            chart.fit_all()

    def _on_chart_hover(self, info):
        if info and "index" in info:
            self.statusBar().showMessage(
                f"{info['name']}: t = {info['t']:.3f} с, x = {info['x']:.2f} м, y = {info['y']:.2f} м")
        elif info and info.get("world"):
            wx, wy = info["world"]
            self.statusBar().showMessage(f"x = {fmt_num(wx, 'м')}, y = {fmt_num(wy, 'м')}")
