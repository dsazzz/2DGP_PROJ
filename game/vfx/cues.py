"""Python counterparts of cues.js: visuals only, with no gameplay decisions."""
from functools import lru_cache
import math

import numpy as np

from .painter import clamp


GLOBAL_LIGHT_DURATION = 1.25


def platform_visual(elapsed):
    if elapsed < 0 or elapsed >= 3:
        return {'state': 'normal', 'opacity': 1}
    if elapsed < .8:
        return {'state': 'warning', 'opacity': .6 + .4 * math.cos(elapsed * 32) ** 2}
    if elapsed < 2:
        return {'state': 'normal', 'opacity': max(0, 1 - (elapsed - .8) * 8)}
    return {'state': 'normal', 'opacity': min(1, (elapsed - 2) * 2)}


def dash_orb_visual(elapsed, slot):
    if slot != 1 or elapsed < 0 or elapsed >= 1.25:
        return {'opacity': 1, 'scale': 1, 'ring': 0}
    return {
        'opacity': 1 - elapsed / .18 if elapsed < .18 else .1 if elapsed < .72 else clamp((elapsed - .72) / .3),
        'scale': 1 + elapsed * 2 if elapsed < .18 else 1,
        'ring': (elapsed - .72) / .53 if elapsed > .72 else 0,
    }


def _smooth(value):
    value = clamp(value)
    return value * value * (3 - 2 * value)


def signal_amount(elapsed, strength=1):
    if elapsed < 0 or elapsed >= GLOBAL_LIGHT_DURATION:
        return 0
    return _smooth(elapsed / .28) * (1 - _smooth((elapsed - .48) / .77)) * clamp(strength)


def ambient_amount(time, strength=.45):
    return clamp(strength) * (.96 + .04 * math.cos((time % 6) / 6 * math.tau))


@lru_cache(maxsize=4)
def _light_fields(width, height):
    if width <= 0 or height <= 0:
        raise ValueError('Light dimensions must be positive')
    y, x = np.mgrid[:height, :width]
    fields = []
    for rx, ry, rgb, alpha in ((.66, .78, (174, 14, 37), .10), (.39, .59, (236, 35, 54), .065)):
        d = np.sqrt(((x + .5 - width / 2) / (width * rx)) ** 2 +
                    ((y + .5 - height / 2) / (height * ry)) ** 2)
        opacity = np.interp(d, (0, .28, .64, 1), (1, .83, .32, 0)) * alpha
        fields.append(opacity[..., None] * np.array(rgb) / 255)
    return fields


def center_light(width, height, amount):
    """Return a premultiplied screen-blend layer, NOT an opaque red wash."""
    a, b = _light_fields(width, height)
    strength = max(0, amount)
    rgb = 1 - (1 - a * strength) * (1 - b * strength)
    result = np.empty((height, width, 4), dtype=np.uint8)
    result[..., :3] = np.rint(np.clip(rgb * 255, 0, 255)).astype(np.uint8)
    result[..., 3] = 255
    return result


def apply_screen_light(scene, amount):
    """CPU reference/fallback for Canvas screen compositing; preserves alpha."""
    height, width = scene.shape[:2]
    a, b = _light_fields(width, height)
    layer = 1 - (1 - a * max(0, amount)) * (1 - b * max(0, amount))
    result = scene.copy()
    result[..., :3] = np.rint(255 - (255 - scene[..., :3].astype(float)) * (1 - layer)).astype(np.uint8)
    return result


class ScreenLight:
    """Screen light for pico2d, with a readback fallback for software renderers."""
    def __init__(self):
        from .pico import StreamingTexture
        self.texture = StreamingTexture()
        self._native_screen = None

    def draw(self, amount):
        if amount <= 0:
            return
        import ctypes
        import sdl2 as s
        from pico2d import pico2d as canvas

        width, height = ctypes.c_int(), ctypes.c_int()
        target = s.SDL_GetRenderTarget(canvas.renderer)
        if target:
            status = s.SDL_QueryTexture(target, None, None, ctypes.byref(width), ctypes.byref(height))
        else:
            status = s.SDL_GetRendererOutputSize(canvas.renderer, ctypes.byref(width), ctypes.byref(height))
        if status < 0:
            raise RuntimeError('Cannot query the active render target')
        w, h = width.value, height.value
        layer = center_light(w, h, amount)
        self.texture.upload(layer)
        blend = s.SDL_ComposeCustomBlendMode(s.SDL_BLENDFACTOR_ONE, s.SDL_BLENDFACTOR_ONE_MINUS_SRC_COLOR,
                                            s.SDL_BLENDOPERATION_ADD, s.SDL_BLENDFACTOR_ZERO,
                                            s.SDL_BLENDFACTOR_ONE, s.SDL_BLENDOPERATION_ADD)
        self._native_screen = s.SDL_SetTextureBlendMode(self.texture.texture, blend) == 0
        if not self._native_screen:
            scene = np.empty((h, w, 4), dtype=np.uint8)
            if s.SDL_RenderReadPixels(canvas.renderer, None, s.SDL_PIXELFORMAT_RGBA32,
                                       ctypes.c_void_p(scene.ctypes.data), w * 4) < 0:
                raise RuntimeError('This renderer supports neither screen blend nor framebuffer readback')
            self.texture.upload(apply_screen_light(scene, amount))
            s.SDL_SetTextureBlendMode(self.texture.texture, s.SDL_BLENDMODE_NONE)
        if s.SDL_RenderCopy(canvas.renderer, self.texture.texture, None, None) < 0:
            raise RuntimeError('Screen light draw failed')

    def draw_ambient(self, time, strength=.45):
        self.draw(ambient_amount(time, strength))

    def draw_signal(self, elapsed, strength=1):
        self.draw(signal_amount(elapsed, strength))

    def close(self):
        self.texture.close()
        self._native_screen = None


class Cues:
    """Draw orb, failure and door feedback. Time and state come from the game."""
    def __init__(self):
        from .pico import StreamingTexture
        self._texture = StreamingTexture()

    def draw_dash_orbs(self, image, foot_x, foot_y, elapsed, scale=.5):
        import ctypes
        import sdl2 as s
        old_alpha = ctypes.c_uint8()
        s.SDL_GetTextureAlphaMod(image.texture, ctypes.byref(old_alpha))
        try:
            for slot in range(2):
                state = dash_orb_visual(elapsed, slot)
                size = 14 * state['scale'] * scale
                image.opacify(state['opacity'] * .9)
                image.draw(foot_x + (-14 + slot * 14) * scale, foot_y + 64 * scale, size, size)
                if state['ring'] > 0:
                    ring = state['ring']
                    y, x = np.mgrid[:44, :44]
                    distance = np.abs(np.hypot(x + .5 - 22, y + .5 - 22) - (7 + ring * 13))
                    rgba = np.zeros((44, 44, 4), dtype=np.uint8)
                    rgba[..., :3] = (255, 221, 146)
                    rgba[..., 3] = np.rint(np.clip(1 - distance, 0, 1) * (1 - ring) * 255).astype(np.uint8)
                    self._texture.upload(rgba)
                    self._texture.draw(foot_x, foot_y + 64 * scale, origin=(22, 22), scale=scale)
        finally:
            s.SDL_SetTextureAlphaMod(image.texture, old_alpha.value)

    def draw_absorb_failure(self, width, height, elapsed):
        if elapsed < 0 or elapsed >= .3 or width < 5 or height < 5:
            return
        rgba = np.zeros((height, width, 4), dtype=np.uint8)
        rgba[..., :3] = (245, 72, 93)
        alpha = round((1 - elapsed / .3) * .8 * 255)
        rgba[2, 2:width - 1, 3] = rgba[height - 2, 2:width - 1, 3] = alpha
        rgba[2:height - 1, 2, 3] = rgba[2:height - 1, width - 2, 3] = alpha
        self._texture.upload(rgba)
        self._texture.draw(0, height, origin=(0, 0))

    def draw_door_flash(self, x, y, width, height, elapsed):
        """x/y is the bottom-left of the door rectangle in pico2d coordinates."""
        if elapsed < 0 or elapsed >= .45 or width <= 0 or height <= 0:
            return
        rgba = np.array([[[230, 200, 151, round((1 - elapsed / .45) * .2 * 255)]]], dtype=np.uint8)
        self._texture.upload(rgba)
        import ctypes
        import sdl2 as s
        from pico2d import pico2d as canvas
        rect = s.SDL_Rect(round(x), round(canvas.get_canvas_height() - y - height), round(width), round(height))
        s.SDL_RenderCopy(canvas.renderer, self._texture.texture, None, ctypes.byref(rect))

    def close(self):
        self._texture.close()
