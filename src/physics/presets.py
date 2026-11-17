"""Пресеты снарядов и окружения: от брошенного камня до пули снайперской винтовки.

Каждый пресет — словарь с полями SimulationConfig. Поля, которых нет в пресете,
остаются значениями по умолчанию (или не меняются при применении пресета).
"""

PROJECTILE_PRESETS = {
    "Камень (бросок рукой)": {
        "mass": 0.45, "diameter": 0.09, "drag_coefficient": 0.47,
        "spin_rpm": 0, "speed": 22.0, "angle": 45.0, "use_magnus": False,
    },
    "Футбольный мяч": {
        "mass": 0.43, "diameter": 0.22, "drag_coefficient": 0.25,
        "spin_rpm": 320, "speed": 28.0, "angle": 22.0, "use_magnus": True,
    },
    "Теннисный мяч": {
        "mass": 0.057, "diameter": 0.067, "drag_coefficient": 0.55,
        "spin_rpm": 2200, "speed": 55.0, "angle": 15.0, "use_magnus": True,
    },
    "Бейсбольный мяч": {
        "mass": 0.145, "diameter": 0.074, "drag_coefficient": 0.34,
        "spin_rpm": 1800, "speed": 45.0, "angle": 28.0, "use_magnus": True,
    },
    "Мяч для гольфа": {
        "mass": 0.0459, "diameter": 0.0427, "drag_coefficient": 0.24,
        "spin_rpm": 3200, "speed": 70.0, "angle": 12.0, "use_magnus": True,
    },
    "Стрела арбалета": {
        "mass": 0.025, "diameter": 0.008, "drag_coefficient": 0.90,
        "spin_rpm": 0, "speed": 100.0, "angle": 8.0, "use_magnus": False,
    },
    "Шар пейнтбола": {
        "mass": 0.0031, "diameter": 0.0173, "drag_coefficient": 0.50,
        "spin_rpm": 0, "speed": 91.0, "angle": 5.0, "use_magnus": False,
    },
    "Шар airsoft (6 мм)": {
        "mass": 0.00025, "diameter": 0.006, "drag_coefficient": 0.47,
        "spin_rpm": 0, "speed": 120.0, "angle": 3.0, "use_magnus": False,
    },
    "Пистолет 9×19 (пистолетная пуля)": {
        "mass": 0.008, "diameter": 0.009, "drag_coefficient": 0.30,
        "spin_rpm": 0, "speed": 360.0, "angle": 2.0, "use_magnus": False, "max_time": 30.0,
    },
    "Автомат АК-74 (5,45×39)": {
        "mass": 0.0034, "diameter": 0.0057, "drag_coefficient": 0.28,
        "spin_rpm": 0, "speed": 880.0, "angle": 1.5, "use_magnus": False, "max_time": 30.0,
    },
    "Снайперская винтовка (.338 Lapua)": {
        "mass": 0.0162, "diameter": 0.0086, "drag_coefficient": 0.26,
        "spin_rpm": 0, "speed": 915.0, "angle": 1.0, "use_magnus": False, "max_time": 30.0,
    },
    "Пушечное ядро": {
        "mass": 5.4, "diameter": 0.12, "drag_coefficient": 0.47,
        "spin_rpm": 0, "speed": 450.0, "angle": 30.0, "use_magnus": False,
    },
}

ENVIRONMENT_PRESETS = {
    "Земля (уровень моря)": {"gravity": 9.81, "air_density": 1.225, "density_scale_height": 8400.0},
    "Земля (высокогорье, 4000 м)": {"gravity": 9.81, "air_density": 0.819, "density_scale_height": 8400.0},
    "Луна": {"gravity": 1.62, "air_density": 0.0, "density_scale_height": 8400.0},
    "Марс": {"gravity": 3.71, "air_density": 0.020, "density_scale_height": 11100.0},
    "Юпитер (уровень облаков)": {"gravity": 24.79, "air_density": 0.16, "density_scale_height": 27000.0},
}
