"""타이틀 화면과 전류창 해제 연출."""
from pathlib import Path
import os
from time import perf_counter

import pico2d as p
from pico2d import pico2d as canvas
import sdl2 as s
from sdl2 import sdlttf

from game.core.display import LOGICAL_SIZE, WINDOW_SIZE
from game.core.paths import ART_ROOT


SETTINGS = (('fullscreen', '화면 모드'), ('master', '전체 음량'),
            ('music', '배경음'), ('effects', '효과음'))


class Title:
    def __init__(self):
        folder = ART_ROOT / 'environment/backgrounds'
        self.sleep = p.load_image(str(folder / 'title-sleep.png'))
        self.awake = p.load_image(str(folder / 'title-awake.png'))
        self.labels = {}
        self.selected = 0
        self.settings = False
        self.wake_start = None

    def label(self, text, size, x, y, color):
        key = text, size, color
        if key not in self.labels:
            path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'malgunbd.ttf'
            font = p.load_font(str(path), size)
            try:
                surface = sdlttf.TTF_RenderUTF8_Blended(font.font, text.encode(), s.SDL_Color(*color, 255))
                if not surface:
                    raise RuntimeError(s.SDL_GetError())
                try:
                    texture = s.SDL_CreateTextureFromSurface(canvas.renderer, surface)
                    if not texture:
                        raise RuntimeError(s.SDL_GetError())
                    self.labels[key] = p.Image(texture)
                finally:
                    s.SDL_FreeSurface(surface)
            finally:
                sdlttf.TTF_CloseFont(font.font)
        image = self.labels[key]
        image.draw(x + image.w / 2, y)

    def handle(self, event, game):
        if self.wake_start is not None or event.type != s.SDL_KEYDOWN or event.key.repeat:
            return
        key = event.key.keysym.sym
        count = len(SETTINGS) + 1 if self.settings else 3
        if key in (s.SDLK_UP, s.SDLK_DOWN):
            self.selected = (self.selected + (1 if key == s.SDLK_DOWN else -1)) % count
        elif self.settings and self.selected < len(SETTINGS) and key in (s.SDLK_LEFT, s.SDLK_RIGHT, s.SDLK_RETURN):
            game.change_setting(SETTINGS[self.selected][0], -1 if key == s.SDLK_LEFT else 1)
        elif self.settings and key in (s.SDLK_ESCAPE, s.SDLK_RETURN):
            self.settings, self.selected = False, 1
        elif key == s.SDLK_RETURN:
            if self.selected == 0:
                self.wake_start = perf_counter()
            elif self.selected == 1:
                self.settings, self.selected = True, 0
            else:
                game.enter('quit')
        elif key == s.SDLK_ESCAPE:
            game.enter('quit')

    def draw(self, game):
        s.SDL_RenderSetLogicalSize(canvas.renderer, *WINDOW_SIZE)
        canvas.canvas_width, canvas.canvas_height = WINDOW_SIZE
        try:
            self.sleep.draw(960, 540)
            if self.wake_start is not None:
                age = perf_counter() - self.wake_start
                # 눈 주위만 바꾸어 배경과 몸의 위치를 유지한다.
                opacity = min(1.0, max(0.0, (age - .22) / .16))
                s.SDL_SetTextureAlphaMod(self.awake.texture, round(255 * opacity))
                self.awake.draw(860, 476)
                return
            self.label('환경설정' if self.settings else 'GLEAM', 92, 118, 680, (226, 237, 244))
            if self.settings:
                values = {'fullscreen': '전체화면 1920×1080' if game.fullscreen else '창 모드 960×540'}
                values.update({key: f'{value}%' for key, value in game.volumes.items()})
                for i, (key, name) in enumerate(SETTINGS):
                    color = (255, 223, 151) if self.selected == i else (195, 211, 225)
                    y = 551 - i * 59
                    self.label(name, 32, 126, y, color)
                    self.label(values[key], 32, 370, y, color)
                self.label('돌아가기', 32, 126, 551-len(SETTINGS)*59,
                           (255, 223, 151) if self.selected == len(SETTINGS) else (195, 211, 225))
                self.label(game.settings_notice or '↑ ↓ 선택    ← → 변경    Esc 돌아가기',
                           24, 126, 151, (185, 199, 211))
                return
            rows = ('게임 시작', '환경설정', '종료')
            for i, row in enumerate(rows):
                active = self.selected == i
                self.label(('›   ' if active else '     ') + row, 34, 120, 532-i*70,
                           (255, 223, 151) if active else (195, 211, 225))
        finally:
            s.SDL_RenderSetLogicalSize(canvas.renderer, *LOGICAL_SIZE)
            canvas.canvas_width, canvas.canvas_height = LOGICAL_SIZE

    def finished(self):
        return self.wake_start is not None and perf_counter() - self.wake_start >= 1.05
