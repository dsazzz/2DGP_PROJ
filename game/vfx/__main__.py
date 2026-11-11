"""Standalone effect preview: python -m game.vfx (not the M1 game loop)."""
import argparse
import json
import math
from pathlib import Path
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description='Gleam Python VFX preview')
    parser.add_argument('--scale', type=int, choices=(1, 2, 3), default=2)
    parser.add_argument('--frames', type=int, default=0, help='Exit after N frames (smoke check)')
    parser.add_argument('--hidden', action='store_true', help='Hide the preview window for smoke checks')
    args = parser.parse_args()
    import pico2d as p
    from pico2d import pico2d as canvas
    import sdl2 as s

    from . import Cues, EFFECTS, MotionEchoes, PicoEffect, ScreenLight
    from .pico import load_rgba

    root = Path(__file__).resolve().parents[2]
    data = json.loads((root / 'art/player/player.json').read_text(encoding='utf-8-sig'))
    sample_rect = data['frames'][data['clips']['run']['frames'][0]]['rect_top_left']
    names = [name for name in EFFECTS if name != 'shatter'] + [
        'globalSignal', 'ambientLight', 'absorbFailure', 'doorFlash', 'dashOrbs', 'motionEchoes']
    s.SDL_SetHint(s.SDL_HINT_RENDER_SCALE_QUALITY, b'0')
    p.open_canvas(640 * args.scale, 360 * args.scale, sync=True)
    p.lattice_on = False
    canvas.lattice_on = False
    if args.hidden:
        s.SDL_HideWindow(canvas.window)
    if s.SDL_RenderSetLogicalSize(canvas.renderer, 640, 360) < 0:
        p.close_canvas()
        raise RuntimeError('Cannot set a 640x360 logical canvas')
    canvas.canvas_width, canvas.canvas_height = 640, 360
    actor = terrain = orb = font = None
    fx = None
    echoes = None
    cues, screen = Cues(), ScreenLight()
    try:
        actor = p.load_image(str(root / 'art/player/player-atlas.png'))
        terrain = p.load_image(str(root / 'art/environment/terrain.png'))
        orb = p.load_image(str(root / 'art/player/dash-orb.png'))
        font_path = Path(p.__file__).resolve().parent / 'data/NanumBarunGothic.ttf'
        if not font_path.exists():
            fonts = list(font_path.parent.glob('*.ttf'))
            if not fonts:
                raise FileNotFoundError('pico2d preview font is missing')
            font_path = fonts[0]
        font = p.load_font(str(font_path), 14)
        echoes = MotionEchoes(load_rgba(root / 'art/player/player-atlas.png'))
        index, stage, grounded, flip, paused = 0, 2, True, False, False
        elapsed, previous, count, running = 0.0, perf_counter(), 0, True
        samples = []
        while running:
            start = perf_counter()
            dt, previous = min(start - previous, .1), start
            reset = False
            for event in p.get_events():
                if event.type == p.SDL_QUIT:
                    running = False
                elif event.type == p.SDL_KEYDOWN:
                    if event.key == p.SDLK_ESCAPE:
                        running = False
                    elif event.key in (p.SDLK_RIGHT, p.SDLK_TAB, p.SDLK_LEFT):
                        index = (index + (-1 if event.key == p.SDLK_LEFT else 1)) % len(names)
                        reset = True
                    elif event.key in (p.SDLK_1, p.SDLK_2, p.SDLK_3):
                        stage = event.key - p.SDLK_1 + 1
                    elif event.key == p.SDLK_g:
                        grounded = not grounded
                    elif event.key == p.SDLK_f:
                        flip = not flip
                    elif event.key == p.SDLK_SPACE:
                        paused = not paused
                    elif event.key == p.SDLK_r:
                        reset = True
            name = names[index]
            if reset:
                if fx:
                    fx.close()
                fx, elapsed, samples = None, 0.0, []
            if name in EFFECTS and fx is None:
                fx = PicoEffect(name, stage=stage, grounded=grounded)
            if not paused:
                elapsed += dt
                if fx:
                    if not fx.effect.spec.loop and elapsed > fx.effect.spec.duration + .45:
                        fx.effect.time, fx.effect._stop_at, elapsed = 0, float('inf'), 0.0
                    fx.update(dt)
            if fx:
                fx.options.update(stage=stage, grounded=grounded)
            s.SDL_SetRenderDrawColor(canvas.renderer, 19, 16, 30, 255)
            s.SDL_RenderClear(canvas.renderer)
            for column in range(20):
                terrain.clip_draw(64, terrain.h - 64, 64, 64, column * 32 + 16, 112, 32, 32)
            foot_x, foot_y = 320, 128 if grounded else 180
            if name in ('speedTrail', 'dashTrail', 'motionEchoes'):
                foot_x += math.sin(elapsed * 2) * 70
                clip = data['clips']['run']
                remaining = elapsed * 1000 % sum(clip['duration_ms'])
                for frame_id, duration in zip(clip['frames'], clip['duration_ms']):
                    sample_rect = data['frames'][frame_id]['rect_top_left']
                    if remaining < duration:
                        break
                    remaining -= duration
                if not paused:
                    samples.append({'x':foot_x, 'y':foot_y, 'time':elapsed, 'rect':sample_rect,
                                    'size':64, 'facing':-1 if flip else 1})
                    samples[:] = [sample for sample in samples if elapsed - sample['time'] < .2]
                echoes.draw(samples, elapsed, stage=stage)
            if fx:
                fx.draw(foot_x, foot_y, flip=flip, layer='back')
            x, y, w, h = sample_rect
            actor.clip_composite_draw(x, actor.h - y - h, w, h, 0, 'h' if flip else '',
                                      foot_x + (1 if flip else -1), foot_y + 12.5, 64, 64)
            if fx:
                fx.draw(foot_x, foot_y, flip=flip, layer='front')
            cycle = elapsed % 2.0
            if name == 'globalSignal':
                screen.draw_signal(cycle)
            elif name == 'ambientLight':
                screen.draw_ambient(elapsed)
            elif name == 'absorbFailure':
                cues.draw_absorb_failure(640, 360, cycle)
            elif name == 'doorFlash':
                cues.draw_door_flash(290, 128, 60, 90, cycle)
            elif name == 'dashOrbs':
                cues.draw_dash_orbs(orb, foot_x, foot_y, cycle)
            font.draw(14, 336, name + ('  [PAUSED]' if paused else ''), (240, 231, 216))
            font.draw(14, 314, 'Left/Right: effect  1/2/3: stage  G: ground  F: flip', (177, 165, 192))
            font.draw(14, 292, 'Space: pause  R: restart  Esc: close', (177, 165, 192))
            font.draw(14, 24, 'Stage %d   %s   640x360 / %dx' % (stage, 'ground' if grounded else 'air', args.scale),
                      (239, 201, 126))
            p.update_canvas()
            count += 1
            if args.frames and count >= args.frames:
                break
            p.delay(max(0, 1 / 60 - (perf_counter() - start)))
    finally:
        if fx:
            fx.close()
        if echoes:
            echoes.close()
        screen.close()
        cues.close()
        # pico2d objects own native resources: release while the renderer still exists.
        del actor, terrain, orb, font
        p.close_canvas()


if __name__ == '__main__':
    main()
