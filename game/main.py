"""Gleam entry point: python game/main.py or python -m game.main."""
import ctypes
from pathlib import Path
import sys
from time import perf_counter

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pico2d as p
from pico2d import pico2d as canvas
import sdl2 as s

from game.world.scene import PlayScene
from game.world.level import load_ldtk
from game.core.paths import ART_ROOT
from game.core.camera import Camera
from game.core.display import LOGICAL_SIZE, WINDOW_SIZE, DEFAULT_VIEW_MODE, VIEW_SIZES


def main():
    s.SDL_SetHint(s.SDL_HINT_RENDER_SCALE_QUALITY, b'0')
    p.open_canvas(*WINDOW_SIZE, sync=True)
    scene = None
    try:
        s.SDL_RenderSetLogicalSize(canvas.renderer, *LOGICAL_SIZE)
        canvas.canvas_width, canvas.canvas_height = LOGICAL_SIZE
        s.SDL_SetWindowTitle(canvas.window, b'GLEAM')
        scene = PlayScene(load_ldtk(ART_ROOT / 'levels/gleam.ldtk'))
        scene.open()
        view_mode = DEFAULT_VIEW_MODE

        def set_view_mode(mode):
            nonlocal view_mode
            view_mode = mode
            size = VIEW_SIZES[mode]
            direction = scene.camera.direction
            scene.camera = Camera(scene.bounds, size=size)
            scene.camera.snap(scene.player.x, scene.player.y + scene.player.body_height / 2, direction)
            scene.view.view_mode = mode
            scene.view.player.zoom = 1.0 if mode == 'logical_1920' else 0.5

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
                replacement = None
                try:
                    replacement = PlayScene(load_ldtk(ART_ROOT / 'levels/gleam.ldtk'))
                    replacement.open()
                except (OSError, ValueError, RuntimeError) as exc:
                    if replacement is not None:
                        replacement.close()
                    print(f'LDtk reload failed: {exc}', flush=True)
                    accumulator = 0.0
                    continue
                scene.close()
                scene = replacement
                set_view_mode(view_mode)
                accumulator = 0.0
                events.clear()
            for item in events:
                if item.type == s.SDL_KEYDOWN and not item.key.repeat:
                    mode = {s.SDLK_F6: 'normal', s.SDLK_F7: 'zoom_half',
                            s.SDLK_F8: 'logical_960', s.SDLK_F9: 'logical_1280',
                            s.SDLK_F10: 'logical_1920'}.get(item.key.keysym.sym)
                    if mode:
                        set_view_mode(mode)
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
