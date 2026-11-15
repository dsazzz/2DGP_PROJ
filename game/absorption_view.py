"""흡수원의 판정을 읽어 반복 광원과 제자리 소멸을 표시한다."""
from game.vfx.pico import PicoEffect


class AbsorbSourceView:
    """효과의 생성·갱신·출력·정리만 소유한다. 판정과 보상은 변경하지 않는다."""

    def __init__(self, source):
        self.source = source
        self.effect = None
        self.reset()

    def reset(self):
        self.close()
        self._consumed = self.source.consumed
        if not self._consumed:
            self.effect = PicoEffect('source')

    def update(self, dt):
        if not self.source.consumed and self._consumed:
            self.reset()
        elif self.source.consumed and not self._consumed:
            phase = self.effect.effect.time if self.effect is not None else 0
            self.close()
            self.effect = PicoEffect('lightAbsorb', idle_phase=phase)
            self._consumed = True
        if self.effect is not None:
            self.effect.update(dt)
            if self.effect.done():
                self.close()

    def draw(self, offset=(0, 0)):
        if self.effect is not None:
            area = self.source.area
            x = area.left + area.width / 2 - offset[0]
            y = area.bottom + area.height / 2 - offset[1]
            self.effect.draw(x, y, scale=1, layer='front')

    def close(self):
        if self.effect is not None:
            self.effect.close()
            self.effect = None
