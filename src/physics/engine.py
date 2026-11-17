"""Численный движок симуляции: сила тяжести, сопротивление воздуха (квадратичное,
с моделью плотности атмосферы по высоте), ветер, эффект Магнуса, сила Архимеда,
отскоки от земли и три интегратора (Эйлер, Верле, Рунге–Кутта 4)."""

from dataclasses import dataclass, field
from math import atan2, cos, degrees, exp, hypot, radians, sin, sqrt

from .config import SimulationConfig

MAX_STEPS = 2_000_000  # защита от зависания при крошечном dt
BOUNCE_STOP_SPEED = 0.4  # м/с: ниже — снаряд считается остановившимся


@dataclass
class SimulationResult:
    """Результат одного запуска: траектория и вычисленные итоги."""
    config: SimulationConfig
    t: list = field(default_factory=list)
    x: list = field(default_factory=list)
    y: list = field(default_factory=list)
    vx: list = field(default_factory=list)
    vy: list = field(default_factory=list)
    ax: list = field(default_factory=list)
    ay: list = field(default_factory=list)
    bounces: list = field(default_factory=list)  # точки отскоков (t, x, y)
    status: str = ""       # чем закончилась симуляция
    flight_time: float = 0.0
    results: dict = field(default_factory=dict)

    def speed_at(self, index: int) -> float:
        return hypot(self.vx[index], self.vy[index])

    def time_index(self, time: float) -> int:
        """Индекс точки, ближайшей к заданному времени (бинарный поиск)."""
        if not self.t:
            return 0
        lo, hi = 0, len(self.t) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.t[mid] < time:
                lo = mid + 1
            else:
                hi = mid
        if lo > 0 and abs(self.t[lo - 1] - time) < abs(self.t[lo] - time):
            lo -= 1
        return lo


class _Physics:
    """Силы, действующие на снаряд, в одинаковой форме для всех интеграторов."""

    def __init__(self, config: SimulationConfig):
        self.cfg = config
        self.g = config.gravity
        self.wind = config.wind_speed
        self.area = config.cross_section_area
        self.spin = config.spin_rpm / 60 * 2 * 3.141592653589793  # рад/с
        self.radius = config.diameter / 2
        self.volume = config.volume
        self.mass = config.mass

    def air_density(self, height: float) -> float:
        """Плотность воздуха на высоте: экспоненциальная модель атмосферы."""
        return self.cfg.air_density * exp(-max(height, 0.0) / self.cfg.density_scale_height)

    def acceleration(self, x: float, y: float, vx: float, vy: float) -> tuple[float, float]:
        """Суммарное ускорение снаряда в точке (x, y) со скоростью (vx, vy)."""
        ax, ay = 0.0, -self.g
        rvx, rvy = vx - self.wind, vy  # скорость относительно воздуха
        speed = hypot(rvx, rvy)
        rho = self.air_density(y)

        if speed > 1e-9 and rho > 0.0:
            # Квадратичное сопротивление: F = -0.5 ρ Cd A |v|² v̂
            if self.cfg.use_drag:
                drag_factor = 0.5 * rho * self.cfg.drag_coefficient * self.area * speed / self.mass
                ax -= drag_factor * rvx
                ay -= drag_factor * rvy
            # Эффект Магнуса: F = 0.5 ρ Cl A |v|² n̂, n̂ перпендикулярно скорости
            if self.cfg.use_magnus and abs(self.spin) > 1e-9:
                spin_ratio = abs(self.spin) * self.radius / speed
                lift_coeff = min(spin_ratio / (2 + spin_ratio), 0.45)
                magnus_factor = 0.5 * rho * lift_coeff * self.area * speed * speed / self.mass
                nx, ny = -rvy / speed, rvx / speed  # поворот v̂ на +90° (backspin — вверх)
                if self.spin < 0:  # topspin — сила в противоположную сторону
                    nx, ny = -nx, -ny
                ax += magnus_factor * nx
                ay += magnus_factor * ny
        # Сила Архимеда: F = ρ g V, направлена вверх
        if self.cfg.use_buoyancy and rho > 0.0:
            ay += rho * self.g * self.volume / self.mass
        return ax, ay


def _step_euler(p: _Physics, state: tuple, dt: float) -> tuple:
    """Симплектический (полунеявный) Эйлер: быстрый, но менее точный."""
    x, y, vx, vy = state
    ax, ay = p.acceleration(x, y, vx, vy)
    return x + vx * dt, y + vy * dt, vx + ax * dt, vy + ay * dt


def _step_verlet(p: _Physics, state: tuple, dt: float) -> tuple:
    """ Velocity Verlet: хорошая точность и сохранение энергии для колебаний."""
    x, y, vx, vy = state
    ax, ay = p.acceleration(x, y, vx, vy)
    x_new, y_new = x + vx * dt + 0.5 * ax * dt * dt, y + vy * dt + 0.5 * ay * dt * dt
    # сила зависит ещё и от скорости, поэтому a в новой точке оцениваем по сдвинутой скорости
    ax_new, ay_new = p.acceleration(x_new, y_new, vx + 0.5 * ax * dt, vy + 0.5 * ay * dt)
    vx_new, vy_new = vx + 0.5 * (ax + ax_new) * dt, vy + 0.5 * (ay + ay_new) * dt
    return x_new, y_new, vx_new, vy_new


def _step_rk4(p: _Physics, state: tuple, dt: float) -> tuple:
    """Классический Рунге–Кутта 4-го порядка: максимальная точность."""
    def deriv(s):
        return s[2], s[3], *p.acceleration(s[0], s[1], s[2], s[3])

    k1 = deriv(state)
    s2 = tuple(state[i] + 0.5 * dt * k1[i] for i in range(4))
    k2 = deriv(s2)
    s3 = tuple(state[i] + 0.5 * dt * k2[i] for i in range(4))
    k3 = deriv(s3)
    s4 = tuple(state[i] + dt * k3[i] for i in range(4))
    k4 = deriv(s4)
    return tuple(state[i] + dt / 6 * (k1[i] + 2 * k2[i] + 2 * k3[i] + k4[i]) for i in range(4))


_STEPS = {"euler": _step_euler, "verlet": _step_verlet, "rk4": _step_rk4}


def _lerp(a: float, b: float, f: float) -> float:
    return a + (b - a) * f


def simulate(config: SimulationConfig) -> SimulationResult:
    """Прогоняет симуляцию от запуска до падения (или предела времени)."""
    dt = config.suggest_dt() if config.auto_dt else config.dt
    dt = min(max(dt, 1e-6), 0.1)
    physics = _Physics(config)
    step = _STEPS[config.integrator]

    result = SimulationResult(config=config)
    state = (0.0, config.height,
             config.speed * cos(radians(config.angle)),
             config.speed * sin(radians(config.angle)))
    t = 0.0
    bounces_done = 0
    result.t.append(t); result.x.append(state[0]); result.y.append(state[1])
    result.vx.append(state[2]); result.vy.append(state[3])
    result.ax.append(0.0); result.ay.append(-config.gravity)

    steps = int(config.max_time / dt) + 2
    steps = min(steps, MAX_STEPS)
    for _ in range(steps):
        state = step(physics, state, dt)
        t += dt
        x, y, vx, vy = state

        if y < 0.0:  # столкновение с землёй
            f = result.y[-1] / (result.y[-1] - y) if result.y[-1] != y else 0.5
            x = _lerp(result.x[-1], x, f); y = 0.0
            vx = _lerp(result.vx[-1], vx, f); vy = _lerp(result.vy[-1], vy, f)
            result.t.append(t); result.x.append(x); result.y.append(y)
            result.vx.append(vx); result.vy.append(vy)
            result.ax.append(0.0); result.ay.append(0.0)
            if config.use_bounces and bounces_done < config.max_bounces:
                if abs(vy) > BOUNCE_STOP_SPEED:
                    bounces_done += 1
                    result.bounces.append((t, x, y))
                    state = (x, y, vx * 0.98, -vy * config.restitution)
                    continue
            result.flight_time = t
            result.status = "Приземление"
            break
        if t >= config.max_time:
            result.t.append(t); result.x.append(x); result.y.append(y)
            result.vx.append(vx); result.vy.append(vy)
            ax, ay = physics.acceleration(x, y, vx, vy)
            result.ax.append(ax); result.ay.append(ay)
            result.flight_time = t
            result.status = "Достигнут предел времени"
            break

        result.t.append(t); result.x.append(x); result.y.append(y)
        result.vx.append(vx); result.vy.append(vy)
        ax, ay = physics.acceleration(x, y, vx, vy)
        result.ax.append(ax); result.ay.append(ay)
    else:
        result.flight_time = result.t[-1] if result.t else 0.0
        result.status = "Достигнут лимит шагов"

    _compute_results(result)
    return result


def _compute_results(result: SimulationResult):
    """Сводка полёта: дальность, высота, апогей, скорость падения, цель и т.д."""
    cfg = result.config
    t, x, y, vx, vy = result.t, result.x, result.y, result.vx, result.vy
    if not t:
        return

    apogee_index = max(range(len(y)), key=y.__getitem__)
    impact_speed = hypot(vx[-1], vy[-1])
    impact_angle = degrees(atan2(-vy[-1], vx[-1])) if vx[-1] != 0 else 90.0
    results = {
        "range": x[-1],
        "flight_time": result.flight_time,
        "max_height": y[apogee_index],
        "apogee_time": t[apogee_index],
        "apogee_distance": x[apogee_index],
        "impact_speed": impact_speed,
        "impact_angle": impact_angle,
        "impact_energy": cfg.mass * impact_speed ** 2 / 2,
        "bounces": len(result.bounces),
    }

    if cfg.target_enabled:
        target = _check_target(result)
        results.update(target)

    results["vacuum_range"] = (cfg.speed ** 2 * sin(2 * radians(cfg.angle)) / cfg.gravity
                               + cfg.speed * cos(radians(cfg.angle)) * sqrt(max(
                                   (cfg.speed * sin(radians(cfg.angle))) ** 2
                                   + 2 * cfg.gravity * cfg.height, 0.0)) / cfg.gravity
                               if cfg.gravity > 0 else 0.0)
    results["drag_loss"] = max(results["vacuum_range"] - results["range"], 0.0)
    result.results = results


def _check_target(result: SimulationResult) -> dict:
    """Проверка попадания в вертикальную мишень при первом пересечении её плоскости."""
    cfg = result.config
    for i in range(1, len(result.x)):
        if result.x[i - 1] < cfg.target_distance <= result.x[i]:
            f = (cfg.target_distance - result.x[i - 1]) / (result.x[i] - result.x[i - 1])
            y_cross = _lerp(result.y[i - 1], result.y[i], f)
            t_cross = _lerp(result.t[i - 1], result.t[i], f)
            v_cross = hypot(_lerp(result.vx[i - 1], result.vx[i], f),
                            _lerp(result.vy[i - 1], result.vy[i], f))
            deviation = y_cross - cfg.target_height
            hit = abs(deviation) <= cfg.target_size / 2
            return {
                "target_hit": hit,
                "target_deviation": deviation,
                "target_time": t_cross,
                "target_speed": v_cross,
                "target_y": y_cross,
            }
    return {"target_hit": False, "target_deviation": None,
            "target_time": None, "target_speed": None, "target_y": None}
