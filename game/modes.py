"""게임 모드 전환. 물리 갱신은 플레이 중에만 실행한다."""
import json

import pico2d as p
import sdl2 as s

from game.core.camera import Camera
from game.core.display import DEFAULT_VIEW_MODE, VIEW_SIZES
from game.core.paths import ART_ROOT, PROJECT_ROOT
from game.title import Title
from game.world.level import load_ldtk
from game.world.scene import PlayScene


VIEW_KEYS = dict(zip((s.SDLK_F6, s.SDLK_F7, s.SDLK_F8, s.SDLK_F9, s.SDLK_F10), VIEW_SIZES))
FRAME_LIMITS = (60, 120, 144)


class GameModes:
    def __init__(self, settings_file=None):
        self.scene = None
        self.settings_file = settings_file or PROJECT_ROOT / '.local/settings.json'
        self.view_mode = DEFAULT_VIEW_MODE
        self.fps = 144
        try:
            settings = json.loads(self.settings_file.read_text(encoding='utf-8'))
            if isinstance(settings, dict):
                if settings.get('view') in tuple(VIEW_SIZES):
                    self.view_mode = settings['view']
                if settings.get('fps') in FRAME_LIMITS:
                    self.fps = settings['fps']
        except (OSError, ValueError):
            pass
        self.title = None
        self.enter('title')

    def enter(self, mode):
        self.mode = mode
        if self.scene:
            self.scene.paused = mode != 'play'
            self.scene._clear_input()

    def apply_view(self):
        if self.scene:
            scene = self.scene
            scene.camera = Camera(scene.bounds, size=VIEW_SIZES[self.view_mode])
            scene.camera.snap(scene.player.x, scene.player.y + scene.player.body_height / 2)
            scene.view.view_mode = self.view_mode
            scene.view.player.zoom = 1.0 if self.view_mode == 'logical_1920' else .5
            scene.view.remember_positions()

    @property
    def running(self):
        return self.mode != 'quit'

    @property
    def updating(self):
        return self.mode == 'play'

    def update(self, dt):
        self.scene.update(dt)
        if self.scene.complete:
            self.enter('ending')

    def after_present(self):
        """로딩 화면을 제출한 뒤 맵을 읽고 물리 시계를 다시 맞춘다."""
        if self.mode == 'title' and self.title and self.title.finished():
            self.title = None
            self.enter('loading')
        if self.mode != 'loading':
            return False
        self.load()
        return True

    def load(self):
        replacement = None
        try:
            replacement = PlayScene(load_ldtk(ART_ROOT / 'levels/gleam.ldtk'))
            replacement.open()
        except (OSError, ValueError, RuntimeError) as exc:
            if replacement:
                replacement.close()
            print(f'Level load failed: {exc}', flush=True)
            self.enter('pause' if self.scene else 'quit')
            return
        if self.scene:
            self.scene.close()
        self.scene = replacement
        self.apply_view()
        self.enter('play')

    def handle_events(self, events):
        if any(e.type == s.SDL_QUIT for e in events):
            self.enter('quit')
            return
        if self.mode == 'title':
            if self.title is None:
                self.title = Title()
            for event in events:
                self.title.handle(event, self)
                if not self.running:
                    break
            return
        if self.mode == 'play':
            for i, event in enumerate(events):
                key = event.key.keysym.sym if event.type == s.SDL_KEYDOWN and not event.key.repeat else None
                if key in (s.SDLK_p, s.SDLK_ESCAPE, s.SDLK_F5) or (
                        event.type == s.SDL_WINDOWEVENT and event.window.event == s.SDL_WINDOWEVENT_FOCUS_LOST):
                    self.scene.handle_events(events[:i])
                    self.enter('loading' if key == s.SDLK_F5 else 'pause')
                    return
                if key in VIEW_KEYS:
                    self.view_mode = VIEW_KEYS[key]
                    self.apply_view()
            self.scene.handle_events(events)
            return
        for event in events:
            if event.type != s.SDL_KEYDOWN or event.key.repeat:
                continue
            key = event.key.keysym.sym
            if self.mode == 'pause':
                if key in (s.SDLK_p, s.SDLK_ESCAPE, s.SDLK_RETURN):
                    self.enter('play')
                    return
                if key == s.SDLK_r:
                    self.scene.restart()
                    self.enter('play')
                    return
            if key == s.SDLK_F5 or (self.mode == 'ending' and key in (s.SDLK_RETURN, s.SDLK_r)):
                self.enter('loading')
                return

    def draw(self, alpha):
        if self.mode == 'title':
            self.title.draw(self)
        elif self.scene:
            self.scene.draw(alpha if self.updating else 1.0)
        else:
            p.clear_canvas()

    def close(self):
        self.title = None
        if self.scene:
            self.scene.close()
