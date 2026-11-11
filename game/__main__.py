"""M1 step 1: open and close the 640x360 game canvas. Run: python -m game."""
import argparse


LOGICAL_SIZE = (640, 360)


def main():
    parser = argparse.ArgumentParser(description='Gleam')
    parser.add_argument('--scale', type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()

    import pico2d as p
    from pico2d import pico2d as canvas
    import sdl2 as s

    width, height = LOGICAL_SIZE
    s.SDL_SetHint(s.SDL_HINT_RENDER_SCALE_QUALITY, b'0')
    p.open_canvas(width * args.scale, height * args.scale, sync=True)
    try:
        if s.SDL_RenderSetLogicalSize(canvas.renderer, width, height) < 0:
            raise RuntimeError('Cannot configure the 640x360 logical canvas')
        # pico2d's bottom-left drawing conversion must use logical dimensions too.
        canvas.canvas_width, canvas.canvas_height = width, height
        title = ('Gleam | 640x360 (%dx)' % args.scale).encode('utf-8')
        running = True
        while running:
            for event in p.get_events():
                if event.type == p.SDL_QUIT or (event.type == p.SDL_KEYDOWN and event.key == p.SDLK_ESCAPE):
                    running = False
            if not running:
                break
            s.SDL_SetWindowTitle(canvas.window, title)
            s.SDL_SetRenderDrawColor(canvas.renderer, 19, 16, 30, 255)
            s.SDL_RenderClear(canvas.renderer)
            p.update_canvas()
    finally:
        p.close_canvas()


if __name__ == '__main__':
    main()
