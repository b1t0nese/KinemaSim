"""Offscreen-проверка интерфейса: запускает приложение, делает пару симуляций
и сохраняет скриншоты вкладок в doc/screenshots/. Запуск:
    QT_QPA_PLATFORM=offscreen env/bin/python tests/screenshot.py"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "doc", "screenshots")
os.makedirs(OUT_DIR, exist_ok=True)


def main():
    app = QApplication(sys.argv)
    with open(os.path.join(os.path.dirname(__file__), "..", "src", "resources", "style.qss"),
              encoding="utf-8") as f:
        app.setStyleSheet(f.read())

    from interface_module.window import MainWindowUI
    window = MainWindowUI()
    window.resize(1500, 920)
    window.show()

    # прогрев布局, чтобы offscreen-геометрия устоялась
    for _ in range(10):
        app.processEvents()

    # mimic App.run_simulation: настройки из панели → simulate → add_run
    from physics.engine import simulate

    def launch(preset_name):
        sp = window.settings_panel
        sp.combo_preset.setCurrentText(preset_name)
        result = simulate(sp.collect_config())
        window.add_run(result, preset_name)
        for _ in range(20):
            app.processEvents()

    launch("Футбольный мяч")
    launch("Автомат АК-74 (5,45×39)")
    window.toggle_play(False)
    window.seek(0.8)

    window.grab().save(os.path.join(OUT_DIR, "sim_tab.png"))

    window.tabs_main.setCurrentIndex(1)
    for _ in range(10):
        app.processEvents()
    window.grab().save(os.path.join(OUT_DIR, "analysis_tab.png"))

    window.tabs_main.setCurrentIndex(2)
    for _ in range(10):
        app.processEvents()
    window.grab().save(os.path.join(OUT_DIR, "data_tab.png"))

    print("✓ Скриншоты сохранены в", os.path.abspath(OUT_DIR))
    window.close()
    app.quit()


if __name__ == "__main__":
    main()
