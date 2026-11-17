from dataclasses import dataclass, field, asdict


INTEGRATORS = ("euler", "verlet", "rk4")
INTEGRATOR_NAMES = {"euler": "Эйлер", "verlet": "Верле", "rk4": "Рунге–Кутта 4"}
SOUND_SPEED = 340.29  # скорость звука при 15 °C на уровне моря, м/с


@dataclass
class SimulationConfig:
    """Все параметры одного запуска снаряда.

    Единицы измерения — СИ: метры, секунды, килограммы, радианы не используются
    (угол в градусах), обороты задаются в об/мин.
    """
    # Снаряд
    mass: float = 0.45          # масса, кг
    diameter: float = 0.22      # диаметр (снаряд считается шаром), м
    drag_coefficient: float = 0.25  # коэффициент лобового сопротивления Cd
    spin_rpm: float = 0.0       # вращение, об/мин (>0 — backspin, подъёмная сила)

    # Параметры запуска
    speed: float = 25.0         # начальная скорость, м/с
    angle: float = 45.0         # угол к горизонту, градусы
    height: float = 0.0         # высота запуска, м

    # Окружающая среда
    gravity: float = 9.81       # ускорение свободного падения, м/с²
    air_density: float = 1.225  # плотность воздуха у земли, кг/м³
    density_scale_height: float = 8400.0  # высота однородной атмосферы, м
    wind_speed: float = 0.0     # скорость ветра, м/с (>0 — попутный, <0 — встречный)

    # Физическая модель
    integrator: str = "rk4"     # euler | verlet | rk4
    dt: float = 0.001           # шаг интегрирования, с
    auto_dt: bool = True        # подбирать шаг автоматически
    max_time: float = 120.0     # предел времени симуляции, с
    use_drag: bool = True       # сопротивление воздуха
    use_magnus: bool = True     # эффект Магнуса (подъёмная сила от вращения)
    use_buoyancy: bool = False  # сила Архимеда
    use_bounces: bool = False   # отскоки от земли
    restitution: float = 0.5    # коэффициент восстановления при отскоке (0..1)
    max_bounces: int = 8        # максимум отскоков

    # Цель (вертикальная мишень на заданной дистанции)
    target_enabled: bool = False
    target_distance: float = 100.0  # дистанция до цели, м
    target_height: float = 1.0      # высота центра цели, м
    target_size: float = 0.5        # размер (высота) мишени, м

    def __post_init__(self):
        if self.integrator not in INTEGRATORS:
            raise ValueError(f"Неизвестный интегратор: {self.integrator}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SimulationConfig":
        valid_fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid_fields})

    @property
    def cross_section_area(self) -> float:
        """Площадь поперечного сечения шара, м²."""
        radius = self.diameter / 2
        return 3.141592653589793 * radius * radius

    @property
    def volume(self) -> float:
        """Объём шара, м³ (нужен для силы Архимеда)."""
        radius = self.diameter / 2
        return 4 / 3 * 3.141592653589793 * radius ** 3

    def suggest_dt(self) -> float:
        """Автоматический шаг: за шаг снаряд смещается не более чем на ~1/40 диаметра,
        но не мельче 10 мкс (иначе полёт пули упрётся в лимит шагов)."""
        flow_time = self.diameter / max(self.speed, 0.1)
        dt = flow_time / 40
        return min(max(dt, 1e-5), 0.005)
