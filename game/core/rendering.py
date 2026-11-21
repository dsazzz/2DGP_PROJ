"""pico2d 이미지의 소수점 위치를 SDL 출력까지 유지하는 공통 그리기 함수."""
import ctypes
import math

from pico2d import pico2d as canvas
import sdl2 as s


def draw_clip(image, left, bottom, width, height, rad, flip, x, y, w=None, h=None):
    """pico2d의 클립·중앙 기준 좌표를 사용하며 목적 사각형은 소수점으로 전달한다."""
    w = width if w is None else w
    h = height if h is None else h
    source = s.SDL_Rect(left, image.h - bottom - height, width, height)
    destination = s.SDL_FRect(x - w / 2, canvas.get_canvas_height() - y - h / 2, w, h)
    flags = s.SDL_FLIP_NONE
    if 'h' in flip:
        flags |= s.SDL_FLIP_HORIZONTAL
    if 'v' in flip:
        flags |= s.SDL_FLIP_VERTICAL
    if rad or flags:
        status = s.SDL_RenderCopyExF(canvas.renderer, image.texture, ctypes.byref(source),
                                    ctypes.byref(destination), -math.degrees(rad), None, flags)
    else:
        status = s.SDL_RenderCopyF(canvas.renderer, image.texture, ctypes.byref(source),
                                  ctypes.byref(destination))
    if status < 0:
        raise RuntimeError(s.SDL_GetError().decode('utf-8', errors='replace'))
