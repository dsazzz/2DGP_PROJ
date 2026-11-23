"""SDL 입력, 고정 물리 시간과 화면 제출을 관리한다."""
import ctypes
from time import perf_counter

import pico2d as p
import sdl2 as s

from game.core.loop import FIXED_DT, FixedStep


def wait_for_frame(deadline):
    remaining_ms = int((deadline - perf_counter()) * 1000) - 1
    if remaining_ms > 0:
        s.SDL_Delay(remaining_ms)
    # SDL_Delay의 오차를 피해 마지막 구간은 고해상도 시계로 맞춘다.
    while perf_counter() < deadline:
        pass


def poll_events():
    events = []
    event = s.SDL_Event()
    while s.SDL_PollEvent(ctypes.byref(event)):
        events.append(event)
        event = s.SDL_Event()
    return events


class GameFramework:
    def __init__(self, game, *, vsync_active=False, display_refresh=0, profile=False):
        self.game = game
        self.vsync_active = vsync_active
        self.display_refresh = display_refresh
        self.profile = profile

    def run(self):
        game = self.game
        stepper = FixedStep(clock=perf_counter)
        mode = game.mode
        frame_deadline = sample_start = perf_counter()
        frames = update_steps = 0
        update_total = draw_total = present_total = 0.0
        while game.running:
            game.handle_events(poll_events())
            if not game.running:
                break
            now = perf_counter()
            if game.mode != mode:
                stepper.reset(now)
            mode = game.mode
            steps = stepper.pump(now) if game.updating else 0
            if self.profile:
                update_start = perf_counter()
            executed = 0
            for _ in range(steps):
                game.update(FIXED_DT)
                executed += 1
                if not game.updating:
                    break
            draw_start = perf_counter()
            if self.profile and steps:
                update_steps += executed
                update_total += draw_start - update_start
            game.draw(stepper.alpha)
            present_start = perf_counter()
            p.update_canvas()
            presented = perf_counter()
            if self.profile:
                frames += 1
                draw_total += present_start - draw_start
                present_total += presented - present_start
                sample_time = presented - sample_start
                if sample_time >= 1:
                    update_ms = update_total * 1000 / update_steps if update_steps else 0.0
                    print(f'{frames / sample_time:6.1f} FPS | '
                          f'update {update_ms:.2f} ms/step | '
                          f'draw {draw_total * 1000 / frames:.2f} ms | '
                          f'present {present_total * 1000 / frames:.2f} ms', flush=True)
                    sample_start = presented
                    frames = update_steps = 0
                    update_total = draw_total = present_total = 0.0
            if game.after_present():
                frame_deadline = perf_counter()
                stepper.reset(frame_deadline)
            frame_dt = 1 / game.fps
            if not self.vsync_active or game.fps < self.display_refresh:
                frame_deadline += frame_dt
                if frame_deadline <= now:
                    frame_deadline = now + frame_dt
                wait_for_frame(frame_deadline)
