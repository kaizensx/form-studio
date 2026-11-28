"""Lithophane or relief, made by Form Studio's lithophane generator: a picture as a height field on a framed plate.

A lithophane (invert = 1) is thick where the picture is dark, so held to the light it shows the picture; a relief
(invert = 0) stands high where the picture is bright. MAKE holds the picture as a grid of grey levels (rows from the
top, 0 = black), the file name and the SHA-256 of the file it was read from; the picture itself is not stored.

The surface is a mesh body: a closed height field with one planar triangle between neighbouring samples, exact at
every sample, so what prints is the picture as sampled. Being a mesh, it is exported as STL and 3MF and never as
STEP. (A bicubic B-spline through the same grid rings between the samples of a sharp-edged picture, by several per
cent of the volume, and tessellates slowly; a picture is better served by its samples.)"""
from build123d import Align, Solid

from form import makers
from form.recipes.base import Feature, Param, Recipe, RecipeError, Stage

BOTTOM = (Align.CENTER, Align.CENTER, Align.MIN)

MAKE = {
    'generator': 'lithophane',
    'picture': 'rings (built in)',
    'sha256': '',
    'grid': [40, 30],
    'pixels': ('eNqNVM9L+mAY3w83p1N0DCY2GrFIFBwaaIxAMQbWujQQwUZ0GOlhl2KRIEhCOxQFIRIEtYuEXfJQdLBDHvIWHeyyY4c8CR66eQu+'
        '89s/8L639+XzfJ7P87yf55l8fbzcXdbKBSkV5ZggSeCYy4XhBBlkuGhKKpRrl3cvH1+T78/X+2ZtT8km+FDAgyEw9P/ACOYJhPhE'
        'VtmrNe9fP7/tt4erelnJxDmaxJAZAkYQeIZGMJLm4hmlXL96eLPfn29P9EI2Pk8RqANCccJLkl4CRx0oSlDz8WxBP7l9fu93Loxt'
        'KcFRhEOGun0UE2bZMEP53E4YQlBcQto2Ljr9x+u6tpniaQcGO4lYPiYkk0KMZx0ZsAOk+dSmVr9+7JzvFzPREIlCMO4P8YKYy8ty'
        'PicKfMiPwxBKhqKZ4v555+ZY21jmAhgEYf5wJC0pqlapaKoipSNh/+w1wC1vaMc3zcNSNsp4kFlkRJRVvdowzUZVV2UxMsuCeJho'
        'tnTYPNW3VhaCGAS7aT4t7xpmy2q3rZZp7MppnnbDEBZcWNnSTxvaemKOdOh8rCCpxpnV7fX7va51ZqiSwPocQnIusa41ajtrMYaA'
        'IZziRUU3rafB0LaHgyfL1BWRp3AIJpjY2k7tqJRZov9uObXa6g7s0Xg8sgfdVlXN/THQS5nSkVFcXaQced6wkNcaVm84+plOf0bD'
        'ntXQ8kLY6wikFleLxkFB5IMuRwWblCtmu2+Pp7+/07Hdb5sVOck6yl1BXiwcgOJA84LWAdoX0D6D/huoD0B9BepTUN+DzhHoXILO'
        'OejemADuoX+9X0xk'),
}


class Design(Recipe):
    title, summary = "Lithophane", "A picture as a height field on a framed plate: a lithophane or a relief."
    category, tags = "Makers", ("lithophane", "relief", "picture")
    params = [
        Param("width", "Width", 100, 20, 170, 1, "mm", "brief", "surface", "The picture's width; its height follows "
              "the picture's proportions."),
        Param("min_t", "Thinnest", 0.8, 0.4, 4, 0.1, "mm", "form", "surface",
              "Where the picture is brightest (lithophane) or darkest (relief). 0.8 mm lets light through PLA."),
        Param("max_t", "Thickest", 3.0, 1.2, 10, 0.1, "mm", "form", "surface",
              "Where the picture is darkest (lithophane) or brightest (relief). 3 mm stops most light."),
        Param("invert", "Lithophane", 1, 0, 1, 1, "", "form", "surface", "1 = dark is thick (a lithophane); 0 = bright is "
              "high (a relief)."),
        Param("frame", "Frame width", 4, 0, 12, 0.5, "mm", "form", "frame", "0 = no frame."),
        Param("frame_t", "Frame thickness", 4, 1.6, 12, 0.1, "mm", "form", "frame",
              "At least 0.4 mm above the thickest point of the picture."),
    ]
    features = [Feature("surface", "Picture surface (mesh body)", "finish"), Feature("frame", "Frame", "structure")]

    def constraints(self, v):
        if v["max_t"] <= v["min_t"] + 0.2:
            return [RecipeError("The thickest point must be at least 0.2 mm above the thinnest", "surface",
                                "Raise the thickest or lower the thinnest.", ["min_t", "max_t"])]
        if v["frame"] > 0 and v["frame_t"] < v["max_t"] + 0.4:
            return [RecipeError("The frame must stand at least 0.4 mm above the thickest point", "frame",
                                "Make the frame thicker, or the picture thinner.", ["frame_t", "max_t"])]
        return []

    def _grid(self, v):
        nx, ny, data = makers.decode_grid(MAKE)
        W = v["width"]
        pitch = W / (nx - 1)
        D = pitch * (ny - 1)
        lo, hi = v["min_t"], v["max_t"]
        z = []
        for j in range(ny):
            row = []
            for i in range(nx):
                g = data[j * nx + i] / 255.0
                f = (1 - g) if v["invert"] >= 0.5 else g
                row.append(lo + (hi - lo) * f)
            z.append(row)
        return nx, ny, W, D, pitch, z

    @staticmethod
    def height_field(xs, ys, Z):
        """A closed mesh body over a tensor grid: the top through the heights Z (rows along ys, columns along xs), a
        wall down every edge and the flat bottom, one planar face per triangle."""
        import numpy as np
        from form.recipes.meshsolid import solid_from_mesh
        nx, ny = len(xs), len(ys)
        X, Y = np.meshgrid(np.asarray(xs, float), np.asarray(ys, float))
        V = np.vstack([np.stack([X, Y, Z], -1).reshape(-1, 3), np.stack([X, Y, np.zeros_like(X)], -1).reshape(-1, 3)])
        n = nx * ny
        idx = np.arange(n).reshape(ny, nx)
        a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
        F = [np.stack([a, d, c], 1), np.stack([a, c, b], 1), np.stack([a + n, b + n, c + n], 1),
             np.stack([a + n, c + n, d + n], 1)]
        ring = np.array(list(idx[0, :]) + list(idx[1:, -1]) + list(idx[-1, -2::-1]) + list(idx[-2:0:-1, 0]))
        q = np.roll(ring, -1)
        F += [np.stack([ring, q, q + n], 1), np.stack([ring, q + n, ring + n], 1)]
        s = solid_from_mesh(V, np.vstack(F))
        return s if s.volume > 0 else Solid(s.wrapped.Reversed())

    def _body(self, v, framed: bool):
        import numpy as np
        nx, ny, W, D, pitch, z = self._grid(v)
        xs = list(-W / 2 + np.arange(nx) * pitch)
        ys = list(D / 2 - np.arange(ny) * pitch)        # picture rows run from the top
        Z = np.array(z, dtype=float)
        if framed and v["frame"] > 0:
            # the frame is part of the same height field: its top all round, its inner edge 0.3 mm outside the picture,
            # so picture and frame are one closed mesh and no boolean is needed
            f, e = v["frame"], min(0.3, v["frame"] / 2)
            xs = [-W / 2 - f, -W / 2 - e] + xs + [W / 2 + e, W / 2 + f]
            ys = [D / 2 + f, D / 2 + e] + ys + [-D / 2 - e, -D / 2 - f]
            Z = np.pad(Z, 2, constant_values=v["frame_t"])
        return self.height_field(xs, ys, Z)

    def build(self, v):
        return [Stage("surface", self._body(v, False)), Stage("frame", self._body(v, True))]

    def derived(self, v):
        nx, ny, W, D, pitch, z = self._grid(v)
        return [{"key": "picture_height", "label": "Picture height", "value": round(D, 2), "unit": "mm",
                 "feature": "surface", "formula": "width x (rows - 1) / (columns - 1) of the picture grid", "interface": False},
                {"key": "sample_pitch", "label": "Sample spacing", "value": round(pitch, 3), "unit": "mm",
                 "feature": "surface", "formula": f"width / ({nx} - 1) grid columns", "interface": False},
                {"key": "grid_points", "label": "Height samples", "value": nx * ny, "unit": "", "feature": "surface",
                 "formula": f"{nx} x {ny} grey levels from the picture: a mesh body, exact at each sample, planar "
                            "between them (never written to STEP)", "interface": False}]
