"""Stage One: "Silent Depot" - level geometry, props and entity spawns.

The map is a 64x48 tile military supply depot at night. Tiles are integers:
  0 empty space (walkable)
  1..N solid walls, each id mapped to a texture by TILE_TEXTURES

Layout, roughly west to east:
  * outer perimeter fence with a main gate and two watchtowers
  * motor pool (trucks, fuel bowsers, generators) in the south-west
  * barracks block in the north-west where the colonel's office sits
  * central parade ground (the largest open sight-line, deliberately risky)
  * supply warehouses east of the parade ground, intel in the command post
  * extraction landing pad in the far east corner

The layout is authored by carving rectangles, which keeps the definition
readable and easy to retune.
"""

import math

import numpy as np

from ..engine.raycaster import Camera
from ..engine.sprites import Sprite

MAP_W = 64
MAP_H = 48

# Tile ids -> texture names in the engine's tile_textures table.
TILE_TEXTURES = [
    "concrete",     # 0: unused (empty)
    "concrete",     # 1: perimeter concrete wall
    "brick",        # 2: barracks brick
    "metal",        # 3: warehouse / command metal cladding
    "crate",        # 4: supply crates
    "sandbag",      # 5: sandbag emplacements
    "fence",        # 6: chain-link fence
    "painted",      # 7: painted depot walls
    "door",         # 8: doors
    "tent",         # 9: canvas tents / hangar skin
    "container",    # 10: shipping containers
    "barrel",       # 11: barrel stacks (as a wall)
]

T_WALL, T_BRICK, T_METAL, T_CRATE = 1, 2, 3, 4
T_SANDBAG, T_FENCE, T_PAINT, T_DOOR = 5, 6, 7, 8
T_TENT, T_CONTAINER, T_BARREL = 9, 10, 11


class Level:
    """Mission stage data: geometry, spawn points, patrol routes, objectives."""

    def __init__(self):
        self.name = "Silent Depot"
        self.subtitle = "Stage One"
        self.grid = np.zeros((MAP_H, MAP_W), dtype=np.int32)
        self.floor_a = "floor_gravel"
        self.floor_b = "floor_concrete"
        self.ceiling = "ceiling"
        self.player_start = (6.5, 40.5)
        self.player_start_angle = -0.35
        self.extraction = (58.5, 27.5)
        self.camera_spawns = []
        self.enemy_spawns = []
        self.truck_spawns = []
        self.waypoints = []
        self.intel_spawns = []
        self.pickup_spawns = []
        self.brush_builders()
        self._build_props()

    # ------------------------------------------------------- authoring help --
    def box(self, x0, y0, x1, y1, tile):
        """Fill an inclusive rectangle with a tile id."""
        x0 = max(0, min(MAP_W - 1, int(x0)))
        x1 = max(0, min(MAP_W - 1, int(x1)))
        y0 = max(0, min(MAP_H - 1, int(y0)))
        y1 = max(0, min(MAP_H - 1, int(y1)))
        self.grid[y0:y1 + 1, x0:x1 + 1] = tile

    def carve(self, x0, y0, x1, y1):
        """Clear an inclusive rectangle back to walkable space."""
        self.box(x0, y0, x1, y1, 0)

    def wall_ring(self, x0, y0, x1, y1, tile, thickness=1):
        for i in range(thickness):
            self.box(x0 + i, y0 + i, x1 - i, y0 + i, tile)
            self.box(x0 + i, y1 - i, x1 - i, y1 - i, tile)
            self.box(x0 + i, y0 + i, x0 + i, y1 - i, tile)
            self.box(x1 - i, y0 + i, x1 - i, y1 - i, tile)

    # --------------------------------------------------------- construction --
    def brush_builders(self):
        # Boundaries of every solid structure are chosen so that there is always
        # a walkable tile adjacent to each spawn and waypoint. The validator in
        # the test suite asserts this, so the two stay in sync.
        self.wall_ring(0, 0, MAP_W - 1, MAP_H - 1, T_WALL, thickness=1)
        self.wall_ring(2, 2, MAP_W - 3, MAP_H - 3, T_FENCE, thickness=1)
        # Gaps in the fence: the west culvert the player enters through, and the
        # north-east lane that opens onto the extraction pad.
        self.carve(2, 39, 3, 42)

        # ---- watchtowers: solid 3x3 platforms at three corners ----
        self.box(4, 4, 6, 6, T_WALL)
        self.box(57, 4, 59, 6, T_WALL)
        self.box(4, 44, 6, 46, T_WALL)

        # ---- barracks, north-west (x6..26, y6..20) ----
        self.wall_ring(6, 6, 26, 20, T_BRICK)
        self.box(19, 6, 19, 20, T_BRICK)          # dividing wall
        self.carve(19, 12, 19, 14)                # doorway between rooms
        self.carve(15, 20, 18, 20)                # main door to the yard
        self.carve(6, 12, 6, 14)                  # side door
        self.box(24, 17, 24, 18, T_DOOR)          # colonel's office door frame
        self.carve(24, 18, 24, 18)
        self.box(8, 9, 12, 9, T_SANDBAG)          # room furniture / cover

        # ---- motor pool, south-west (x6..26, y32..44) ----
        self.wall_ring(6, 32, 26, 44, T_PAINT)
        self.box(6, 38, 20, 38, T_WALL)           # partition wall
        self.carve(17, 38, 19, 38)                # bay opening
        self.carve(6, 39, 6, 41)                  # west door (insertion route)
        self.carve(14, 44, 16, 44)                # south vehicle gate
        self.box(9, 41, 11, 41, T_SANDBAG)
        self.box(24, 33, 24, 35, T_SANDBAG)

        # ---- parade ground guard hut (x29..35, y22..26) ----
        self.wall_ring(29, 22, 35, 26, T_PAINT)
        self.carve(31, 26, 33, 26)

        # ---- supply warehouse, east (x38..54, y28..42) ----
        self.wall_ring(38, 28, 54, 42, T_METAL)
        self.box(42, 28, 42, 42, T_CRATE)         # racking
        self.carve(42, 34, 42, 36)
        self.box(47, 28, 47, 42, T_CRATE)
        self.carve(47, 34, 47, 36)
        self.carve(44, 42, 47, 42)                # south rolling door
        self.carve(38, 33, 38, 35)                # west personnel door
        self.carve(54, 33, 54, 35)                # east loading door

        # ---- command post, north-east (x40..54, y6..18) ----
        self.wall_ring(40, 6, 54, 18, T_METAL)
        self.box(47, 6, 47, 18, T_METAL)          # dividing wall
        self.carve(47, 11, 47, 13)
        self.box(52, 10, 52, 16, T_CRATE)         # filing stacks
        self.carve(52, 13, 52, 14)
        self.carve(44, 18, 46, 18)                # front door

        # ---- yard clutter and containers ----
        self.box(30, 8, 36, 9, T_CONTAINER)
        self.carve(33, 8, 33, 9)
        self.box(30, 15, 34, 15, T_CONTAINER)
        self.box(28, 34, 32, 34, T_SANDBAG)       # yard revetment
        self.carve(30, 34, 30, 34)
        self.box(34, 44, 40, 44, T_BARREL)        # fuel drum line
        self.carve(37, 44, 37, 44)
        self.box(44, 44, 48, 44, T_BARREL)
        self.carve(46, 44, 46, 44)

        # ---- canvas tents in the east yard ----
        self.box(56, 20, 60, 24, T_TENT)
        self.carve(58, 24, 58, 24)
        self.box(56, 30, 60, 34, T_TENT)
        self.carve(58, 30, 58, 30)

        # ---- clear the extraction pad approach lane ----
        self.carve(55, 20, 60, 20)
        self.carve(55, 25, 60, 29)
        self.carve(55, 35, 60, 43)
        self.carve(55, 7, 60, 19)

    def _build_props(self):
        """Spawn data for cameras, guards, vehicles, intel and pickups.

        Every position here is deliberately placed on a walkable tile adjacent
        to the structure it guards; the geometry test in the suite enforces it.
        """
        self.camera_spawns = [
            # (x, y, facing angle, name) - all mounted facing open ground.
            (28.5, 19.5, math.radians(120), "Parade West"),
            (36.5, 27.5, math.radians(225), "Parade East"),
            (41.5, 27.5, math.radians(60), "Warehouse North"),
            (46.5, 19.5, math.radians(210), "Command Post"),
            (37.5, 43.5, math.radians(270), "Motor Pool South"),
            (12.5, 31.5, math.radians(90), "Motor Pool North"),
            (24.5, 5.5, math.radians(160), "Barracks North"),
        ]

        # Guards: (x, y, facing, patrol route as list of points, kind)
        self.enemy_spawns = [
            # Outer mobile patrol walking the inside of the fence.
            (10.5, 40.5, 0.0, [(10.5, 40.5), (16.5, 40.5), (16.5, 36.5),
                               (10.5, 36.5)], "soldier"),
            # Parade ground sentry, two-point back and forth.
            (30.5, 21.5, math.pi, [(30.5, 21.5), (30.5, 29.5)], "soldier"),
            # Motor pool interior guard.
            (16.5, 36.5, -1.57, [(16.5, 36.5), (23.5, 36.5), (23.5, 40.5),
                                 (12.5, 40.5)], "soldier"),
            # Warehouse interior patrol between the racking.
            (43.5, 30.5, 1.57, [(43.5, 30.5), (50.5, 30.5), (50.5, 40.5),
                                (43.5, 40.5)], "soldier"),
            # Command post roving guard.
            (44.5, 8.5, -1.57, [(44.5, 8.5), (44.5, 16.5), (41.5, 16.5),
                                (41.5, 8.5)], "soldier"),
            # North yard patrol, near the containers.
            (31.5, 11.5, 1.57, [(31.5, 11.5), (31.5, 13.5), (28.5, 13.5),
                                (28.5, 11.5)], "soldier"),
            # Static tower sentries (between the corner towers and the fence).
            (8.5, 8.5, 0.9, [(8.5, 8.5)], "soldier"),
            (55.5, 8.5, 2.4, [(55.5, 8.5)], "soldier"),
            (8.5, 42.5, -0.9, [(8.5, 42.5)], "soldier"),
            # Barracks doorway sentry.
            (16.5, 22.5, 1.57, [(16.5, 22.5), (16.5, 25.5)], "soldier"),
            # Barracks inner-room guard (west room, clear of furniture).
            (14.5, 12.5, 3.14, [(14.5, 12.5), (14.5, 17.5)], "soldier"),
            # Colonel and his escort in the east room.
            (22.5, 12.5, 3.14, [(22.5, 12.5), (22.5, 16.5), (18.5, 16.5)],
             "officer"),
        ]

        # Parked trucks: (x, y, facing, patrolling?, route)
        self.truck_spawns = [
            # The two fuelled bowsers in the motor pool, on the walkable tile
            # just north of the partition wall.
            (9.5, 36.5, 0.0, False, None),
            (24.5, 37.5, 0.0, False, None),
            # A cargo truck parked in the open yard (not a target).
            (44.5, 24.5, 0.0, False, None),
            # Mobile patrol truck looping the roads.
            (13.5, 40.5, 0.0, True, [(13.5, 40.5), (22.5, 40.5), (22.5, 42.5),
                                     (13.5, 42.5)]),
            # A second mobile truck on the north road.
            (30.5, 12.5, 0.0, True, [(30.5, 12.5), (36.5, 12.5), (36.5, 13.5),
                                     (28.5, 13.5), (28.5, 11.5), (30.5, 11.5)]),
        ]

        # Mission intel: (x, y, label)
        self.intel_spawns = [
            (51.5, 13.5, "OPORD - Depot Manifests"),
            (44.5, 8.5, "SIGINT - Convoy Schedule"),
            (12.5, 12.5, "PERSONNEL - Officer Roster"),
        ]

        # Pickups: (kind, x, y)  kind in ammo/medkit/pistol/smg/shotgun/sniper
        self.pickup_spawns = [
            ("medkit", 10.5, 42.5),
            ("ammo", 12.5, 42.5),
            ("smg", 15.5, 43.5),
            ("shotgun", 25.5, 36.5),
            ("ammo", 44.5, 43.5),
            ("medkit", 39.5, 33.5),
            ("sniper", 50.5, 44.5),
            ("ammo", 33.5, 11.5),
            ("medkit", 44.5, 17.5),
            ("ammo", 16.5, 24.5),
        ]

    # ------------------------------------------------------------- helpers ----
    def is_solid(self, x, y):
        """Tile test in world coordinates, with a small safety margin."""
        ix = int(x)
        iy = int(y)
        if ix < 0 or iy < 0 or ix >= MAP_W or iy >= MAP_H:
            return True
        return self.grid[iy, ix] != 0

    def blocked_at(self, x, y, radius):
        """True when a circle at (x, y) overlaps any solid tile."""
        from ..utils import circle_aabb_overlap
        ix, iy = int(x), int(y)
        for ty in range(iy - 1, iy + 2):
            for tx in range(ix - 1, ix + 2):
                if tx < 0 or ty < 0 or tx >= MAP_W or ty >= MAP_H:
                    return True
                if self.grid[ty, tx] == 0:
                    continue
                if circle_aabb_overlap(x, y, radius, tx, ty, tx + 1.0, ty + 1.0):
                    return True
        return False

    def tile_at(self, x, y):
        ix, iy = int(x), int(y)
        if ix < 0 or iy < 0 or ix >= MAP_W or iy >= MAP_H:
            return T_WALL
        return int(self.grid[iy, ix])

    def floor_name_at(self, x, y):
        """Concrete indoors, gravel outdoors: gives each area its own texture."""
        tile = self.tile_at(x, y)
        if tile == 0:
            return self.floor_a
        return self.floor_b

    def camera(self):
        return Camera(self.player_start[0], self.player_start[1],
                      self.player_start_angle, eye_z=0.62)

    # --------------------------------------------------------- sprite build --
    def build_sprites(self, art, entities=None):
        """Create static prop sprites (dynamic entities add their own)."""
        sprites = []

        def add(kind, x, y, height, width, z=0.0, emerge=0.0, facing=0.0,
                tag=None):
            frames = art.props[kind][0]
            sprite = Sprite(x, y, kind=kind, art_frames={0: frames},
                            height=height, width=width, z_base=z,
                            emit=emerge, facing=facing, tag=tag)
            sprites.append(sprite)
            return sprite

        # Watchtower structures on top of the solid bases.
        add("tower", 5.5, 5.5, 2.6, 1.7)
        add("tower", 57.5, 5.5, 2.6, 1.7)
        add("tower", 5.5, 44.5, 2.6, 1.7)

        # Lamp posts along the parade ground and roads.
        lamps = [(27.0, 29.0), (37.0, 29.0), (27.0, 17.0), (37.0, 17.0),
                 (12.0, 27.0), (28.0, 44.0), (46.0, 24.0), (46.0, 4.0),
                 (54.0, 20.0), (20.0, 24.0)]
        for lx, ly in lamps:
            add("lamp", lx, ly, 2.4, 0.55, emerge=0.55)

        # Extraction landing pad and marker.
        add("helipad", self.extraction[0], self.extraction[1], 0.25, 3.0)
        add("extraction", self.extraction[0], self.extraction[1], 1.8, 0.9,
            z=1.1, emerge=0.9, tag="extraction")

        # Yard clutter: barrels, crates, sandbag stacks, generators.
        clutter = [
            ("barrel", 8.5, 33.5), ("barrel", 9.2, 34.3), ("barrel", 8.8, 34.9),
            ("crate", 30.5, 11.5), ("crate", 31.2, 12.4),
            ("crate", 21.5, 28.5), ("crate", 22.3, 28.4),
            ("sandbags", 33.0, 37.5), ("sandbags", 38.0, 44.5),
            ("generator", 25.0, 44.5), ("generator", 36.0, 22.5),
            ("barrel", 42.5, 44.2), ("barrel", 43.2, 44.6),
            ("crate", 55.5, 26.5), ("crate", 56.2, 27.3),
            ("sandbags", 18.0, 7.0), ("barrel", 31.0, 6.5),
            ("crate", 52.5, 44.0), ("crate", 53.2, 44.6),
            ("barrel", 16.5, 20.5), ("generator", 44.0, 34.5),
        ]
        for kind, cx, cy in clutter:
            heights = {"barrel": 0.85, "crate": 0.7, "sandbags": 0.6,
                       "generator": 0.65}
            widths = {"barrel": 0.6, "crate": 0.75, "sandbags": 1.0,
                      "generator": 0.9}
            add(kind, cx, cy, heights[kind], widths[kind])

        # Intel laptops with waypoint markers.
        for ix, iy, label in self.intel_spawns:
            add("laptop", ix, iy, 0.5, 0.6, tag=("intel", label))
            add("waypoint", ix, iy, 1.5, 0.55, z=0.9, emerge=0.85,
                tag=("intel_marker", label))

        # Pickups (wired up by the game so they can be collected).
        for kind, px, py in self.pickup_spawns:
            build = "medkit" if kind == "medkit" else "ammo"
            height = {"medkit": 0.35, "ammo": 0.3}.get(build, 0.35)
            add(build, px, py, height, 0.5, tag=("pickup", kind, px, py))

        return sprites

    # --------------------------------------------------------------- routes --
    def patrol_route_for(self, index):
        if 0 <= index < len(self.enemy_spawns):
            return self.enemy_spawns[index][3]
        return None
