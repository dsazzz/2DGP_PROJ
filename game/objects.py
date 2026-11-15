"""맵에 배치하는 오브젝트의 상태와 동작. 표현 모듈에 의존하지 않는다."""
import math

from game.collision import AABB


class AbsorbSource:
    """입력 순간 영역에 겹친 대상을 한 번만 소비한다. 행동 조건은 호출 쪽에서 검사한다."""

    def __init__(self, area):
        self.area = area
        self.reset()

    def reset(self):
        self.consumed = False

    def try_absorb(self, body):
        """현재 겹침으로만 판정한다. 실패한 입력은 저장하지 않는다."""
        if self.consumed or not self.area.overlaps(body):
            return False
        self.consumed = True
        return True


class Spikes:
    """고정 가시의 위험 영역. 사망 처리는 플레이어의 기존 경로 판정을 사용한다."""

    def __init__(self, area: AABB):
        self.area = area


class JumpPlatform:
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


class MovingPlatform:
    """높이를 유지하면서 시작 x와 끝 x 사이를 일정 속도로 왕복한다."""

    def __init__(self, area, end_x, speed=64):
        if not all(math.isfinite(value) for value in (end_x, speed)) or speed < 0:
            raise ValueError('Platform needs finite endpoints and a nonnegative speed')
        self.start_area = area
        self.end_x = end_x
        self.speed = speed
        self._dx = end_x - area.left
        self._length = abs(self._dx)
        self.reset()

    def reset(self):
        self.area = self.start_area
        self.previous_area = self.area
        self.delta = (0.0, 0.0)
        self._travel = 0.0

    def update(self, dt):
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        self.previous_area = previous = self.area
        if self._length:
            # 끝점을 넘긴 거리도 되돌아오는 구간에 반영한다.
            self._travel = (self._travel + self.speed * dt) % (2 * self._length)
            progress = min(self._travel, 2 * self._length - self._travel) / self._length
            start = self.start_area
            self.area = AABB(start.left + self._dx * progress,
                             start.bottom, start.width, start.height)
        self.delta = (self.area.left - previous.left, 0.0)

    def area_at(self, fraction):
        """이번 갱신 구간의 상자. 플레이어의 분할된 대시 이동에서도 사용한다."""
        area = self.previous_area
        return AABB(area.left + self.delta[0] * fraction,
                    area.bottom, area.width, area.height)

    def supports(self, body, *, previous=False):
        area = self.previous_area if previous else self.area
        return (body.left < area.right and body.right > area.left
                and math.isclose(body.bottom, area.top, rel_tol=0, abs_tol=1e-7))

    def landing_time(self, body, dx, dy, start=0, end=1):
        """플레이어 발과 움직이는 윗면이 만나는 비율. 아래·옆 진입은 통과한다."""
        area = self.area_at(start)
        if body.bottom < area.top - 1e-7 or dy >= 0:
            return None
        time = max(0.0, (area.top - body.bottom) / dy)
        if time > 1:
            return None
        x = body.left + dx * time
        platform_x = area.left + self.delta[0] * (end - start) * time
        if x < platform_x + area.width and x + body.width > platform_x:
            return time
        return None


class DisappearingPlatform:
    """윗면을 밟으면 경고 후 사라지고, 빈 위치에 다시 나타나는 발판."""

    def __init__(self, area, warning_time=.5, hidden_time=2.0):
        if any(not math.isfinite(value) or value <= 0 for value in (warning_time, hidden_time)):
            raise ValueError('Platform times must be finite and positive')
        self.area = area
        self.warning_time, self.hidden_time = warning_time, hidden_time
        self.reset()

    def reset(self):
        self.state = 'READY'
        self.time_left = 0.0

    @property
    def collidable(self):
        return self.state != 'HIDDEN'

    def update(self, dt, body):
        """물리 갱신 전에 시간과 충돌 활성 여부를 갱신한다."""
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        if self.state == 'READY':
            return
        self.time_left -= dt
        if self.state == 'WARNING' and self.time_left <= 1e-9:
            self.state = 'HIDDEN'
            self.time_left += self.hidden_time
        if self.state == 'HIDDEN' and self.time_left <= 1e-9:
            self.time_left = 0.0
            if not body.overlaps(self.area):
                self.reset()

    def trigger(self, player):
        """물리 갱신 뒤 유효한 윗면 접촉으로만 경고를 시작한다."""
        body = player.body
        if (self.state != 'READY' or player.state == 'DEAD' or not player.grounded
                or not player.contact.hit_bottom or body.left >= self.area.right
                or body.right <= self.area.left
                or not math.isclose(body.bottom, self.area.top, rel_tol=0, abs_tol=1e-7)):
            return False
        self.state, self.time_left = 'WARNING', self.warning_time
        return True
