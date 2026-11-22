"""플레이어의 실제 위치를 따라가는 월드 카메라."""
import math

from game.core.collision import AABB
from game.core.display import LOGICAL_SIZE


HORIZONTAL_ANCHOR = .35  # 여우를 화면 왼쪽 35%에 두어 오른쪽 진행로를 보여준다.


class Camera:
    def __init__(self, bounds, size=LOGICAL_SIZE):
        self.bounds = bounds
        self.width, self.height = size
        self.x = self.y = 0.0
        self._clamp()

    @property
    def offset(self):
        # 모든 레이어가 같은 소수점 원점을 사용한다.
        return self.x, self.y

    @property
    def view(self):
        return AABB(*self.offset, self.width, self.height)

    def to_screen(self, x, y):
        left, bottom = self.offset
        return x - left, y - bottom

    def visible(self, box):
        return self.view.overlaps(box)

    def snap(self, x, y):
        """진입·초기화 시 이전 위치에서 따라오는 과정 없이 즉시 배치한다."""
        self.x, self.y = x - self.width * HORIZONTAL_ANCHOR, y - self.height / 2
        self._clamp()

    def follow(self, x, y, dt):
        """빠른 대시도 진행로가 보이도록 가로 추적 지연을 제한한다."""
        target = x - self.width * HORIZONTAL_ANCHOR
        lag = self.width * .08
        self.x += (target - self.x) * -math.expm1(-16 * dt)
        self.x = max(target - lag, min(target + lag, self.x))
        low, high = self.height * .35, self.height * .65
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
