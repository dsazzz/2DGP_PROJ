"""캐릭터 애니메이션과 독립적으로 재생하는 게임용 별 이펙트."""
import json

import pico2d as p

from game.paths import ART_ROOT


ASSETS = ART_ROOT / 'player'


class Sparkles:
    def __init__(self):
        self.sparkles = json.loads((ASSETS / 'sparkles.json').read_text(encoding='utf-8'))
        self.sparkle_image = p.load_image(str(ASSETS / self.sparkles['atlas']))
        self.enabled = True
        self.time_ms = 0.0

    def update(self, dt):
        self.time_ms += dt * 1000

    def draw(self, tier, x, y, zoom=1.0, flip=False):
        # WHITE는 몸 발광만, GOLD/CYAN은 별의 두 색상 단계를 표시한다.
        if not self.enabled or tier == 0:
            return
        stage = self.sparkles['stages'][tier - 1]
        frame_ms = stage['ticks_per_frame'] * 1000 / stage['tick_hz']
        phase = int(self.time_ms / frame_ms) % 3
        rect = stage['pico2d_clip_rects'][phase]
        width, height = stage['cell_size']
        anchor_x, anchor_y = stage['anchor_px']
        dx = (width / 2 - anchor_x) * zoom
        dy = (anchor_y - height / 2) * zoom
        center_x = x - dx if flip else x + dx
        self.sparkle_image.clip_composite_draw(
            *rect, 0, 'h' if flip else '', center_x, y + dy,
            width * zoom, height * zoom,
        )
