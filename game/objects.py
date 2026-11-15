"""맵에 배치하는 오브젝트의 상태와 동작. 표현 모듈에 의존하지 않는다."""
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
        self.contact_time = self._attempt_time = None
        self.consumed = self._touching = False

    def cancel_attempt(self):
        """포커스 이탈·사망 때 보류 중인 시도를 버린다."""
        self._attempt_time = None

    def try_absorb(self):
        """시도를 기록하고 지금 소비되었으면 True를 반환한다.

        재입력 여부는 입력부가 구분한다. False는 아직 소비되지 않았다는 뜻이다.
        """
        if self.consumed:
            return False
        self._attempt_time = self.time
        return self._try_consume()

    def update(self, dt, body, movement_paths=()):
        """경로는 (시작 AABB, dx, dy, 갱신 내 시작 초, 이동 초)이다."""
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        start = self.time
        self.time += dt
        if self.consumed:
            return False
        contacted = False
        if not self._touching:
            for box, dx, dy, offset, duration in movement_paths:
                contact_fraction = first_contact_time(box, dx, dy, (self.area,))
                if contact_fraction is not None:
                    self.contact_time = start + offset + duration * contact_fraction
                    contacted = True
                    break
            if not contacted and body.overlaps(self.area):
                self.contact_time = self.time
                contacted = True
        # 접촉면에 정확히 멈춰도 다음 갱신에서 접촉 시각을 다시 잡지 않는다.
        closed_overlap = (body.left <= self.area.right and body.right >= self.area.left
                          and body.bottom <= self.area.top and body.top >= self.area.bottom)
        self._touching = body.overlaps(self.area) or ((contacted or self._touching) and closed_overlap)
        return self._try_consume()

    def _try_consume(self):
        if self._attempt_time is None or self.contact_time is None:
            return False
        difference = abs(self._attempt_time - self.contact_time)
        on_boundary = math.isclose(difference, self.window, rel_tol=0, abs_tol=1e-9)
        if difference > self.window and not on_boundary:
            return False
        self.consumed = True
        return True


class JumpPad:
    def __init__(self, area, launch_height=128, press_duration=.12):
        self.area = area
        self.launch_height = launch_height
        self.press_duration = press_duration
        self.reset()

    def reset(self):
        self.pressed_left = 0.0
        self._touching = False

    @property
    def pressed(self):
        return self.pressed_left > 0

    def update(self, dt, player):
        self.pressed_left = max(0.0, self.pressed_left - dt)
        body = player.body
        on_top = (body.left < self.area.right and body.right > self.area.left
                  and math.isclose(body.bottom, self.area.top, rel_tol=0, abs_tol=1e-7))
        activated = (on_top and not self._touching and player.state != 'DEAD'
                     and player.grounded and player.contact.hit_bottom)
        self._touching = on_top
        if activated:
            player.bounce(self.launch_height)
            self.pressed_left = self.press_duration
        return activated
