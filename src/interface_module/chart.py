"""Универсальный виджет графика на QPainter: оси с «красивыми» делениями, сетка,
зум колесом, панорамирование мышью, кроссхэйр, маркеры, векторные стрелки, легенда.

График ничего не знает о физике — работает с мировыми координатами и списками
точек, всю логику (что показывать) задаёт окно через set_* методы."""

from math import atan2, cos, floor, log10, pow as math_pow, sin, sqrt
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (QPainter, QPen, QColor, QBrush, QPainterPath,
                           QPolygonF, QFont)
from PySide6.QtWidgets import QWidget

MARGIN_LEFT = 58
MARGIN_BOTTOM = 42
MARGIN_TOP = 16
MARGIN_RIGHT = 18

BG_COLOR = QColor("#10131a")
GRID_COLOR = QColor("#222837")
AXIS_COLOR = QColor("#39415480")
TEXT_COLOR = QColor("#8d97a8")
CURSOR_COLOR = QColor("#5b8cff")


def format_tick(value: float, step: float) -> str:
    """Подпись деления оси: без хвостов нулей, с пробелом-разделителем тысяч."""
    decimals = max(0, min(4, int(-floor(log10(step))) if step < 1 else 0))
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    negative = text.startswith("-")
    digits = text.lstrip("-").replace(".", "")
    if len(digits) > 4:
        cleaned = text.lstrip("-")
        point = cleaned.find(".")
        int_part = cleaned if point == -1 else cleaned[:point]
        offset = len(int_part) % 3
        groups = [int_part[max(0, i - 3):i] for i in range(offset, len(int_part) + 3, 3)]
        int_part = " ".join([g for g in groups if g])
        rest = "" if point == -1 else cleaned[point:]
        text = int_part + rest
    return ("-" if negative else "") + text


def nice_step(raw: float) -> float:
    """Шаг сетки вида 1/2/5 × 10^k, дающий ~7 делений."""
    if raw <= 0:
        return 1.0
    magnitude = math_pow(10, floor(log10(raw)))
    for factor in (1.0, 2.0, 5.0, 10.0):
        if raw <= factor * magnitude:
            return factor * magnitude
    return 10 * magnitude


class ChartWidget(QWidget):
    """График с набором кривых, маркеров и анимационным курсором.

    Серия: словарь {points, color, width, dashed, name, visible, pickable, data}.
    Маркер: {x, y, color, label}. Вектор: {x, y, dx, dy, scale, color, label}.
    """
    hoverMoved = Signal(object)  # dict с ближайшей точкой серии | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 180)
        self.setMouseTracking(True)
        self.series: list[dict] = []
        self.markers: list[dict] = []
        self.vectors: list[dict] = []
        self.cursor: dict | None = None          # {x, y, color} — летящий снаряд
        self.ground_y: float | None = None       # линия земли
        self.x_label = ""
        self.y_label = ""
        self.equal_scale = False
        self.show_grid = True
        self.show_legend = True
        self.view: tuple | None = None           # (xmin, xmax, ymin, ymax)
        self._drag_start = None
        self._hover_world = None
        self._user_view = False                  # пользователь зумил/двигал — не рефитить на resize
        self._font_small = QFont(self.font())
        self._font_small.setPointSizeF(self.font().pointSizeF() * 0.92)

    # ─── Публичный API ────────────────────────────────────────────────

    def set_series(self, series: list):
        self.series = series
        self.fit_all()

    def set_markers(self, markers: list):
        self.markers = markers

    def set_vectors(self, vectors: list):
        self.vectors = vectors

    def set_cursor(self, cursor: dict | None):
        self.cursor = cursor

    def fit_all(self):
        """Подгонка вида под все видимые данные (с отступами)."""
        xs, ys = [], []
        for s in self.series:
            if not s.get("visible", True):
                continue
            xs.extend(p[0] for p in s["points"])
            ys.extend(p[1] for p in s["points"])
        if self.cursor:
            xs.append(self.cursor["x"]); ys.append(self.cursor["y"])
        for m in self.markers:
            xs.append(m["x"]); ys.append(m["y"])
        if not xs:
            self.view = None
            self.update()
            return
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        pad_x = (xmax - xmin) * 0.04 + 0.5
        pad_y = (ymax - ymin) * 0.08 + 0.5
        # слева мёртвый отступ не нужен: данные у нас не уходят в минус (x, t ≥ 0)
        if xmin >= 0:
            xmin = 0.0
        else:
            xmin -= pad_x
        self.view = (xmin, xmax + pad_x, ymin - pad_y, ymax + pad_y)
        if self.ground_y is not None:
            self.view = (self.view[0], self.view[1], min(self.view[2], self.ground_y - pad_y * 0.5),
                         self.view[3])
        self._apply_equal_scale()
        self._user_view = False
        self.update()

    def reset_view(self):
        self.fit_all()

    def resizeEvent(self, event):
        if self.equal_scale and not self._user_view:
            self.fit_all()
        super().resizeEvent(event)

    # ─── Преобразования координат ─────────────────────────────────────

    def _plot_rect(self) -> QRectF:
        return QRectF(MARGIN_LEFT, MARGIN_TOP,
                      max(self.width() - MARGIN_LEFT - MARGIN_RIGHT, 10),
                      max(self.height() - MARGIN_TOP - MARGIN_BOTTOM, 10))

    def _apply_equal_scale(self):
        """Одинаковое количество метров на пиксель по осям (честная картинка)."""
        if not self.equal_scale or not self.view:
            return
        xmin, xmax, ymin, ymax = self.view
        rect = self._plot_rect()
        scale_x = (xmax - xmin) / rect.width()
        scale_y = (ymax - ymin) / rect.height()
        scale = max(scale_x, scale_y)
        cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        half_w, half_h = scale * rect.width() / 2, scale * rect.height() / 2
        self.view = (cx - half_w, cx + half_w, cy - half_h, cy + half_h)

    def _to_screen(self, x: float, y: float) -> QPointF:
        xmin, xmax, ymin, ymax = self.view
        rect = self._plot_rect()
        sx = rect.left() + (x - xmin) / (xmax - xmin) * rect.width()
        sy = rect.bottom() - (y - ymin) / (ymax - ymin) * rect.height()
        return QPointF(sx, sy)

    def _to_world(self, sx: float, sy: float) -> tuple:
        xmin, xmax, ymin, ymax = self.view
        rect = self._plot_rect()
        x = xmin + (sx - rect.left()) / rect.width() * (xmax - xmin)
        y = ymin + (rect.bottom() - sy) / rect.height() * (ymax - ymin)
        return x, y

    # ─── События мыши: зум, пан, кроссхэйр ─────────────────────────────

    def wheelEvent(self, event):
        if not self.view:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        wx, wy = self._to_world(event.position().x(), event.position().y())
        xmin, xmax, ymin, ymax = self.view
        xmin = wx + (xmin - wx) * factor
        xmax = wx + (xmax - wx) * factor
        ymin = wy + (ymin - wy) * factor
        ymax = wy + (ymax - wy) * factor
        self.view = (xmin, xmax, ymin, ymax)
        self._apply_equal_scale()
        self._user_view = True
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = (event.position().x(), event.position().y(), self.view)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._drag_start and self.view:
            sx0, sy0, (xmin0, xmax0, ymin0, ymax0) = self._drag_start
            rect = self._plot_rect()
            dx_world = (pos.x() - sx0) / rect.width() * (xmax0 - xmin0)
            dy_world = (pos.y() - sy0) / rect.height() * (ymax0 - ymin0)
            self.view = (xmin0 - dx_world, xmax0 - dx_world, ymin0 + dy_world, ymax0 + dy_world)
            self._user_view = True
            self.update()
            return
        if self.view:
            self._hover_world = self._to_world(pos.x(), pos.y())
            self._emit_hover(pos)
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag_start = None

    def mouseDoubleClickEvent(self, event):
        self.fit_all()

    def leaveEvent(self, event):
        self._hover_world = None
        self.hoverMoved.emit(None)
        self.update()

    def _emit_hover(self, pos):
        """Ближайшая точка среди pickable-серий в радиусе 18 px.

        Точки серии отсортированы по x, поэтому поиск ближайшей — бинарный,
        это важно для пуль со ста тысячами точек траектории.
        """
        best = None
        best_dist = 18.0
        for s in self.series:
            if not s.get("pickable") or not s.get("visible", True):
                continue
            points = s["points"]
            if not points:
                continue
            wx, _ = self._to_world(pos.x(), pos.y())
            lo, hi = 0, len(points) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if points[mid][0] < wx:
                    lo = mid + 1
                else:
                    hi = mid
            for i in range(max(0, lo - 2), min(len(points), lo + 3)):
                sp = self._to_screen(*points[i])
                dist = sqrt((sp.x() - pos.x()) ** 2 + (sp.y() - pos.y()) ** 2)
                if dist < best_dist:
                    best_dist = dist
                    best = {"series": s, "index": i}
        if best:
            s, i = best["series"], best["index"]
            self.hoverMoved.emit({
                "name": s.get("name", ""), "color": s.get("color"),
                "index": i, "t": s.get("time", [None] * len(s["points"]))[i],
                "x": s["points"][i][0], "y": s["points"][i][1],
                "world": self._hover_world,
            })
        else:
            self.hoverMoved.emit({"world": self._hover_world} if self._hover_world else None)

    # ─── Отрисовка ────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(self.rect(), BG_COLOR)
        if not self.view:
            painter.setPen(TEXT_COLOR)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Нет данных — запустите симуляцию 🚀")
            return
        rect = self._plot_rect()
        # тонкая рамка вокруг области построения
        painter.setPen(QPen(QColor("#262c38"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 6, 6)
        painter.setClipRect(rect)

        self._draw_grid(painter, rect)
        self._draw_ground(painter, rect)
        self._draw_series(painter)
        self._draw_markers(painter)
        self._draw_vectors(painter)
        self._draw_cursor(painter)
        self._draw_crosshair(painter, rect)
        painter.setClipping(False)
        self._draw_axes(painter, rect)
        if self.show_legend:
            self._draw_legend(painter, rect)

    def _draw_grid(self, painter, rect):
        if not self.show_grid:
            return
        xmin, xmax, ymin, ymax = self.view
        step_x = nice_step((xmax - xmin) / 7)
        step_y = nice_step((ymax - ymin) / 6)
        pen = QPen(GRID_COLOR, 1)
        painter.setPen(pen)
        x = floor(xmin / step_x) * step_x
        while x <= xmax:
            sp = self._to_screen(x, 0)
            painter.drawLine(QPointF(sp.x(), rect.top()), QPointF(sp.x(), rect.bottom()))
            x += step_x
        y = floor(ymin / step_y) * step_y
        while y <= ymax:
            sp = self._to_screen(0, y)
            painter.drawLine(QPointF(rect.left(), sp.y()), QPointF(rect.right(), sp.y()))
            y += step_y

    def _draw_axes(self, painter, rect):
        painter.setPen(QPen(QColor("#4a5468"), 1))
        painter.setFont(self._font_small)
        painter.drawLine(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.bottom()))
        painter.drawLine(QPointF(rect.left(), rect.bottom()), QPointF(rect.right(), rect.bottom()))

        xmin, xmax, ymin, ymax = self.view
        step_x = nice_step((xmax - xmin) / 7)
        step_y = nice_step((ymax - ymin) / 6)
        painter.setPen(QPen(TEXT_COLOR))
        x = floor(xmin / step_x) * step_x
        while x <= xmax:
            sp = self._to_screen(x, 0)
            painter.drawText(QPointF(sp.x() - 16, rect.bottom() + 16), format_tick(x, step_x))
            x += step_x
        y = floor(ymin / step_y) * step_y
        while y <= ymax:
            sp = self._to_screen(0, y)
            painter.drawText(QPointF(rect.left() - 50, sp.y() + 4), format_tick(y, step_y))
            y += step_y

        if self.x_label:
            painter.drawText(QPointF(rect.center().x() - len(self.x_label) * 2.6, self.height() - 6),
                             self.x_label)
        if self.y_label:
            painter.save()
            painter.translate(12, rect.center().y())
            painter.rotate(-90)
            painter.drawText(QPointF(-len(self.y_label) * 2.6, 0), self.y_label)
            painter.restore()

    def _draw_ground(self, painter, rect):
        if self.ground_y is None:
            return
        sp = self._to_screen(0, self.ground_y)
        if rect.top() <= sp.y() <= rect.bottom():
            painter.setPen(QPen(QColor("#3a4356"), 2))
            painter.drawLine(QPointF(rect.left(), sp.y()), QPointF(rect.right(), sp.y()))
            painter.setPen(QPen(QColor("#2a3140"), 1))
            step = 14
            y0 = sp.y()
            for x in range(int(rect.left()), int(rect.right()) + step, step):
                painter.drawLine(QPointF(x, y0), QPointF(x - 7, y0 + 7))

    def _draw_series(self, painter):
        for s in self.series:
            if not s.get("visible", True) or not s["points"]:
                continue
            pen = QPen(QColor(s.get("color", "#5b8cff")), s.get("width", 2))
            if s.get("dashed"):
                pen.setDashPattern([5, 4])
            pen.setCosmetic(True)
            painter.setPen(pen)
            path = QPainterPath()
            sp = self._to_screen(*s["points"][0])
            path.moveTo(sp)
            for point in s["points"][1:]:
                path.lineTo(self._to_screen(*point))
            painter.drawPath(path)

    def _draw_markers(self, painter):
        painter.setFont(self._font_small)
        rect = self._plot_rect()
        for m in self.markers:
            sp = self._to_screen(m["x"], m["y"])
            color = QColor(m.get("color", "#ffb454"))
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(sp, 4, 4)
            if m.get("label"):
                label_width = painter.fontMetrics().horizontalAdvance(m["label"])
                # если маркер у правого края — подпись рисуем слева от точки
                label_x = sp.x() + 7
                if label_x + label_width > rect.right() - 4:
                    label_x = sp.x() - 7 - label_width
                painter.setPen(QPen(color.lighter(120)))
                painter.drawText(QPointF(label_x, sp.y() - 7), m["label"])

    def _draw_vectors(self, painter):
        """Стрелки (скорость, ускорение) у летящего снаряда; длины — в пикселях."""
        painter.setFont(self._font_small)
        for v in self.vectors:
            start = self._to_screen(v["x"], v["y"])
            length = sqrt(v["dx"] ** 2 + v["dy"] ** 2) * v.get("scale", 1.0) * self.width() / 900
            length = min(length, v.get("max_px", 130))  # иначе пуля «протянет» вектор через весь график
            if length < 2:
                continue
            angle = atan2(-v["dy"], v["dx"])  # экранный y направлен вниз
            end = QPointF(start.x() + length * cos(angle),
                          start.y() + length * sin(angle))
            color = QColor(v.get("color", "#3ecf8e"))
            pen = QPen(color, 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QBrush(color))
            painter.drawLine(start, end)
            arrow = QPolygonF([
                end,
                QPointF(end.x() - 9 * cos(angle - 0.42), end.y() - 9 * sin(angle - 0.42)),
                QPointF(end.x() - 9 * cos(angle + 0.42), end.y() - 9 * sin(angle + 0.42)),
            ])
            painter.drawPolygon(arrow)
            if v.get("label"):
                painter.drawText(QPointF(end.x() + 4, end.y() - 4), v["label"])

    def _draw_cursor(self, painter):
        if not self.cursor:
            return
        sp = self._to_screen(self.cursor["x"], self.cursor["y"])
        color = QColor(self.cursor.get("color", "#ffffff"))
        painter.setPen(QPen(color, 2))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(sp, 6, 6)
        painter.setBrush(QBrush(color.lighter(150)))
        painter.drawEllipse(sp, 2.5, 2.5)

    def _draw_crosshair(self, painter, rect):
        if not self._hover_world:
            return
        wx, wy = self._hover_world
        sp = self._to_screen(wx, wy)
        pen = QPen(QColor("#5b8cff55"), 1)
        pen.setDashPattern([3, 3])
        painter.setPen(pen)
        if rect.left() <= sp.x() <= rect.right():
            painter.drawLine(QPointF(sp.x(), rect.top()), QPointF(sp.x(), rect.bottom()))
        if rect.top() <= sp.y() <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), sp.y()), QPointF(rect.right(), sp.y()))

    def _draw_legend(self, painter, rect):
        # имена дедуплицируются: кинетическая и потенциальная энергия идут
        # двумя сериями с одним именем запуска
        visible, seen = [], set()
        for s in self.series:
            if s.get("name") and s.get("visible", True) and s["name"] not in seen:
                seen.add(s["name"])
                visible.append(s)
        if not visible:
            return
        painter.setFont(self._font_small)
        line_h = 18
        width = max(painter.fontMetrics().horizontalAdvance(s["name"]) for s in visible) + 34
        box = QRectF(rect.right() - width, rect.top() + 4, width, line_h * len(visible) + 6)
        painter.setPen(QPen(QColor("#2a3140"), 1))
        painter.setBrush(QBrush(QColor("#14171ce0")))
        painter.drawRoundedRect(box, 6, 6)
        for i, s in enumerate(visible):
            y = box.top() + 5 + line_h * i
            painter.setPen(QPen(QColor(s.get("color", "#5b8cff")), 3))
            painter.drawLine(QPointF(box.left() + 8, y + 9), QPointF(box.left() + 22, y + 9))
            painter.setPen(QPen(TEXT_COLOR))
            painter.drawText(QPointF(box.left() + 28, y + 14), s["name"])
