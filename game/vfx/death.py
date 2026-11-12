"""사망 반동과 빛 조각의 시각적 타이밍. 게임의 사망 판정은 담당하지 않는다."""
import math

from .painter import TAU, clamp, fit, rand


FREEZE_TIME = .05
BURST_TIME = FREEZE_TIME + .205  # dead 클립이 몸에서 별 조각으로 바뀌는 시점.
DURATION = .9
WHITE = ('#34354a', '#66677e', '#999bb2', '#bfc4d8', '#dbe3ee', '#eef5fa', '#f8fcff', '#ffffff')
GOLD = ('#392039', '#704039', '#b16b37', '#eaa847', '#ffd373', '#ffe7a7', '#fff1ce', '#fff9e9')
CYAN = ('#173341', '#235361', '#398092', '#61b4c8', '#8ae3f1', '#b9f2fa', '#defaff', '#f3fdff')


def recoil_offset(elapsed, direction=1):
    """월드 좌표 기준 반동. 잠깐 정지하고, 몸이 분해되면 방출 위치를 유지한다."""
    age = clamp(elapsed - FREEZE_TIME, 0, BURST_TIME - FREEZE_TIME)
    return direction * 160 * age, 340 * age - 500 * age * age


def death_burst(p, t, o):
    if t < 0 or t >= DURATION:
        return
    stage, seed = int(clamp(o.get('stage', 2), 1, 3)), o.get('seed', 113)
    gold = fit(WHITE if stage == 1 else o.get('palette', GOLD))
    cyan = fit(o.get('accent_palette', CYAN))
    if t < FREEZE_TIME:
        flash = 1 - t / FREEZE_TIME
        p.line(-7 * flash, -28, 7 * flash, -28, gold[7], flash)
        p.line(0, -28 - 6 * flash, 0, -28 + 6 * flash, gold[7], flash)
        p.glow(0, -28, 18, gold[5], flash * .35)

    age = t - BURST_TIME
    if age < 0:
        return
    cx, up = recoil_offset(BURST_TIME)
    cy = -up - 28
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

    for i in range(16):
        a = age - rand(seed, i, 1) * .025
        life = .28 + rand(seed, i, 2) * .32
        if not 0 < a < life:
            continue
        angle = i / 16 * TAU + (rand(seed, i, 3) - .5) * .7
        speed = 180 + rand(seed, i, 4) * 160
        travel = (1 - math.exp(-4 * a)) / 4
        vx, vy = math.cos(angle) * speed, math.sin(angle) * speed * .75 - 35
        sx, sy = (rand(seed, i, 6) - .5) * 24, (rand(seed, i, 7) - .5) * 16
        x, y = cx + sx + vx * travel, cy + sy + vy * travel + 130 * a * a
        fade = clamp((life - a) / .15)
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
