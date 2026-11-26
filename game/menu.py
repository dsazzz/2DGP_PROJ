"""타이틀과 일시정지 화면에서 쓰는 메뉴."""
import ctypes
import os
from pathlib import Path

import numpy as np
import pico2d as p
from pico2d import pico2d as canvas
import sdl2 as s
from sdl2 import sdlttf

from game.core.display import LOGICAL_SIZE, WINDOW_SIZE
from game.core.paths import ART_ROOT


SETTINGS = (('fullscreen', '화면 모드'), ('master', '전체 음량'),
            ('music', '배경음'), ('effects', '효과음'))
TITLE_ACTIONS = ('start', 'settings', 'quit')
PAUSE_ITEMS = (('play', '계속하기'), ('restart', '재시작'),
               ('settings', '환경 설정'), ('title', '타이틀로'), ('quit', '게임 종료'))
PAUSE_ACTIONS = tuple(action for action, _ in PAUSE_ITEMS)
TEXT = (246, 246, 246)
SELECTED = (255, 223, 151)


def label_glow(surface):
    """문자 투명도를 흐리게 만들어 금빛을 한 번만 굽는다."""
    converted = s.SDL_ConvertSurfaceFormat(surface, s.SDL_PIXELFORMAT_RGBA32, 0)
    if not converted:
        raise RuntimeError(s.SDL_GetError())
    try:
        glyph = converted.contents
        raw = ctypes.string_at(glyph.pixels, glyph.pitch * glyph.h)
        alpha = np.frombuffer(raw, np.uint8).reshape(glyph.h, glyph.pitch)[:, 3:glyph.w * 4:4]
        padding = 10
        alpha = np.pad(alpha, padding)
        offsets = np.arange(-padding, padding + 1)
        kernel = np.exp(-0.5 * (offsets / 3.7) ** 2)
        kernel /= kernel.sum()
        blur = np.apply_along_axis(lambda row: np.convolve(row, kernel, 'same'), 1, alpha)
        blur = np.apply_along_axis(lambda col: np.convolve(col, kernel, 'same'), 0, blur)
    finally:
        s.SDL_FreeSurface(converted)
    height, width = blur.shape
    pixels = np.empty((height, width, 4), dtype=np.uint8)
    pixels[..., :3] = (255, 181, 79)
    pixels[..., 3] = np.rint(blur * .8).astype(np.uint8)
    halo = s.SDL_CreateRGBSurfaceWithFormatFrom(ctypes.c_void_p(pixels.ctypes.data),
                                               width, height, 32, width * 4, s.SDL_PIXELFORMAT_RGBA32)
    if not halo:
        raise RuntimeError(s.SDL_GetError())
    try:
        texture = s.SDL_CreateTextureFromSurface(canvas.renderer, halo)
        if not texture:
            raise RuntimeError(s.SDL_GetError())
        return p.Image(texture)
    finally:
        s.SDL_FreeSurface(halo)


class Menu:
    def __init__(self):
        self.labels = {}
        self.cursor = None
        self.pause_background = None
        self.reset()

    def reset(self):
        self.selected = 0
        self.settings = False

    def handle(self, key, game):
        actions = PAUSE_ACTIONS if game.mode == 'pause' else TITLE_ACTIONS
        if key in (s.SDLK_UP, s.SDLK_DOWN):
            count = len(SETTINGS) + 1 if self.settings else len(actions)
            direction = 1 if key == s.SDLK_DOWN else -1
            self.selected = (self.selected + direction) % count
        elif self.settings:
            if key == s.SDLK_ESCAPE or (key == s.SDLK_RETURN and self.selected == len(SETTINGS)):
                self.settings, self.selected = False, actions.index('settings')
            elif key in (s.SDLK_LEFT, s.SDLK_RIGHT, s.SDLK_RETURN) and self.selected < len(SETTINGS):
                game.change_setting(SETTINGS[self.selected][0], -1 if key == s.SDLK_LEFT else 1)
        elif key == s.SDLK_ESCAPE:
            return 'play' if game.mode == 'pause' else 'quit'
        elif key == s.SDLK_RETURN:
            action = actions[self.selected]
            if action == 'settings':
                self.settings, self.selected = True, 0
            else:
                return action
        return None

    def label(self, text, size, x, y, color, *, font_name='malgunbd.ttf', glow=False, centered=False):
        key = text, size, color, font_name, glow
        if key not in self.labels:
            path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / font_name
            font = p.load_font(str(path), size)
            try:
                surface = sdlttf.TTF_RenderUTF8_Blended(font.font, text.encode(), s.SDL_Color(*color, 255))
                if not surface:
                    raise RuntimeError(s.SDL_GetError())
                try:
                    texture = s.SDL_CreateTextureFromSurface(canvas.renderer, surface)
                    if not texture:
                        raise RuntimeError(s.SDL_GetError())
                    image = p.Image(texture)
                    self.labels[key] = image, label_glow(surface) if glow else None
                finally:
                    s.SDL_FreeSurface(surface)
            finally:
                sdlttf.TTF_CloseFont(font.font)
        image, halo = self.labels[key]
        center = x if centered else x + image.w / 2
        if halo is not None:
            halo.draw(center, y)
        image.draw(center, y)

    def draw_cursor(self, x, y):
        if self.cursor is None:
            self.cursor = p.load_image(str(ART_ROOT / 'environment/backgrounds/title-cursor.png'))
        self.cursor.draw(x, y)

    def draw_settings(self, game):
        paused = game.mode == 'pause'
        name_x, value_x, top, spacing, size = (727, 970, 651, 75, 38) if paused else (126, 370, 551, 59, 32)
        values = {'fullscreen': '전체화면 1920×1080' if game.fullscreen else '창 모드 960×540'}
        values.update({key: f'{value}%' for key, value in game.volumes.items()})
        for i, (key, name) in enumerate(SETTINGS):
            color = SELECTED if self.selected == i else TEXT
            y = top - i * spacing
            self.label(name, size, name_x, y, color)
            self.label(values[key], size, value_x, y, color)
        self.label('돌아가기', size, name_x, top - len(SETTINGS) * spacing,
                   SELECTED if self.selected == len(SETTINGS) else TEXT)
        self.label(game.settings_notice or '↑ ↓ 선택    ← → 변경    Esc 돌아가기',
                   24, 960 if paused else 126, 227 if paused else 151, (202, 198, 190), centered=paused)

    def draw_pause(self, game):
        if self.pause_background is None:
            path = ART_ROOT / 'environment/backgrounds/pause.png'
            self.pause_background = p.load_image(str(path))
        renderer = canvas.renderer
        s.SDL_RenderSetLogicalSize(renderer, *WINDOW_SIZE)
        canvas.canvas_width, canvas.canvas_height = WINDOW_SIZE
        try:
            self.pause_background.draw(960, 540)
            if self.settings:
                self.draw_settings(game)
                return
            self.label('PAUSED', 132, 960, 829, TEXT, font_name='georgia.ttf', centered=True)
            for row, (_, caption) in enumerate(PAUSE_ITEMS):
                active = row == self.selected
                y = 651 - row * 75
                self.label(caption, 40, 826, y, SELECTED if active else TEXT, glow=active)
                if active:
                    self.draw_cursor(768, y)
        finally:
            s.SDL_RenderSetLogicalSize(renderer, *LOGICAL_SIZE)
            canvas.canvas_width, canvas.canvas_height = LOGICAL_SIZE

    def close(self):
        self.labels.clear()
        self.cursor = self.pause_background = None
