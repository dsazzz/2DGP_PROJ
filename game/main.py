"""발표용 데모 진입점: python game/main.py 또는 python -m game.main."""
import ctypes
from pathlib import Path
import sys
from time import perf_counter

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pico2d as p
from pico2d import pico2d as canvas
import sdl2 as s

from game.demo import DemoScene


def main():
    s.SDL_SetHint(s.SDL_HINT_RENDER_SCALE_QUALITY, b'0')
    p.open_canvas(1920, 1080, sync=True)
    scene = None
    try:
        s.SDL_RenderSetLogicalSize(canvas.renderer, 640, 360)
        canvas.canvas_width, canvas.canvas_height = 640, 360
        s.SDL_SetWindowTitle(canvas.window, b'GLEAM')
        scene = DemoScene()
        scene.open()
        accumulator, previous, running = 0.0, perf_counter(), True
        fixed_dt = 1 / 144
        while running:
            now = perf_counter()
            accumulator += min(max(now - previous, 0.0), .1)
            previous = now
            events, event = [], s.SDL_Event()
            while s.SDL_PollEvent(ctypes.byref(event)):
                if event.type == s.SDL_QUIT or (
                        event.type == s.SDL_KEYDOWN and event.key.keysym.sym == s.SDLK_ESCAPE):
                    running = False
                events.append(event)
                event = s.SDL_Event()
            if not running:
                break
            if any(event.type == s.SDL_KEYDOWN and event.key.keysym.sym == s.SDLK_F5
                   and not event.key.repeat for event in events):
                replacement = DemoScene()
                replacement.open()
                scene.close()
                scene = replacement
                accumulator = 0.0
                events.clear()
            scene.handle_events(events)
            while accumulator + 1e-9 >= fixed_dt:
                scene.update(fixed_dt)
                accumulator = max(0.0, accumulator - fixed_dt)
            scene.draw()
            p.update_canvas()
            s.SDL_Delay(1)
    finally:
        if scene is not None:
            scene.close()
        p.close_canvas()


if __name__ == '__main__':
    main()
