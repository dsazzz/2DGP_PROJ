"""사망 반동과 빛 조각의 시각적 타이밍. 게임의 사망 판정은 담당하지 않는다."""
import json
import math

from game.core.paths import ART_ROOT
from .painter import TAU, clamp, fit, rand


SETTINGS = json.loads((ART_ROOT / 'player' / 'player-settings.json').read_text(encoding='utf-8'))['death']
FREEZE_TIME = SETTINGS['freeze_time']
BURST_TIME = FREEZE_TIME + SETTINGS['burst_delay']
DURATION = SETTINGS['duration']
WHITE, GOLD, CYAN = (SETTINGS[key] for key in ('white_palette', 'gold_palette', 'cyan_palette'))


def recoil_offset(elapsed, direction=1):
    """월드 좌표 기준 반동. 잠깐 정지하고, 몸이 분해되면 방출 위치를 유지한다."""
    age = clamp(elapsed - FREEZE_TIME, 0, BURST_TIME - FREEZE_TIME)
    vx, vy = SETTINGS['recoil_speed']
    return direction * vx * age, vy * age - SETTINGS['recoil_gravity'] / 2 * age * age


def death_burst(p, t, o):
    if t < 0 or t >= DURATION:
        return
    stage, seed = int(clamp(o.get('stage', 2), 1, 3)), o.get('seed', SETTINGS['seed'])
    gold = fit(WHITE if stage == 1 else o.get('palette', GOLD))
    cyan = fit(o.get('accent_palette', CYAN))
    height = SETTINGS['center_height']
    if t < FREEZE_TIME:
        flash = 1 - t / FREEZE_TIME
        p.line(-7 * flash, -height, 7 * flash, -height, gold[7], flash)
        p.line(0, -height - 6 * flash, 0, -height + 6 * flash, gold[7], flash)
        p.glow(0, -height, 18, gold[5], flash * .35)

    age = t - BURST_TIME
    if age < 0:
        return
    cx, up = recoil_offset(BURST_TIME)
    cy = -up - height
    flash = clamp(1 - age / .08)
    if flash:
        p.circle(cx, cy, 2 + flash * 4, gold[7], flash)
        p.glow(cx, cy, 34, gold[5], flash * .42)
    ring = clamp(1 - age / .18)
    if ring:
        radius = 6 + age * 210
        for start in (.15, 2.2, 4.3):
            points = [(cx + math.cos(start + i * .16) * radius,
                       cy + math.sin(start + i * .16) * radius * .8) for i in range(9)]
            p.polyline(points, gold[5], ring * .7)

    particles = SETTINGS['particles']
    for i in range(particles['count']):
        a = age - rand(seed, i, 1) * particles['delay_spread']
        lo, hi = particles['life']
        life = lo + rand(seed, i, 2) * (hi - lo)
        if not 0 < a < life:
            continue
        angle = i / particles['count'] * TAU + (rand(seed, i, 3) - .5) * particles['angle_spread']
        lo, hi = particles['speed']
        speed = lo + rand(seed, i, 4) * (hi - lo)
        drag = particles['drag']
        travel = (1 - math.exp(-drag * a)) / drag if drag else a
        vx, vy = math.cos(angle) * speed, math.sin(angle) * speed * .75 - 35
        sx, sy = (rand(seed, i, 6) - .5) * 24, (rand(seed, i, 7) - .5) * 16
        x, y = cx + sx + vx * travel, cy + sy + vy * travel + particles['gravity'] / 2 * a * a
        fade = clamp((life - a) / particles['fade_time'])
        colors = cyan if stage == 3 and math.sin(angle) < .2 else gold
        length = (6 + rand(seed, i, 5) * 5) * (1 - a / life)
        dx, dy = math.cos(angle) * length, math.sin(angle) * length
        p.beam(x - dx, y - dy, x, y, 2.5 if i % 3 == 0 else 1.6, colors[3], fade)
        p.line(x - dx, y - dy - 1, x, y - 1, colors[5], fade)
        p.circle(x, y, 1.1, colors[7], fade)
        p.glow(x, y, 5, colors[4], fade * .18)
        twinkle = max(0, 1 - abs(a - life * .6) / .055)
        if i % 5 == 0 and twinkle:
            p.line(x - 2, y, x + 2, y, colors[6], twinkle * fade)
            p.line(x, y - 2, x, y + 2, colors[7], twinkle * fade)
