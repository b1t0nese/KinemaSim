"""Самопроверка движка: сравнение с аналитикой без сопротивления и sanity-чеки.
Запуск: python tests/test_engine.py (из папки проекта, с src в sys.path)."""
import sys
import os
from math import cos, sin, tan, radians, sqrt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from physics.config import SimulationConfig
from physics.engine import simulate


def close(a, b, tol=0.02):
    """Относительная близость в 2% (или абсолютные 2 см)."""
    return abs(a - b) <= max(tol * max(abs(a), abs(b)), 0.02)


def test_vacuum_analytic():
    """Без воздуха дальность/высота/время должны сходиться с формулами."""
    cfg = SimulationConfig(speed=50, angle=30, gravity=9.81, air_density=0,
                           use_drag=False, use_magnus=False, auto_dt=False, dt=0.001)
    res = simulate(cfg)
    v, a, g = cfg.speed, radians(cfg.angle), cfg.gravity
    assert close(res.results["max_height"], (v * sin(a)) ** 2 / 2 / g, 0.01), res.results
    assert close(res.results["range"], v * cos(a) * (v * sin(a) + sqrt((v * sin(a)) ** 2 + 0)) / g, 0.01)
    assert close(res.results["flight_time"], 2 * v * sin(a) / g, 0.01)
    assert res.results["impact_speed"] > 49.9  # в вакууме скорость сохраняется
    print("✓ вакуум: аналитика сходится (h=%.2f м, x=%.2f м, t=%.3f с)" %
          (res.results["max_height"], res.results["range"], res.results["flight_time"]))


def test_integrators_agree():
    """Все три интегратора при мелком шаге дают близкие результаты с сопротивлением."""
    answers = []
    for integrator in ("euler", "verlet", "rk4"):
        cfg = SimulationConfig(mass=0.145, diameter=0.074, drag_coefficient=0.34,
                               speed=45, angle=30, auto_dt=False, dt=0.0002,
                               integrator=integrator, use_magnus=False)
        answers.append(simulate(cfg).results["range"])
    assert max(answers) - min(answers) < 1.0, answers
    print("✓ интеграторы согласованы: дальности %s" % ["%.2f" % a for a in answers])


def test_drag_reduces_range():
    """Сопротивление воздуха заметно уменьшает дальность."""
    vacuum = simulate(SimulationConfig(speed=45, angle=30, air_density=0, use_drag=False))
    air = simulate(SimulationConfig(speed=45, angle=30, air_density=1.225, use_drag=True))
    assert air.results["range"] < vacuum.results["range"] * 0.85
    print("✓ сопротивление: вакуум %.1f м → воздух %.1f м" %
          (vacuum.results["range"], air.results["range"]))


def test_magnus_lift():
    """Backspin увеличивает максимальную высоту (подъёмная сила Магнуса)."""
    plain = SimulationConfig(mass=0.0459, diameter=0.0427, drag_coefficient=0.24,
                             speed=70, angle=12, use_magnus=False, use_drag=True)
    spinning = SimulationConfig(**{**plain.__dict__, "spin_rpm": 3200, "use_magnus": True})
    h_plain = simulate(plain).results["max_height"]
    h_spin = simulate(spinning).results["max_height"]
    assert h_spin > h_plain * 1.1, (h_plain, h_spin)
    print("✓ Магнус: высота без вращения %.1f м → с backspin %.1f м" % (h_plain, h_spin))


def test_wind_and_target():
    """Попутный ветер увеличивает дальность; цель регистрирует попадание."""
    head = simulate(SimulationConfig(speed=40, angle=45, wind_speed=-8))
    tail = simulate(SimulationConfig(speed=40, angle=45, wind_speed=8))
    assert tail.results["range"] > head.results["range"]

    cfg = SimulationConfig(speed=40, angle=45, air_density=0, use_drag=False, auto_dt=False, dt=0.001,
                           target_enabled=True, target_distance=160, target_height=5, target_size=4)
    res = simulate(cfg)
    v, a, g = cfg.speed, radians(cfg.angle), cfg.gravity
    y_at = 160 * tan(a) - g * 160 ** 2 / (2 * v ** 2 * cos(a) ** 2)
    assert res.results["target_hit"] == (abs(y_at - 5) <= 2)
    print("✓ ветер и цель: встречный %.1f м < попутный %.1f м; попадание=%s" %
          (head.results["range"], tail.results["range"], res.results["target_hit"]))


def test_bounces_and_bullet():
    """Отскоки считаются; пуля летит далеко, но время полёта небольшое."""
    res = simulate(SimulationConfig(speed=20, angle=45, use_bounces=True, restitution=0.6))
    assert res.results["bounces"] >= 1
    bullet = simulate(SimulationConfig(mass=0.0034, diameter=0.0057, drag_coefficient=0.28,
                                       speed=880, angle=1.5, max_time=10))
    assert bullet.results["range"] > 200
    assert bullet.results["max_height"] > 1
    print("✓ отскоки: %d шт; пуля 5.45: дальность %.0f м, высота %.1f м" %
          (res.results["bounces"], bullet.results["range"], bullet.results["max_height"]))


if __name__ == "__main__":
    test_vacuum_analytic()
    test_integrators_agree()
    test_drag_reduces_range()
    test_magnus_lift()
    test_wind_and_target()
    test_bounces_and_bullet()
    print("\n🎉 Все проверки пройдены.")
