"""월드 좌표를 유지하면서 진행 방향의 앞쪽을 보여주는 2D 카메라."""
import math

from game.collision import AABB


class Camera:
    def __init__(self, bounds, size=(640, 360)):
        self.bounds = bounds
        self.width, self.height = size
        self.look_ahead = self.width * .1
        self.turn_delay = .12
        self.turn_speed = 8.0
        self.vertical_zone = (.35, .65)
        self.direction = 1
        self.lead = self.look_ahead
        self.pending_direction = 0
        self.pending_time = 0.0
        self.x = self.y = 0.0
        self._clamp()

    @property
    def offset(self):
        # 모든 레이어가 같은 정수 원점을 사용한다.
        return round(self.x), round(self.y)

    @property
    def view(self):
        return AABB(*self.offset, self.width, self.height)

    def to_screen(self, x, y):
        left, bottom = self.offset
        return x - left, y - bottom

    def visible(self, box):
        return self.view.overlaps(box)

    def snap(self, x, y, direction=1):
        """진입·초기화 시 이전 위치에서 따라오는 과정 없이 즉시 배치한다."""
        self.direction = -1 if direction < 0 else 1
        self.lead = self.direction * self.look_ahead
        self.pending_direction, self.pending_time = 0, 0.0
        self.x, self.y = x - self.width / 2 + self.lead, y - self.height / 2
        self._clamp()

    def follow(self, x, y, direction, dt):
        """direction은 현재 가로 이동 의도다. 정지하면 마지막 구도를 유지한다."""
        direction = (direction > 0) - (direction < 0)
        if direction and direction != self.direction:
            if direction != self.pending_direction:
                self.pending_direction, self.pending_time = direction, 0.0
            self.pending_time += dt
            if self.pending_time >= self.turn_delay:
                self.direction = direction
                self.pending_direction, self.pending_time = 0, 0.0
        else:
            self.pending_direction, self.pending_time = 0, 0.0
        amount = -math.expm1(-self.turn_speed * dt)
        self.lead += (self.direction * self.look_ahead - self.lead) * amount
        self.x = x - self.width / 2 + self.lead

        low, high = (self.height * value for value in self.vertical_zone)
        screen_y = y - self.y
        if screen_y < low:
            self.y = y - low
        elif screen_y > high:
            self.y = y - high
        self._clamp()

    def _clamp(self):
        if self.bounds.width <= self.width:
            self.x = self.bounds.left + (self.bounds.width - self.width) / 2
        else:
            self.x = max(self.bounds.left, min(self.bounds.right - self.width, self.x))
        if self.bounds.height <= self.height:
            self.y = self.bounds.bottom + (self.bounds.height - self.height) / 2
        else:
            self.y = max(self.bounds.bottom, min(self.bounds.top - self.height, self.y))
