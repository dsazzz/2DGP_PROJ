"""Live Python effect instances and offscreen RGBA rendering, without a window."""
import math

from .effects import EFFECTS
from .painter import Frame, Painter, clamp


class Effect:
    def __init__(self, name, **options):
        self.spec = EFFECTS[name]
        self.options = {**self.spec.defaults, **options}
        self.time = 0.0
        self._stop_at = math.inf
        self._frame = None

    def update(self, dt):
        if not math.isfinite(dt) or dt < 0:
            raise ValueError('dt must be finite and nonnegative')
        self.time += dt

    def stop(self):
        if self._stop_at == math.inf:
            self._stop_at = self.time

    def done(self):
        return (self.time - self._stop_at >= .3 or
                (not self.spec.loop and self.time >= self.spec.duration))

    def draw(self, frame, layer=None, *, local=False):
        """Draw at options x/y in the frame's top-left coordinate system."""
        if layer not in (None, 'back', 'front'):
            raise ValueError('layer must be back, front or None')
        if layer is not None and layer != self.spec.layer:
            return
        if self.time < 0:
            return
        p = Painter(frame)
        if not local:
            p.place(self.options.get('x', 0), self.options.get('y', 0),
                    self.options.get('flip', False), self.options.get('angle', 0))
        p.fade = clamp(1 - (self.time - self._stop_at) / .3)
        p.light_k = self.options.get('light', 1)
        t = self.time % self.spec.duration if self.spec.loop else min(self.time, self.spec.duration)
        self.spec.draw(p, t, self.options)

    def rgba(self, layer=None):
        """Local untransformed pixels; use the SDL adapter for placement/rotation."""
        if self._frame is None:
            self._frame = Frame(*self.spec.size, -self.spec.origin[0], -self.spec.origin[1])
        self._frame.clear()
        self.draw(self._frame, layer, local=True)
        return self._frame.rgba()


def create_fx(name, **options):
    return Effect(name, **options)


def render_effect(name, elapsed, *, layer=None, **options):
    effect = Effect(name, **options)
    if not math.isfinite(elapsed):
        raise ValueError('elapsed must be finite')
    effect.time = elapsed
    return effect.rgba(layer)
