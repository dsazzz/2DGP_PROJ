"""Upload Python-rendered RGBA directly to pico2d's SDL renderer.

Close these textures before closing the pico2d canvas. No PNG files are written
or reloaded during gameplay. Positions are in pico2d's bottom-left coordinates.
"""
import ctypes
from functools import lru_cache
import json
import math

import numpy as np

from .runtime import Effect


@lru_cache(maxsize=4)
def _effect_frames(name, options_json):
    """같은 효과 프레임을 모든 개체·재시작에서 공유한다. SDL 자원은 저장하지 않는다."""
    effect = Effect(name, **json.loads(options_json))
    frames = []
    for index in range(round(effect.spec.duration * effect.spec.fps)):
        effect.time = index / effect.spec.fps
        frames.append(effect.rgba())
    return tuple(frames)


def load_rgba(path):
    """Read PNG pixels for motion silhouettes using pico2d's existing SDL_image."""
    # Import pico2d first so its bundled SDL DLL search path is initialized.
    import pico2d  # noqa: F401
    import sdl2 as s
    from sdl2 import sdlimage

    source = sdlimage.IMG_Load(str(path).encode('utf-8'))
    if not source:
        raise OSError('Cannot load image: ' + str(path))
    converted = None
    locked = False
    try:
        converted = s.SDL_ConvertSurfaceFormat(source, s.SDL_PIXELFORMAT_RGBA32, 0)
        if not converted:
            raise OSError(s.SDL_GetError().decode('utf-8', errors='replace'))
        if s.SDL_LockSurface(converted) < 0:
            raise OSError('Cannot lock image pixels')
        locked = True
        surface = converted.contents
        raw = ctypes.string_at(surface.pixels, surface.pitch * surface.h)
        return np.frombuffer(raw, np.uint8).reshape(surface.h, surface.pitch)[:, :surface.w * 4].reshape(
            surface.h, surface.w, 4).copy()
    finally:
        if locked:
            s.SDL_UnlockSurface(converted)
        if converted:
            s.SDL_FreeSurface(converted)
        s.SDL_FreeSurface(source)


class StreamingTexture:
    def __init__(self):
        self.texture = None
        self._size = None
        self._owner = None

    def upload(self, rgba):
        import sdl2 as s
        from pico2d import pico2d as canvas

        renderer = getattr(canvas, 'renderer', None)
        if not renderer:
            raise RuntimeError('Open the pico2d canvas before drawing effects')
        rgba = np.ascontiguousarray(rgba, dtype=np.uint8)
        if rgba.ndim != 3 or rgba.shape[2] != 4:
            raise ValueError('Expected an H x W x 4 RGBA array')
        h, w, _ = rgba.shape
        owner = ctypes.cast(renderer, ctypes.c_void_p).value
        if self.texture is not None and owner != self._owner:
            raise RuntimeError('Close effect textures before replacing the canvas')
        if self.texture is None or self._size != (w, h):
            self.close()
            s.SDL_SetHint(s.SDL_HINT_RENDER_SCALE_QUALITY, b'0')
            self.texture = s.SDL_CreateTexture(renderer, s.SDL_PIXELFORMAT_RGBA32,
                                                s.SDL_TEXTUREACCESS_STREAMING, w, h)
            if not self.texture:
                raise RuntimeError(s.SDL_GetError().decode('utf-8', errors='replace'))
            self._size, self._owner = (w, h), owner
            if s.SDL_SetTextureBlendMode(self.texture, s.SDL_BLENDMODE_BLEND) < 0:
                self.close()
                raise RuntimeError('SDL renderer does not support alpha blending')
        if s.SDL_UpdateTexture(self.texture, None, ctypes.c_void_p(rgba.ctypes.data), w * 4) < 0:
            raise RuntimeError(s.SDL_GetError().decode('utf-8', errors='replace'))

    def draw(self, x, y, *, origin=(0, 0), scale=1, flip=False, angle=0, opacity=1):
        import sdl2 as s
        from pico2d import pico2d as canvas

        if self.texture is None:
            raise RuntimeError('Upload pixels before drawing')
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError('scale must be finite and positive')
        w, h = self._size
        ox, oy = origin
        if flip:
            ox = w - ox
        left, top = x - ox * scale, canvas.get_canvas_height() - y - oy * scale
        rect = s.SDL_FRect(left, top, w * scale, h * scale)
        center = s.SDL_FPoint(ox * scale, oy * scale)
        s.SDL_SetTextureAlphaMod(self.texture, round(max(0, min(1, opacity)) * 255))
        status = s.SDL_RenderCopyExF(canvas.renderer, self.texture, None, ctypes.byref(rect),
                                    -math.degrees(angle), ctypes.byref(center),
                                    s.SDL_FLIP_HORIZONTAL if flip else s.SDL_FLIP_NONE)
        if status < 0:
            raise RuntimeError(s.SDL_GetError().decode('utf-8', errors='replace'))

    def close(self):
        if self.texture is not None:
            import sdl2 as s
            s.SDL_DestroyTexture(self.texture)
        self.texture = self._size = self._owner = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class PicoEffect:
    """A live effect. update(dt), draw(x,y), then close() before canvas shutdown."""
    def __init__(self, name, **options):
        self.name = name
        self.effect = Effect(name, **options)
        self.texture = StreamingTexture()
        self._upload_key = None
        self._loop = None

    def prerender(self):
        """게임 시작 전에 효과를 굽고 재생 중에는 픽셀 계산을 생략한다."""
        options = json.dumps(self.options, sort_keys=True)
        self._loop = (options, _effect_frames(self.name, options))

    def prerender_loop(self):
        if not self.effect.spec.loop:
            raise ValueError('Only looping effects can be prerendered')
        self.prerender()

    @property
    def options(self):
        return self.effect.options

    def update(self, dt):
        self.effect.update(dt)

    def stop(self):
        self.effect.stop()

    def done(self):
        return self.effect.done()

    def draw(self, x, y, *, scale=.5, flip=False, angle=0, layer=None):
        if layer not in (None, 'back', 'front'):
            raise ValueError('layer must be back, front or None')
        if (layer is not None and layer != self.effect.spec.layer) or self.done():
            return
        # Runtime options may change (appearance/grounded/target), even at the same time.
        cached = (self._loop is not None and math.isinf(self.effect._stop_at)
                  and self._loop[0] == json.dumps(self.options, sort_keys=True))
        index = None
        if cached:
            index = math.floor((self.effect.time + 1e-9) * self.effect.spec.fps)
            index = index % len(self._loop[1]) if self.effect.spec.loop else min(index, len(self._loop[1]) - 1)
        key = (index if cached else self.effect.time, self.effect._stop_at, repr(self.options), layer)
        if key != self._upload_key:
            self.texture.upload(self._loop[1][index] if cached else self.effect.rgba(layer))
            self._upload_key = key
        self.texture.draw(x, y, origin=self.effect.spec.origin, scale=scale, flip=flip, angle=angle)

    def close(self):
        self.texture.close()
        self._upload_key = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
