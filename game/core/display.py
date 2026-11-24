"""Display contract. LDtk pixels and physics remain world units at every viewport."""
import ctypes

from pico2d import pico2d as canvas
import sdl2 as s


LOGICAL_SIZE = (960, 540)
WINDOW_SIZE = (1920, 1080)
DEFAULT_VIEW_MODE = 'logical_960'
VIEW_SIZES = {'normal': (640, 360), 'zoom_half': (1280, 720),
              'logical_960': LOGICAL_SIZE, 'logical_1280': (1280, 720),
              'logical_1920': WINDOW_SIZE}


def set_fullscreen(enabled):
    window = canvas.window
    if enabled:
        display = s.SDL_GetWindowDisplayIndex(window)
        desired, closest = s.SDL_DisplayMode(), s.SDL_DisplayMode()
        desired.w, desired.h = WINDOW_SIZE
        current = s.SDL_DisplayMode()
        if s.SDL_GetCurrentDisplayMode(display, ctypes.byref(current)) == 0:
            desired.refresh_rate = current.refresh_rate
        if not s.SDL_GetClosestDisplayMode(display, ctypes.byref(desired), ctypes.byref(closest)):
            return False
        if (closest.w, closest.h) != WINDOW_SIZE:
            return False
        if s.SDL_SetWindowDisplayMode(window, ctypes.byref(closest)) < 0:
            return False
        return s.SDL_SetWindowFullscreen(window, s.SDL_WINDOW_FULLSCREEN) == 0
    if s.SDL_SetWindowFullscreen(window, 0) < 0:
        return False
    s.SDL_SetWindowSize(window, *LOGICAL_SIZE)
    return True


def configure_display(profile):
    s.SDL_RenderSetLogicalSize(canvas.renderer, *LOGICAL_SIZE)
    canvas.canvas_width, canvas.canvas_height = LOGICAL_SIZE
    s.SDL_SetWindowTitle(canvas.window, b'GLEAM')
    if profile:
        renderer_info = s.SDL_RendererInfo()
        s.SDL_GetRendererInfo(canvas.renderer, ctypes.byref(renderer_info))
        display = s.SDL_DisplayMode()
        index = s.SDL_GetWindowDisplayIndex(canvas.window)
        s.SDL_GetCurrentDisplayMode(index, ctypes.byref(display))
        backend = renderer_info.name.decode('utf-8') if renderer_info.name else 'unknown'
        acceleration = 'GPU' if renderer_info.flags & s.SDL_RENDERER_ACCELERATED else 'software'
        pacing = 'VSync' if renderer_info.flags & s.SDL_RENDERER_PRESENTVSYNC else 'uncapped'
        refresh = f'{display.refresh_rate} Hz' if display.refresh_rate else 'unknown refresh rate'
        print(f'GLEAM | {backend} ({acceleration}) | {refresh} | {pacing}', flush=True)
