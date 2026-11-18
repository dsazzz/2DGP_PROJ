"""데모의 월드 표시와 HUD. 오브젝트 동작과 플레이어 상태는 수정하지 않는다."""
import ctypes
import json
import os
from pathlib import Path

import pico2d as p
from pico2d import pico2d as canvas
import sdl2 as s
from sdl2 import sdlttf

from game.collision import AABB
from game.objects_view import (
    AbsorbSourceView, DisappearingPlatformView, JumpPlatformView,
    MovingPlatformView, PlatformView, SpikesView,
)
from game.paths import ART_ROOT
from game.player_view import PlayerView
from game.rendering import draw_clip
from game.vfx.pico import PicoEffect


class DemoView:
    def __init__(self, scene):
        self.scene = scene
        self.player = PlayerView(scene.player)
        self.player.preload()
        for stage in (2, 3):
            effect = PicoEffect('absorbBoost', stage=stage)
            effect.prerender()
        self.object_views = tuple(
            view(obj) for objects, view in (
                (scene.sources, AbsorbSourceView), (scene.spikes, SpikesView),
                (scene.moving, MovingPlatformView), (scene.disappearing, DisappearingPlatformView),
                (scene.jump_platforms, JumpPlatformView),
            ) for obj in objects
        )
        self.platform_views = tuple(PlatformView(area) for area in scene.platforms)
        self.platform_views += tuple(PlatformView(area, one_way=True) for area in scene.one_way)
        self.environment = json.loads((ART_ROOT / 'environment' / 'environment.json').read_text(encoding='utf-8'))
        self.frames = {frame['id']: frame for frame in self.environment['assets']}
        self.images = {}
        self.fonts = {}
        self.text_images = {}
        self.tile_layers = []
        for layer in scene.data.get('tile_layers', ()):
            size = layer['size']
            ox, oy = layer['offset']
            # LDtk에서 16px로 편집한 지형은 원본 64px 타일을 같은 월드 크기로 그린다.
            is_terrain = (size == 16 and Path(layer['image']).resolve()
                          == (ART_ROOT / 'levels' / 'editor' / 'terrain.png').resolve())
            image_path = str((ART_ROOT / 'environment' / 'terrain.png').resolve()) if is_terrain else layer['image']
            source_size = size * 4 if is_terrain else size
            tiles = []
            for tile in layer['tiles']:
                x, y = tile['px'][0] + ox, scene.bounds.height - tile['px'][1] - oy - size
                flip = ('h' if tile['f'] & 1 else '') + ('v' if tile['f'] & 2 else '')
                source = tuple(value * 4 for value in tile['src']) if is_terrain else tile['src']
                tiles.append((x, y, source, flip, layer['opacity'] * tile.get('a', 1)))
            self.tile_layers.append((image_path, size, source_size, is_terrain, tiles))

    def reset(self):
        self.player.reset()
        for view in self.object_views:
            if isinstance(view, AbsorbSourceView):
                view.reset()

    def update(self, dt):
        scene = self.scene
        for view in self.object_views:
            if isinstance(view, AbsorbSourceView):
                view.update(dt)
        self.player.update(dt, scene.solids,
                           one_way=scene.active_one_way + tuple(obj.area for obj in scene.moving))

    def image(self, name):
        if name not in self.images:
            self.images[name] = p.load_image(str(ART_ROOT / 'environment' / name))
        return self.images[name]

    @staticmethod
    def rect(x, y, width, height, color):
        s.SDL_SetRenderDrawColor(canvas.renderer, *color)
        area = s.SDL_FRect(x, 360 - y - height, width, height)
        s.SDL_RenderFillRectF(canvas.renderer, ctypes.byref(area))

    def text(self, x, y, message, *, size=11, color=(218, 215, 233), center=False):
        if size not in self.fonts:
            path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'malgun.ttf'
            self.fonts[size] = p.load_font(str(path), size)
        key = message, size, color
        if key not in self.text_images:
            if len(self.text_images) >= 96:
                self.text_images.clear()
            surface = sdlttf.TTF_RenderUTF8_Blended(
                self.fonts[size].font, message.encode('utf-8'), s.SDL_Color(*color, 255))
            if not surface:
                raise RuntimeError(s.SDL_GetError().decode('utf-8'))
            texture = s.SDL_CreateTextureFromSurface(canvas.renderer, surface)
            s.SDL_FreeSurface(surface)
            self.text_images[key] = p.Image(texture)
        image = self.text_images[key]
        draw_clip(image, 0, 0, image.w, image.h, 0, '', x if center else x + image.w / 2, y)

    def asset(self, identifier, x, y, scale=.5, opacity=1):
        frame = self.frames[identifier]
        atlas = self.environment['atlases'][frame['atlas']]
        image = self.image(atlas['image'])
        left, top, width, height = frame['rect']
        anchor_x, anchor_y = frame.get('anchor_px', (width / 2, height))
        image.opacify(opacity)
        try:
            draw_clip(image, left, image.h - top - height, width, height, 0, '',
                      x + (width / 2 - anchor_x) * scale,
                      y + (anchor_y - height / 2) * scale, width * scale, height * scale)
        finally:
            image.opacify(1)

    def background(self):
        scene = self.scene
        offset_x, offset_y = scene.camera.offset
        image = self.image('backgrounds/lab-wall.png')
        x0 = -(offset_x * .2 % 384)
        y0 = -(offset_y * .1 % 256)
        for x in (x0, x0 + 384, x0 + 768):
            for y in (y0, y0 + 256):
                draw_clip(image, 0, 0, image.w, image.h, 0, '', x + 192, y + 128, 384, 256)
        # 고정 배경 판은 플레이 영역보다 뒤에 두어 기믹과 혼동하지 않는다.
        for world_x, name in ((1152, 'containment'), (2592, 'resonance')):
            x = world_x - offset_x * .85
            if -640 < x < 640:
                image = self.image('backgrounds/' + name + '.png')
                draw_clip(image, 0, 0, image.w, image.h, 0, '', x + 320, 180, 640, 360)
        self.rect(0, 0, 640, 360, (8, 6, 18, 48))

    def terrain(self):
        scene = self.scene
        if 'tile_layers' in scene.data:
            view = scene.camera.view
            cx, cy = scene.camera.offset
            for path, size, source_size, is_terrain, tiles in self.tile_layers:
                if path not in self.images:
                    self.images[path] = p.load_image(path)
                image = self.images[path]
                for x, y, source, flip, opacity in tiles:
                    if x >= view.right or x + size <= view.left or y >= view.top or y + size <= view.bottom:
                        continue
                    left, top = source
                    sx, sy = x + size / 2 - cx, y + size / 2 - cy
                    image.opacify(opacity)
                    draw_clip(image, left, image.h - top - source_size, source_size, source_size,
                              0, flip, sx, sy, size, size)
                    if is_terrain and (left, top) == (64, 0):
                        # 원본 윗부분의 투명 5px를 접촉면 색으로 채워 오브젝트가 떠 보이지 않게 한다.
                        cap_height = size * 5 / source_size
                        cap_y = y + cap_height / 2 if 'v' in flip else y + size - cap_height / 2
                        draw_clip(image, left, image.h - 6, source_size, 1, 0, flip,
                                  sx, cap_y - cy, size, cap_height)
                image.opacify(1)
            return
        image = self.image('terrain.png')
        for area in scene.floors:
            if not scene.camera.visible(area):
                continue
            for x in range(int(area.left), int(area.right), 32):
                for y in range(int(area.bottom), int(area.top), 32):
                    identifier = 'floor_top' if y + 32 == area.top else 'fill_base'
                    left, top, width, height = self.frames[identifier]['rect']
                    screen_x, screen_y = scene.camera.to_screen(x + 16, y + 16)
                    if -32 < screen_x < 672:
                        draw_clip(image, left, image.h - top - height, width, height,
                                  0, '', screen_x, screen_y, 32, 32)

    def world(self):
        scene = self.scene
        offset = scene.camera.offset
        s.SDL_SetRenderDrawBlendMode(canvas.renderer, s.SDL_BLENDMODE_BLEND)
        s.SDL_SetRenderDrawColor(canvas.renderer, 18, 15, 29, 255)
        s.SDL_RenderClear(canvas.renderer)
        self.background()
        self.terrain()
        for view in self.platform_views:
            if scene.camera.visible(view.area):
                view.draw(offset)
        for index, checkpoint in enumerate(scene.data['checkpoints']):
            if checkpoint['terminal'] is None:
                continue
            x, y = scene.camera.to_screen(*checkpoint['terminal'])
            if -64 < x < 704:
                self.asset('terminal', x, y)
                color = (111, 239, 188, 255) if index <= scene.checkpoint else (128, 119, 157, 160)
                self.rect(x - 5, y + 29, 10, 3, color)
                if index == scene.checkpoint:
                    self.text(x, y + 56, 'SAVED', size=8, color=(122, 216, 181), center=True)
        x, y = scene.camera.to_screen(scene.exit.left + scene.exit.width / 2, scene.exit.bottom)
        if -100 < x < 740:
            self.asset('exit_open', x, y)
            self.text(x, y + 120, 'EXIT', size=12, color=(148, 255, 210), center=True)
        for view in self.object_views:
            obj = getattr(view, 'source', getattr(view, 'spikes', getattr(view, 'platform', None)))
            if obj is not None and scene.camera.visible(obj.area):
                view.draw(offset)
        self.player.draw(offset)

    def draw(self):
        scene = self.scene
        self.world()
        self.rect(12, 318, 616, 32, (14, 11, 25, 230))
        self.rect(12, 318, 3, 32, (225, 184, 104, 255))
        self.text(24, 335, 'GLEAM', size=16, color=(248, 216, 152))
        minutes, seconds = divmod(int(scene.elapsed), 60)
        self.text(381, 335, '%02d:%02d   사망 %d   흡수 %d/%d' % (
            minutes, seconds, scene.deaths, scene.absorbed, len(scene.sources)), size=10)
        self.rect(12, 10, 616, 40, (14, 11, 25, 230))
        self.text(24, 36, scene.section['hint'], size=10)
        self.text(24, 20, 'R 재시작    Shift+R 처음부터    F5 맵 다시 읽기    P 일시정지    Esc 종료',
                  size=9, color=(140, 131, 164))
        if scene.checkpoint_flash:
            self.text(320, 294, 'CHECKPOINT SAVED', size=12, color=(135, 247, 199), center=True)
        if scene.paused or scene.complete:
            self.rect(0, 0, 640, 360, (8, 6, 16, 205))
            self.rect(124, 110, 392, 140, (23, 19, 37, 255))
            self.rect(124, 246, 392, 2, (231, 193, 119, 255))
            if scene.complete:
                self.text(320, 174, '%02d:%02d  /  사망 %d  /  흡수 %d/%d' % (
                    minutes, seconds, scene.deaths, scene.absorbed, len(scene.sources)), center=True)
                self.text(320, 139, 'Enter 또는 R  다시 플레이', center=True)
            else:
                self.text(320, 214, 'PAUSED', size=24, color=(247, 219, 161), center=True)
                self.text(320, 165, 'Enter / P  계속하기', center=True)
                self.text(320, 137, 'R  체크포인트 재시작', size=10, center=True)

    def close(self):
        self.player.close()
        for view in self.object_views + self.platform_views:
            view.close()
        self.text_images.clear()
        self.images.clear()
        for font in self.fonts.values():
            sdlttf.TTF_CloseFont(font.font)
        self.fonts.clear()
