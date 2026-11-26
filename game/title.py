"""타이틀 화면과 게임 시작 연출."""
from time import perf_counter

import pico2d as p
from pico2d import pico2d as canvas
import sdl2 as s

from game.core.display import LOGICAL_SIZE, WINDOW_SIZE
from game.core.paths import ART_ROOT


ITEMS = ('게임 시작', '환경 설정', '게임 종료')


class Title:
    def __init__(self):
        folder = ART_ROOT / 'environment/backgrounds'
        self.sleep = p.load_image(str(folder / 'title-sleep.png'))
        self.awake = p.load_image(str(folder / 'title-awake.png'))
        self.wake_start = None

    def draw_items(self, menu):
        for row, item in enumerate(ITEMS):
            active = row == menu.selected
            color = (255, 225, 132) if active else (246, 246, 246)
            y = 440 - row * 55
            menu.label(item, 40, 172, y, color, glow=active)
            if active:
                menu.draw_cursor(136, y)

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
            game.menu.label('GLEAM', 178, 145, 824, (248, 248, 246), font_name='georgia.ttf')
            if game.menu.settings:
                game.menu.draw_settings(game)
            else:
                self.draw_items(game.menu)
        finally:
            s.SDL_RenderSetLogicalSize(canvas.renderer, *LOGICAL_SIZE)
            canvas.canvas_width, canvas.canvas_height = LOGICAL_SIZE

    def finished(self):
        return self.wake_start is not None and perf_counter() - self.wake_start >= 1.05
