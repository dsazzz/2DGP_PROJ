"""Draw world-space terrain sprites; no editor formats or gameplay rules."""
import ctypes
import math

import numpy as np
import pico2d as p
from pico2d import pico2d as canvas
import sdl2 as s

from game.core.rendering import draw_clip
from game.vfx.pico import StreamingTexture, load_rgba


CHUNK_SIZE = 128


class TerrainView:
    def __init__(self, layers):
        self.layers = []
        for layer in layers:
            chunks = {}
            padding = 0
            for tile in layer['tiles']:
                x, y, w, h = tile['rect']
                padding = max(padding, w, h)
                key = math.floor(x / CHUNK_SIZE), math.floor(y / CHUNK_SIZE)
                chunks.setdefault(key, []).append(tile)
            self.layers.append((layer['image'], padding, chunks, {}))

    def preload(self):
        try:
            for path, _, chunks, textures in self.layers:
                if chunks:
                    atlas = load_rgba(path)
                    for key, tiles in chunks.items():
                        baked = self._bake_chunk(tiles, atlas)
                        if baked is not None:
                            textures[key] = baked
        except Exception:
            self.close()
            raise

    @staticmethod
    def _bake_chunk(tiles, atlas):
        # 겹치거나 원본과 크기가 다른 타일은 기존 합성 순서로 그린다.
        if any(tile['opacity'] != 1 or tile['rect'][2:] != tile['source'][2:]
               or any(int(value) != value for value in tile['rect']) for tile in tiles):
            return None
        rects = [tuple(map(int, tile['rect'])) for tile in tiles]
        left = min(x for x, _, _, _ in rects)
        top = max(y + h for _, y, _, h in rects)
        width = max(x + w for x, _, w, _ in rects) - left
        height = top - min(y for _, y, _, _ in rects)
        pixels = np.zeros((height, width, 4), dtype=np.uint8)
        occupied = np.zeros((height, width), dtype=bool)
        for tile, (x, y, w, h) in zip(tiles, rects):
            col, row = x - left, top - y - h
            area = np.s_[row:row+h, col:col+w]
            if occupied[area].any():
                return None
            occupied[area] = True
            sx, sy, sw, sh = tile['source']
            source = atlas[sy:sy+sh, sx:sx+sw]
            if 'h' in tile['flip']:
                source = source[:, ::-1]
            if 'v' in tile['flip']:
                source = source[::-1]
            pixels[area] = source
        texture = StreamingTexture()
        try:
            texture.upload(pixels)
            if (pixels[..., 3] == 255).all():
                s.SDL_SetTextureBlendMode(texture.texture, s.SDL_BLENDMODE_NONE)
            return texture, left, top, width, height
        except Exception:
            texture.close()
            raise

    def draw(self, camera, images):
        view, (cx, cy) = camera.view, camera.offset
        scale_x, scale_y = ctypes.c_float(), ctypes.c_float()
        s.SDL_RenderGetScale(canvas.renderer, ctypes.byref(scale_x), ctypes.byref(scale_y))
        aligned_x = math.isclose(cx * scale_x.value, round(cx * scale_x.value), abs_tol=1e-7)
        aligned_y = math.isclose(cy * scale_y.value, round(cy * scale_y.value), abs_tol=1e-7)
        for path, padding, chunks, textures in self.layers:
            image, alpha = images.get(path), 1
            for row in range(math.floor((view.bottom - padding) / CHUNK_SIZE),
                             math.floor(view.top / CHUNK_SIZE) + 1):
                for col in range(math.floor((view.left - padding) / CHUNK_SIZE),
                                 math.floor(view.right / CHUNK_SIZE) + 1):
                    key = col, row
                    if key in textures:
                        texture, left, top, width, height = textures[key]
                        # 출력 픽셀 중간에서 잘리는 구역은 타일 단위 샘플링을 유지한다.
                        if ((aligned_x or (left >= view.left and left + width <= view.right))
                                and (aligned_y or (top <= view.top and top - height >= view.bottom))):
                            texture.draw(left - cx, top - cy)
                            continue
                    for tile in chunks.get(key, ()):
                        x,y,w,h = tile['rect']
                        if x >= view.right or x+w <= view.left or y >= view.top or y+h <= view.bottom:
                            continue
                        if image is None:
                            image = images[path] = p.load_image(path)
                        left,top,sw,sh = tile['source']
                        opacity = tile['opacity']
                        if alpha != opacity:
                            image.opacify(opacity)
                            alpha = opacity
                        draw_clip(image,left,image.h-top-sh,sw,sh,0,tile['flip'],
                                  x+w/2-cx,y+h/2-cy,w,h)
            if alpha != 1:
                image.opacify(1)

    def close(self):
        for _, _, _, textures in self.layers:
            for texture, *_ in textures.values():
                texture.close()
            textures.clear()
