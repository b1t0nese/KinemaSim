"""KinemaSim — симулятор и визуализация кинематики: от брошенного камня
до выстрела снайперской винтовки. PySide6 + .ui файлы, вся физика в physics/."""

import argparse
import json
import sys
import time

from PySide6.QtCore import QObject, QThread, QMetaObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from interface_module.window import MainWindowUI
from physics.config import SimulationConfig
from physics.engine import simulate
from ui_loader import resource_path

APP_NAME = "KinemaSim"
APP_VERSION = "1.0.1"
CONFIG_EXTENSION = ".kinemasim.json"


class SimulationWorker(QObject):
    """Симуляция в фоне: чистый Python занял бы главный поток и заморозил окно.
    Живёт в собственном потоке всю сессию, запуски приходят через invokeMethod."""
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.config: SimulationConfig | None = None
        self.started_at = 0.0

    @Slot()
    def run(self):
        try:
            result = simulate(self.config)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


class App(QObject):
    """Оркестрация: окно + действия с файлами, сама симуляция — по сигналу окна.

    Наследуется от QObject, чтобы сигналы воркера приходили в главный поток
    (AutoConnection), а не исполнялись внутри потока расчёта."""

    def __init__(self, config_path: str | None=None):
        super().__init__()
        self.appApplication: QApplication | None = None
        self.windowUI: MainWindowUI | None = None
        self.run_counter = 0

        self.sim_worker = SimulationWorker()
        self.sim_thread = QThread()
        self.sim_worker.moveToThread(self.sim_thread)
        self.sim_worker.finished.connect(self.on_simulation_finished)
        self.sim_worker.failed.connect(self.on_simulation_failed)
        self.sim_thread.start()
        self._sim_busy = False

        self.windowUI = MainWindowUI()
        self.init_window()
        if config_path:
            self.load_config(config_path)

    def init_window(self):
        w = self.windowUI
        w.simulation_requested.connect(self.run_simulation)
        w.action_save_config.triggered.connect(lambda: self.save_config())
        w.action_load_config.triggered.connect(lambda: self.load_config())
        w.action_reset_view.triggered.connect(w._reset_views)
        w.action_export_png.triggered.connect(w.export_png)
        w.action_about.triggered.connect(self.show_about)
        w.btn_export_csv.clicked.connect(self.export_csv)
        w.closeEvent = self.close_application

    def start(self, qapp: QApplication):
        log_prefix = f"[{APP_NAME}]"
        print(f"{log_prefix} ▶ Запуск...")
        self.appApplication = qapp
        with open(resource_path("resources", "style.qss"), "r", encoding="utf-8") as f:
            qapp.setStyleSheet(f.read())
        print(f"{log_prefix} ✓ Тема применена")
        self.windowUI.show()
        exit_code = qapp.exec()
        print(f"{log_prefix} ✕ Выход (код {exit_code})")
        sys.exit(exit_code)

    # ─── Симуляция ───────────────────────────────────────────────────

    def run_simulation(self):
        """Собирает настройки из окна и запускает расчёт в фоновом потоке."""
        if self._sim_busy:
            return  # предыдущий расчёт ещё идёт
        self._sim_busy = True
        self.sim_worker.config = self.windowUI.settings_panel.collect_config()
        self.sim_worker.started_at = time.perf_counter()
        self.windowUI.settings_panel.btn_run.setEnabled(False)
        self.windowUI.statusBar().showMessage("⏳ Считаю симуляцию…")
        QMetaObject.invokeMethod(self.sim_worker, "run", Qt.ConnectionType.QueuedConnection)

    def on_simulation_finished(self, result):
        self._sim_busy = False
        self.windowUI.settings_panel.btn_run.setEnabled(True)

        elapsed_ms = (time.perf_counter() - self.sim_worker.started_at) * 1000
        self.run_counter += 1
        preset_name = self.windowUI.settings_panel.combo_preset.currentText()
        if preset_name == "— вручную —":
            name = f"Запуск {self.run_counter}"
        else:
            name = f"{preset_name} #{self.run_counter}"
        self.windowUI.add_run(result, name)

        r = result.results
        self.windowUI.statusBar().showMessage(
            f"✓ {result.status.lower()}: {len(result.t):,} шагов за {elapsed_ms:.0f} мс — "
            f"дальность {r['range']:.1f} м, высота {r['max_height']:.1f} м, "
            f"время {r['flight_time']:.2f} с".replace(",", " "))

    def on_simulation_failed(self, message: str):
        self._sim_busy = False
        self.windowUI.settings_panel.btn_run.setEnabled(True)
        self.windowUI.statusBar().showMessage(f"✗ Ошибка симуляции: {message}")
        QMessageBox.warning(self.windowUI, "Ошибка симуляции", message)

    def close_application(self, event):
        if self._sim_busy:  # даём фоновому расчёту доделать, окно остаётся живым
            self.windowUI.statusBar().showMessage("⏳ Дожимаю расчёт перед выходом…")
            deadline = time.time() + 30
            while self._sim_busy and time.time() < deadline:
                QApplication.processEvents()
                time.sleep(0.05)
        self.sim_thread.quit()
        self.sim_thread.wait(5000)
        self.sim_thread.deleteLater()
        self.sim_worker.deleteLater()
        event.accept()

    # ─── Файлы: настройки и экспорт ──────────────────────────────────

    def save_config(self, path: str | None=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self.windowUI, "Сохранить настройки", f"settings{CONFIG_EXTENSION}",
                f"KinemaSim settings (*{CONFIG_EXTENSION})")
        if not path:
            return
        if not path.endswith(CONFIG_EXTENSION):
            path += CONFIG_EXTENSION
        config = self.windowUI.settings_panel.collect_config().to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        self.windowUI.statusBar().showMessage(f"✓ Настройки сохранены: {path}")

    def load_config(self, path: str | None=None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self.windowUI, "Загрузить настройки", "",
                f"KinemaSim settings (*{CONFIG_EXTENSION});;JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = SimulationConfig.from_dict(json.load(f))
        except Exception as e:
            QMessageBox.warning(self.windowUI, "Ошибка загрузки",
                                f"Не удалось загрузить настройки:\n{e}")
            return
        self.windowUI.settings_panel.apply_config(config)
        self.windowUI.statusBar().showMessage(f"✓ Настройки загружены: {path}")

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self.windowUI, "Экспорт данных полёта в CSV",
            "kinemasim_data.csv", "CSV (*.csv)")
        if path:
            if not path.endswith(".csv"):
                path += ".csv"
            self.windowUI.export_csv(path)
            self.windowUI.statusBar().showMessage(f"✓ Данные сохранены: {path}")

    def show_about(self):
        QMessageBox.about(
            self.windowUI, f"О {APP_NAME}",
            f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            "<p>Симулятор и визуализация кинематики: от брошенного камня до пули "
            "снайперской винтовки.</p>"
            "<p>Моделируются: сила тяжести, квадратичное сопротивление воздуха "
            "с падением плотности по высоте, ветер, эффект Магнуса, сила Архимеда "
            "и отскоки. Три численных интегратора: Эйлер, Верле и Рунге–Кутта 4.</p>"
            "<p style='color:#98a2b3'>PySide6 · собственный рендер графиков на QPainter</p>")


def main():
    global app, application

    arg_parser = argparse.ArgumentParser(
        APP_NAME, description="Симулятор и визуализация кинематики: "
        "настраивается всё — от брошенного камня до выстрела пули.")
    arg_parser.add_argument("--config", nargs="?", default=None,
                            help="путь к JSON-файлу с настройками симуляции")
    arguments = arg_parser.parse_args()

    application = QApplication(sys.argv)
    app = App(config_path=arguments.config)
    app.start(application)


if __name__ == "__main__":
    main()
