"""Electric appearance and frame cache; accepts world-space bands only."""
import ctypes
from functools import lru_cache
import math

import numpy as np
import sdl2 as s
from pico2d import pico2d as canvas
from game.core.collision import AABB
from game.objects.models import merge_straight_bands
from game.vfx.painter import rand

def _crackle(area, kind, tick):
    """Deterministic branching lines confined to the gameplay danger area."""
    horizontal = kind == 'horizontal'
    vertical = kind == 'vertical'
    length = area.width if horizontal else area.height
    if not (horizontal or vertical):
        length = max(area.width, area.height)
    steps = max(2, math.ceil(length / 4.5))
    phase = tick / ELECTRIC_FRAMES * math.tau
    seed = (round(area.left * 8), round(area.bottom * 8), round(area.width * 8), round(area.height * 8))
    lines = []
    if horizontal or vertical:
        for strand in range(2):
            points = []
            for j in range(steps + 1):
                u = j / steps
                # Matching endpoint seeds keep adjacent rendering chunks connected.
                axis = (area.left + area.width*u) if horizontal else (area.bottom + area.height*u)
                fixed = area.bottom if horizontal else area.left
                noise = (rand(round(axis*8), round(fixed*8), strand, 99)
                         if j in (0, steps) else rand(*seed, strand, j))
                # Persistent irregular paths drift gently instead of flashing anew.
                jitter = .12 + .72*noise + .075*math.sin(phase + noise*math.tau)
                x = area.left + (area.width * u if horizontal else area.width * jitter)
                y = area.bottom + (area.height * jitter if horizontal else area.height * u)
                points.append((x, y))
            lines.extend((a, b, strand) for a, b in zip(points, points[1:]))
            for j in range(1, steps, 7):
                x, y = points[j]
                u = min(1, j / steps + .10 + .08 * rand(*seed, strand, j, 1))
                v = .10 + .80 * rand(*seed, strand, j, 2)
                target = (area.left + area.width*u, area.bottom + area.height*v) if horizontal else (
                    area.left + area.width*v, area.bottom + area.height*u)
                lines.append(((x, y), target, 3))
    else:
        # Dense junction web joins vertical and horizontal paths without a box outline.
        for j in range(4):
            drift = .055*math.sin(phase + j)
            x1 = area.left + area.width * (.14 + .72 * rand(*seed, j, 1) + drift)
            y1 = area.bottom + area.height * (.14 + .72 * rand(*seed, j, 2) + drift)
            x2 = area.left + area.width * (.14 + .72 * rand(*seed, j, 3) - drift)
            y2 = area.bottom + area.height * (.14 + .72 * rand(*seed, j, 4) - drift)
            lines.append(((x1, y1), (x2, y2), j % 4))
    return lines


class _ElectricPaths:
    def __init__(self, bands):
        self.parts = []
        for area, kind in merge_straight_bands(bands):
            if kind == 'junction':
                self.parts.append((area, kind))
                continue
            horizontal = kind == 'horizontal'
            start, end = (area.left, area.right) if horizontal else (area.bottom, area.top)
            while start < end:
                stop = min(start + 64, end)
                chunk = (AABB(start, area.bottom, stop-start, area.height) if horizontal
                         else AABB(area.left, start, area.width, stop-start))
                self.parts.append((chunk, kind))
                start = stop
        self._neighbors = {}
        for i, (node, kind) in enumerate(self.parts):
            if kind != 'junction':
                continue
            neighbors = []
            for j, (band, direction) in enumerate(self.parts):
                if direction == 'horizontal' and node.bottom <= band.bottom + band.height/2 <= node.top:
                    if node.left <= band.left <= node.right or node.left <= band.right <= node.right:
                        neighbors.append(j)
                elif direction == 'vertical' and node.left <= band.left + band.width/2 <= node.right:
                    if node.bottom <= band.bottom <= node.top or node.bottom <= band.top <= node.top:
                        neighbors.append(j)
            self._neighbors[i] = neighbors
        self._cache = {}

    def _lines(self, index, tick):
        cached = self._cache.get(index)
        if cached is None or cached[0] != tick:
            area, kind = self.parts[index]
            lines = _crackle(area, kind, tick)
            if kind == 'junction':
                # Join actual strand endpoints through the junction, with no outline.
                points = []
                for neighbor in self._neighbors[index]:
                    band, direction = self.parts[neighbor]
                    for a, b, strand in self._lines(neighbor, tick):
                        if strand == 3:
                            continue
                        for x, y in (a, b):
                            endpoint = ((abs(x-band.left) < 1e-6 or abs(x-band.right) < 1e-6)
                                        if direction == 'horizontal' else
                                        (abs(y-band.bottom) < 1e-6 or abs(y-band.top) < 1e-6))
                            if endpoint and area.left <= x <= area.right and area.bottom <= y <= area.top:
                                points.append((x, y, strand))
                if points:
                    drift = .04*math.sin(tick/ELECTRIC_FRAMES*math.tau)
                    anchor = (area.left + area.width*(.25 + .5*rand(index, 777) + drift),
                              area.bottom + area.height*(.25 + .5*rand(index, 778) - drift))
                    for x, y, strand in points:
                        mid = ((x + anchor[0])/2 + (rand(index, strand, 779)-.5)*2,
                               (y + anchor[1])/2 + (rand(index, strand, 780)-.5)*2)
                        mid = (max(area.left, min(area.right, mid[0])),
                               max(area.bottom, min(area.top, mid[1])))
                        lines.extend((((x, y), mid, strand), (mid, anchor, strand)))
            cached = (tick, lines)
            self._cache[index] = cached
        return cached[1]

ELECTRIC_FRAMES = 12
ELECTRIC_FPS = 10
ELECTRIC_CHUNK = 128
_SHEET_COLUMNS = 4
_COLORS = ((213, 68, 85, 210), (232, 127, 137, 190),
           (177, 47, 66, 155), (177, 47, 66, 145))


def _line_pixels(a, b):
    steps = max(1, math.ceil(max(abs(b[0]-a[0]), abs(b[1]-a[1]))))
    return (np.rint(np.linspace(a[0], b[0], steps+1)).astype(np.int32),
            np.rint(np.linspace(a[1], b[1], steps+1)).astype(np.int32))


@lru_cache(maxsize=2)
def _electric_frames(key):
    """Bake one layout, shared by reloads. Cache contains pixels, never SDL handles."""
    if not key:
        return ()
    paths = _ElectricPaths((AABB(x, y, w, h), kind) for x, y, w, h, kind in key)
    chunk_size = ELECTRIC_CHUNK
    origins = set()
    for x, y, w, h, _ in key:
        for cy in range(math.floor((y-1)/chunk_size), math.floor((y+h+1)/chunk_size)+1):
            for cx in range(math.floor((x-1)/chunk_size), math.floor((x+w+1)/chunk_size)+1):
                origins.add((cx*chunk_size, cy*chunk_size))
    sheets = {origin: np.zeros((chunk_size*3, chunk_size*_SHEET_COLUMNS, 4), np.uint8)
              for origin in sorted(origins)}
    for tick in range(ELECTRIC_FRAMES):
        lines = [line for index in range(len(paths.parts)) for line in paths._lines(index, tick)]
        # Draw all dim side-light before cores; no opaque collision outlines.
        pixels = [(*_line_pixels(a, b), strand) for a, b, strand in lines]
        for glow in (True, False):
            for xs, ys, strand in pixels:
                yy = ys-1 if glow else ys
                color = (128, 27, 44, 70) if glow else _COLORS[strand]
                cells = set(zip((xs//chunk_size).tolist(), (yy//chunk_size).tolist()))
                for cx, cy in cells:
                    origin = (cx*chunk_size, cy*chunk_size)
                    sheet = sheets.get(origin)
                    if sheet is None:
                        continue
                    selected = ((xs >= origin[0]) & (xs < origin[0]+chunk_size)
                                & (yy >= origin[1]) & (yy < origin[1]+chunk_size))
                    px = xs[selected]-origin[0] + (tick % _SHEET_COLUMNS)*chunk_size
                    py = chunk_size-1-(yy[selected]-origin[1]) + (tick//_SHEET_COLUMNS)*chunk_size
                    sheet[py, px] = color
    return tuple((AABB(x, y, chunk_size, chunk_size), sheet)
                 for (x, y), sheet in sheets.items() if sheet[..., 3].any())


class ElectricEffect:
    """Cached electric FX: at most one texture draw per visible 128px chunk."""
    def __init__(self, bands):
        self.key = tuple((a.left, a.bottom, a.width, a.height, kind) for a, kind in bands)
        self.time = 0.0
        self.chunks = None
        self._textures = {}

    def prerender(self):
        if self.chunks is None:
            self.chunks = _electric_frames(self.key)

    def reset(self):
        self.time = 0.0

    def update(self, dt):
        self.time += dt

    def draw(self, camera):
        self.prerender()
        index = math.floor((self.time+1e-9)*ELECTRIC_FPS) % ELECTRIC_FRAMES
        ox, oy = camera.offset
        height = canvas.get_canvas_height()
        size = ELECTRIC_CHUNK
        source = s.SDL_Rect((index % _SHEET_COLUMNS)*size, (index//_SHEET_COLUMNS)*size, size, size)
        for chunk_index, (area, sheet) in enumerate(self.chunks):
            if not camera.visible(area):
                continue
            texture = self._textures.get(chunk_index)
            if texture is None:
                h, w, _ = sheet.shape
                texture = s.SDL_CreateTexture(canvas.renderer, s.SDL_PIXELFORMAT_RGBA32,
                                              s.SDL_TEXTUREACCESS_STATIC, w, h)
                if not texture:
                    raise RuntimeError(s.SDL_GetError().decode('utf-8', errors='replace'))
                self._textures[chunk_index] = texture
                if s.SDL_UpdateTexture(texture, None, ctypes.c_void_p(sheet.ctypes.data), w*4) < 0:
                    raise RuntimeError('Cannot upload cached electric frames')
                s.SDL_SetTextureBlendMode(texture, s.SDL_BLENDMODE_BLEND)
            destination = s.SDL_FRect(area.left-ox, height-(area.top-oy), size, size)
            if s.SDL_RenderCopyF(canvas.renderer, texture, ctypes.byref(source), ctypes.byref(destination)) < 0:
                raise RuntimeError(s.SDL_GetError().decode('utf-8', errors='replace'))

    def close(self):
        for texture in self._textures.values():
            s.SDL_DestroyTexture(texture)
        self._textures.clear()


