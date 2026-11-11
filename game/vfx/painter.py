"""NumPy rasterizer for the primitives used by Gleam's approved JS effects.

Ported from pixelfx core/{painter,color,math,fx}.js (MIT).
Keep LICENSE and NOTICE.md from this directory with redistributed copies.
Coordinates are pixels, x right/y down; RGBA output is top-down.
"""
from functools import lru_cache
import math

import numpy as np


TAU = math.tau
BAYER = (np.array([0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]) + .5) / 16


def clamp(value, low=0, high=1):
    return max(low, min(high, value))


def rand(*numbers):
    """Match JS Math.imul and unsigned shifts, including negative seeds."""
    h = 0x9E3779B9
    for number in numbers:
        h = ((h ^ (int(number) & 0xFFFFFFFF)) * 0x85EBCA6B) & 0xFFFFFFFF
        h ^= h >> 13
        h = (h * 0xC2B2AE35) & 0xFFFFFFFF
        h ^= h >> 16
    return h / 4294967296


def hex_color(value):
    if isinstance(value, (int, np.integer)):
        return int(value) & 0xFFFFFFFF
    text = value.lstrip('#')
    if len(text) == 3:
        text = ''.join(ch * 2 for ch in text)
    rgb = int(text[:6], 16)
    return 0xFF000000 | ((rgb & 255) << 16) | (rgb & 0xFF00) | (rgb >> 16)


@lru_cache(maxsize=64)
def _fit(palette, count):
    if not palette or count < 1:
        raise ValueError('A nonempty palette and positive count are required')
    colors = tuple(hex_color(c) for c in palette)
    return tuple(colors[math.floor(i * (len(colors) - 1) / max(1, count - 1) + .5)]
                 for i in range(count))


def fit(palette, count=8):
    return _fit(tuple(palette), count)


def _value(value, *args):
    return value(*args) if callable(value) else value


class Frame:
    def __init__(self, width, height, ox=0, oy=0):
        if width <= 0 or height <= 0:
            raise ValueError('Frame dimensions must be positive')
        self.w, self.h = int(width), int(height)
        self.ox, self.oy = int(ox), int(oy)
        self.color = np.zeros((self.h, self.w), dtype=np.uint32)
        self.light = np.zeros_like(self.color)

    def clear(self):
        self.color.fill(0)
        self.light.fill(0)
        return self

    def rgba(self, background=None, light_strength=1):
        """Match pixelfx composite(), including Uint8ClampedArray rounding."""
        c, light = self.color, self.light
        rgb = np.stack([(c >> s) & 255 for s in (0, 8, 16)], axis=-1).astype(float)
        alpha = (c >> 24).astype(float)
        if background is not None:
            bg = np.asarray(background, dtype=np.uint32)
            channels = np.stack([(bg >> s) & 255 for s in (0, 8, 16)], axis=-1)
            rgb = rgb * (alpha[..., None] / 255) + channels * (1 - alpha[..., None] / 255)
            alpha.fill(255)
        glow = np.stack([(light >> s) & 255 for s in (0, 8, 16)], axis=-1) * light_strength
        has_light = (light & 0xFFFFFF) != 0
        old_a = alpha / 255
        new_a = np.minimum(1, np.maximum(old_a, glow.max(axis=-1) / 255))
        premultiplied = rgb * old_a[..., None] + glow
        lit = np.minimum(255, premultiplied / np.maximum(new_a[..., None], 1e-30))
        rgb = np.where(has_light[..., None], lit, rgb)
        alpha = np.where(has_light, new_a * 255, alpha)
        return np.rint(np.clip(np.dstack((rgb, alpha)), 0, 255)).astype(np.uint8)


class Painter:
    def __init__(self, frame):
        self.frame = frame
        self.fade = self.light_k = 1.0
        self.place(0, 0)

    def place(self, x, y, flip=False, angle=0):
        self.tx, self.ty, self.fx = x, y, -1 if flip else 1
        self.cs, self.sn = math.cos(angle), math.sin(angle)
        return self

    def _to(self, x, y):
        return (self.tx + x * self.fx * self.cs - y * self.sn,
                self.ty + x * self.fx * self.sn + y * self.cs)

    def _cell(self, x, y):
        xx, yy = self._to(math.floor(x) + .5, math.floor(y) + .5)
        return math.floor(xx), math.floor(yy)

    def _region(self, x0, y0, x1, y1):
        corners = [self._to(x, y) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
        return self._screen_region(min(p[0] for p in corners), min(p[1] for p in corners),
                                   max(p[0] for p in corners), max(p[1] for p in corners))

    def _screen_region(self, x0, y0, x1, y1):
        f = self.frame
        left, right = max(math.floor(x0), f.ox), min(math.ceil(x1), f.ox + f.w - 1)
        top, bottom = max(math.floor(y0), f.oy), min(math.ceil(y1), f.oy + f.h - 1)
        sy, sx = np.mgrid[top:bottom + 1, left:right + 1]
        dx, dy = sx + .5 - self.tx, sy + .5 - self.ty
        lx, ly = (dx * self.cs + dy * self.sn) * self.fx, -dx * self.sn + dy * self.cs
        return sx, sy, lx, ly

    def _put(self, sx, sy, color, alpha=1):
        f = self.frame
        sx, sy, color, alpha = np.broadcast_arrays(sx, sy, color, np.asarray(alpha) * self.fade)
        keep = ((color != 0) & ((alpha >= 1) | (alpha > BAYER[((sy & 3) << 2) | (sx & 3)]))
                & (sx >= f.ox) & (sy >= f.oy) & (sx < f.ox + f.w) & (sy < f.oy + f.h))
        f.color[sy[keep] - f.oy, sx[keep] - f.ox] = color[keep].astype(np.uint32)

    def _add(self, sx, sy, color, strength):
        f = self.frame
        sx, sy, color, strength = np.broadcast_arrays(sx, sy, color,
                                                       np.asarray(strength) * self.fade * self.light_k)
        keep = ((strength > .004) & (sx >= f.ox) & (sy >= f.oy)
                & (sx < f.ox + f.w) & (sy < f.oy + f.h))
        x, y, color, k = sx[keep] - f.ox, sy[keep] - f.oy, color[keep].astype(np.uint32), strength[keep]
        previous = f.light[y, x]
        result = np.full(previous.shape, 0xFF000000, dtype=np.uint32)
        for shift in (0, 8, 16):
            channel = np.minimum(255, ((previous >> shift) & 255) + ((color >> shift) & 255) * k)
            result |= channel.astype(np.uint32) << shift
        f.light[y, x] = result

    def _blend(self, sx, sy, color, alpha):
        f = self.frame
        sx, sy, color, alpha = np.broadcast_arrays(sx, sy, color, np.asarray(alpha) * self.fade)
        keep = ((color != 0) & (alpha > .004) & (sx >= f.ox) & (sy >= f.oy)
                & (sx < f.ox + f.w) & (sy < f.oy + f.h))
        x, y, c, a = sx[keep] - f.ox, sy[keep] - f.oy, color[keep].astype(np.uint32), alpha[keep]
        old = f.color[y, x]
        out_a = a + (old >> 24) / 255 * (1 - a)
        k = a / out_a
        result = ((out_a * 255).astype(np.uint32) & 255) << 24
        for shift in (0, 8, 16):
            channel = (((c >> shift) & 255) * k + ((old >> shift) & 255) * (1 - k))
            result |= (channel.astype(np.uint32) & 255) << shift
        f.color[y, x] = result

    def px(self, x, y, color):
        self.dot(x, y, color)

    def dot(self, x, y, color, alpha=1):
        sx, sy = self._cell(x, y)
        self._pixel(sx, sy, color, alpha)

    def _pixel(self, sx, sy, color, alpha):
        # Scalar writes avoid NumPy allocation for short particle strokes.
        f = self.frame
        a = alpha * self.fade
        if (color and a > 0 and (a >= 1 or a > BAYER[((sy & 3) << 2) | (sx & 3)])
                and f.ox <= sx < f.ox + f.w and f.oy <= sy < f.oy + f.h):
            f.color[sy - f.oy, sx - f.ox] = color & 0xFFFFFFFF

    def blend(self, x, y, color, alpha):
        sx, sy = self._cell(x, y)
        f, a = self.frame, alpha * self.fade
        if not color or a <= .004 or not (f.ox <= sx < f.ox + f.w and f.oy <= sy < f.oy + f.h):
            return
        xx, yy = sx - f.ox, sy - f.oy
        old = int(f.color[yy, xx])
        out_a = a + (old >> 24) / 255 * (1 - a)
        k = a / out_a
        out = (int(out_a * 255) & 255) << 24
        for shift in (0, 8, 16):
            out |= (int(((color >> shift) & 255) * k + ((old >> shift) & 255) * (1 - k)) & 255) << shift
        f.color[yy, xx] = out

    def line(self, x0, y0, x1, y1, color, alpha=1):
        sx, sy = self._cell(x0, y0)
        ex, ey = self._cell(x1, y1)
        dx, dy = abs(ex - sx), -abs(ey - sy)
        stepx, stepy = (1 if sx < ex else -1), (1 if sy < ey else -1)
        n, error, i = max(dx, -dy) or 1, dx + dy, 0
        while True:
            u = i / n
            # These are already screen pixels, so don't transform them twice.
            self._pixel(sx, sy, _value(color, u), _value(alpha, u))
            if sx == ex and sy == ey:
                break
            e2 = 2 * error
            if e2 >= dy:
                error, sx = error + dy, sx + stepx
            if e2 <= dx:
                error, sy = error + dx, sy + stepy
            i += 1

    def polyline(self, points, color, alpha=1):
        for a, b in zip(points, points[1:]):
            self.line(*a, *b, color, alpha)

    def _disc(self, cx, cy, rx, ry, color, alpha, blend=False):
        if rx <= 0 or ry <= 0:
            return
        sx, sy, x, y = self._region(cx - rx, cy - ry, cx + rx, cy + ry)
        dx, dy = (x - cx) / rx, (y - cy) / ry
        d2 = dx * dx + dy * dy
        keep = d2 <= 1
        d, angle = np.sqrt(d2[keep]), np.arctan2(dy[keep], dx[keep])
        writer = self._blend if blend else self._put
        writer(sx[keep], sy[keep], _value(color, d, angle), _value(alpha, d, angle))

    def circle(self, cx, cy, radius, color, alpha=1):
        if radius < .6:
            return self.dot(cx, cy, _value(color, 0, 0), _value(alpha, 0, 0))
        self._disc(cx, cy, radius, radius, color, alpha)

    def ellipse(self, cx, cy, rx, ry, color, alpha=1):
        self._disc(cx, cy, rx, ry, color, alpha)

    def disc(self, cx, cy, radius, color, alpha):
        if radius < .5:
            return self.blend(cx, cy, _value(color, 0, 0), _value(alpha, 0, 0))
        self._disc(cx, cy, radius, radius, color, alpha, True)

    def beam(self, x0, y0, x1, y1, width, color, alpha=1):
        r, dx, dy = width / 2, x1 - x0, y1 - y0
        sx, sy, x, y = self._region(min(x0, x1) - r, min(y0, y1) - r,
                                   max(x0, x1) + r, max(y0, y1) + r)
        u = np.clip(((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy or 1e-9), 0, 1)
        d2 = (x0 + dx * u - x) ** 2 + (y0 + dy * u - y) ** 2
        keep = d2 <= r * r
        v = np.sqrt(d2[keep]) / r
        self._put(sx[keep], sy[keep], _value(color, u[keep], v), _value(alpha, u[keep], v))

    def glow(self, x, y, radius, color, strength=.5):
        if radius < 1 or strength <= .004:
            return
        cx, cy = self._to(x, y)
        sx, sy, _, _ = self._screen_region(cx - radius, cy - radius, cx + radius, cy + radius)
        d2 = ((sx + .5 - cx) / radius) ** 2 + ((sy + .5 - cy) / radius) ** 2
        keep = d2 < 1
        self._add(sx[keep], sy[keep], color, (1 - np.sqrt(d2[keep])) ** 2 * strength)

    def glow_line(self, x0, y0, x1, y1, radius, color, strength=.5):
        if radius < 1 or strength <= .004:
            return
        ax, ay = self._to(x0, y0)
        bx, by = self._to(x1, y1)
        dx, dy = bx - ax, by - ay
        sx, sy, _, _ = self._screen_region(min(ax, bx) - radius, min(ay, by) - radius,
                                          max(ax, bx) + radius, max(ay, by) + radius)
        px, py = sx + .5, sy + .5
        u = np.clip(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1e-9), 0, 1)
        d = np.sqrt((ax + dx * u - px) ** 2 + (ay + dy * u - py) ** 2) / radius
        keep = d < 1
        self._add(sx[keep], sy[keep], color, (1 - d[keep]) ** 2 * strength)
