"""흡수원의 첫 접촉 시각과 새 대시 입력을 비교한다. 표현·보상은 호출 쪽 책임이다."""
import math

from game.collision import first_contact_time


class AbsorbSource:
    """공통 게임 시간으로 접촉 전후를 판정하며, 성공은 reset 전까지 한 번만 반환한다."""

    def __init__(self, area, *, window=.15):
        if not math.isfinite(window) or window < 0:
            raise ValueError('Absorption window must be finite and nonnegative')
        self.area, self.window = area, window
        self.reset()

    def reset(self):
        self.time = 0.0
        self.contact_time = self._dash_time = None
        self.consumed = self._touching = False

    def cancel_input(self):
        """포커스를 잃었을 때 보류 중인 입력을 버린다."""
        self._dash_time = None

    def press_dash(self):
        """실행 가능한 새 대시 입력만 전달한다. 키 유지·DASH 상태는 입력이 아니다."""
        if self.consumed:
            return False
        self._dash_time = self.time
        return self._consume()

    def update(self, dt, body, movement_paths=()):
        """경로는 (시작 AABB, dx, dy, 갱신 내 시작 초, 이동 초)이다."""
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        start = self.time
        self.time += dt
        if self.consumed:
            return False
        hit = False
        if not self._touching:
            for box, dx, dy, offset, duration in movement_paths:
                at = first_contact_time(box, dx, dy, (self.area,))
                if at is not None:
                    self.contact_time = start + offset + duration * at
                    hit = True
                    break
            if not hit and body.overlaps(self.area):
                self.contact_time = self.time
                hit = True
        # 접촉면에 정확히 멈춰도 다음 갱신에서 접촉 시각을 다시 잡지 않는다.
        closed_overlap = (body.left <= self.area.right and body.right >= self.area.left
                          and body.bottom <= self.area.top and body.top >= self.area.bottom)
        self._touching = body.overlaps(self.area) or ((hit or self._touching) and closed_overlap)
        return self._consume()

    def _consume(self):
        if self._dash_time is None or self.contact_time is None:
            return False
        difference = abs(self._dash_time - self.contact_time)
        if difference > self.window and not math.isclose(difference, self.window, rel_tol=0, abs_tol=1e-9):
            return False
        self.consumed = True
        return True
