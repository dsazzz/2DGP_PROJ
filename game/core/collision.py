"""정적 사각형 지형의 축별 이동과 직선 이동 구간 충돌을 해결한다."""
from dataclasses import dataclass
import math
from typing import Iterable, Optional


@dataclass(frozen=True)
class AABB:
    """왼쪽 아래 기준 상자. 변만 맞닿는 것은 겹침으로 보지 않는다."""

    left: float
    bottom: float
    width: float
    height: float

    def __post_init__(self):
        if not all(math.isfinite(value) for value in (
            self.left, self.bottom, self.width, self.height,
        )) or self.width <= 0 or self.height <= 0:
            raise ValueError('AABB needs finite coordinates and positive dimensions')

    @property
    def right(self):
        return self.left + self.width

    @property
    def top(self):
        return self.bottom + self.height

    def overlaps(self, other):
        return (self.left < other.right and self.right > other.left
                and self.bottom < other.top and self.top > other.bottom)


@dataclass(frozen=True)
class MoveResult:
    """이동 후 상자와 이번 이동에서 닿은 면. 속도·게임 상태는 바꾸지 않는다."""

    box: AABB
    hit_left: bool = False
    hit_right: bool = False
    hit_bottom: bool = False
    hit_top: bool = False


def move_and_collide(box: AABB, dx: float, dy: float,
                     solids: Iterable[AABB], *,
                     one_way: Iterable[AABB] = ()) -> MoveResult:
    """x축 다음 y축 순서로 이동한다. 입력 상자와 지형은 변경하지 않는다.

    각 축의 이동 구간 전체에서 가장 가까운 면을 찾는다. 시작할 때 이미
    일반 지형 안에 겹친 배치는 지원하지 않으며 오류로 알린다.
    one_way는 하강 중 발이 윗면을 지날 때만 막는다. 상승·옆면과 이미
    윗면 아래에서 시작한 이동은 막지 않는다. 이동 발판·곡선·회전 지형,
    직선 경로의 첫 충돌에서 멈출 때는 sweep_and_collide를 사용한다.
    """
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValueError('Movement must be finite')
    solids = tuple(solids)
    if any(box.overlaps(solid) for solid in solids):
        raise ValueError('The starting box overlaps a solid')

    x = box.left + dx
    hit_left = hit_right = False
    for solid in solids:
        if box.bottom >= solid.top or box.top <= solid.bottom:
            continue
        if dx > 0 and box.right <= solid.left and x + box.width >= solid.left:
            x = min(x, solid.left - box.width)
            hit_right = True
        elif dx < 0 and box.left >= solid.right and x <= solid.right:
            x = max(x, solid.right)
            hit_left = True

    y = box.bottom + dy
    hit_bottom = hit_top = False
    for solid in solids:
        if x >= solid.right or x + box.width <= solid.left:
            continue
        if dy > 0 and box.top <= solid.bottom and y + box.height >= solid.bottom:
            y = min(y, solid.bottom - box.height)
            hit_top = True
        elif dy < 0 and box.bottom >= solid.top and y <= solid.top:
            y = max(y, solid.top)
            hit_bottom = True

    if dy < 0:
        for platform in one_way:
            if x >= platform.right or x + box.width <= platform.left:
                continue
            if box.bottom >= platform.top and y <= platform.top:
                y = max(y, platform.top)
                hit_bottom = True

    return MoveResult(AABB(x, y, box.width, box.height),
                      hit_left, hit_right, hit_bottom, hit_top)


def _axis_times(low, high, delta, other_low, other_high):
    if delta > 0:
        return (other_low - high) / delta, (other_high - low) / delta
    if delta < 0:
        return (other_high - low) / delta, (other_low - high) / delta
    if high <= other_low or low >= other_high:
        return math.inf, -math.inf
    return -math.inf, math.inf


def first_contact_time(box: AABB, dx: float, dy: float,
                       areas: Iterable[AABB]) -> Optional[float]:
    """이동 구간에서 영역에 처음 진입하는 비율(0~1). 없으면 None.

    시작부터 겹치면 0이며, 한 점을 스치거나 접한 면에서 멀어지면 무시한다.
    지형을 막거나 게임 상태를 바꾸지 않는 트리거용 기하 검사다.
    """
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValueError('Movement must be finite')
    first = None
    for area in areas:
        if box.overlaps(area):
            return 0.0
        enter_x, exit_x = _axis_times(box.left, box.right, dx, area.left, area.right)
        enter_y, exit_y = _axis_times(box.bottom, box.top, dy, area.bottom, area.top)
        enter, leave = max(enter_x, enter_y), min(exit_x, exit_y)
        if 0 <= enter <= 1 and enter < leave:
            first = enter if first is None else min(first, enter)
    return first


def sweep_and_collide(box: AABB, dx: float, dy: float,
                      solids: Iterable[AABB], *,
                      one_way: Iterable[AABB] = ()) -> MoveResult:
    """직선 구간의 첫 접촉에서 두 축을 함께 멈춘다. 남은 이동으로 미끄러지지 않는다."""
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValueError
    solids = tuple(solids)
    if any(box.overlaps(solid) for solid in solids):
        raise ValueError

    candidates = []
    for solid in solids:
        enter_x, exit_x = _axis_times(box.left, box.right, dx, solid.left, solid.right)
        enter_y, exit_y = _axis_times(box.bottom, box.top, dy, solid.bottom, solid.top)
        enter, leave = max(enter_x, enter_y), min(exit_x, exit_y)
        # 한 점을 스치고 멀어지는 경로는 내부로 들어가지 않으므로 막지 않는다.
        if 0 <= enter <= 1 and enter < leave:
            hit_x = math.isclose(enter_x, enter, rel_tol=0, abs_tol=1e-10)
            hit_y = math.isclose(enter_y, enter, rel_tol=0, abs_tol=1e-10)
            candidates.append((enter, solid, hit_x, hit_y))

    if dy < 0:
        for platform in one_way:
            if box.bottom < platform.top:
                continue
            time = (platform.top - box.bottom) / dy
            if 0 <= time <= 1:
                x = box.left + dx * time
                # 발이 윗면을 통과하는 순간의 가로 범위로 판정한다.
                if x < platform.right and x + box.width > platform.left:
                    candidates.append((time, platform, False, True))

    time = min((candidate[0] for candidate in candidates), default=1.0)
    x, y = box.left + dx * time, box.bottom + dy * time
    hit_left = hit_right = hit_bottom = hit_top = False
    for at, solid, hit_x, hit_y in candidates:
        if not math.isclose(at, time, rel_tol=0, abs_tol=1e-10):
            continue
        # 접촉면에 맞춰 다음 갱신에서 반올림 오차로 파고들지 않게 한다.
        if hit_x and dx > 0:
            x = min(x, solid.left - box.width)
            hit_right = True
        elif hit_x and dx < 0:
            x = max(x, solid.right)
            hit_left = True
        if hit_y and dy > 0:
            y = min(y, solid.bottom - box.height)
            hit_top = True
        elif hit_y and dy < 0:
            y = max(y, solid.top)
            hit_bottom = True
    return MoveResult(AABB(x, y, box.width, box.height),
                      hit_left, hit_right, hit_bottom, hit_top)
