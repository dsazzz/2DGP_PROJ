"""고정 물리 틱에 쓸 시간을 누적한다."""
from time import perf_counter


PHYSICS_HZ = 60
FIXED_DT = 1 / PHYSICS_HZ


class FixedStep:
    def __init__(self, *, clock=perf_counter, fixed_dt=FIXED_DT):
        self._clock = clock
        self.fixed_dt = fixed_dt
        self.reset()

    def pump(self, now=None):
        """흐른 시간을 누적하고 이번에 실행할 틱 수를 반환한다."""
        now = self._clock() if now is None else now
        self.accumulator += min(max(now - self.previous, 0.0), 0.1)
        self.previous = now
        steps = int((self.accumulator + self.fixed_dt * 1e-9) / self.fixed_dt)
        self.accumulator = max(0.0, self.accumulator - steps * self.fixed_dt)
        return steps

    def reset(self, now=None):
        """이전 장면의 남은 시간과 경과 시간을 비운다."""
        self.accumulator = 0.0
        self.previous = self._clock() if now is None else now

    @property
    def alpha(self):
        return self.accumulator / self.fixed_dt
