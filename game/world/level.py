"""LDtk 1.5 프로젝트를 게임 배치 데이터로 읽는다. 에디터 좌표 해석은 여기서만 한다."""
import json
from pathlib import Path


def _fields(entity):
    return {field['__identifier']: field['__value'] for field in entity.get('fieldInstances', ())
            if field.get('__value') is not None}


def _rectangles(values, columns, rows, cell):
    """같은 가로 구간을 세로로 합쳐 IntGrid 내부의 불필요한 충돌 경계를 없앤다."""
    active, result = {}, []
    for row in range(rows):
        runs, col = [], 0
        while col < columns:
            if values[row * columns + col] != 1:
                col += 1
                continue
            start = col
            while col < columns and values[row * columns + col] == 1:
                col += 1
            runs.append((start, col - start))
        current = {}
        for key in runs:
            previous = active.pop(key, None)
            current[key] = ([key[0] * cell, row * cell, key[1] * cell, cell]
                            if previous is None else previous)
            if previous is not None:
                previous[3] += cell
        result.extend(active.values())
        active = current
    return result + list(active.values())


def load_ldtk(path, identifier=None):
    path = Path(path)
    project = json.loads(path.read_text(encoding='utf-8-sig'))
    levels = list(project.get('levels', ()))
    for world in project.get('worlds', ()):
        levels.extend(world.get('levels', ()))
    level = next((item for item in levels if identifier is None or item['identifier'] == identifier), None)
    if level is None:
        raise ValueError('LDtk: playable level not found')
    if level.get('layerInstances') is None and level.get('externalRelPath'):
        level = json.loads((path.parent / level['externalRelPath']).read_text(encoding='utf-8-sig'))
    width, height = level['pxWid'], level['pxHei']
    data = {key: [] for key in ('floor', 'platforms', 'one_way', 'spikes', 'ceiling_spikes', 'sources', 'moving',
                                'disappearing', 'jump_platforms', 'checkpoints', 'sections', 'tile_layers')}
    data.update(size=[width, height], ldtk_path=str(path.resolve()))
    tilesets = {item['uid']: item for item in project['defs']['tilesets']}
    spawn, exit_area, checkpoints = None, None, []
    for layer in reversed(level.get('layerInstances') or ()):
        ox, oy = layer.get('__pxTotalOffsetX', 0), layer.get('__pxTotalOffsetY', 0)
        cell = layer['__gridSize']
        if layer['__identifier'] == 'Collision' and layer['__type'] == 'IntGrid':
            values, columns, rows = layer['intGridCsv'], layer['__cWid'], layer['__cHei']
            if len(values) != columns * rows or any(value not in (0, 1) for value in values):
                raise ValueError('LDtk: Collision must contain only empty (0) and Solid (1) cells')
            for x, y, w, h in _rectangles(values, columns, rows, cell):
                data['floor'].append([x + ox, height - y - oy - h, w, h])
        tiles = layer.get('autoLayerTiles', ()) or layer.get('gridTiles', ())
        if tiles:
            tileset = tilesets[layer['__tilesetDefUid']]
            data['tile_layers'].append({
                'image': str((path.parent / tileset['relPath']).resolve()),
                'size': tileset['tileGridSize'], 'offset': [ox, oy],
                'opacity': layer.get('__opacity', 1), 'tiles': tiles,
            })
        for entity in layer.get('entityInstances', ()):
            kind, fields = entity['__identifier'], _fields(entity)
            x, y = entity['px'][0] + ox, height - entity['px'][1] - oy
            ew, eh = entity['width'], entity['height']
            thickness = fields.get('Thickness', 8)
            area = [x, y - thickness, ew, thickness]
            if kind == 'PlayerSpawn':
                if spawn is not None:
                    raise ValueError('LDtk: use exactly one PlayerSpawn')
                spawn = [x, y]
            elif kind == 'Checkpoint':
                checkpoints.append((fields.get('Order', 0), {
                    'spawn': [x + fields.get('RespawnOffsetX', 24), y], 'terminal': [x, y]}))
            elif kind == 'Exit':
                if exit_area is not None:
                    raise ValueError('LDtk: use exactly one Exit')
                exit_area = [x - 28, y, 56, 104]
            elif kind == 'Platform':
                data['platforms'].append(area)
            elif kind == 'OneWay':
                data['one_way'].append(area)
            elif kind == 'MovingPlatform':
                data['moving'].append({'area': area, 'end_x': x + fields.get('Travel', 296),
                                       'speed': fields.get('Speed', 64)})
            elif kind == 'DisappearingPlatform':
                data['disappearing'].append({'area': area, 'warning_time': fields.get('WarningTime', .5),
                                             'hidden_time': fields.get('HiddenTime', 2)})
            elif kind == 'JumpPlatform':
                data['jump_platforms'].append({'area': [x - 24, y, 48, 32.5],
                                              'launch_height': fields.get('LaunchHeight', 128)})
            elif kind == 'Spikes':
                # Entity 원점은 가시의 위험 영역 왼쪽 위. 그림 여백은 판정에 넣지 않는다.
                hazard_height = fields.get('HazardHeight', 10.5)
                data['spikes'].append([x, y - hazard_height, ew * 128 / 144, hazard_height])
            elif kind == 'CeilingSpikes':
                # 원점은 천장에 붙는 받침대 중앙. 뒤집힌 그림의 받침대(8)에서
                # 위험 영역(31)까지 23px를 띄워 금속 받침과 여백은 무해하게 둔다.
                hazard_height = fields.get('HazardHeight', 10.5)
                hazard_width = ew * 128 / 144
                top = y - 23 / 28 * hazard_height
                data['ceiling_spikes'].append([x - hazard_width / 2, top - hazard_height,
                                              hazard_width, hazard_height])
            elif kind == 'AbsorbSource':
                size = fields.get('BodySize', 28)
                data['sources'].append([x - size / 2, y - size / 2, size, size])
            elif kind == 'Hint':
                data['sections'].append({'x': x, 'hint': fields.get('Text', '')})
    if spawn is None or exit_area is None:
        raise ValueError('LDtk: add one PlayerSpawn and one Exit in an Entities layer')
    checkpoints.sort(key=lambda item: item[0])
    data['checkpoints'] = [item for _, item in checkpoints]
    if checkpoints and checkpoints[0][0] == 0:
        data['checkpoints'][0]['spawn'] = spawn
    else:
        data['checkpoints'].insert(0, {'spawn': spawn, 'terminal': None})
    data['exit'] = exit_area
    data['sections'].sort(key=lambda section: section['x'])
    return data
