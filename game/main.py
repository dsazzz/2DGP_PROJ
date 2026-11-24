"""Gleam entry point: python game/main.py or python -m game.main."""
import argparse
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pico2d as p
import sdl2 as s

from game.modes import GameModes
from game.core.display import LOGICAL_SIZE, configure_display
from game.core.framework import GameFramework


def main(*, vsync=False, profile=False):
    s.SDL_SetHint(s.SDL_HINT_RENDER_SCALE_QUALITY, b'0')
    s.SDL_SetHintWithPriority(s.SDL_HINT_RENDER_VSYNC, b'1' if vsync else b'0', s.SDL_HINT_OVERRIDE)
    p.open_canvas(*LOGICAL_SIZE, sync=vsync)
    game = None
    try:
        game = GameModes()
        game.apply_settings()
        vsync_active, display_refresh = configure_display(vsync, profile, game.fps)
        GameFramework(game, vsync_active=vsync_active, display_refresh=display_refresh, profile=profile).run()
    finally:
        if game is not None:
            game.close()
        p.close_canvas()


def run():
    parser = argparse.ArgumentParser(description='Run GLEAM.')
    parser.add_argument('--vsync', action='store_true', help='Sync presentation to the display.')
    parser.add_argument('--perf', action='store_true', help='Print renderer and frame timings.')
    args = parser.parse_args()
    main(vsync=args.vsync, profile=args.perf)


if __name__ == '__main__':
    run()
