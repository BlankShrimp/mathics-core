# -*- coding: utf-8 -*-
# cython: language_level=3

"""
Drawing Graphics
"""


from math import floor, sin, cos, pi, sqrt, atan2, radians, exp

from mathics.version import __version__  # noqa used in loading to check consistency.

from mathics.builtin.base import (
    Builtin,
    InstanceableBuiltin,
    BoxConstructError,
)
from mathics.builtin.options import options_to_rules
from mathics.core.expression import (
    Expression,
    Integer,
    Rational,
    Real,
    String,
    Symbol,
    SymbolList,
    SymbolN,
    SymbolMakeBoxes,
    system_symbols,
    system_symbols_dict,
    from_python,
)

from mathics.builtin.drawing.colors import convert as convert_color
from mathics.core.formatter import lookup_method
from mathics.core.numbers import machine_epsilon
from mathics.format.asy_fns import asy_bezier


GRAPHICS_OPTIONS = {
    "AspectRatio": "Automatic",
    "Axes": "False",
    "AxesStyle": "{}",
    "Background": "Automatic",
    "ImageSize": "Automatic",
    "LabelStyle": "{}",
    "PlotRange": "Automatic",
    "PlotRangePadding": "Automatic",
    "TicksStyle": "{}",
    "$OptionSyntax": "Ignore",
}

# faction of point relative canvas width
DEFAULT_POINT_FACTOR = 0.005

class CoordinatesError(BoxConstructError):
    pass


class ColorError(BoxConstructError):
    pass


def get_class(name):
    from mathics.builtin.box.graphics3d import GLOBALS3D

    c = GLOBALS.get(name)
    if c is None:
        return GLOBALS3D.get(name)
    else:
        return c

    # globals() does not work with Cython, otherwise one could use something
    # like return globals().get(name)


def coords(value):
    if value.has_form("List", 2):
        x, y = value.leaves[0].round_to_float(), value.leaves[1].round_to_float()
        if x is None or y is None:
            raise CoordinatesError
        return (x, y)
    raise CoordinatesError


class Coords(object):
    def __init__(self, graphics, expr=None, pos=None, d=None):
        self.graphics = graphics
        self.p = pos
        self.d = d
        if expr is not None:
            if expr.has_form("Offset", 1, 2):
                self.d = coords(expr.leaves[0])
                if len(expr.leaves) > 1:
                    self.p = coords(expr.leaves[1])
                else:
                    self.p = None
            else:
                self.p = coords(expr)

    def pos(self):
        p = self.graphics.translate(self.p)
        p = (cut(p[0]), cut(p[1]))
        if self.d is not None:
            d = self.graphics.translate_absolute(self.d)
            return (p[0] + d[0], p[1] + d[1])
        return p

    def add(self, x, y):
        p = (self.p[0] + x, self.p[1] + y)
        return Coords(self.graphics, pos=p, d=self.d)


def cut(value):
    "Cut values in graphics primitives (not displayed otherwise in SVG)"
    border = 10 ** 8
    if value < -border:
        value = -border
    elif value > border:
        value = border
    return value


def create_css(
    edge_color=None, face_color=None, stroke_width=None, font_color=None, opacity=1.0
):
    css = []
    if edge_color is not None:
        color, stroke_opacity = edge_color.to_css()
        css.append("stroke: %s" % color)
        css.append("stroke-opacity: %s" % stroke_opacity)
    else:
        css.append("stroke: none")
    if stroke_width is not None:
        css.append("stroke-width: %fpx" % stroke_width)
    if face_color is not None:
        color, fill_opacity = face_color.to_css()
        css.append("fill: %s" % color)
        css.append("fill-opacity: %s" % fill_opacity)
    else:
        css.append("fill: none")
    if font_color is not None:
        color, _ = font_color.to_css()
        css.append("color: %s" % color)
    css.append("opacity: %s" % opacity)
    return "; ".join(css)


def _to_float(x):
    x = x.round_to_float()
    if x is None:
        raise BoxConstructError
    return x


def _data_and_options(leaves, defined_options):
    data = []
    options = defined_options.copy()
    for leaf in leaves:
        if leaf.get_head_name() == "System`Rule":
            if len(leaf.leaves) != 2:
                raise BoxConstructError
            name, value = leaf.leaves
            name_head = name.get_head_name()
            if name_head == "System`Symbol":
                py_name = name.get_name()
            elif name_head == "System`String":
                py_name = "System`" + name.get_string_value()
            else:  # unsupported name type
                raise BoxConstructError
            options[py_name] = value
        else:
            data.append(leaf)
    return data, options


def _euclidean_distance(a, b):
    return sqrt(sum((x1 - x2) * (x1 - x2) for x1, x2 in zip(a, b)))


def _component_distance(a, b, i):
    return abs(a[i] - b[i])


def _cie2000_distance(lab1, lab2):
    # reference: https://en.wikipedia.org/wiki/Color_difference#CIEDE2000
    e = machine_epsilon
    kL = kC = kH = 1  # common values

    L1, L2 = lab1[0], lab2[0]
    a1, a2 = lab1[1], lab2[1]
    b1, b2 = lab1[2], lab2[2]

    dL = L2 - L1
    Lm = (L1 + L2) / 2
    C1 = sqrt(a1 ** 2 + b1 ** 2)
    C2 = sqrt(a2 ** 2 + b2 ** 2)
    Cm = (C1 + C2) / 2

    a1 = a1 * (1 + (1 - sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7))) / 2)
    a2 = a2 * (1 + (1 - sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7))) / 2)

    C1 = sqrt(a1 ** 2 + b1 ** 2)
    C2 = sqrt(a2 ** 2 + b2 ** 2)
    Cm = (C1 + C2) / 2
    dC = C2 - C1

    h1 = (180 * atan2(b1, a1 + e)) / pi % 360
    h2 = (180 * atan2(b2, a2 + e)) / pi % 360
    if abs(h2 - h1) <= 180:
        dh = h2 - h1
    elif abs(h2 - h1) > 180 and h2 <= h1:
        dh = h2 - h1 + 360
    elif abs(h2 - h1) > 180 and h2 > h1:
        dh = h2 - h1 - 360

    dH = 2 * sqrt(C1 * C2) * sin(radians(dh) / 2)

    Hm = (h1 + h2) / 2 if abs(h2 - h1) <= 180 else (h1 + h2 + 360) / 2
    T = (
        1
        - 0.17 * cos(radians(Hm - 30))
        + 0.24 * cos(radians(2 * Hm))
        + 0.32 * cos(radians(3 * Hm + 6))
        - 0.2 * cos(radians(4 * Hm - 63))
    )

    SL = 1 + (0.015 * (Lm - 50) ** 2) / sqrt(20 + (Lm - 50) ** 2)
    SC = 1 + 0.045 * Cm
    SH = 1 + 0.015 * Cm * T

    rT = (
        -2
        * sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7))
        * sin(radians(60 * exp(-((Hm - 275) ** 2 / 25 ** 2))))
    )
    return sqrt(
        (dL / (SL * kL)) ** 2
        + (dC / (SC * kC)) ** 2
        + (dH / (SH * kH)) ** 2
        + rT * (dC / (SC * kC)) * (dH / (SH * kH))
    )


def _CMC_distance(lab1, lab2, l, c):
    # reference https://en.wikipedia.org/wiki/Color_difference#CMC_l:c_.281984.29
    L1, L2 = lab1[0], lab2[0]
    a1, a2 = lab1[1], lab2[1]
    b1, b2 = lab1[2], lab2[2]

    dL, da, db = L2 - L1, a2 - a1, b2 - b1
    e = machine_epsilon

    C1 = sqrt(a1 ** 2 + b1 ** 2)
    C2 = sqrt(a2 ** 2 + b2 ** 2)

    h1 = (180 * atan2(b1, a1 + e)) / pi % 360
    dC = C2 - C1
    dH2 = da ** 2 + db ** 2 - dC ** 2
    F = C1 ** 2 / sqrt(C1 ** 4 + 1900)
    T = (
        0.56 + abs(0.2 * cos(radians(h1 + 168)))
        if (164 <= h1 and h1 <= 345)
        else 0.36 + abs(0.4 * cos(radians(h1 + 35)))
    )

    SL = 0.511 if L1 < 16 else (0.040975 * L1) / (1 + 0.01765 * L1)
    SC = (0.0638 * C1) / (1 + 0.0131 * C1) + 0.638
    SH = SC * (F * T + 1 - F)
    return sqrt((dL / (l * SL)) ** 2 + (dC / (c * SC)) ** 2 + dH2 / SH ** 2)


def _extract_graphics(graphics, format, evaluation):
    graphics_box = Expression(SymbolMakeBoxes, graphics).evaluate(evaluation)
    # builtin = GraphicsBox(expression=False)
    elements, calc_dimensions = graphics_box._prepare_elements(
        graphics_box.leaves, {"evaluation": evaluation}, neg_y=True
    )
    xmin, xmax, ymin, ymax, _, _, _, _ = calc_dimensions()

    # xmin, xmax have always been moved to 0 here. the untransformed
    # and unscaled bounds are found in elements.xmin, elements.ymin,
    # elements.extent_width, elements.extent_height.

    # now compute the position of origin (0, 0) in the transformed
    # coordinate space.

    ex = elements.extent_width
    ey = elements.extent_height

    sx = (xmax - xmin) / ex
    sy = (ymax - ymin) / ey

    ox = -elements.xmin * sx + xmin
    oy = -elements.ymin * sy + ymin

    # generate code for svg or asy.

    if format in ("asy", "svg"):
        format_fn = lookup_method(elements, format)
        code = format_fn(elements)
    else:
        raise NotImplementedError

    return xmin, xmax, ymin, ymax, ox, oy, ex, ey, code


class Show(Builtin):
    """
    <dl>
      <dt>'Show[$graphics$, $options$]'
      <dd>shows graphics with the specified options added.
    </dl>
    """

    options = GRAPHICS_OPTIONS

    def apply(self, graphics, evaluation, options):
        """Show[graphics_, OptionsPattern[%(name)s]]"""

        for option in options:
            if option not in ("System`ImageSize",):
                options[option] = Expression(SymbolN, options[option]).evaluate(
                    evaluation
                )

        # The below could probably be done with graphics.filter..
        new_leaves = []
        options_set = set(options.keys())
        for leaf in graphics.leaves:
            leaf_name = leaf.get_head_name()
            if leaf_name == "System`Rule" and str(leaf.leaves[0]) in options_set:
                continue
            new_leaves.append(leaf)

        new_leaves += options_to_rules(options)
        graphics = graphics.restructure(graphics.head, new_leaves, evaluation)

        return graphics


class Graphics(Builtin):
    r"""
    <dl>
      <dt>'Graphics[$primitives$, $options$]'
      <dd>represents a graphic.
    </dl>

    Options include:

    <ul>
      <li>Axes
      <li>TicksStyle
      <li>AxesStyle
      <li>LabelStyle
      <li>AspectRatio
      <li>PlotRange
      <li>PlotRangePadding
      <li>ImageSize
      <li>Background
    </ul>

    >> Graphics[{Blue, Line[{{0,0}, {1,1}}]}]
     = -Graphics-

    'Graphics' supports 'PlotRange':
    >> Graphics[{Rectangle[{1, 1}]}, Axes -> True, PlotRange -> {{-2, 1.5}, {-1, 1.5}}]
     = -Graphics-

    >> Graphics[{Rectangle[],Red,Disk[{1,0}]},PlotRange->{{0,1},{0,1}}]
     = -Graphics-

    'Graphics' produces 'GraphicsBox' boxes:
    >> Graphics[Rectangle[]] // ToBoxes // Head
     = GraphicsBox

    In 'TeXForm', 'Graphics' produces Asymptote figures:
    >> Graphics[Circle[]] // TeXForm
     = #<--#
     . \begin{asy}
     . usepackage("amsmath");
     . size(5.8556cm, 5.8333cm);
     . draw(ellipse((175,175),175,175), rgb(0, 0, 0)+linewidth(0.66667));
     . clip(box((-0.33333,0.33333), (350.33,349.67)));
     . \end{asy}
    """

    options = GRAPHICS_OPTIONS

    box_suffix = "Box"

    def apply_makeboxes(self, content, evaluation, options):
        """MakeBoxes[%(name)s[content_, OptionsPattern[%(name)s]],
        StandardForm|TraditionalForm|OutputForm]"""

        def convert(content):
            head = content.get_head_name()

            if head == "System`List":
                return Expression(
                    SymbolList, *[convert(item) for item in content.leaves]
                )
            elif head == "System`Style":
                return Expression(
                    "StyleBox", *[convert(item) for item in content.leaves]
                )

            if head in element_heads:
                if head == "System`Text":
                    head = "System`Inset"
                atoms = content.get_atoms(include_heads=False)
                if any(
                    not isinstance(atom, (Integer, Real))
                    and not atom.get_name() in GRAPHICS_SYMBOLS
                    for atom in atoms
                ):
                    if head == "System`Inset":
                        inset = content.leaves[0]
                        if inset.get_head_name() == "System`Graphics":
                            opts = {}
                            # opts = dict(opt._leaves[0].name:opt_leaves[1]   for opt in  inset._leaves[1:])
                            inset = self.apply_makeboxes(
                                inset._leaves[0], evaluation, opts
                            )
                        n_leaves = [inset] + [
                            Expression(SymbolN, leaf).evaluate(evaluation)
                            for leaf in content.leaves[1:]
                        ]
                    else:
                        n_leaves = (
                            Expression(SymbolN, leaf).evaluate(evaluation)
                            for leaf in content.leaves
                        )
                else:
                    n_leaves = content.leaves
                return Expression(head + self.box_suffix, *n_leaves)
            return content

        for option in options:
            if option not in ("System`ImageSize",):
                options[option] = Expression(SymbolN, options[option]).evaluate(
                    evaluation
                )

        from mathics.builtin.box.graphics import GraphicsBox
        from mathics.builtin.box.graphics3d import Graphics3DBox
        from mathics.builtin.drawing.graphics3d import Graphics3D

        if type(self) is Graphics:
            return GraphicsBox(
                convert(content), evaluation=evaluation, *options_to_rules(options)
            )
        elif type(self) is Graphics3D:
            return Graphics3DBox(
                convert(content), evaluation=evaluation, *options_to_rules(options)
            )


class _GraphicsElement(InstanceableBuiltin):
    def init(self, graphics, item=None, style=None, opacity=1.0):
        if item is not None and not item.has_form(self.get_name(), None):
            raise BoxConstructError
        self.graphics = graphics
        self.style = style
        self.opacity = opacity
        self.is_completely_visible = False  # True for axis elements

    @staticmethod
    def create_as_style(klass, graphics, item):
        return klass(graphics, item)


class _Color(_GraphicsElement):
    formats = {
        # we are adding ImageSizeMultipliers in the rule below, because we do _not_ want color boxes to
        # diminish in size when they appear in lists or rows. we only want the display of colors this
        # way in the notebook, so we restrict the rule to StandardForm.
        (
            ("StandardForm",),
            "%(name)s[x__?(NumericQ[#] && 0 <= # <= 1&)]",
        ): "Style[Graphics[{EdgeForm[Black], %(name)s[x], Rectangle[]}, ImageSize -> 16], "
        + "ImageSizeMultipliers -> {1, 1}]"
    }

    rules = {"%(name)s[x_List]": "Apply[%(name)s, x]"}

    components_sizes = []
    default_components = []

    def init(self, item=None, components=None):
        super(_Color, self).init(None, item)
        if item is not None:
            leaves = item.leaves
            if len(leaves) in self.components_sizes:
                # we must not clip here; we copy the components, without clipping,
                # e.g. RGBColor[-1, 0, 0] stays RGBColor[-1, 0, 0]. this is especially
                # important for color spaces like LAB that have negative components.

                components = [value.round_to_float() for value in leaves]
                if None in components:
                    raise ColorError

                # the following lines always extend to the maximum available
                # default_components, so RGBColor[0, 0, 0] will _always_
                # become RGBColor[0, 0, 0, 1]. does not seem the right thing
                # to do in this general context. poke1024

                if len(components) < 3:
                    components.extend(self.default_components[len(components) :])

                self.components = components
            else:
                raise ColorError
        elif components is not None:
            self.components = components

    @staticmethod
    def create(expr):
        head = expr.get_head_name()
        cls = get_class(head)
        if cls is None:
            raise ColorError
        return cls(expr)

    @staticmethod
    def create_as_style(klass, graphics, item):
        return klass(item)

    def to_css(self):
        rgba = self.to_rgba()
        alpha = rgba[3] if len(rgba) > 3 else 1.0
        return (
            r"rgb(%f%%, %f%%, %f%%)" % (rgba[0] * 100, rgba[1] * 100, rgba[2] * 100),
            alpha,
        )

    def to_js(self):
        return self.to_rgba()

    def to_expr(self):
        return Expression(self.get_name(), *self.components)

    def to_rgba(self):
        return self.to_color_space("RGB")

    def to_color_space(self, color_space):
        components = convert_color(self.components, self.color_space, color_space)
        if components is None:
            raise ValueError(
                "cannot convert from color space %s to %s."
                % (self.color_space, color_space)
            )
        return components


class RGBColor(_Color):
    """
    <dl>
    <dt>'RGBColor[$r$, $g$, $b$]'
        <dd>represents a color with the specified red, green and blue
        components.
    </dl>

    >> Graphics[MapIndexed[{RGBColor @@ #1, Disk[2*#2 ~Join~ {0}]} &, IdentityMatrix[3]], ImageSize->Small]
     = -Graphics-

    >> RGBColor[0, 1, 0]
     = RGBColor[0, 1, 0]

    >> RGBColor[0, 1, 0] // ToBoxes
     = StyleBox[GraphicsBox[...], ...]
    """

    color_space = "RGB"
    components_sizes = [3, 4]
    default_components = [0, 0, 0, 1]

    def to_rgba(self):
        return self.components


class LABColor(_Color):
    """
    <dl>
    <dt>'LABColor[$l$, $a$, $b$]'
        <dd>represents a color with the specified lightness, red/green and yellow/blue
        components in the CIE 1976 L*a*b* (CIELAB) color space.
    </dl>
    """

    color_space = "LAB"
    components_sizes = [3, 4]
    default_components = [0, 0, 0, 1]


class LCHColor(_Color):
    """
    <dl>
    <dt>'LCHColor[$l$, $c$, $h$]'
        <dd>represents a color with the specified lightness, chroma and hue
        components in the CIELCh CIELab cube color space.
    </dl>
    """

    color_space = "LCH"
    components_sizes = [3, 4]
    default_components = [0, 0, 0, 1]


class LUVColor(_Color):
    """
    <dl>
    <dt>'LCHColor[$l$, $u$, $v$]'
        <dd>represents a color with the specified components in the CIE 1976 L*u*v* (CIELUV) color space.
    </dl>
    """

    color_space = "LUV"
    components_sizes = [3, 4]
    default_components = [0, 0, 0, 1]


class XYZColor(_Color):
    """
    <dl>
    <dt>'XYZColor[$x$, $y$, $z$]'
        <dd>represents a color with the specified components in the CIE 1931 XYZ color space.
    </dl>
    """

    color_space = "XYZ"
    components_sizes = [3, 4]
    default_components = [0, 0, 0, 1]


class CMYKColor(_Color):
    """
    <dl>
    <dt>'CMYKColor[$c$, $m$, $y$, $k$]'
        <dd>represents a color with the specified cyan, magenta,
        yellow and black components.
    </dl>

    >> Graphics[MapIndexed[{CMYKColor @@ #1, Disk[2*#2 ~Join~ {0}]} &, IdentityMatrix[4]], ImageSize->Small]
     = -Graphics-
    """

    color_space = "CMYK"
    components_sizes = [3, 4, 5]
    default_components = [0, 0, 0, 0, 1]


class Hue(_Color):
    """
    <dl>
    <dt>'Hue[$h$, $s$, $l$, $a$]'
        <dd>represents the color with hue $h$, saturation $s$,
        lightness $l$ and opacity $a$.
    <dt>'Hue[$h$, $s$, $l$]'
        <dd>is equivalent to 'Hue[$h$, $s$, $l$, 1]'.
    <dt>'Hue[$h$, $s$]'
        <dd>is equivalent to 'Hue[$h$, $s$, 1, 1]'.
    <dt>'Hue[$h$]'
        <dd>is equivalent to 'Hue[$h$, 1, 1, 1]'.
    </dl>
    >> Graphics[Table[{EdgeForm[Gray], Hue[h, s], Disk[{12h, 8s}]}, {h, 0, 1, 1/6}, {s, 0, 1, 1/4}]]
     = -Graphics-

    >> Graphics[Table[{EdgeForm[{GrayLevel[0, 0.5]}], Hue[(-11+q+10r)/72, 1, 1, 0.6], Disk[(8-r) {Cos[2Pi q/12], Sin[2Pi q/12]}, (8-r)/3]}, {r, 6}, {q, 12}]]
     = -Graphics-
    """

    color_space = "HSB"
    components_sizes = [1, 2, 3, 4]
    default_components = [0, 1, 1, 1]

    def hsl_to_rgba(self):
        h, s, l = self.components[:3]
        if l < 0.5:
            q = l * (1 + s)
        else:
            q = l + s - l * s
        p = 2 * l - q

        rgb = (h + 1 / 3, h, h - 1 / 3)

        def map(value):
            if value < 0:
                value += 1
            if value > 1:
                value -= 1
            return value

        def trans(t):
            if t < 1 / 6:
                return p + ((q - p) * 6 * t)
            elif t < 1 / 2:
                return q
            elif t < 2 / 3:
                return p + ((q - p) * 6 * (2 / 3 - t))
            else:
                return p

        result = tuple([trans(list(map(t))) for t in rgb]) + (self.components[3],)
        return result


class GrayLevel(_Color):
    """
    <dl>
    <dt>'GrayLevel[$g$]'
        <dd>represents a shade of gray specified by $g$, ranging from
        0 (black) to 1 (white).
    <dt>'GrayLevel[$g$, $a$]'
        <dd>represents a shade of gray specified by $g$ with opacity $a$.
    </dl>
    """

    color_space = "Grayscale"
    components_sizes = [1, 2]
    default_components = [0, 1]


def expression_to_color(color):
    try:
        return _Color.create(color)
    except ColorError:
        return None


def color_to_expression(components, colorspace):
    if colorspace == "Grayscale":
        converted_color_name = "GrayLevel"
    elif colorspace == "HSB":
        converted_color_name = "Hue"
    else:
        converted_color_name = colorspace + "Color"

    return Expression(converted_color_name, *components)


class ColorDistance(Builtin):
    """
    <dl>
    <dt>'ColorDistance[$c1$, $c2$]'
        <dd>returns a measure of color distance between the colors $c1$ and $c2$.
    <dt>'ColorDistance[$list$, $c2$]'
        <dd>returns a list of color distances between the colors in $list$ and $c2$.
    </dl>

    The option DistanceFunction specifies the method used to measure the color
    distance. Available options are:

    CIE76: euclidean distance in the LABColor space
    CIE94: euclidean distance in the LCHColor space
    CIE2000 or CIEDE2000: CIE94 distance with corrections
    CMC: Colour Measurement Committee metric (1984)
    DeltaL: difference in the L component of LCHColor
    DeltaC: difference in the C component of LCHColor
    DeltaH: difference in the H component of LCHColor

    It is also possible to specify a custom distance

    >> ColorDistance[Magenta, Green]
     = 2.2507
    >> ColorDistance[{Red, Blue}, {Green, Yellow}, DistanceFunction -> {"CMC", "Perceptibility"}]
     = {1.0495, 1.27455}
    #> ColorDistance[Blue, Red, DistanceFunction -> "CIE2000"]
     = 0.557976
    #> ColorDistance[Red, Black, DistanceFunction -> (Abs[#1[[1]] - #2[[1]]] &)]
     = 0.542917

    """

    options = {"DistanceFunction": "Automatic"}

    requires = ("numpy",)

    messages = {
        "invdist": "`1` is not Automatic or a valid distance specification.",
        "invarg": "`1` and `2` should be two colors or a color and a lists of colors or "
        + "two lists of colors of the same length.",
    }

    # If numpy is not installed, 100 * c1.to_color_space returns
    # a list of 100 x 3 elements, instead of doing elementwise multiplication
    requires = ("numpy",)

    # the docs say LABColor's colorspace corresponds to the CIE 1976 L^* a^* b^* color space
    # with {l,a,b}={L^*,a^*,b^*}/100. Corrections factors are put accordingly.

    _distances = {
        "CIE76": lambda c1, c2: _euclidean_distance(
            c1.to_color_space("LAB")[:3], c2.to_color_space("LAB")[:3]
        ),
        "CIE94": lambda c1, c2: _euclidean_distance(
            c1.to_color_space("LCH")[:3], c2.to_color_space("LCH")[:3]
        ),
        "CIE2000": lambda c1, c2: _cie2000_distance(
            100 * c1.to_color_space("LAB")[:3], 100 * c2.to_color_space("LAB")[:3]
        )
        / 100,
        "CIEDE2000": lambda c1, c2: _cie2000_distance(
            100 * c1.to_color_space("LAB")[:3], 100 * c2.to_color_space("LAB")[:3]
        )
        / 100,
        "DeltaL": lambda c1, c2: _component_distance(
            c1.to_color_space("LCH"), c2.to_color_space("LCH"), 0
        ),
        "DeltaC": lambda c1, c2: _component_distance(
            c1.to_color_space("LCH"), c2.to_color_space("LCH"), 1
        ),
        "DeltaH": lambda c1, c2: _component_distance(
            c1.to_color_space("LCH"), c2.to_color_space("LCH"), 2
        ),
        "CMC": lambda c1, c2: _CMC_distance(
            100 * c1.to_color_space("LAB")[:3], 100 * c2.to_color_space("LAB")[:3], 1, 1
        )
        / 100,
    }

    def apply(self, c1, c2, evaluation, options):
        "ColorDistance[c1_, c2_, OptionsPattern[ColorDistance]]"

        distance_function = options.get("System`DistanceFunction")
        compute = None
        if isinstance(distance_function, String):
            compute = ColorDistance._distances.get(distance_function.get_string_value())
            if not compute:
                evaluation.message("ColorDistance", "invdist", distance_function)
                return
        elif distance_function.has_form("List", 2):
            if distance_function.leaves[0].get_string_value() == "CMC":
                if distance_function.leaves[1].get_string_value() == "Acceptability":
                    compute = (
                        lambda c1, c2: _CMC_distance(
                            100 * c1.to_color_space("LAB")[:3],
                            100 * c2.to_color_space("LAB")[:3],
                            2,
                            1,
                        )
                        / 100
                    )
                elif distance_function.leaves[1].get_string_value() == "Perceptibility":
                    compute = ColorDistance._distances.get("CMC")

                elif distance_function.leaves[1].has_form("List", 2):
                    if isinstance(
                        distance_function.leaves[1].leaves[0], Integer
                    ) and isinstance(distance_function.leaves[1].leaves[1], Integer):
                        if (
                            distance_function.leaves[1].leaves[0].get_int_value() > 0
                            and distance_function.leaves[1].leaves[1].get_int_value()
                            > 0
                        ):
                            lightness = (
                                distance_function.leaves[1].leaves[0].get_int_value()
                            )
                            chroma = (
                                distance_function.leaves[1].leaves[1].get_int_value()
                            )
                            compute = (
                                lambda c1, c2: _CMC_distance(
                                    100 * c1.to_color_space("LAB")[:3],
                                    100 * c2.to_color_space("LAB")[:3],
                                    lightness,
                                    chroma,
                                )
                                / 100
                            )

        elif (
            isinstance(distance_function, Symbol)
            and distance_function.get_name() == "System`Automatic"
        ):
            compute = ColorDistance._distances.get("CIE76")
        else:

            def compute(a, b):
                return Expression(
                    "Apply",
                    distance_function,
                    Expression(
                        "List",
                        Expression(
                            "List", *[Real(val) for val in a.to_color_space("LAB")]
                        ),
                        Expression(
                            "List", *[Real(val) for val in b.to_color_space("LAB")]
                        ),
                    ),
                )

        if compute == None:
            evaluation.message("ColorDistance", "invdist", distance_function)
            return

        def distance(a, b):
            try:
                py_a = _Color.create(a)
                py_b = _Color.create(b)
            except ColorError:
                evaluation.message("ColorDistance", "invarg", a, b)
                raise
            result = from_python(compute(py_a, py_b))
            return result

        try:
            if c1.get_head_name() == "System`List":
                if c2.get_head_name() == "System`List":
                    if len(c1.leaves) != len(c2.leaves):
                        evaluation.message("ColorDistance", "invarg", c1, c2)
                        return
                    else:
                        return Expression(
                            "List",
                            *[distance(a, b) for a, b in zip(c1.leaves, c2.leaves)],
                        )
                else:
                    return Expression(SymbolList, *[distance(c, c2) for c in c1.leaves])
            elif c2.get_head_name() == "System`List":
                return Expression(SymbolList, *[distance(c1, c) for c in c2.leaves])
            else:
                return distance(c1, c2)
        except ColorError:
            return
        except NotImplementedError:
            evaluation.message("ColorDistance", "invdist", distance_function)
            return


class _Size(_GraphicsElement):
    def init(self, graphics, item=None, value=None):
        super(_Size, self).init(graphics, item)
        if item is not None:
            self.value = item.leaves[0].round_to_float()
        elif value is not None:
            self.value = value
        else:
            raise BoxConstructError
        if self.value < 0:
            raise BoxConstructError


class _Thickness(_Size):
    pass


class AbsoluteThickness(_Thickness):
    """
    <dl>
    <dt>'AbsoluteThickness[$p$]'
        <dd>sets the line thickness for subsequent graphics primitives
        to $p$ points.
    </dl>

    >> Graphics[Table[{AbsoluteThickness[t], Line[{{20 t, 10}, {20 t, 80}}], Text[ToString[t]<>"pt", {20 t, 0}]}, {t, 0, 10}]]
     = -Graphics-
    """

    def get_thickness(self):
        return self.graphics.translate_absolute((self.value, 0))[0]


class Thickness(_Thickness):
    """
    <dl>
    <dt>'Thickness[$t$]'
        <dd>sets the line thickness for subsequent graphics primitives
        to $t$ times the size of the plot area.
    </dl>

    >> Graphics[{Thickness[0.2], Line[{{0, 0}, {0, 5}}]}, Axes->True, PlotRange->{{-5, 5}, {-5, 5}}]
     = -Graphics-
    """

    def get_thickness(self):
        return self.graphics.translate_relative(self.value)


class Thin(Builtin):
    """
    <dl>
    <dt>'Thin'
        <dd>sets the line width for subsequent graphics primitives to 0.5pt.
    </dl>
    """

    rules = {"Thin": "AbsoluteThickness[0.5]"}


class Thick(Builtin):
    """
    <dl>
    <dt>'Thick'
        <dd>sets the line width for subsequent graphics primitives to 2pt.
    </dl>
    """

    rules = {"Thick": "AbsoluteThickness[2]"}


class PointSize(_Size):
    """
    <dl>
      <dt>'PointSize[$t$]'
      <dd>sets the diameter of points to $t$, which is relative to the overall width.
    </dl>
    'PointSize' can be used for both two- and three-dimensional graphics. The initial default pointsize is 0.008 for two-dimensional graphics and 0.01 for three-dimensional graphics.

    >> Table[Graphics[{PointSize[r], Point[{0, 0}]}], {r, {0.02, 0.05, 0.1, 0.3}}]
     = {-Graphics-, -Graphics-, -Graphics-, -Graphics-}

    >> Table[Graphics3D[{PointSize[r], Point[{0, 0, 0}]}], {r, {0.05, 0.1, 0.8}}]
    = {-Graphics3D-, -Graphics3D-, -Graphics3D-}
    """

    def get_absolute_size(self):
        if self.graphics.view_width is None:
            self.graphics.view_width = 400
        if self.value is None:
            self.value = DEFAULT_POINT_FACTOR
        return self.graphics.view_width * self.value


class FontColor(Builtin):
    """
    <dl>
    <dt>'FontColor'
        <dd>is an option for Style to set the font color.
    </dl>
    """

    pass


class Offset(Builtin):
    pass


class Rectangle(Builtin):
    """
    <dl>
    <dt>'Rectangle[{$xmin$, $ymin$}]'
        <dd>represents a unit square with bottom-left corner at {$xmin$, $ymin$}.
    <dt>'Rectangle[{$xmin$, $ymin$}, {$xmax$, $ymax$}]
        <dd>is a rectange extending from {$xmin$, $ymin$} to {$xmax$, $ymax$}.
    </dl>

    >> Graphics[Rectangle[]]
     = -Graphics-

    >> Graphics[{Blue, Rectangle[{0.5, 0}], Orange, Rectangle[{0, 0.5}]}]
     = -Graphics-
    """

    rules = {"Rectangle[]": "Rectangle[{0, 0}]"}


class Disk(Builtin):
    """
    <dl>
    <dt>'Disk[{$cx$, $cy$}, $r$]'
        <dd>fills a circle with center '($cx$, $cy$)' and radius $r$.
    <dt>'Disk[{$cx$, $cy$}, {$rx$, $ry$}]'
        <dd>fills an ellipse.
    <dt>'Disk[{$cx$, $cy$}]'
        <dd>chooses radius 1.
    <dt>'Disk[]'
        <dd>chooses center '(0, 0)' and radius 1.
    <dt>'Disk[{$x$, $y$}, ..., {$t1$, $t2$}]'
        <dd>is a sector from angle $t1$ to $t2$.
    </dl>

    >> Graphics[{Blue, Disk[{0, 0}, {2, 1}]}]
     = -Graphics-
    The outer border can be drawn using 'EdgeForm':
    >> Graphics[{EdgeForm[Black], Red, Disk[]}]
     = -Graphics-

    Disk can also draw sectors of circles and ellipses
    >> Graphics[Disk[{0, 0}, 1, {Pi / 3, 2 Pi / 3}]]
     = -Graphics-
    >> Graphics[{Blue, Disk[{0, 0}, {1, 2}, {Pi / 3, 5 Pi / 3}]}]
     = -Graphics-
    """

    rules = {"Disk[]": "Disk[{0, 0}]"}


class Circle(Builtin):
    """
    <dl>
      <dt>'Circle[{$cx$, $cy$}, $r$]'
      <dd>draws a circle with center '($cx$, $cy$)' and radius $r$.

      <dt>'Circle[{$cx$, $cy$}, {$rx$, $ry$}]'
      <dd>draws an ellipse.

      <dt>'Circle[{$cx$, $cy$}]'
      <dd>chooses radius 1.

      <dt>'Circle[]'
      <dd>chooses center '(0, 0)' and radius 1.
    </dl>

    >> Graphics[{Red, Circle[{0, 0}, {2, 1}]}]
     = -Graphics-
    >> Graphics[{Circle[], Disk[{0, 0}, {1, 1}, {0, 2.1}]}]
     = -Graphics-

    Target practice:
    >> Graphics[Circle[], Axes-> True]
     = -Graphics-
    """

    rules = {"Circle[]": "Circle[{0, 0}]"}


class Inset(Builtin):
    pass


class Text(Inset):
    """
    <dl>
    <dt>'Text["$text$", {$x$, $y$}]'
        <dd>draws $text$ centered on position '{$x$, $y$}'.
    </dl>

    >> Graphics[{Text["First", {0, 0}], Text["Second", {1, 1}]}, Axes->True, PlotRange->{{-2, 2}, {-2, 2}}]
     = -Graphics-

    #> Graphics[{Text[x, {0,0}]}]
     = -Graphics-
    """


class _Polyline(_GraphicsElement):
    def do_init(self, graphics, points):
        if not points.has_form("List", None):
            raise BoxConstructError
        if (
            points.leaves
            and points.leaves[0].has_form("List", None)
            and all(leaf.has_form("List", None) for leaf in points.leaves[0].leaves)
        ):
            leaves = points.leaves
            self.multi_parts = True
        else:
            leaves = [Expression(SymbolList, *points.leaves)]
            self.multi_parts = False
        lines = []
        for leaf in leaves:
            if leaf.has_form("List", None):
                lines.append(leaf.leaves)
            else:
                raise BoxConstructError
        self.lines = [
            [graphics.coords(graphics, point) for point in line] for line in lines
        ]

    def extent(self):
        l = self.style.get_line_width(face_element=False)
        result = []
        for line in self.lines:
            for c in line:
                x, y = c.pos()
                result.extend(
                    [(x - l, y - l), (x - l, y + l), (x + l, y - l), (x + l, y + l)]
                )
        return result


class Point(Builtin):
    """
    <dl>
    <dt>'Point[{$point_1$, $point_2$ ...}]'
        <dd>represents the point primitive.
    <dt>'Point[{{$p_11$, $p_12$, ...}, {$p_21$, $p_22$, ...}, ...}]'
        <dd>represents a number of point primitives.
    </dl>

    Points are rendered if possible as circular regions. Their diameters can be specified using 'PointSize'.

    Points can be specified as {$x$, $y$}:

    >> Graphics[Point[{0, 0}]]
    = -Graphics-

    >> Graphics[Point[Table[{Sin[t], Cos[t]}, {t, 0, 2. Pi, Pi / 15.}]]]
    = -Graphics-

    or as {$x$, $y$, $z$}:

    >> Graphics3D[{Orange, PointSize[0.05], Point[Table[{Sin[t], Cos[t], 0}, {t, 0, 2 Pi, Pi / 15.}]]}]
     = -Graphics3D-

    """

    pass


# FIXME: We model points as line segments which
# is kind of  wrong.
class Line(Builtin):
    """
    <dl>
    <dt>'Line[{$point_1$, $point_2$ ...}]'
        <dd>represents the line primitive.
    <dt>'Line[{{$p_11$, $p_12$, ...}, {$p_21$, $p_22$, ...}, ...}]'
        <dd>represents a number of line primitives.
    </dl>

    >> Graphics[Line[{{0,1},{0,0},{1,0},{1,1}}]]
    = -Graphics-

    >> Graphics3D[Line[{{0,0,0},{0,1,1},{1,0,0}}]]
    = -Graphics3D-
    """

    pass


def _svg_bezier(*segments):
    # see https://www.w3.org/TR/SVG/paths.html#PathDataCubicBezierCommands
    # see https://docs.webplatform.org/wiki/svg/tutorials/smarter_svg_shapes

    while segments and not segments[0][1]:
        segments = segments[1:]

    if not segments:
        return

    forms = "LQC"  # SVG commands for line, quadratic bezier, cubic bezier

    def path(max_degree, p):
        max_degree = min(max_degree, len(forms))
        while p:
            n = min(max_degree, len(p))  # 1, 2, or 3
            if n < 1:
                raise BoxConstructError
            yield forms[n - 1] + " ".join("%f,%f" % xy for xy in p[:n])
            p = p[n:]

    k, p = segments[0]
    yield "M%f,%f" % p[0]

    for s in path(k, p[1:]):
        yield s

    for k, p in segments[1:]:
        for s in path(k, p):
            yield s


# For a more generic implementation in Python using scipi,
# sympy and numpy, see:
#  https://github.com/Tarheel-Formal-Methods/kaa
class BernsteinBasis(Builtin):
    """
    <dl>
      <dt>'BernsteinBasis[$d$,$n$,$x$]'
      <dd>returns the $n$th Bernstein basis of degree $d$ at $x$.
    </dl>

    A Bernstein polynomial is a polynomial that is a linear combination of Bernstein basis polynomials.

    With the advent of computer graphics, Bernstein polynomials, restricted to the interval [0, 1], became important in the form of Bézier curves.

    'BernsteinBasis[d,n,x]' equals 'Binomial[d, n] x^n (1-x)^(d-n)' in the interval [0, 1] and zero elsewhere.

    >> BernsteinBasis[4, 3, 0.5]
     = 0.25
    """
    attributes = ("Listable", "NumericFunction", "Protected")
    rules = {
        "BernsteinBasis[d_, n_, x_]": "Piecewise[{{Binomial[d, n] * x ^ n * (1 - x) ^ (d - n), 0 < x < 1}}, 0]"
    }


class BezierFunction(Builtin):
    rules = {
        "BezierFunction[p_]": "Function[x, Total[p * BernsteinBasis[Length[p] - 1, Range[0, Length[p] - 1], x]]]"
    }


class BezierCurve(Builtin):
    """
    <dl>
    <dt>'BezierCurve[{$p1$, $p2$ ...}]'
        <dd>represents a bezier curve with $p1$, $p2$ as control points.
    </dl>

    >> Graphics[BezierCurve[{{0, 0},{1, 1},{2, -1},{3, 0}}]]
     = -Graphics-

    >> Module[{p={{0, 0},{1, 1},{2, -1},{4, 0}}}, Graphics[{BezierCurve[p], Red, Point[Table[BezierFunction[p][x], {x, 0, 1, 0.1}]]}]]
     = -Graphics-
    """

    options = {"SplineDegree": "3"}


class FilledCurve(Builtin):
    """
    <dl>
    <dt>'FilledCurve[{$segment1$, $segment2$ ...}]'
        <dd>represents a filled curve.
    </dl>

    >> Graphics[FilledCurve[{Line[{{0, 0}, {1, 1}, {2, 0}}]}]]
    = -Graphics-

    >> Graphics[FilledCurve[{BezierCurve[{{0, 0}, {1, 1}, {2, 0}}], Line[{{3, 0}, {0, 2}}]}]]
    = -Graphics-
    """

    pass


class Polygon(Builtin):
    """
    <dl>
      <dt>'Polygon[{$point_1$, $point_2$ ...}]'
      <dd>represents the filled polygon primitive.

      <dt>'Polygon[{{$p_11$, $p_12$, ...}, {$p_21$, $p_22$, ...}, ...}]'
      <dd>represents a number of filled polygon primitives.
    </dl>

    A Right Triangle:
    >> Graphics[Polygon[{{1,0},{0,0},{0,1}}]]
    = -Graphics-

    Notice that there is a line connecting from the last point to the first one.

    A point is an element of the polygon if a ray from the point in any direction in the plane crosses the boundary line segments an odd number of times.
    >> Graphics[Polygon[{{150,0},{121,90},{198,35},{102,35},{179,90}}]]
    = -Graphics-

    >> Graphics3D[Polygon[{{0,0,0},{0,1,1},{1,0,0}}]]
    = -Graphics3D-
    """

    pass


class RegularPolygon(Builtin):
    """
    <dl>
    <dt>'RegularPolygon[$n$]'
        <dd>gives the regular polygon with $n$ edges.
    <dt>'RegularPolygon[$r$, $n$]'
        <dd>gives the regular polygon with $n$ edges and radius $r$.
    <dt>'RegularPolygon[{$r$, $phi$}, $n$]'
        <dd>gives the regular polygon with radius $r$ with one vertex drawn at angle $phi$.
    <dt>'RegularPolygon[{$x, $y}, $r$, $n$]'
        <dd>gives the regular polygon centered at the position {$x, $y}.
    </dl>

    >> Graphics[RegularPolygon[5]]
    = -Graphics-

    >> Graphics[{Yellow, Rectangle[], Orange, RegularPolygon[{1, 1}, {0.25, 0}, 3]}]
    = -Graphics-
    """


class Arrow(Builtin):
    """
    <dl>
    <dt>'Arrow[{$p1$, $p2$}]'
        <dd>represents a line from $p1$ to $p2$ that ends with an arrow at $p2$.
    <dt>'Arrow[{$p1$, $p2$}, $s$]'
        <dd>represents a line with arrow that keeps a distance of $s$ from $p1$
        and $p2$.
    <dt>'Arrow[{$point_1$, $point_2$}, {$s1$, $s2$}]'
        <dd>represents a line with arrow that keeps a distance of $s1$ from $p1$
        and a distance of $s2$ from $p2$.
    </dl>

    >> Graphics[Arrow[{{0,0}, {1,1}}]]
    = -Graphics-

    >> Graphics[{Circle[], Arrow[{{2, 1}, {0, 0}}, 1]}]
    = -Graphics-

    Keeping distances may happen across multiple segments:

    >> Table[Graphics[{Circle[], Arrow[Table[{Cos[phi],Sin[phi]},{phi,0,2*Pi,Pi/2}],{d, d}]}],{d,0,2,0.5}]
     = {-Graphics-, -Graphics-, -Graphics-, -Graphics-, -Graphics-}
    """

    pass


class Arrowheads(_GraphicsElement):
    """
    <dl>
    <dt>'Arrowheads[$s$]'
        <dd>specifies that Arrow[] draws one arrow of size $s$ (relative to width of image, defaults to 0.04).
    <dt>'Arrowheads[{$spec1$, $spec2$, ..., $specn$}]'
        <dd>specifies that Arrow[] draws n arrows as defined by $spec1$, $spec2$, ... $specn$.
    <dt>'Arrowheads[{{$s$}}]'
        <dd>specifies that one arrow of size $s$ should be drawn.
    <dt>'Arrowheads[{{$s$, $pos$}}]'
        <dd>specifies that one arrow of size $s$ should be drawn at position $pos$ (for the arrow to
        be on the line, $pos$ has to be between 0, i.e. the start for the line, and 1, i.e. the end
        of the line).
    <dt>'Arrowheads[{{$s$, $pos$, $g$}}]'
        <dd>specifies that one arrow of size $s$ should be drawn at position $pos$ using Graphics $g$.
    </dl>

    Arrows on both ends can be achieved using negative sizes:

    >> Graphics[{Circle[],Arrowheads[{-0.04, 0.04}], Arrow[{{0, 0}, {2, 2}}, {1,1}]}]
     = -Graphics-

    You may also specify our own arrow shapes:

    >> Graphics[{Circle[], Arrowheads[{{0.04, 1, Graphics[{Red, Disk[]}]}}], Arrow[{{0, 0}, {Cos[Pi/3],Sin[Pi/3]}}]}]
     = -Graphics-

    >> Graphics[{Arrowheads[Table[{0.04, i/10, Graphics[Disk[]]},{i,1,10}]], Arrow[{{0, 0}, {6, 5}, {1, -3}, {-2, 2}}]}]
     = -Graphics-
    """

    default_size = 0.04

    symbolic_sizes = {
        "System`Tiny": 3,
        "System`Small": 5,
        "System`Medium": 9,
        "System`Large": 18,
    }

    def init(self, graphics, item=None):
        super(Arrowheads, self).init(graphics, item)
        if len(item.leaves) != 1:
            raise BoxConstructError
        self.spec = item.leaves[0]

    def _arrow_size(self, s, extent):
        if isinstance(s, Symbol):
            size = self.symbolic_sizes.get(s.get_name(), 0)
            return self.graphics.translate_absolute((size, 0))[0]
        else:
            return _to_float(s) * extent

    def heads(self, extent, default_arrow, custom_arrow):
        # see https://reference.wolfram.com/language/ref/Arrowheads.html

        if self.spec.get_head_name() == "System`List":
            leaves = self.spec.leaves
            if all(x.get_head_name() == "System`List" for x in leaves):
                for head in leaves:
                    spec = head.leaves
                    if len(spec) not in (2, 3):
                        raise BoxConstructError
                    size_spec = spec[0]
                    if (
                        isinstance(size_spec, Symbol)
                        and size_spec.get_name() == "System`Automatic"
                    ):
                        s = self.default_size * extent
                    elif size_spec.is_numeric():
                        s = self._arrow_size(size_spec, extent)
                    else:
                        raise BoxConstructError

                    if len(spec) == 3 and custom_arrow:
                        graphics = spec[2]
                        if graphics.get_head_name() != "System`Graphics":
                            raise BoxConstructError
                        arrow = custom_arrow(graphics)
                    else:
                        arrow = default_arrow

                    if not isinstance(spec[1], (Real, Rational, Integer)):
                        raise BoxConstructError

                    yield s, _to_float(spec[1]), arrow
            else:
                n = max(1.0, len(leaves) - 1.0)
                for i, head in enumerate(leaves):
                    yield self._arrow_size(head, extent), i / n, default_arrow
        else:
            yield self._arrow_size(self.spec, extent), 1, default_arrow


def _norm(p, q):
    px, py = p
    qx, qy = q

    dx = qx - px
    dy = qy - py

    length = sqrt(dx * dx + dy * dy)
    return dx, dy, length


class _Line:
    def make_draw_svg(self, style):
        def draw(points):
            yield '<polyline points="'
            yield " ".join("%f,%f" % xy for xy in points)
            yield '" style="%s" />' % style

        return draw

    def make_draw_asy(self, pen):
        def draw(points):
            yield "draw("
            yield "--".join(["(%.5g,%5g)" % xy for xy in points])
            yield ", % s);" % pen

        return draw

    def arrows(self, points, heads):  # heads has to be sorted by pos
        def segments(points):
            for i in range(len(points) - 1):
                px, py = points[i]
                dx, dy, dl = _norm((px, py), points[i + 1])
                yield dl, px, py, dx, dy

        seg = list(segments(points))

        if not seg:
            return

        i = 0
        t0 = 0.0
        n = len(seg)
        dl, px, py, dx, dy = seg[i]
        total = sum(segment[0] for segment in seg)

        for s, t, draw in ((s, pos * total - t0, draw) for s, pos, draw in heads):
            if s == 0.0:  # ignore zero-sized arrows
                continue

            if i < n:  # not yet past last segment?
                while t > dl:  # position past current segment?
                    t -= dl
                    t0 += dl
                    i += 1
                    if i == n:
                        px += dx  # move to last segment's end
                        py += dy
                        break
                    else:
                        dl, px, py, dx, dy = seg[i]

            for shape in draw(px, py, dx / dl, dy / dl, t, s):
                yield shape


def _bezier_derivative(p):
    # see http://pomax.github.io/bezierinfo/, Section 12 Derivatives
    n = len(p[0]) - 1
    return [[n * (x1 - x0) for x1, x0 in zip(w, w[1:])] for w in p]


def _bezier_evaluate(p, t):
    # see http://pomax.github.io/bezierinfo/, Section 4 Controlling Bezier Curvatures
    n = len(p[0]) - 1
    if n == 3:
        t2 = t * t
        t3 = t2 * t
        mt = 1 - t
        mt2 = mt * mt
        mt3 = mt2 * mt
        return [
            w[0] * mt3 + 3 * w[1] * mt2 * t + 3 * w[2] * mt * t2 + w[3] * t3 for w in p
        ]
    elif n == 2:
        t2 = t * t
        mt = 1 - t
        mt2 = mt * mt
        return [w[0] * mt2 + w[1] * 2 * mt * t + w[2] * t2 for w in p]
    elif n == 1:
        mt = 1 - t
        return [w[0] * mt + w[1] * t for w in p]
    else:
        raise ValueError("cannot compute bezier curve of order %d" % n)


class _BezierCurve:
    def __init__(self, spline_degree=3):
        self.spline_degree = spline_degree

    def make_draw_svg(self, style):
        def draw(points):
            s = " ".join(_svg_bezier((self.spline_degree, points)))
            yield '<path d="%s" style="%s"/>' % (s, style)

        return draw

    def make_draw_asy(self, pen):
        def draw(points):
            for path in asy_bezier((self.spline_degree, points)):
                yield "draw(%s, %s);" % (path, pen)

        return draw

    def arrows(self, points, heads):  # heads has to be sorted by pos
        if len(points) < 2:
            return

        # FIXME combined curves

        cp = list(zip(*points))
        if len(points) >= 3:
            dcp = _bezier_derivative(cp)
        else:
            dcp = cp

        for s, t, draw in heads:
            if s == 0.0:  # ignore zero-sized arrows
                continue

            px, py = _bezier_evaluate(cp, t)

            tx, ty = _bezier_evaluate(dcp, t)
            tl = -sqrt(tx * tx + ty * ty)
            tx /= tl
            ty /= tl

            for shape in draw(px, py, tx, ty, 0.0, s):
                yield shape


def total_extent(extents):
    xmin = xmax = ymin = ymax = None
    for extent in extents:
        for x, y in extent:
            if xmin is None or x < xmin:
                xmin = x
            if xmax is None or x > xmax:
                xmax = x
            if ymin is None or y < ymin:
                ymin = y
            if ymax is None or y > ymax:
                ymax = y
    return xmin, xmax, ymin, ymax


class EdgeForm(Builtin):
    """
    >> Graphics[{EdgeForm[{Thick, Green}], Disk[]}]
     = -Graphics-

    >> Graphics[{Style[Disk[],EdgeForm[{Thick,Red}]], Circle[{1,1}]}]
     = -Graphics-
    """

    pass


class FaceForm(Builtin):
    pass


def _style(graphics, item):
    head = item.get_head_name()
    if head in style_heads:
        klass = get_class(head)
        style = klass.create_as_style(klass, graphics, item)
    elif head in ("System`EdgeForm", "System`FaceForm"):
        style = graphics.get_style_class()(
            graphics, edge=head == "System`EdgeForm", face=head == "System`FaceForm"
        )
        if len(item.leaves) > 1:
            raise BoxConstructError
        if item.leaves:
            if item.leaves[0].has_form("List", None):
                for dir in item.leaves[0].leaves:
                    style.append(dir, allow_forms=False)
            else:
                style.append(item.leaves[0], allow_forms=False)
    else:
        raise BoxConstructError
    return style


class Style(object):
    def __init__(self, graphics, edge=False, face=False):
        self.styles = []
        self.options = {}
        self.graphics = graphics
        self.edge = edge
        self.face = face
        self.klass = graphics.get_style_class()

    def append(self, item, allow_forms=True):
        self.styles.append(_style(self.graphics, item))

    def set_option(self, name, value):
        self.options[name] = value

    def extend(self, style, pre=True):
        if pre:
            self.styles = style.styles + self.styles
        else:
            self.styles.extend(style.styles)

    def clone(self):
        result = self.klass(self.graphics, edge=self.edge, face=self.face)
        result.styles = self.styles[:]
        result.options = self.options.copy()
        return result

    def get_default_face_color(self):
        return RGBColor(components=(0, 0, 0, 1))

    def get_default_edge_color(self):
        return RGBColor(components=(0, 0, 0, 1))

    def get_style(
        self, style_class, face_element=None, default_to_faces=True, consider_forms=True
    ):
        if face_element is not None:
            default_to_faces = consider_forms = face_element
        edge_style = face_style = None
        if style_class == _Color:
            if default_to_faces:
                face_style = self.get_default_face_color()
            else:
                edge_style = self.get_default_edge_color()
        elif style_class == _Thickness:
            if not default_to_faces:
                edge_style = AbsoluteThickness(self.graphics, value=0.5)
        for item in self.styles:
            if isinstance(item, style_class):
                if default_to_faces:
                    face_style = item
                else:
                    edge_style = item
            elif isinstance(item, Style):
                if consider_forms:
                    if item.edge:
                        edge_style, _ = item.get_style(
                            style_class, default_to_faces=False, consider_forms=False
                        )
                    elif item.face:
                        _, face_style = item.get_style(
                            style_class, default_to_faces=True, consider_forms=False
                        )

        return edge_style, face_style

    def get_option(self, name):
        return self.options.get(name, None)

    def get_line_width(self, face_element=True):
        if self.graphics.pixel_width is None:
            return 0
        edge_style, _ = self.get_style(
            _Thickness, default_to_faces=face_element, consider_forms=face_element
        )
        if edge_style is None:
            return 0
        return edge_style.get_thickness()


def _flatten(leaves):
    for leaf in leaves:
        if leaf.get_head_name() == "System`List":
            flattened = leaf.flatten(Symbol("List"))
            if flattened.get_head_name() == "System`List":
                for x in flattened.leaves:
                    yield x
            else:
                yield flattened
        else:
            yield leaf


class _GraphicsElements(object):
    def __init__(self, content, evaluation):
        self.evaluation = evaluation
        self.elements = []

        builtins = evaluation.definitions.builtin

        def get_options(name):
            builtin = builtins.get(name)
            if builtin is None:
                return None
            return builtin.options

        def stylebox_style(style, specs):
            new_style = style.clone()
            for spec in _flatten(specs):
                head_name = spec.get_head_name()
                if head_name in style_and_form_heads:
                    new_style.append(spec)
                elif head_name == "System`Rule" and len(spec.leaves) == 2:
                    option, expr = spec.leaves
                    if not isinstance(option, Symbol):
                        raise BoxConstructError

                    name = option.get_name()
                    create = style_options.get(name, None)
                    if create is None:
                        raise BoxConstructError

                    new_style.set_option(name, create(style.graphics, expr))
                else:
                    raise BoxConstructError
            return new_style

        def convert(content, style):
            if content.has_form("List", None):
                items = content.leaves
            else:
                items = [content]
            style = style.clone()
            for item in items:
                if item.get_name() == "System`Null":
                    continue
                head = item.get_head_name()
                if head in style_and_form_heads:
                    style.append(item)
                elif head == "System`StyleBox":
                    if len(item.leaves) < 1:
                        raise BoxConstructError
                    for element in convert(
                        item.leaves[0], stylebox_style(style, item.leaves[1:])
                    ):
                        yield element
                elif head[-3:] == "Box":  # and head[:-3] in element_heads:
                    element_class = get_class(head)
                    if element_class is not None:
                        options = get_options(head[:-3])
                        if options:
                            data, options = _data_and_options(item.leaves, options)
                            new_item = Expression(head, *data)
                            element = get_class(head)(self, style, new_item, options)
                        else:
                            element = get_class(head)(self, style, item)
                        yield element
                    else:
                        raise BoxConstructError
                elif head == "System`List":
                    for element in convert(item, style):
                        yield element
                else:
                    raise BoxConstructError

        self.elements = list(convert(content, self.get_style_class()(self)))

    def create_style(self, expr):
        style = self.get_style_class()(self)

        def convert(expr):
            if expr.has_form(("List", "Directive"), None):
                for item in expr.leaves:
                    convert(item)
            else:
                style.append(expr)

        convert(expr)
        return style

    def get_style_class(self):
        return Style


class GraphicsElements(_GraphicsElements):
    coords = Coords

    def __init__(self, content, evaluation, neg_y=False):
        super(GraphicsElements, self).__init__(content, evaluation)
        self.neg_y = neg_y
        self.xmin = self.ymin = self.pixel_width = None
        self.pixel_height = self.extent_width = self.extent_height = None
        self.view_width = None
        self.content = content

    def translate(self, coords):
        if self.pixel_width is not None:
            w = self.extent_width if self.extent_width > 0 else 1
            h = self.extent_height if self.extent_height > 0 else 1
            result = [
                (coords[0] - self.xmin) * self.pixel_width / w,
                (coords[1] - self.ymin) * self.pixel_height / h,
            ]
            if self.neg_y:
                result[1] = self.pixel_height - result[1]
            return tuple(result)
        else:
            return (coords[0], coords[1])

    def translate_absolute(self, d):
        if self.pixel_width is None:
            return (0, 0)
        else:
            l = 96.0 / 72
            return (d[0] * l, (-1 if self.neg_y else 1) * d[1] * l)

    def translate_relative(self, x):
        if self.pixel_width is None:
            return 0
        else:
            return x * self.pixel_width

    def extent(self, completely_visible_only=False):
        if completely_visible_only:
            ext = total_extent(
                [
                    element.extent()
                    for element in self.elements
                    if element.is_completely_visible
                ]
            )
        else:
            ext = total_extent([element.extent() for element in self.elements])
        xmin, xmax, ymin, ymax = ext
        if xmin == xmax:
            if xmin is None:
                return 0, 0, 0, 0
            xmin = 0
            xmax *= 2
        if ymin == ymax:
            if ymin is None:
                return 0, 0, 0, 0
            ymin = 0
            ymax *= 2
        return xmin, xmax, ymin, ymax

    def set_size(
        self, xmin, ymin, extent_width, extent_height, pixel_width, pixel_height
    ):

        self.xmin, self.ymin = xmin, ymin
        self.extent_width, self.extent_height = extent_width, extent_height
        self.pixel_width, self.pixel_height = pixel_width, pixel_height


class Directive(Builtin):
    attributes = ("ReadProtected",)


class Blend(Builtin):
    """
    <dl>
    <dt>'Blend[{$c1$, $c2$}]'
        <dd>represents the color between $c1$ and $c2$.
    <dt>'Blend[{$c1$, $c2$}, $x$]'
        <dd>represents the color formed by blending $c1$ and $c2$ with
        factors 1 - $x$ and $x$ respectively.
    <dt>'Blend[{$c1$, $c2$, ..., $cn$}, $x$]'
        <dd>blends between the colors $c1$ to $cn$ according to the
        factor $x$.
    </dl>

    >> Blend[{Red, Blue}]
     = RGBColor[0.5, 0., 0.5]
    >> Blend[{Red, Blue}, 0.3]
     = RGBColor[0.7, 0., 0.3]
    >> Blend[{Red, Blue, Green}, 0.75]
     = RGBColor[0., 0.5, 0.5]

    >> Graphics[Table[{Blend[{Red, Green, Blue}, x], Rectangle[{10 x, 0}]}, {x, 0, 1, 1/10}]]
     = -Graphics-

    >> Graphics[Table[{Blend[{RGBColor[1, 0.5, 0, 0.5], RGBColor[0, 0, 1, 0.5]}, x], Disk[{5x, 0}]}, {x, 0, 1, 1/10}]]
     = -Graphics-

    #> Blend[{Red, Green, Blue}, {1, 0.5}]
     : {1, 0.5} should be a real number or a list of non-negative numbers, which has the same length as {RGBColor[1, 0, 0], RGBColor[0, 1, 0], RGBColor[0, 0, 1]}.
     = Blend[{RGBColor[1, 0, 0], RGBColor[0, 1, 0], RGBColor[0, 0, 1]}, {1, 0.5}]
    """

    messages = {
        "arg": (
            "`1` is not a valid list of color or gray-level directives, "
            "or pairs of a real number and a directive."
        ),
        "argl": (
            "`1` should be a real number or a list of non-negative "
            "numbers, which has the same length as `2`."
        ),
    }

    rules = {"Blend[colors_]": "Blend[colors, ConstantArray[1, Length[colors]]]"}

    def do_blend(self, colors, values):
        type = None
        homogenous = True
        for color in colors:
            if type is None:
                type = color.__class__
            else:
                if color.__class__ != type:
                    homogenous = False
                    break
        if not homogenous:
            colors = [RGBColor(components=color.to_rgba()) for color in colors]
            type = RGBColor
        total = sum(values)
        result = None
        for color, value in zip(colors, values):
            frac = value / total
            part = [component * frac for component in color.components]
            if result is None:
                result = part
            else:
                result = [r + p for r, p in zip(result, part)]
        return type(components=result)

    def apply(self, colors, u, evaluation):
        "Blend[{colors___}, u_]"

        colors_orig = colors
        try:
            colors = [_Color.create(color) for color in colors.get_sequence()]
            if not colors:
                raise ColorError
        except ColorError:
            evaluation.message("Blend", "arg", Expression(SymbolList, colors_orig))
            return

        if u.has_form("List", None):
            values = [value.round_to_float(evaluation) for value in u.leaves]
            if None in values:
                values = None
            if len(u.leaves) != len(colors):
                values = None
            use_list = True
        else:
            values = u.round_to_float(evaluation)
            if values is None:
                pass
            elif values > 1:
                values = 1.0
            elif values < 0:
                values = 0.0
            use_list = False
        if values is None:
            return evaluation.message(
                "Blend", "argl", u, Expression(SymbolList, colors_orig)
            )

        if use_list:
            return self.do_blend(colors, values).to_expr()
        else:
            x = values
            pos = int(floor(x * (len(colors) - 1)))
            x = (x - pos * 1.0 / (len(colors) - 1)) * (len(colors) - 1)
            if pos == len(colors) - 1:
                return colors[-1].to_expr()
            else:
                return self.do_blend(colors[pos : (pos + 2)], [1 - x, x]).to_expr()


class Lighter(Builtin):
    """
    <dl>
    <dt>'Lighter[$c$, $f$]'
        <dd>is equivalent to 'Blend[{$c$, White}, $f$]'.
    <dt>'Lighter[$c$]'
        <dd>is equivalent to 'Lighter[$c$, 1/3]'.
    </dl>

    >> Lighter[Orange, 1/4]
     = RGBColor[1., 0.625, 0.25]
    >> Graphics[{Lighter[Orange, 1/4], Disk[]}]
     = -Graphics-
    >> Graphics[Table[{Lighter[Orange, x], Disk[{12x, 0}]}, {x, 0, 1, 1/6}]]
     = -Graphics-
    """

    rules = {
        "Lighter[c_, f_]": "Blend[{c, White}, f]",
        "Lighter[c_]": "Lighter[c, 1/3]",
    }


class Darker(Builtin):
    """
    <dl>
    <dt>'Darker[$c$, $f$]'
        <dd>is equivalent to 'Blend[{$c$, Black}, $f$]'.
    <dt>'Darker[$c$]'
        <dd>is equivalent to 'Darker[$c$, 1/3]'.
    </dl>

    >> Graphics[{Darker[Red], Disk[]}]
     = -Graphics-

    >> Graphics3D[{Darker[Green], Sphere[]}]
     = -Graphics3D-

    >> Graphics[Table[{Darker[Yellow, x], Disk[{12x, 0}]}, {x, 0, 1, 1/6}]]
     = -Graphics-
    """

    rules = {"Darker[c_, f_]": "Blend[{c, Black}, f]", "Darker[c_]": "Darker[c, 1/3]"}


class Tiny(Builtin):
    """
    <dl>
    <dt>'ImageSize' -> 'Tiny'
        <dd>produces a tiny image.
    </dl>
    """


class Small(Builtin):
    """
    <dl>
    <dt>'ImageSize' -> 'Small'
        <dd>produces a small image.
    </dl>
    """


class Medium(Builtin):
    """
    <dl>
    <dt>'ImageSize' -> 'Medium'
        <dd>produces a medium-sized image.
    </dl>
    """


class Large(Builtin):
    """
    <dl>
    <dt>'ImageSize' -> 'Large'
        <dd>produces a large image.
    </dl>
    """


element_heads = frozenset(
    system_symbols(
        "Rectangle",
        "Disk",
        "Line",
        "Arrow",
        "FilledCurve",
        "BezierCurve",
        "Point",
        "Circle",
        "Polygon",
        "RegularPolygon",
        "Inset",
        "Text",
        "Sphere",
        "Style",
    )
)

styles = system_symbols_dict(
    {
        "RGBColor": RGBColor,
        "XYZColor": XYZColor,
        "LABColor": LABColor,
        "LCHColor": LCHColor,
        "LUVColor": LUVColor,
        "CMYKColor": CMYKColor,
        "Hue": Hue,
        "GrayLevel": GrayLevel,
        "Thickness": Thickness,
        "AbsoluteThickness": AbsoluteThickness,
        "Thick": Thick,
        "Thin": Thin,
        "PointSize": PointSize,
        "Arrowheads": Arrowheads,
    }
)

style_options = system_symbols_dict(
    {"FontColor": _style, "ImageSizeMultipliers": (lambda *x: x[1])}
)

style_heads = frozenset(styles.keys())

style_and_form_heads = frozenset(
    style_heads.union(set(["System`EdgeForm", "System`FaceForm"]))
)

GLOBALS = system_symbols_dict(
    {
        "Rectangle": Rectangle,
        "Disk": Disk,
        "Circle": Circle,
        "Polygon": Polygon,
        "RegularPolygon": RegularPolygon,
        "Inset": Inset,
        "Text": Text,
    }
)

GLOBALS.update(styles)

GRAPHICS_SYMBOLS = set(
    ["System`List", "System`Rule", "System`VertexColors"]
    + list(element_heads)
    + [element + "Box" for element in element_heads]
    + list(style_heads)
)
