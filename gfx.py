"""Процедурная low-poly геометрия для Fart Together (без внешних моделей)."""
import math
import random

from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat,
                          GeomVertexWriter, NodePath, PNMImage, Texture, Vec3)

import sim

U = 100.0  # пикселей симуляции в одной единице 3D-мира


def track_z(s):
    """Высота горки: плавно спускается вниз с небольшими горбами."""
    return -s * 0.0011 + 0.8 * math.sin(s / 1700.0)


def to3d(x, y, lift=0.0):
    s = -y
    return Vec3(x / U, s / U, track_z(s) + lift)


class Mesh:
    """Набирает треугольники с плоскими нормалями (граненый low-poly стиль)."""

    def __init__(self, uv=False):
        self.uv = uv
        fmt = GeomVertexFormat.get_v3n3c4t2() if uv else GeomVertexFormat.get_v3n3c4()
        self.vdata = GeomVertexData("m", fmt, Geom.UH_static)
        self.vw = GeomVertexWriter(self.vdata, "vertex")
        self.nw = GeomVertexWriter(self.vdata, "normal")
        self.cw = GeomVertexWriter(self.vdata, "color")
        self.tw = GeomVertexWriter(self.vdata, "texcoord") if uv else None
        self.prim = GeomTriangles(Geom.UH_static)
        self.n = 0

    def tri(self, a, b, c, color, uvs=None, normal=None):
        a, b, c = Vec3(*a), Vec3(*b), Vec3(*c)
        if normal is None:
            normal = (b - a).cross(c - a)
            if normal.length() < 1e-9:
                return
            normal.normalize()
        for i, p in enumerate((a, b, c)):
            self.vw.add_data3(p)
            self.nw.add_data3(normal)
            self.cw.add_data4(*color) if len(color) == 4 else self.cw.add_data4(color[0], color[1], color[2], 1)
            if self.tw:
                self.tw.add_data2(*(uvs[i] if uvs else (0, 0)))
        self.prim.add_vertices(self.n, self.n + 1, self.n + 2)
        self.n += 3

    def quad(self, a, b, c, d, color, uvs=None, normal=None):
        """a-b-c-d против часовой стрелки, если смотреть с лицевой стороны."""
        self.tri(a, b, c, color, uvs and (uvs[0], uvs[1], uvs[2]), normal)
        self.tri(a, c, d, color, uvs and (uvs[0], uvs[2], uvs[3]), normal)

    def node(self, name="mesh"):
        geom = Geom(self.vdata)
        geom.add_primitive(self.prim)
        gn = GeomNode(name)
        gn.add_geom(geom)
        return NodePath(gn)


# ---------------------------------------------------------------- primitives
def sphere(lat=6, lon=10, color=(1, 1, 1, 1)):
    m = Mesh()
    pts = [[Vec3(math.sin(math.pi * i / lat) * math.cos(2 * math.pi * j / lon),
                 math.sin(math.pi * i / lat) * math.sin(2 * math.pi * j / lon),
                 math.cos(math.pi * i / lat)) for j in range(lon + 1)] for i in range(lat + 1)]
    for i in range(lat):
        for j in range(lon):
            a, b, c, d = pts[i][j], pts[i + 1][j], pts[i + 1][j + 1], pts[i][j + 1]
            if i == 0:
                m.tri(a, b, c, color)
            elif i == lat - 1:
                m.tri(a, b, d, color)
            else:
                m.quad(a, b, c, d, color)
    return m.node("sphere")


def cylinder(seg=12, color=(1, 1, 1, 1), caps=True):
    """Радиус 1, высота 1, ось Z от 0 до 1."""
    m = Mesh()
    for j in range(seg):
        a0, a1 = 2 * math.pi * j / seg, 2 * math.pi * (j + 1) / seg
        p0, p1 = Vec3(math.cos(a0), math.sin(a0), 0), Vec3(math.cos(a1), math.sin(a1), 0)
        m.quad(p0, p1, p1 + Vec3(0, 0, 1), p0 + Vec3(0, 0, 1), color)
        if caps:
            m.tri(Vec3(0, 0, 1), p0 + Vec3(0, 0, 1), p1 + Vec3(0, 0, 1), color)
            m.tri(Vec3(0, 0, 0), p1, p0, color)
    return m.node("cyl")


def cone(seg=8, color=(1, 1, 1, 1)):
    m = Mesh()
    for j in range(seg):
        a0, a1 = 2 * math.pi * j / seg, 2 * math.pi * (j + 1) / seg
        p0, p1 = Vec3(math.cos(a0), math.sin(a0), 0), Vec3(math.cos(a1), math.sin(a1), 0)
        m.tri(p0, p1, Vec3(0, 0, 1), color)
        m.tri(Vec3(0, 0, 0), p1, p0, color)
    return m.node("cone")


def box(color=(1, 1, 1, 1), top=None):
    """Куб от -0.5 до 0.5 по X/Y и от 0 до 1 по Z."""
    m = Mesh()
    top = top or color
    x0, x1, y0, y1 = -0.5, 0.5, -0.5, 0.5
    v = lambda x, y, z: Vec3(x, y, z)
    m.quad(v(x0, y0, 1), v(x1, y0, 1), v(x1, y1, 1), v(x0, y1, 1), top)
    m.quad(v(x0, y1, 0), v(x1, y1, 0), v(x1, y0, 0), v(x0, y0, 0), color)
    m.quad(v(x0, y0, 0), v(x1, y0, 0), v(x1, y0, 1), v(x0, y0, 1), color)
    m.quad(v(x1, y1, 0), v(x0, y1, 0), v(x0, y1, 1), v(x1, y1, 1), color)
    m.quad(v(x1, y0, 0), v(x1, y1, 0), v(x1, y1, 1), v(x1, y0, 1), color)
    m.quad(v(x0, y1, 0), v(x0, y0, 0), v(x0, y0, 1), v(x0, y1, 1), color)
    return m.node("box")


def torus(R, r, seg=24, tube=8, color=(1, 1, 1, 1)):
    m = Mesh()

    def p(i, j):
        a, b = 2 * math.pi * i / seg, 2 * math.pi * j / tube
        return Vec3((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b))
    for i in range(seg):
        for j in range(tube):
            m.quad(p(i, j), p(i + 1, j), p(i + 1, j + 1), p(i, j + 1), color)
    return m.node("torus")


def part(parent, proto, pos, scale, color, hpr=(0, 0, 0)):
    np = proto.copy_to(parent)
    np.set_pos(*pos)
    np.set_scale(*scale) if isinstance(scale, (tuple, list)) else np.set_scale(scale)
    np.set_hpr(*hpr)
    np.set_color(*color)
    return np


# ---------------------------------------------------------------- palette
C_WATER = (0.13, 0.55, 0.95, 1)
C_RIM = (0.36, 0.84, 0.80, 1)
C_RIM_DARK = (0.22, 0.62, 0.66, 1)
C_LIP = (0.86, 0.96, 1.0, 1)
C_CLIFF = (0.93, 0.47, 0.42, 1)
C_CLIFF_TOP = (0.98, 0.62, 0.52, 1)
C_CLIFF_DARK = (0.78, 0.36, 0.36, 1)
C_GRASS = (0.45, 0.72, 0.30, 1)
C_TRUNK = (0.55, 0.36, 0.22, 1)
C_ORANGE = (0.96, 0.45, 0.13, 1)
C_RAFT = (0.99, 0.85, 0.68, 1)
C_FLOOR = (0.50, 0.70, 0.34, 1)
C_FLOOR_LINE = (0.36, 0.55, 0.25, 1)
C_HANDLE = (0.80, 0.22, 0.18, 1)
C_GAS = (0.67, 0.92, 0.15, 1)
C_SKY = (0.80, 0.91, 0.98, 1)


def water_texture():
    """Голубая вода с белыми струями — текстура тайлится и прокручивается."""
    w, h = 128, 512
    img = PNMImage(w, h, 4)
    img.fill(C_WATER[0], C_WATER[1], C_WATER[2])
    img.alpha_fill(1)
    rnd = random.Random(3)
    for _ in range(14):
        x = rnd.randint(0, w - 1)
        y0 = rnd.randint(0, h - 1)
        ln = rnd.randint(180, 460)
        width = 1
        bright = rnd.uniform(0.45, 0.85)
        for k in range(ln):
            yy = (y0 + k) % h
            xx = int(x + 2 * math.sin((y0 + k) / 70.0)) % w
            fade = math.sin(math.pi * k / ln)
            for dx in range(width):
                c = img.get_xel((xx + dx) % w, yy)
                a = bright * fade
                img.set_xel((xx + dx) % w, yy, c[0] + (1 - c[0]) * a, c[1] + (1 - c[1]) * a, c[2] + (1 - c[2]) * a)
    tex = Texture("water")
    tex.load(img)
    tex.set_wrap_u(Texture.WM_repeat)
    tex.set_wrap_v(Texture.WM_repeat)
    tex.set_minfilter(Texture.FT_linear_mipmap_linear)
    tex.set_anisotropic_degree(4)
    return tex


# ---------------------------------------------------------------- track
def build_track(parent):
    step = 40
    s_vals = list(range(-1200, sim.TRACK_LEN + 2400, step))
    water = Mesh(uv=True)
    walls = Mesh()
    rail_h, lip_h, depth = 0.55, 0.06, 1.3
    for s0, s1 in zip(s_vals, s_vals[1:]):
        c0, c1 = sim.center_x(s0) / U, sim.center_x(s1) / U
        h0, h1 = sim.half_width(s0) / U, sim.half_width(s1) / U
        z0, z1 = track_z(s0), track_z(s1)
        y0, y1 = s0 / U, s1 / U
        L0, R0 = Vec3(c0 - h0, y0, z0), Vec3(c0 + h0, y0, z0)
        L1, R1 = Vec3(c1 - h1, y1, z1), Vec3(c1 + h1, y1, z1)
        v0, v1 = s0 / 700.0, s1 / 700.0
        water.quad(L0, R0, R1, L1, (1, 1, 1, 1), [(0, v0), (1.3, v0), (1.3, v1), (0, v1)], normal=Vec3(0, 0, 1))
        rail = sim.has_rail(s0)
        up = Vec3(0, 0, rail_h if rail else lip_h)
        out = 0.28 if rail else 0.12
        for side, A, B in ((-1, L0, L1), (1, R0, R1)):
            o = Vec3(side * out, 0, 0)
            top_col = C_RIM if rail else C_LIP
            # внутренняя стенка, верх бортика, внешняя стенка до низа жёлоба
            if side < 0:
                walls.quad(A + up, A, B, B + up, C_RIM_DARK if rail else C_LIP)
                walls.quad(A + up + o, A + up, B + up, B + up + o, top_col)
                walls.quad(A + o - Vec3(0, 0, depth), A + o + up, B + o + up, B + o - Vec3(0, 0, depth), C_RIM)
                walls.quad(A - Vec3(0, 0, depth), A + o - Vec3(0, 0, depth), B + o - Vec3(0, 0, depth), B - Vec3(0, 0, depth), C_RIM_DARK)
            else:
                walls.quad(A, A + up, B + up, B, C_RIM_DARK if rail else C_LIP)
                walls.quad(A + up, A + up + o, B + up + o, B + up, top_col)
                walls.quad(A + o + up, A + o - Vec3(0, 0, depth), B + o - Vec3(0, 0, depth), B + o + up, C_RIM)
                walls.quad(A + o - Vec3(0, 0, depth), A - Vec3(0, 0, depth), B - Vec3(0, 0, depth), B + o - Vec3(0, 0, depth), C_RIM_DARK)
        # днище жёлоба
        walls.quad(R0 - Vec3(0, 0, depth), L0 - Vec3(0, 0, depth), L1 - Vec3(0, 0, depth), R1 - Vec3(0, 0, depth), C_RIM_DARK)
    wnp = water.node("water")
    wnp.reparent_to(parent)
    wnp.set_texture(water_texture())
    walls.node("walls").reparent_to(parent)
    # опоры под горкой
    pillar = cylinder(10)
    for s in range(-600, sim.TRACK_LEN + 2000, 900):
        for side in (-0.55, 0.55):
            cx, hw = sim.center_x(s) / U, sim.half_width(s) / U
            p = part(parent, pillar, (cx + side * hw, s / U, track_z(s) - 30), (0.35, 0.35, 29), C_RIM_DARK)
    return wnp


def build_scenery(parent):
    """Коралловые скалы-столы, деревья и пол каньона внизу."""
    rnd = random.Random(11)
    rocks = Mesh()
    foliage = Mesh()
    unit_tree = None

    def add_box(m, cx, cy, z0, z1, sx, sy, col, top):
        x0, x1, y0, y1 = cx - sx, cx + sx, cy - sy, cy + sy
        v = Vec3
        m.quad(v(x0, y0, z1), v(x1, y0, z1), v(x1, y1, z1), v(x0, y1, z1), top)
        m.quad(v(x0, y0, z0), v(x1, y0, z0), v(x1, y0, z1), v(x0, y0, z1), col)
        m.quad(v(x1, y1, z0), v(x0, y1, z0), v(x0, y1, z1), v(x1, y1, z1), col)
        m.quad(v(x1, y0, z0), v(x1, y1, z0), v(x1, y1, z1), v(x1, y0, z1), C_CLIFF_DARK)
        m.quad(v(x0, y1, z0), v(x0, y0, z0), v(x0, y0, z1), v(x0, y1, z1), C_CLIFF_DARK)

    def add_tree(m, x, y, z, k):
        tr = 0.12 * k
        m.quad(Vec3(x - tr, y, z), Vec3(x + tr, y, z), Vec3(x + tr, y, z + 1.2 * k), Vec3(x - tr, y, z + 1.2 * k), C_TRUNK)
        m.quad(Vec3(x, y - tr, z), Vec3(x, y + tr, z), Vec3(x, y + tr, z + 1.2 * k), Vec3(x, y - tr, z + 1.2 * k), C_TRUNK)
        for dz, rr in ((1.2, 0.75), (1.75, 0.55)):
            cz = z + dz * k
            r = rr * k
            pts = [Vec3(x + r * math.cos(a * math.pi / 3), y + r * math.sin(a * math.pi / 3), cz) for a in range(6)]
            top = Vec3(x, y, cz + r * 0.9)
            bot = Vec3(x, y, cz - r * 0.6)
            g = (0.30 + rnd.random() * 0.1, 0.62 + rnd.random() * 0.1, 0.25, 1)
            for i in range(6):
                m.tri(pts[i], pts[(i + 1) % 6], top, g)
                m.tri(pts[(i + 1) % 6], pts[i], bot, (g[0] * 0.8, g[1] * 0.8, g[2] * 0.8, 1))

    for s in range(-1500, sim.TRACK_LEN + 3000, 260):
        for side in (-1, 1):
            if rnd.random() < 0.25:
                continue
            cx, hw = sim.center_x(s) / U, sim.half_width(s) / U
            sx, sy = rnd.uniform(1.0, 3.0), rnd.uniform(1.0, 2.6)
            dist = hw + 0.9 + sx + rnd.uniform(0, 9) ** 1.3
            x = cx + side * dist
            y = s / U + rnd.uniform(-1, 1)
            ztop = track_z(s) + (rnd.uniform(-7, 0.5) if dist < hw + 6 else rnd.uniform(-5, 7))
            add_box(rocks, x, y, track_z(s) - 40, ztop, sx, sy, C_CLIFF, C_CLIFF_TOP)
            if rnd.random() < 0.7:
                add_box(rocks, x, y, ztop, ztop + 0.15, sx * 0.98, sy * 0.98, C_GRASS, C_GRASS)
                for _ in range(rnd.randint(1, 3)):
                    add_tree(foliage, x + rnd.uniform(-sx, sx) * 0.7, y + rnd.uniform(-sy, sy) * 0.7,
                             ztop + 0.15, rnd.uniform(0.8, 1.6))
    rocks.node("rocks").reparent_to(parent)
    foliage.node("trees").reparent_to(parent)


# ---------------------------------------------------------------- raft & animals
ANIMAL_LOOK = {
    "frog": dict(body=(0.42, 0.72, 0.25, 1), belly=(0.80, 0.90, 0.45, 1)),
    "bear": dict(body=(0.20, 0.20, 0.23, 1), belly=(0.45, 0.42, 0.42, 1)),
    "hippo": dict(body=(0.22, 0.38, 0.55, 1), belly=(0.85, 0.40, 0.42, 1)),
    "monkey": dict(body=(0.88, 0.52, 0.27, 1), belly=(0.98, 0.78, 0.55, 1)),
}


class Protos:
    def __init__(self):
        self.sphere = sphere(6, 10)
        self.sphere_hi = sphere(10, 18)
        self.cyl = cylinder(14)
        self.cone = cone(7)
        self.box = box()


def build_raft(parent, P):
    raft = parent.attach_new_node("raft")
    t = torus(0.62, 0.15, 28, 8, C_RAFT)
    t.reparent_to(raft)
    t.set_z(0.12)
    band = torus(0.64, 0.12, 28, 6, C_RIM)
    band.reparent_to(raft)
    band.set_z(0.0)
    part(raft, P.cyl, (0, 0, 0.02), (0.56, 0.56, 0.08), C_FLOOR)
    for k in range(-3, 4):
        part(raft, P.box, (k * 0.15, 0, 0.1), (0.012, 1.0 * math.sqrt(max(0.05, 1 - (k * 0.15 / 0.56) ** 2)), 0.01), C_FLOOR_LINE)
    for i in range(4):
        a = math.pi / 4 + i * math.pi / 2
        part(raft, P.box, (math.cos(a) * 0.66, math.sin(a) * 0.66, 0.2), (0.09, 0.16, 0.12), C_HANDLE,
             hpr=(math.degrees(a), 0, 0))
    return raft


def build_animal(parent, P, kind):
    """Зверь сидит на краю плота: +Y смотрит в центр плота, спиной (и попой) наружу."""
    look = ANIMAL_LOOK[kind]
    body, belly = look["body"], look["belly"]
    a = parent.attach_new_node(kind)
    s = 1.0
    if kind == "hippo":
        s = 1.1
    elif kind == "monkey":
        s = 0.95
    # туловище
    part(a, P.sphere_hi, (0, 0, 0.30), (0.20 * s, 0.17 * s, 0.24 * s), body)
    part(a, P.sphere, (0, 0.07, 0.25), (0.15 * s, 0.11 * s, 0.17 * s), belly)
    # попа и ноги свисают с бортика
    part(a, P.sphere, (0, -0.10, 0.18), (0.19 * s, 0.13 * s, 0.13 * s), body)
    for sx in (-1, 1):
        part(a, P.sphere, (sx * 0.12 * s, -0.08, 0.04), (0.07, 0.09, 0.07), body)
        # руки держатся за бортик
        part(a, P.sphere, (sx * 0.19 * s, 0.12, 0.30), (0.06, 0.13, 0.06), body, hpr=(0, 30, 0))
    hz = 0.56 * s
    if kind == "frog":
        part(a, P.sphere_hi, (0, 0.08, hz), (0.17, 0.15, 0.12), body)
        part(a, P.sphere, (0, 0.17, hz - 0.03), (0.14, 0.06, 0.06), belly)
        for sx in (-1, 1):
            part(a, P.sphere, (sx * 0.09, 0.10, hz + 0.09), (0.065, 0.065, 0.065), body)
            part(a, P.sphere, (sx * 0.09, 0.15, hz + 0.10), (0.04, 0.03, 0.04), (1, 1, 1, 1))
            part(a, P.sphere, (sx * 0.09, 0.175, hz + 0.10), (0.02, 0.012, 0.02), (0.05, 0.05, 0.05, 1))
    elif kind == "bear":
        part(a, P.sphere_hi, (0, 0.06, hz), (0.15, 0.14, 0.14), body)
        part(a, P.sphere, (0, 0.18, hz - 0.03), (0.07, 0.06, 0.05), belly)
        part(a, P.sphere, (0, 0.235, hz - 0.01), (0.025, 0.02, 0.02), (0.05, 0.05, 0.05, 1))
        for sx in (-1, 1):
            part(a, P.sphere, (sx * 0.11, 0.03, hz + 0.12), (0.05, 0.03, 0.05), body)
            part(a, P.sphere, (sx * 0.06, 0.18, hz + 0.04), (0.025, 0.015, 0.025), (1, 1, 1, 1))
    elif kind == "hippo":
        part(a, P.sphere_hi, (0, 0.08, hz), (0.16, 0.15, 0.13), body)
        part(a, P.sphere_hi, (0, 0.20, hz - 0.04), (0.13, 0.09, 0.08), body)
        for sx in (-1, 1):
            part(a, P.sphere, (sx * 0.05, 0.285, hz - 0.02), (0.02, 0.01, 0.015), (0.08, 0.1, 0.15, 1))
            part(a, P.sphere, (sx * 0.1, 0.03, hz + 0.11), (0.035, 0.025, 0.04), body)
            part(a, P.sphere, (sx * 0.07, 0.17, hz + 0.08), (0.03, 0.02, 0.03), (1, 1, 1, 1))
    else:  # monkey
        part(a, P.sphere_hi, (0, 0.06, hz), (0.15, 0.14, 0.14), body)
        part(a, P.sphere, (0, 0.14, hz - 0.01), (0.11, 0.06, 0.09), belly)
        for sx in (-1, 1):
            part(a, P.sphere, (sx * 0.15, 0.04, hz + 0.02), (0.02, 0.06, 0.06), belly)
            part(a, P.sphere, (sx * 0.05, 0.19, hz + 0.03), (0.025, 0.012, 0.025), (0.05, 0.05, 0.05, 1))
        # хвост
        part(a, P.cyl, (0, -0.20, 0.18), (0.025, 0.025, 0.25), body, hpr=(0, 60, 0))
    return a


# ---------------------------------------------------------------- obstacles
def build_hammer(parent, P, ob):
    root = parent.attach_new_node("hammer")
    s = ob.s
    cx, hw = sim.center_x(s) / U, sim.half_width(s) / U
    z = track_z(s)
    root.set_pos(cx, s / U, z)
    top = 3.6
    for side in (-1, 1):
        part(root, P.box, (side * (hw + 0.6), 0, -1.2), (0.6, 0.6, top + 1.6), C_CLIFF, )
        part(root, P.box, (side * (hw + 0.6), 0, top + 0.4), (0.7, 0.7, 0.12), C_CLIFF_TOP)
    part(root, P.cyl, (-(hw + 0.6), 0, top), (0.2, 0.2, 2 * (hw + 0.6)), C_ORANGE, hpr=(0, 0, 90))
    pivot = root.attach_new_node("pivot")
    pivot.set_z(top)
    L = top - 0.45
    part(pivot, P.cyl, (0, 0, -L), (0.1, 0.1, L), C_ORANGE)
    head = pivot.attach_new_node("head")
    head.set_z(-L)
    part(head, P.cyl, (0, -0.55, 0), (0.45, 0.45, 1.1), C_RIM, hpr=(0, -90, 0))
    for e in (-0.56, 0.56):
        part(head, P.cyl, (0, e - 0.02, 0), (0.33, 0.33, 0.04), C_ORANGE, hpr=(0, -90, 0))
    return root, pivot, L


def build_spinner(parent, P, ob):
    root = parent.attach_new_node("spinner")
    s = ob.s
    root.set_pos(sim.center_x(s) / U, s / U, track_z(s))
    part(root, P.cyl, (0, 0, -0.5), (0.18, 0.18, 0.95), (0.45, 0.45, 0.52, 1))
    rot = root.attach_new_node("rot")
    rot.set_z(0.3)
    L = ob.half_len() / U
    part(rot, P.box, (0, 0, -0.1), (2 * L, 0.22, 0.2), (0.85, 0.30, 0.75, 1))
    n = int(L * 4)
    for i in range(-n, n + 1):
        x = i / n * L * 0.95
        for d in (-1, 1):
            part(rot, P.cone, (x, d * 0.1, 0), (0.06, 0.06, 0.16), (1, 1, 1, 1), hpr=(0, -d * 90, 0))
    return root, rot


def build_mine(parent, P):
    root = parent.attach_new_node("mine")
    part(root, P.sphere_hi, (0, 0, 0), (0.42, 0.42, 0.38), (0.80, 0.18, 0.22, 1))
    part(root, P.cyl, (0, 0, -0.05), (0.47, 0.47, 0.1), C_RIM)
    for i in range(7):
        a = i * 2 * math.pi / 7
        part(root, P.cone, (math.cos(a) * 0.3, math.sin(a) * 0.3, 0.18), (0.07, 0.07, 0.2), (1, 1, 1, 1),
             hpr=(math.degrees(a) - 90, -40, 0))
    part(root, P.cone, (0, 0, 0.34), (0.07, 0.07, 0.2), (1, 1, 1, 1))
    return root


def build_finish(parent, P, font):
    from panda3d.core import TextNode
    s = sim.TRACK_LEN
    cx, hw = sim.center_x(s) / U, sim.half_width(s) / U
    root = parent.attach_new_node("finish")
    root.set_pos(cx, s / U, track_z(s))
    for side in (-1, 1):
        part(root, P.box, (side * (hw + 0.3), 0, -1), (0.35, 0.35, 5.6), (0.85, 0.62, 0.30, 1))
        part(root, P.box, (side * (hw + 0.3), 0, 4.6), (0.5, 0.5, 0.25), (0.35, 0.65, 0.30, 1))
    part(root, P.box, (0, 0, 3.6), (2 * hw + 1.2, 0.3, 0.9), (0.98, 0.78, 0.25, 1))
    part(root, P.box, (0, -0.05, 3.75), (3.2, 0.32, 0.62), (0.35, 0.65, 0.30, 1))
    tn = TextNode("finish_txt")
    tn.set_text("FINISH")
    if font:
        tn.set_font(font)
    tn.set_align(TextNode.A_center)
    tn.set_text_color(0.98, 0.85, 0.3, 1)
    tn.set_shadow(0.05, 0.05)
    tn.set_shadow_color(0.5, 0.2, 0.1, 1)
    t = root.attach_new_node(tn)
    t.set_pos(0, -0.25, 3.82)
    t.set_scale(0.5)
    t.set_two_sided(True)
    # шашечки на воде
    sq = 0.5
    n = int(2 * hw / sq)
    for i in range(n):
        for j in range(2):
            col = (1, 1, 1, 1) if (i + j) % 2 == 0 else (0.1, 0.1, 0.12, 1)
            part(root, P.box, (-hw + (i + 0.5) * sq, (j - 0.5) * sq, 0.005), (sq, sq, 0.01), col)
    return root


def build_checkpoint(parent, P, s):
    cx, hw = sim.center_x(s) / U, sim.half_width(s) / U
    root = parent.attach_new_node("cp")
    root.set_pos(cx, s / U, track_z(s))
    flags = []
    for side in (-1, 1):
        part(root, P.cyl, (side * (hw + 0.2), 0, 0), (0.06, 0.06, 1.6), (0.9, 0.9, 0.95, 1))
        f = part(root, P.box, (side * (hw + 0.2) - side * 0.25, 0, 1.3), (0.5, 0.04, 0.3), (1, 1, 1, 1))
        flags.append(f)
    line = part(root, P.box, (0, 0, 0.005), (2 * hw, 0.12, 0.01), (1, 1, 1, 0.8))
    return root, flags + [line]
