# -*- coding: utf-8 -*-
"""
Format a Mathics object as plain text 
"""


from mathics.builtin.exceptions import BoxConstructError
from mathics.builtin.box.graphics import GraphicsBox
from mathics.builtin.box.graphics3d import Graphics3DBox
from mathics.builtin.box.layout import (
    _BoxedString,
    GridBox,
    RowBox,
    StyleBox,
    SubscriptBox,
    SuperscriptBox,
    SubsuperscriptBox,
    SqrtBox,
    FractionBox,
)

from mathics.core.atoms import String
from mathics.core.formatter import (
    add_conversion_fn,
)
from mathics.core.symbols import Atom, SymbolTrue


def string(self, **options) -> str:
    value = self.value
    show_string_characters = (
        options.get("System`ShowStringCharacters", None) is SymbolTrue
    )
    if value.startswith('"') and value.endswith('"'):  # nopep8
        if not show_string_characters:
            value = value[1:-1]
    return value


add_conversion_fn(String, string)
add_conversion_fn(_BoxedString, string)


def fractionbox(self, **options) -> str:
    _options = self.box_options.copy()
    _options.update(options)
    options = _options
    num_text = self.num.boxes_to_text(**options)
    den_text = self.den.boxes_to_text(**options)
    if isinstance(self.num, RowBox):
        num_text = f"({num_text})"
    if isinstance(self.den, RowBox):
        den_text = f"({den_text})"

    return " / ".join([num_text, den_text])


add_conversion_fn(FractionBox, fractionbox)


def gridbox(self, elements=None, **box_options) -> str:
    if not elements:
        elements = self._elements
    evaluation = box_options.get("evaluation")
    items, options = self.get_array(elements, evaluation)
    result = ""
    if not items:
        return ""
    widths = [0] * len(items[0])
    cells = [
        [
            item.evaluate(evaluation).boxes_to_text(**box_options).splitlines()
            for item in row
        ]
        for row in items
    ]
    for row in cells:
        for index, cell in enumerate(row):
            if index >= len(widths):
                raise BoxConstructError
            for line in cell:
                widths[index] = max(widths[index], len(line))
    for row_index, row in enumerate(cells):
        if row_index > 0:
            result += "\n"
        k = 0
        while True:
            line_exists = False
            line = ""
            for cell_index, cell in enumerate(row):
                if len(cell) > k:
                    line_exists = True
                    text = cell[k]
                else:
                    text = ""
                line += text
                if cell_index < len(row) - 1:
                    line += " " * (widths[cell_index] - len(text))
                    # if cell_index < len(row) - 1:
                    line += "   "
            if line_exists:
                result += line + "\n"
            else:
                break
            k += 1
    return result


add_conversion_fn(GridBox, gridbox)


def sqrtbox(self, **options) -> str:
    _options = self.box_options.copy()
    _options.update(options)
    options = _options
    if self.index:
        return "Sqrt[%s,%s]" % (
            self.radicand.boxes_to_text(**options),
            self.index.boxes_to_text(**options),
        )
    return "Sqrt[%s]" % (self.radicand.boxes_to_text(**options))


add_conversion_fn(SqrtBox, sqrtbox)


def superscriptbox(self, **options) -> str:
    _options = self.box_options.copy()
    _options.update(options)
    options = _options
    if isinstance(self.superindex, Atom):
        return "%s^%s" % (
            self.base.boxes_to_text(**options),
            self.superindex.boxes_to_text(**options),
        )

    return "%s^(%s)" % (
        self.base.boxes_to_text(**options),
        self.superindex.boxes_to_text(**options),
    )


add_conversion_fn(SuperscriptBox, superscriptbox)


def subscriptbox(self, **options) -> str:
    _options = self.box_options.copy()
    _options.update(options)
    options = _options
    return "Subscript[%s, %s]" % (
        self.base.boxes_to_text(**options),
        self.subindex.boxes_to_text(**options),
    )


add_conversion_fn(SubscriptBox, subscriptbox)


def subsuperscriptbox(self, **options) -> str:
    _options = self.box_options.copy()
    _options.update(options)
    options = _options
    return "Subsuperscript[%s, %s, %s]" % (
        self.base.boxes_to_text(**options),
        self.subindex.boxes_to_text(**options),
        self.superindex.boxes_to_text(**options),
    )


add_conversion_fn(SubsuperscriptBox, subsuperscriptbox)


def rowbox(self, elements=None, **options) -> str:
    _options = self.box_options.copy()
    _options.update(options)
    options = _options
    return "".join([element.boxes_to_text(**options) for element in self.items])


add_conversion_fn(RowBox, rowbox)


def stylebox(self, **options) -> str:
    options.pop("evaluation", None)
    _options = self.box_options.copy()
    _options.update(options)
    options = _options
    return self.boxes.boxes_to_text(**options)


add_conversion_fn(StyleBox, stylebox)


def graphicsbox(self, elements=None, **options) -> str:
    if not elements:
        elements = self._elements

    self._prepare_elements(elements, options)  # to test for Box errors
    return "-Graphics-"


add_conversion_fn(GraphicsBox, graphicsbox)


def graphics3dbox(self, elements=None, **options) -> str:
    if not elements:
        elements = self._elements
    return "-Graphics3D-"


add_conversion_fn(Graphics3DBox, graphics3dbox)