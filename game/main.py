"""Gleam entry point: python game/main.py or python -m game.main."""
import argparse
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


TARGET_FPS = 144


def wait_for_frame(deadline):
    remaining_ms = int((deadline - perf_counter()) * 1000) - 1
    if remaining_ms > 0:
        s.SDL_Delay(remaining_ms)
    # SDL_Delay의 오차를 피해 마지막 구간은 고해상도 시계로 맞춘다.
    while perf_counter() < deadline:
        pass


def main(*, vsync=False, profile=False):
    s.SDL_SetHint(s.SDL_HINT_RENDER_SCALE_QUALITY, b'0')
    s.SDL_SetHintWithPriority(s.SDL_HINT_RENDER_VSYNC, b'1' if vsync else b'0', s.SDL_HINT_OVERRIDE)
    p.open_canvas(*WINDOW_SIZE, sync=vsync)
    scene = None
    try:
        renderer_info = s.SDL_RendererInfo()
        s.SDL_GetRendererInfo(canvas.renderer, ctypes.byref(renderer_info))
        vsync_active = vsync and bool(renderer_info.flags & s.SDL_RENDERER_PRESENTVSYNC)
        s.SDL_RenderSetLogicalSize(canvas.renderer, *LOGICAL_SIZE)
        canvas.canvas_width, canvas.canvas_height = LOGICAL_SIZE
        s.SDL_SetWindowTitle(canvas.window, b'GLEAM')
        if profile:
            display = s.SDL_DisplayMode()
            index = s.SDL_GetWindowDisplayIndex(canvas.window)
            s.SDL_GetCurrentDisplayMode(index, ctypes.byref(display))
            backend = renderer_info.name.decode('utf-8') if renderer_info.name else 'unknown'
            acceleration = 'GPU' if renderer_info.flags & s.SDL_RENDERER_ACCELERATED else 'software'
            pacing = 'VSync' if vsync_active else f'{TARGET_FPS} FPS cap'
            refresh = f'{display.refresh_rate} Hz' if display.refresh_rate else 'unknown refresh rate'
            print(f'GLEAM | {backend} ({acceleration}) | {refresh} | {pacing}', flush=True)
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
        frame_dt = 1 / TARGET_FPS
        frame_deadline = sample_start = previous
        frames = draw_total = present_total = 0
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
            draw_start = perf_counter()
            scene.draw()
            present_start = perf_counter()
            p.update_canvas()
            presented = perf_counter()
            if profile:
                frames += 1
                draw_total += present_start - draw_start
                present_total += presented - present_start
                sample_time = presented - sample_start
                if sample_time >= 1:
                    print(f'{frames / sample_time:6.1f} FPS | '
                          f'draw {draw_total * 1000 / frames:.2f} ms | '
                          f'present {present_total * 1000 / frames:.2f} ms', flush=True)
                    sample_start = presented
                    frames = draw_total = present_total = 0
            if not vsync_active:
                frame_deadline += frame_dt
                if frame_deadline <= now:
                    frame_deadline = now + frame_dt
                wait_for_frame(frame_deadline)
    finally:
        if scene is not None:
            scene.close()
        p.close_canvas()


def run():
    parser = argparse.ArgumentParser(description='Run GLEAM.')
    parser.add_argument('--vsync', action='store_true', help='Sync presentation to the display.')
    parser.add_argument('--perf', action='store_true', help='Print renderer and frame timings.')
    args = parser.parse_args()
    main(vsync=args.vsync, profile=args.perf)


if __name__ == '__main__':
    run()
