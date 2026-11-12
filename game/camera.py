"""월드 좌표를 화면으로 옮기고 카메라의 맵 경계를 제한한다."""
from game.collision import AABB


class Camera:
    def __init__(self, bounds, size=(640, 360)):
        self.bounds = bounds
        self.width, self.height = size
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

    def snap(self, x, y):
        self.x, self.y = x - self.width / 2, y - self.height / 2
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
