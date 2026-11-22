"""Playable world's rendering and HUD; never changes gameplay state."""
import ctypes
import json
import os
from pathlib import Path

import numpy as np
import pico2d as p
from pico2d import pico2d as canvas
import sdl2 as s
from sdl2 import sdlttf

from game.core.camera import Camera
from game.core.collision import AABB
from game.objects.views import (
    AbsorbSourceView, DisappearingPlatformView, JumpPlatformView,
    MovingPlatformView, PlatformView, ElectricView, draw_visual,
)
from game.world.terrain import TerrainView
from game.core.paths import ART_ROOT
from game.objects.player_view import PlayerView
from game.core.rendering import draw_clip
from game.vfx.pico import PicoEffect, load_rgba
from game.core.display import LOGICAL_SIZE, DEFAULT_VIEW_MODE, VIEW_SIZES


class WorldView:
    def __init__(self, scene):
        self.scene = scene
        self.view_mode = DEFAULT_VIEW_MODE
        self._zoom_target = None
        self.images = {}
        self.player = PlayerView(scene.player)
        self.render_camera = Camera(scene.bounds)
        self.remember_positions()
        self.player.preload()
        for stage in (2, 3):
            effect = PicoEffect('absorbBoost', stage=stage)
            effect.prerender()
        self.object_views = tuple(AbsorbSourceView(obj) for obj in scene.sources)
        visuals = scene.data['visuals']
        self.object_views += tuple(
            view(obj, visual=visual, images=self.images)
            for key, objects, view in (
                ('moving', scene.moving, MovingPlatformView),
                ('disappearing', scene.disappearing, DisappearingPlatformView),
                ('jump_platforms', scene.jump_platforms, JumpPlatformView),
            ) for obj, visual in zip(objects, visuals[key])
        )
        self.electric_view = ElectricView(scene.electric)
        self.electric_view.prerender()
        self.platform_views = tuple(PlatformView(area, visual=visual, images=self.images)
                                    for area, visual in zip(scene.platforms, visuals['platforms']))
        self.platform_views += tuple(PlatformView(area, one_way=True, visual=visual, images=self.images)
                                     for area, visual in zip(scene.one_way, visuals['one_way']))
        self.environment = json.loads((ART_ROOT / 'environment' / 'environment.json').read_text(encoding='utf-8'))
        self.frames = {frame['id']: frame for frame in self.environment['assets']}
        self.fonts = {}
        self.text_images = {}
        self.tiles = TerrainView(scene.data['tile_layers'])
        try:
            self._load_backgrounds()
            self.tiles.preload()
        except Exception:
            self.close()
            raise

    def _load_backgrounds(self):
        # 기존 반투명 어두운 색을 배경 픽셀에 미리 적용한다.
        tint = np.array([8, 6, 18], dtype=np.uint16) * 48
        for name in ('lab-wall', 'containment', 'resonance'):
            path = 'backgrounds/' + name + '.png'
            pixels = load_rgba(ART_ROOT / 'environment' / path)
            pixels[..., :3] = (pixels[..., :3].astype(np.uint16) * 207 + tint) // 255
            height, width = pixels.shape[:2]
            surface = s.SDL_CreateRGBSurfaceWithFormatFrom(ctypes.c_void_p(pixels.ctypes.data),
                width, height, 32, width * 4, s.SDL_PIXELFORMAT_RGBA32)
            if not surface:
                raise RuntimeError(s.SDL_GetError().decode('utf-8'))
            try:
                texture = s.SDL_CreateTextureFromSurface(canvas.renderer, surface)
            finally:
                s.SDL_FreeSurface(surface)
            if not texture:
                raise RuntimeError(s.SDL_GetError().decode('utf-8'))
            if (pixels[..., 3] == 255).all():
                s.SDL_SetTextureBlendMode(texture, s.SDL_BLENDMODE_NONE)
            self.images[path] = p.Image(texture)

    def reset(self):
        self.player.reset()
        self.remember_positions()
        for view in self.object_views:
            if isinstance(view, AbsorbSourceView):
                view.reset()
        self.electric_view.reset()

    def remember_positions(self):
        """분할 물리 갱신에 들어가기 전, 한 틱의 시작 위치를 보관한다."""
        scene = self.scene
        self.previous_camera = scene.camera.offset
        self.previous_player = scene.player.x, scene.player.y
        self.previous_platform_x = {obj: obj.area.left for obj in scene.moving}

    def _camera_for_frame(self, alpha):
        model = self.scene.camera
        camera = self.render_camera
        camera.width, camera.height = model.width, model.height
        x = model.x + (self.previous_camera[0] - model.x) * (1 - alpha)
        y = model.y + (self.previous_camera[1] - model.y) * (1 - alpha)
        # 출력 표면의 한 픽셀에 원점을 맞춰 경계 타일도 묶어서 그린다.
        sx, sy = ctypes.c_float(), ctypes.c_float()
        s.SDL_RenderGetScale(canvas.renderer, ctypes.byref(sx), ctypes.byref(sy))
        camera.x = round(x * sx.value) / sx.value
        camera.y = round(y * sy.value) / sy.value
        return camera

    def update(self, dt):
        scene = self.scene
        for view in self.object_views:
            if isinstance(view, AbsorbSourceView):
                view.update(dt)
        self.electric_view.update(dt)
        self.player.update(dt, scene.solids,
                           one_way=scene.active_one_way + tuple(obj.area for obj in scene.moving))

    def image(self, name):
        if name not in self.images:
            self.images[name] = p.load_image(str(ART_ROOT / 'environment' / name))
        return self.images[name]

    @staticmethod
    def rect(x, y, width, height, color):
        s.SDL_SetRenderDrawColor(canvas.renderer, *color)
        area = s.SDL_FRect(x, canvas.get_canvas_height() - y - height, width, height)
        s.SDL_RenderFillRectF(canvas.renderer, ctypes.byref(area))

    def text(self, x, y, message, *, size=11, color=(218, 215, 233), center=False):
        if not message:
            return
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

    def background(self, camera=None):
        camera = camera or self.scene.camera
        offset_x, offset_y = camera.offset
        image = self.image('backgrounds/lab-wall.png')
        x0 = -(offset_x * .2 % 384)
        y0 = -(offset_y * .1 % 256)
        for col in range(int(camera.width // 384) + 2):
            x = x0 + col * 384
            for row in range(int(camera.height // 256) + 2):
                y = y0 + row * 256
                draw_clip(image, 0, 0, image.w, image.h, 0, '', x + 192, y + 128, 384, 256)
        # 고정 배경 판은 플레이 영역보다 뒤에 두어 기믹과 혼동하지 않는다.
        for world_x, name in ((1152, 'containment'), (2592, 'resonance')):
            x = world_x - offset_x * .85
            if -640 < x < camera.width:
                image = self.image('backgrounds/' + name + '.png')
                draw_clip(image, 0, 0, image.w, image.h, 0, '', x + 320, camera.height / 2, 640, 360)

    def terrain(self, camera=None):
        self.tiles.draw(camera or self.scene.camera, self.images)

    def world(self, alpha=1.0):
        scene = self.scene
        camera = self._camera_for_frame(alpha)
        offset = camera.offset
        viewport = camera.view
        s.SDL_SetRenderDrawBlendMode(canvas.renderer, s.SDL_BLENDMODE_BLEND)
        s.SDL_SetRenderDrawColor(canvas.renderer, 16, 13, 26, 255)
        s.SDL_RenderClear(canvas.renderer)
        self.background(camera)
        self.terrain(camera)
        self.electric_view.draw(camera)
        for view in self.platform_views:
            bounds = AABB(*view.visual['rect']) if view.visual else view.area
            if viewport.overlaps(bounds):
                view.draw(offset)
        for index, checkpoint in enumerate(scene.data['checkpoints']):
            if checkpoint['terminal'] is None:
                continue
            x, y = camera.to_screen(*checkpoint['terminal'])
            if -64 < x < camera.width + 64:
                if checkpoint.get('visual'):
                    draw_visual(checkpoint['visual'], self.images, offset)
                else:
                    self.asset('terminal', x, y)
                color = (111, 239, 188, 255) if index <= scene.checkpoint else (128, 119, 157, 160)
                self.rect(x - 5, y + 29, 10, 3, color)
                if index == scene.checkpoint:
                    self.text(x, y + 56, 'SAVED', size=8, color=(122, 216, 181), center=True)
        if scene.exit is not None:
            x, y = camera.to_screen(scene.exit.left + scene.exit.width / 2, scene.exit.bottom)
            if -100 < x < camera.width + 100:
                if scene.data.get('exit_visual'):
                    draw_visual(scene.data['exit_visual'], self.images, offset)
                else:
                    self.asset('exit_open', x, y)
                self.text(x, y + 120, 'EXIT', size=12, color=(148, 255, 210), center=True)
        for view in self.object_views:
            obj = getattr(view, 'source', getattr(view, 'platform', None))
            visual = getattr(view, 'visual', None)
            bounds = AABB(*visual['rect']) if visual else obj.area
            draw_offset = offset
            if isinstance(view, MovingPlatformView):
                shift = (self.previous_platform_x[obj] - obj.area.left) * (1 - alpha)
                draw_offset = offset[0] - shift, offset[1]
                bounds = AABB(bounds.left + shift + (obj.area.left - obj.start_area.left if visual else 0),
                              bounds.bottom, bounds.width, bounds.height)
            elif isinstance(view, AbsorbSourceView):
                bounds = AABB(obj.area.left+obj.area.width/2-96,
                              obj.area.bottom+obj.area.height/2-80, 192, 160)
            if viewport.overlaps(bounds):
                view.draw(draw_offset)
        dx = (self.previous_player[0] - scene.player.x) * (1 - alpha)
        dy = (self.previous_player[1] - scene.player.y) * (1 - alpha)
        self.player.draw(offset, motion_offset=(dx, dy))

    def draw(self, alpha=1.0):
        scene = self.scene
        if self.view_mode == 'zoom_half':
            if self._zoom_target is None:
                self._zoom_target = s.SDL_CreateTexture(canvas.renderer, s.SDL_PIXELFORMAT_RGBA8888,
                                                        s.SDL_TEXTUREACCESS_TARGET, 640, 360)
                if not self._zoom_target:
                    raise RuntimeError('Could not create zoom comparison target')
            if s.SDL_SetRenderTarget(canvas.renderer, self._zoom_target) < 0:
                raise RuntimeError('Could not set zoom comparison target')
            s.SDL_RenderSetLogicalSize(canvas.renderer, 640, 360)
            s.SDL_RenderSetScale(canvas.renderer, .5, .5)
            canvas.canvas_width, canvas.canvas_height = 1280, 720
            try:
                self.world(alpha)
            finally:
                s.SDL_SetRenderTarget(canvas.renderer, None)
                s.SDL_RenderSetLogicalSize(canvas.renderer, 640, 360)
                canvas.canvas_width, canvas.canvas_height = 640, 360
            s.SDL_RenderCopy(canvas.renderer, self._zoom_target, None, None)
        else:
            width, height = VIEW_SIZES[self.view_mode]
            s.SDL_RenderSetLogicalSize(canvas.renderer, width, height)
            canvas.canvas_width, canvas.canvas_height = width, height
            self.world(alpha)
        s.SDL_RenderSetLogicalSize(canvas.renderer, *LOGICAL_SIZE)
        canvas.canvas_width, canvas.canvas_height = LOGICAL_SIZE
        hud_w, hud_h = LOGICAL_SIZE
        self.rect(12, hud_h-42, hud_w-24, 32, (14, 11, 25, 230))
        self.rect(12, hud_h-42, 3, 32, (225, 184, 104, 255))
        self.text(24, hud_h-25, 'GLEAM', size=16, color=(248, 216, 152))
        minutes, seconds = divmod(int(scene.elapsed), 60)
        self.text(hud_w-259, hud_h-25, '%02d:%02d   사망 %d   흡수 %d/%d' % (
            minutes, seconds, scene.deaths, scene.absorbed, len(scene.sources)), size=10)
        self.rect(12, 10, hud_w-24, 40, (14, 11, 25, 230))
        self.text(24, 36, scene.section['hint'], size=10)
        self.text(24, 20, 'R 재시작    Shift+R 처음부터    F5 맵 다시 읽기    P 일시정지    Esc 종료',
                  size=9, color=(140, 131, 164))
        self.text(hud_w/2, 64, {'normal': 'F6: 640x360', 'zoom_half': 'F7: 0.5x / 640x360',
                            'logical_960': 'F8: 960x540', 'logical_1280': 'F9: 1280x720',
                            'logical_1920': 'F10: 1920x1080 / player 1x'}[self.view_mode]
                  + '   |   F6-F10', size=10, center=True)
        if scene.checkpoint_flash:
            self.text(hud_w/2, hud_h-66, 'CHECKPOINT SAVED', size=12, color=(135, 247, 199), center=True)
        if scene.paused or scene.complete:
            cx, cy = hud_w/2, hud_h/2
            self.rect(0, 0, hud_w, hud_h, (8, 6, 16, 205))
            self.rect(cx-196, cy-70, 392, 140, (23, 19, 37, 255))
            self.rect(cx-196, cy+66, 392, 2, (231, 193, 119, 255))
            if scene.complete:
                self.text(cx, cy-6, '%02d:%02d  /  사망 %d  /  흡수 %d/%d' % (
                    minutes, seconds, scene.deaths, scene.absorbed, len(scene.sources)), center=True)
                self.text(cx, cy-41, 'Enter 또는 R  다시 플레이', center=True)
            else:
                self.text(cx, cy+34, 'PAUSED', size=24, color=(247, 219, 161), center=True)
                self.text(cx, cy-15, 'Enter / P  계속하기', center=True)
                self.text(cx, cy-43, 'R  체크포인트 재시작', size=10, center=True)

    def close(self):
        if self._zoom_target is not None:
            s.SDL_DestroyTexture(self._zoom_target)
            self._zoom_target = None
        self.player.close()
        self.electric_view.close()
        self.tiles.close()
        for view in self.object_views + self.platform_views:
            view.close()
        self.text_images.clear()
        self.images.clear()
        for font in self.fonts.values():
            sdlttf.TTF_CloseFont(font.font)
        self.fonts.clear()
