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


def configure_display(vsync, profile, fps):
    renderer_info = s.SDL_RendererInfo()
    s.SDL_GetRendererInfo(canvas.renderer, ctypes.byref(renderer_info))
    vsync_active = vsync and bool(renderer_info.flags & s.SDL_RENDERER_PRESENTVSYNC)
    s.SDL_RenderSetLogicalSize(canvas.renderer, *LOGICAL_SIZE)
    canvas.canvas_width, canvas.canvas_height = LOGICAL_SIZE
    s.SDL_SetWindowTitle(canvas.window, b'GLEAM')
    display_refresh = 0
    if profile or vsync_active:
        display = s.SDL_DisplayMode()
        index = s.SDL_GetWindowDisplayIndex(canvas.window)
        s.SDL_GetCurrentDisplayMode(index, ctypes.byref(display))
        display_refresh = display.refresh_rate
    if profile:
        backend = renderer_info.name.decode('utf-8') if renderer_info.name else 'unknown'
        acceleration = 'GPU' if renderer_info.flags & s.SDL_RENDERER_ACCELERATED else 'software'
        pacing = 'VSync' if vsync_active else f'{fps} FPS cap'
        refresh = f'{display.refresh_rate} Hz' if display.refresh_rate else 'unknown refresh rate'
        print(f'GLEAM | {backend} ({acceleration}) | {refresh} | {pacing}', flush=True)
    return vsync_active, display_refresh
