#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Graphs
"""

# uses GraphViz, if it's installed in the PATH (see pydotplus.graphviz.find_graphviz and http://www.graphviz.org).
# export PATH="$PATH:/Users/bernhard/dev/homebrew/bin"

from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import division

from mathics.builtin.base import Builtin, AtomBuiltin
from mathics.builtin.graphics import GraphicsBox
from mathics.core.expression import Expression, Symbol, Atom, Real, Integer, system_symbols_dict, from_python

from itertools import permutations
from collections import defaultdict
from math import sqrt

try:
    import networkx as nx
except ImportError:
    nx = {}


def _circular_layout(G):
    return nx.drawing.circular_layout(G, scale=1.5)


def _spectral_layout(G):
    return nx.drawing.spectral_layout(G, scale=2.0)


def _shell_layout(G):
    return nx.drawing.shell_layout(G, scale=2.0)


def _generic_layout(G):
    pos = None

    try:
        import pydotplus

        if pydotplus.graphviz.find_graphviz():
            pos = nx.nx_pydot.graphviz_layout(G)
    except ImportError:
        pass

    return nx.drawing.fruchterman_reingold_layout(G, pos=pos, k=1.0)


def _components(G):
    if isinstance(G, (nx.MultiDiGraph, nx.DiGraph)):
        return nx.strongly_connected_components(G)
    else:
        return nx.connected_components(G)


def _squared_distances(edges, pos):
    for e in edges:
        e1, e2 = e.leaves
        if e1 != e2:
            x1, y1 = pos[e1]
            x2, y2 = pos[e2]
            dx = x2 - x1
            dy = y2 - y1
            yield dx * dx + dy * dy


_vertex_size_names = system_symbols_dict({
    'Large': 0.8,
    'Medium': 0.3,
    'Small': 0.2,
    'Tiny': 0.05,
})


def _vertex_size(expr):
    if isinstance(expr, Symbol):
        return _vertex_size_names.get(expr.get_name())
    else:
        return expr.round_to_float()


def _vertex_style(expr):
    return expr


def _edge_style(expr):
    return expr


def _parse_property(expr, attr_dict=None):
    if expr.has_form('Rule', 2):
        name, value = expr.leaves
        if isinstance(name, Symbol):
            if attr_dict is None:
                attr_dict = {}
            attr_dict[name.get_name()] = value
    elif expr.has_form('List', None):
        for item in expr.leaves:
            attr_dict = _parse_property(item, attr_dict)
    return attr_dict


class _NetworkXBuiltin(Builtin):
    requires = (
        'networkx',
    )

    options = {
        'VertexSize': '{}',
        'VertexStyle': '{}',
        'EdgeStyle': '{}',
        'EdgeWeight': '{}',
    }

    messages = {
        'graph': 'Expected a graph at position 1 in ``.',
    }

    def _build_graph(self, graph, evaluation, options, expr):
        head = graph.get_head_name()
        if head == 'System`Graph':
            return graph
        elif head == 'System`List':
            return _graph_from_list(graph.leaves, options)
        else:
            evaluation.message(self.get_name(), 'graph', expr)

    def _evaluate_atom(self, graph, options, compute):
        head = graph.get_head_name()
        if head == 'System`Graph':
            return compute(graph)
        elif head == 'System`List':
            return compute(_graph_from_list(graph.leaves, options))

    def _evaluate(self, graph, options, compute):
        head = graph.get_head_name()
        if head == 'System`Graph':
            return compute(graph.G)
        elif head == 'System`List':
            return compute(_graph_from_list(graph.leaves, options).G)
        else:
            evaluation.message(self.get_name(), 'graph', expr)

    def _evaluate_to_list(self, graph, options, compute):
        r = self._evaluate(graph, options, compute)
        if r:
            return Expression('List', *r)


class GraphBox(GraphicsBox):
    def boxes_to_text(self, leaves, **options):
        return '-Graph-'


class _Collection:
    def __init__(self, expressions, properties=None, index=None):
        self.expressions = expressions
        self.properties = properties if properties else None
        self.index = index

    def clone(self):
        properties = self.properties
        return _Collection(
            self.expressions[:],
            properties[:] if properties else None,
            None)

    def extend(self, expressions, properties):
        if properties:
            if self.properties is None:
                self.properties = [None] * len(self.expressions)
            self.properties.extend(properties)
        self.expressions.extend(expressions)
        self.index = None

    def delete(self, expressions):
        index = self.get_index()
        removed = set(index[x] for x in expressions)
        self.expressions = [x for i, x in enumerate(self.expressions) if i not in removed]
        self.properties = [x for i, x in enumerate(self.properties) if i not in removed]
        self.index = None

    def get_index(self):
        index = self.index
        if index is None:
            index = dict((v, i) for i, v in enumerate(self.expressions))
            self.index = index
        return index

    def get_properties(self):
        if self.properties:
            for p in self.properties:
                yield p
        else:
            for _ in range(len(self.expressions)):
                yield None

    def get_sorted(self):
        index = self.get_index()
        return lambda c: sorted(c, key=lambda v: index[v])

    def get_property(self, item, name):
        properties = self.properties
        if properties is None:
            return None
        index = self.get_index()
        i = index.get(item)
        if i is None:
            return None
        p = properties[i]
        if p is None:
            return None
        return p.get(name)


class Graph(Atom):
    def __init__(self, vertices, edges, G, layout, options, highlights=None, **kwargs):
        super(Graph, self).__init__(**kwargs)
        self.vertices = vertices
        self.edges = edges
        self.G = G
        self.layout = layout
        self.options = options
        self.highlights = highlights

    def add_vertices(self, new_vertices, new_vertex_properties):
        vertices = self.vertices.clone()
        vertices.extend(new_vertices, new_vertex_properties)
        G = self.G.copy()
        G.add_nodes_from(zip(new_vertices, new_vertex_properties))
        return Graph(vertices, self.edges, G, self.layout, self.options, self.highlights)

    def __str__(self):
        return '-Graph-'

    def with_highlight(self, highlights):
        return Graph(
            self.vertices, self.edges, self.G, self.layout, self.options, highlights)

    def do_copy(self):
        return Graph(
            self.vertices, self.edges, self.G, self.layout, self.options, self.highlights)

    def default_format(self, evaluation, form):
        return '-Graph-'

    def get_sort_key(self, pattern_sort=False):
        if pattern_sort:
            return super(Graph, self).get_sort_key(True)
        else:
            return hash(self)

    def same(self, other):
        return isinstance(other, Graph) and self.G == other.G
        # FIXME
        # self.properties == other.properties
        # self.options == other.options
        # self.highlights == other.highlights

    def to_python(self, *args, **kwargs):
        return self.G

    def __hash__(self):
        return hash(("Graph", self.G))  # FIXME self.properties, ...

    def _styling(self, name, elements, parse, default_value):
        expr = self.options.get(name)
        if expr is None:
            return lambda x: default_value

        values = {}
        if expr.has_form('List', None):
            if all(leaf.has_form('Rule', 2) for leaf in expr.leaves):
                for rule in expr.leaves:
                    v, r = rule.leaves
                    values[v] = parse(r) or default_value
            else:
                for v, r in zip(elements, expr.leaves):
                    values[v] = parse(r) or default_value
        else:
            default_value = parse(expr) or default_value

        return lambda x: values.get(x, default_value)

    def atom_to_boxes(self, form, evaluation):
        G = self.G
        highlights = self.highlights

        edges = self.edges.expressions
        vertices = self.vertices.expressions
        pos = self.layout(G)

        distances = list(_squared_distances(edges, pos))
        default_radius = 0.1

        if len(distances) <= 1:
            minimum_distance = 1.
        else:
            minimum_distance = sqrt(min(*distances))

        vertex_size = self._styling(
            'System`VertexSize', vertices, _vertex_size, default_radius)

        vertex_style = self._styling(
            'System`VertexStyle', vertices, _vertex_style, None)

        edge_style = self._styling(
            'System`EdgeStyle', edges, _edge_style, None)

        directed = isinstance(G, nx.DiGraph)
        edge = 'DirectedEdge' if directed else 'UndirectedEdge'

        if highlights:
            def highlighted(exprs):
                items = Expression('List', *exprs)
                listspec = Expression('List', Integer(1))

                matches = Expression('Replace', items, highlights, listspec).evaluate(evaluation)
                if matches.get_head_name() != 'System`List':
                    return
                if len(matches.leaves) != len(exprs):
                    return

                for expr, m in zip(exprs, matches.leaves):
                    if m.get_head_name() == 'System`Missing':
                        yield expr, None
                    else:
                        yield expr, m
        else:
            def highlighted(exprs):
                for expr in exprs:
                    yield expr, None

        def edge_primitives():
            yield Expression('AbsoluteThickness', 0.1)

            if directed:
                yield Expression('Arrowheads', 0.04)
            else:
                yield Expression('Arrowheads', 0)

            # FIXME handle multigraphs with multiple same edges
            # FIXME needs curves in Graphics

            for (e, style), properties in zip(highlighted(edges), self.edges.get_properties()):
                e1, e2 = e.leaves

                p1 = pos[e1]
                p2 = pos[e2]

                r1 = vertex_size(e1) * minimum_distance
                r2 = vertex_size(e2) * minimum_distance

                q1 = Expression('List', *p1)
                q2 = Expression('List', *p2)
                arrow = Expression('Arrow', Expression('List', q1, q2), Expression('List', r1, r2))

                if style is None and properties is not None:
                    style = properties.get('System`EdgeStyle')

                if style is None:
                    style = edge_style(e)

                if style is not None:
                    arrow = Expression('Style', arrow, style)

                yield arrow

        def vertex_primitives():
            for (v, style), properties in zip(highlighted(vertices), self.vertices.get_properties()):
                xy = pos.get(v)
                if xy is None:
                    continue  # FIXME isolated vertices are not supported yet

                x, y = xy
                r = vertex_size(v) * minimum_distance

                disk = Expression(
                    'Disk',
                    Expression('List', x, y),
                    Expression('List', r, r))

                if style is None and properties is not None:
                    style = properties.get('System`VertexStyle')

                if style is None:
                    style = vertex_style(v)

                if style is not None:
                    yield Expression('Style', disk, style)
                else:
                    yield disk

                # yield Expression('FontSize', Expression('Scaled', r))
                # yield Expression('Text', v, Expression('List', x, y))

        vertex_face = Expression('FaceForm', Expression('RGBColor', .8, .8, .9))
        vertex_edge = Expression('EdgeForm', Expression('RGBColor', 0, 0, 0))

        edge_expression = Expression(
            'Style',
            Expression('List', *list(edge_primitives())),
            Expression('List'))
        vertex_expression = Expression(
            'Style',
            Expression('List', *list(vertex_primitives())),
            Expression('List', vertex_face, vertex_edge))

        graphics = Expression('Graphics', Expression('List', edge_expression, vertex_expression))
        graphics_box = Expression('MakeBoxes', graphics, form).evaluate(evaluation)
        return Expression('GraphBox', *graphics_box.leaves)

    def get_property(self, item, name):
        if item.get_head_name() in ('System`DirectedEdge', 'System`UndirectedEdge'):
            x = self.edges.get_property(item, name)
        if x is None:
            x = self.vertices.get_property(item, name)
        return x

    def update_weights(self, evaluation):
        weights = None
        G = self.G

        if isinstance(G, (nx.MultiGraph, nx.MultiDiGraph)):
            for u, v, k, data in G.edges_iter(data=True, keys=True):
                w = data.get('System`EdgeWeight')
                if w is not None:
                    w = w.evaluate(evaluation).to_mpmath()
                    G[u][v][k]['WEIGHT'] = w
                    weights = 'WEIGHT'
        else:
            for u, v, data in G.edges_iter(data=True):
                w = data.get('System`EdgeWeight')
                if w is not None:
                    w = w.evaluate(evaluation).to_mpmath()
                    G[u][v]['WEIGHT'] = w
                    weights = 'WEIGHT'

        return weights

    def coalesced_graph(self, evaluation):
        if isinstance(self.G, (nx.DiGraph, nx.Graph)):
            return self.G

        new_edges = defaultdict(lambda: 0)
        for u, v, data in self.G.edges_iter(data=True):
            w = data.get('System`EdgeWeight')
            if w is not None:
                w = w.evaluate(evaluation).to_mpmath()
            else:
                w = 1
            new_edges[(u, v)] += w

        if isinstance(self.G, nx.MultiDiGraph):
            new_graph = nx.DiGraph()
        else:
            new_graph = nx.Graph()

        # FIXME make sure vertex order is unchanged from self.G
        new_graph.add_edges_from(((u, v, {'WEIGHT': w}) for (u, v), w in new_edges.items()))

        return new_graph, 'WEIGHT'


def _is_path(vertices, G):
    return all(d <= 2 for d in G.degree(vertices).values())


def _is_connected(G):
    if isinstance(G, (nx.MultiDiGraph, nx.DiGraph)):
        return len(list(nx.strongly_connected_components(G))) == 1
    else:
        return nx.is_connected(G)


def _edge_weights(options):
    expr = options.get('System`EdgeWeight')
    if expr is None:
        return []
    if not expr.has_form('List', None):
        return []
    return expr.leaves


def _graph_from_list(rules, options):
    known_vertices = set()
    known_edges = set()
    multi_graph = [False]

    vertices = []
    vertex_properties = []
    edges = []
    edge_properties = []

    def add_vertex(x, attr_dict=None):
        if x.get_head_name() == 'System`Property' and len(x.leaves) == 2:
            expr, prop = x.leaves
            attr_dict = _parse_property(prop, attr_dict)
            return add_vertex(expr, attr_dict)
        elif x not in known_vertices:
            known_vertices.add(x)
            vertices.append(x)
            vertex_properties.append(attr_dict)
        return x

    directed_edges = []
    undirected_edges = []

    def track_edges(*edges):
        if multi_graph[0]:
            return
        previous_n_edges = len(known_edges)
        for edge in edges:
            known_edges.add(edge)
        if len(known_edges) < previous_n_edges + len(edges):
            multi_graph[0] = True

    edge_weights = _edge_weights(options)

    class ParseError(Exception):
        pass

    def parse_edge(r, attr_dict):
        name = r.get_head_name()

        if name == 'System`Property' and len(r.leaves) == 2:
            expr, prop = r.leaves
            attr_dict = _parse_property(prop, attr_dict)
            parse_edge(expr, attr_dict)
            return

        if len(r.leaves) != 2:
            raise ParseError

        u, v = r.leaves

        u = add_vertex(u)
        v = add_vertex(v)

        if name == 'System`Rule' or name == 'System`DirectedEdge':
            edges_container = directed_edges
            head = 'System`DirectedEdge'
            track_edges((u, v))
        elif name == 'System`UndirectedEdge':
            edges_container = undirected_edges
            head = 'System`UndirectedEdge'
            track_edges((u, v), (v, u))
        else:
            raise ParseError

        if head == name:
            edges.append(r)
        else:
            edges.append(Expression(head, u, v))
        edge_properties.append(attr_dict)

        edges_container.append((u, v, attr_dict))

    try:
        for i, r in enumerate(rules):
            if i < len(edge_weights):
                attr_dict = {'System`EdgeWeight': edge_weights[i]}
            else:
                attr_dict = None
            parse_edge(r, attr_dict)
    except ParseError:
        return

    empty_dict = {}
    if directed_edges:
        G = nx.MultiDiGraph() if multi_graph[0] else nx.DiGraph()
        for u, v, attr_dict in directed_edges:
            attr_dict = attr_dict or empty_dict
            G.add_edge(u, v, **attr_dict)
        for u, v, attr_dict in undirected_edges:
            attr_dict = attr_dict or empty_dict
            G.add_edge(u, v, **attr_dict)
            G.add_edge(v, u, **attr_dict)
    else:
        G = nx.MultiGraph() if multi_graph[0] else nx.Graph()
        for u, v, attr_dict in undirected_edges:
            attr_dict = attr_dict or empty_dict
            G.add_edge(u, v, **attr_dict)

    if _is_path(vertices, G):
        layout = _spectral_layout
    else:
        layout = _generic_layout

    return Graph(
        _Collection(vertices, vertex_properties),
        _Collection(edges, edge_properties),
        G, layout, options)


class Property(Builtin):
    pass


class PropertyValue(Builtin):
    '''
    >> g = Graph[{a <-> b, Property[b <-> c, SomeKey -> 123]}];
    >> PropertyValue[{g, b <-> c}, SomeKey]
    '''

    def apply(self, graph, item, name, evaluation):
        'PropertyValue[{graph_Graph, item_}, name_Symbol]'
        value = graph.get_property(item, name.get_name())
        if value is None:
            return  # FIXME
        return value


class DirectedEdge(Builtin):
    pass


class UndirectedEdge(Builtin):
    pass


class GraphAtom(AtomBuiltin):
    '''
    >> Graph[{1->2, 2->3, 3->1}]
     = -Graph-

    >> Graph[{1->2, 2->3, 3->1}, EdgeStyle -> {Red, Blue, Green}]
     = -Graph-

    >> Graph[{1->2, Property[2->3, EdgeStyle -> Thick], 3->1}]
     = -Graph-

    >> Graph[{1->2, 2->3, 3->1}, VertexStyle -> {1 -> Green, 3 -> Blue}]
     = -Graph-
    '''

    requires = (
        'networkx',
    )

    options = {
        'VertexSize': '{}',
        'VertexStyle': '{}',
        'EdgeStyle': '{}',
    }

    def apply(self, graph, evaluation, options):
        'Graph[graph_List, OptionsPattern[%(name)s]]'
        return _graph_from_list(graph.leaves, options)


class PathGraph(_NetworkXBuiltin):
    '''
    >> PathGraph[{1, 2, 3}]
     = -Graph-
    '''

    def apply(self, l, evaluation, options):
        'PathGraph[l_List, OptionsPattern[%(name)s]]'
        leaves = l.leaves
        def edges():
            for u, v in zip(leaves, leaves[1:]):
                yield Expression('UndirectedEdge', u, v)

        return _graph_from_list(edges(), options)


class PathGraphQ(_NetworkXBuiltin):
    '''
    >> PathGraphQ[{1 -> 2, 2 -> 3}]
     = True

    >> PathGraphQ[{1 -> 2, 2 -> 3, 2 -> 4}]
     = False
    '''

    def apply(self, graph, evaluation, options):
        'PathGraphQ[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('PathGraphQ', graph))
        if graph:
            return Symbol('True') if _is_path(graph.vertices.expressions, graph.G) else Symbol('False')


class ConnectedGraphQ(_NetworkXBuiltin):
    '''
    >> g = Graph[{1 -> 2, 2 -> 3}]; ConnectedGraphQ[g]
     = False

    >> g = Graph[{1 -> 2, 2 -> 3, 3 -> 1}]; ConnectedGraphQ[g]
     = True

    >> g = Graph[{1 <-> 2, 2 <-> 3}]; ConnectedGraphQ[g]
     = True

    >> g = Graph[{1 <-> 2, 2 <-> 3, 4 <-> 5}]; ConnectedGraphQ[g]
     = False
    '''

    def apply(self, graph, evaluation, options):
        'ConnectedGraphQ[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('ConnectedGraphQ', graph))
        if graph:
            return Symbol('True') if _is_connected(graph.G) else Symbol('False')


class ConnectedComponents(_NetworkXBuiltin):
    '''
    >> g = Graph[{1 -> 2, 2 -> 3, 3 <-> 4}]; ConnectedComponents[g]
     = {{3, 4}, {2}, {1}}

    >> g = Graph[{1 -> 2, 2 -> 3, 3 -> 1}]; ConnectedComponents[g]
     = {{1, 2, 3}}

    >> g = Graph[{1 <-> 2, 2 <-> 3, 3 -> 4, 4 <-> 5}]; ConnectedComponents[g]
     = {{4, 5}, {1, 2, 3}}
    '''

    def apply(self, graph, evaluation, options):
        'ConnectedComponents[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('ConnectedComponents', graph))
        if graph:
            vertices_sorted = graph.vertices.get_sorted()
            components = [Expression('List', *vertices_sorted(c)) for c in _components(graph.G)]
            return Expression('List', *components)


class WeaklyConnectedComponents(_NetworkXBuiltin):
    '''
    >> g = Graph[{1 -> 2, 2 -> 3, 3 <-> 4}]; WeaklyConnectedComponents[g]
     = {{1, 2, 3, 4}}

    >> g = Graph[{1 -> 2, 2 -> 3, 3 -> 1}]; WeaklyConnectedComponents[g]
     = {{1, 2, 3}}

    >> g = Graph[{1 <-> 2, 2 <-> 3, 3 -> 4, 4 <-> 5, 6 <-> 7, 7 <-> 8}]; WeaklyConnectedComponents[g]
     = {{1, 2, 3, 4, 5}, {6, 7, 8}}
    '''

    def apply(self, graph, evaluation, options):
        'WeaklyConnectedComponents[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('WeaklyConnectedComponents', graph))
        if graph:
            vertices_sorted = graph.vertices_sorted()
            return Expression(
                'List',
                *[Expression('List', *vertices_sorted(c)) for c in nx.connected_components(graph.G.to_undirected())])


class FindVertexCut(_NetworkXBuiltin):
    '''
    >> g = Graph[{1 -> 2, 2 -> 3}]; FindVertexCut[g]
     = {}

    >> g = Graph[{1 <-> 2, 2 <-> 3}]; FindVertexCut[g]
     = {2}
    '''

    def apply(self, graph, evaluation, options):
        'FindVertexCut[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('FindVertexCut', graph))
        if graph:
            if not _is_connected(graph.G):
                return Expression('List')
            else:
                return Expression('List', *nx.minimum_node_cut(graph.G))

    def apply_st(self, graph, s, t, evaluation, options):
        'FindVertexCut[graph_, s_, t_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('FindVertexCut', graph, s, t))
        if graph:
            if not _is_connected(graph.G):
                return Expression('List')
            else:
                return Expression('List', *nx.minimum_node_cut(graph.G, s, t))


class HighlightGraph(_NetworkXBuiltin):
    '''

    '''

    def apply(self, graph, what, evaluation, options):
        'HighlightGraph[graph_, what_List, OptionsPattern[%(name)s]]'
        default_highlight = [Expression('RGBColor', 1, 0, 0)]

        def parse(item):
            if item.get_head_name() == 'System`Rule':
                return Expression('DirectedEdge', *item.leaves)
            else:
                return item

        rules = []
        for item in what.leaves:
            if item.get_head_name() == 'System`Style':
                if len(item.leaves) >= 2:
                    rules.append((parse(item.leaves[0]), item.leaves[1:]))
            else:
                rules.append((parse(item), default_highlight))

        rules.append((Expression('Blank'), Expression('Missing')))

        graph = self._build_graph(graph, evaluation, options, lambda: Expression('HighlightGraph', graph, what))
        if graph:
            rule_exprs = Expression('List', *[Expression('Rule', *r) for r in rules])
            return graph.with_highlight(rule_exprs)


class _PatternList(_NetworkXBuiltin):
    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression(self.get_name(), graph))
        if graph:
            return Expression('List', *self._items(graph))

    def apply_patt(self, graph, patt, evaluation, options):
        '%(name)s[graph_, patt_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression(self.get_name(), graph, patt))
        if graph:
            return Expression('Cases', Expression('List', *self._items(graph)), patt)


class _PatternCount(_NetworkXBuiltin):
    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression(self.get_name(), graph))
        if graph:
            return Integer(len(self._items(graph)))

    def apply_patt(self, graph, patt, evaluation, options):
        '%(name)s[graph_, patt_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression(self.get_name(), graph, patt))
        if graph:
            return Expression('Length', Expression('Cases', Expression('List', *self._items(graph)), patt))


class VertexCount(_PatternCount):
    '''
    >> VertexCount[{1 -> 2, 2 -> 3}]
     = 3

    >> VertexCount[{1 -> x, x -> 3}, _Integer]
     = 2
    '''

    def _items(self, graph):
        return graph.vertices.expressions


class VertexList(_PatternList):
    '''
    >> VertexList[{1 -> 2, 2 -> 3}]
     = {1, 2, 3}

    >> VertexList[{a -> c, c -> b}]
     = {a, c, b}
    '''

    def _items(self, graph):
        return graph.vertices.expressions


class EdgeCount(_PatternCount):
    '''
    >> EdgeCount[{1 -> 2, 2 -> 3}]
     = 2
    '''

    def _items(self, graph):
        return graph.edges.expressions


class EdgeList(_PatternList):
    '''
    >> EdgeList[{1 -> 2, 2 <-> 3}]
     = {DirectedEdge[1, 2], UndirectedEdge[2, 3]}
    '''

    def _items(self, graph):
        return graph.edges.expressions


class EdgeConnectivity(_NetworkXBuiltin):
    '''
    >> EdgeConnectivity[{1 <-> 2, 2 <-> 3}]
     = 1

    >> EdgeConnectivity[{1 -> 2, 2 -> 3}]
     = 0

    >> EdgeConnectivity[{1 -> 2, 2 -> 3, 3 -> 1}]
     = 1

    >> EdgeConnectivity[{1 <-> 2, 2 <-> 3, 1 <-> 3}]
     = 2
    '''

    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('EdgeConnectivity', graph))
        if graph:
            return Integer(nx.edge_connectivity(graph.G))

    def apply_st(self, graph, s, t, evaluation, options):
        '%(name)s[graph_, s_, t_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('EdgeConnectivity', graph, s, t))
        if graph:
            return Integer(nx.edge_connectivity(graph.G, s, t))


class VertexConnectivity(_NetworkXBuiltin):
    '''
    >> VertexConnectivity[{1 <-> 2, 2 <-> 3}]
     = 1

    >> VertexConnectivity[{1 -> 2, 2 -> 3}]
     = 0

    >> VertexConnectivity[{1 -> 2, 2 -> 3, 3 -> 1}]
     = 1

    >> VertexConnectivity[{1 <-> 2, 2 <-> 3, 1 <-> 3}]
     = 2
    '''

    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('VertexConnectivity', graph))
        if graph:
            if not _is_connected(graph.G):
                return Integer(0)
            else:
                return Integer(nx.node_connectivity(graph.G))

    def apply_st(self, graph, s, t, evaluation, options):
        '%(name)s[graph_, s_, t_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('VertexConnectivity', graph, s, t))
        if graph:
            if not _is_connected(graph.G):
                return Integer(0)
            else:
                return Integer(nx.node_connectivity(graph.G, s, t))


class _Centrality(_NetworkXBuiltin):
    pass


class BetweennessCentrality(_Centrality):
    '''
    >> g = Graph[{a -> b, b -> c, d -> c, d -> a, e -> c, d -> b}]; BetweennessCentrality[g]
     = {0., 1., 0., 0., 0.}

    >> g = Graph[{a -> b, b -> c, c -> d, d -> e, e -> c, e -> a}]; BetweennessCentrality[g]
     = {3., 3., 6., 6., 6.}
    '''

    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('BetweennessCentrality', graph))
        if graph:
            weight = graph.update_weights(evaluation)
            centrality = nx.betweenness_centrality(graph.G, normalized=False, weight=weight)
            return Expression('List', *[Real(centrality.get(v, 0.)) for v in graph.vertices.expressions])


class ClosenessCentrality(_Centrality):
    '''
    >> g = Graph[{a -> b, b -> c, d -> c, d -> a, e -> c, d -> b}]; ClosenessCentrality[g]
     = {0.666667, 1., 0., 1., 1.}

    >> g = Graph[{a -> b, b -> c, c -> d, d -> e, e -> c, e -> a}]; ClosenessCentrality[g]
     = {0.4, 0.4, 0.4, 0.5, 0.666667}
    '''

    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('ClosenessCentrality', graph))
        if graph:
            weight = graph.update_weights(evaluation)
            centrality = nx.closeness_centrality(graph.G, normalized=False, distance=weight)
            return Expression('List', *[Real(centrality.get(v, 0.)) for v in graph.vertices.expressions])


class DegreeCentrality(_Centrality):
    '''
    >> g = Graph[{a -> b, b <-> c, d -> c, d -> a, e <-> c, d -> b}]; DegreeCentrality[g]
     = {2, 4, 5, 3, 2}

    >> g = Graph[{a -> b, b <-> c, d -> c, d -> a, e <-> c, d -> b}]; DegreeCentrality[g, "In"]
     = {1, 3, 3, 0, 1}

    >> g = Graph[{a -> b, b <-> c, d -> c, d -> a, e <-> c, d -> b}]; DegreeCentrality[g, "Out"]
     = {1, 1, 2, 3, 1}
    '''

    def _from_dict(self, graph, centrality):
        s = len(graph.G) - 1  # undo networkx's normalization
        return Expression('List', *[Integer(s * centrality.get(v, 0)) for v in graph.vertices.expressions])

    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('DegreeCentrality', graph))
        if graph:
            return self._from_dict(graph, nx.degree_centrality(graph.G))

    def apply_in(self, graph, evaluation, options):
        '%(name)s[graph_, "In", OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('DegreeCentrality', graph))
        if graph:
            return self._from_dict(graph, nx.in_degree_centrality(graph.G))

    def apply_out(self, graph, evaluation, options):
        '%(name)s[graph_, "Out", OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('DegreeCentrality', graph))
        if graph:
            return self._from_dict(graph, nx.out_degree_centrality(graph.G))


class _ComponentwiseCentrality(_Centrality):
    def _centrality(self, g, weight):
        raise NotImplementedError

    def _compute(self, graph, evaluation, reverse=False, normalized=True, **kwargs):
        vertices = graph.vertices.expressions
        G, weight = graph.coalesced_graph(evaluation)
        if reverse:
            G = G.reverse()

        components = list(_components(G))
        components = [c for c in components if len(c) > 1]

        result = [0] * len(vertices)
        for bunch in components:
            g = G.subgraph(bunch)
            centrality = self._centrality(g, weight, **kwargs)
            values = [centrality.get(v, 0) for v in vertices]
            if normalized:
                s = sum(values) * len(components)
            else:
                s = 1
            if s > 0:
                for i, x in enumerate(values):
                    result[i] += x / s
        return Expression('List', *[Real(x) for x in result])



class EigenvectorCentrality(_ComponentwiseCentrality):
    '''
    >> g = Graph[{a -> b, b -> c, c -> d, d -> e, e -> c, e -> a}]; EigenvectorCentrality[g, "In"]
     = {0.16238, 0.136013, 0.276307, 0.23144, 0.193859}

    >> EigenvectorCentrality[g, "Out"]
     = {0.136013, 0.16238, 0.193859, 0.23144, 0.276307}

    >> g = Graph[{a <-> b, b <-> c, c <-> d, d <-> e, e <-> c, e <-> a}]; EigenvectorCentrality[g]
     = {0.162435, 0.162435, 0.240597, 0.193937, 0.240597}

    >> g = Graph[{a <-> b, b <-> c, a <-> c, d <-> e, e <-> f, f <-> d, e <-> d}]; EigenvectorCentrality[g]
     = {0.166667, 0.166667, 0.166667, 0.183013, 0.183013, 0.133975}

    >> g = Graph[{a - > b, b -> c, c -> d, b -> e, a -> e}]; EigenvectorCentrality[g]
     = {0.166667, 0.166667, 0.166667, 0.183013, 0.183013, 0.133975}

    >> g = Graph[{a -> b, b -> c, c -> d, b -> e, a -> e, c -> a}]; EigenvectorCentrality[g]
     = {0.333333, 0.333333, 0.333333, 0., 0.}
    '''

    def _centrality(self, g, weight):
        return nx.eigenvector_centrality(g, max_iter=10000, tol=1.0e-7, weight=weight)

    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('EigenvectorCentrality', graph))
        if graph:
            return self._compute(graph, evaluation)


    def apply_in_out(self, graph, dir, evaluation, options):
        '%(name)s[graph_, dir_String, OptionsPattern[%(name)s]]'
        py_dir = dir.get_string_value()
        if py_dir not in ('In', 'Out'):
            return
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('EigenvectorCentrality', graph))
        if graph:
            return self._compute(graph, evaluation, py_dir == 'Out')


class KatzCentrality(_ComponentwiseCentrality):
    '''
    >> g = Graph[{a -> b, b -> c, c -> d, d -> e, e -> c, e -> a}]; KatzCentrality[g, 0.2]
     = {1.25202, 1.2504, 1.5021, 1.30042, 1.26008}

    >> g = Graph[{a <-> b, b <-> c, a <-> c, d <-> e, e <-> f, f <-> d, e <-> d}]; KatzCentrality[g, 0.1]
     = {1.25, 1.25, 1.25, 1.41026, 1.41026, 1.28205}
    '''

    rules = {
        'KatzCentrality[g_, alpha_]': 'KatzCentrality[g, alpha, 1]',
    }

    def _centrality(self, g, weight, alpha, beta):
        return nx.katz_centrality(g, alpha=alpha, beta=beta, normalized=False, weight=weight)

    def apply(self, graph, alpha, beta, evaluation, options):
        '%(name)s[graph_, alpha_, beta_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('KatzCentrality'))
        if graph:
            py_alpha = alpha.to_mpmath()
            py_beta = beta.to_mpmath()
            if py_alpha is None or py_beta is None:
                return
            return self._compute(graph, evaluation, normalized=False, alpha=py_alpha, beta=py_beta)


class PageRankCentrality(_Centrality):
    '''
    >> g = Graph[{a -> d, b -> c, d -> c, d -> a, e -> c, d -> c}]; PageRankCentrality[g, 0.2]
     = {0.184502, 0.207565, 0.170664, 0.266605, 0.170664}
    '''

    def apply_alpha_beta(self, graph, alpha, evaluation, options):
        '%(name)s[graph_, alpha_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('PageRankCentrality'))
        if graph:
            py_alpha = alpha.to_mpmath()
            if py_alpha is None:
                return
            G, weight = graph.coalesced_graph(evaluation)
            centrality = nx.pagerank(G, alpha=py_alpha, weight=weight, tol=1.0e-7)
            return Expression('List', *[Real(centrality.get(v, 0)) for v in graph.vertices.expressions])


class HITSCentrality(_Centrality):
    '''
    >> g = Graph[{a -> d, b -> c, d -> c, d -> a, e -> c}]; HITSCentrality[g]
     = {{0.292893, 0., 0., 0.707107, 0.}, {0., 1., 0.707107, 0., 0.707107}}
    '''

    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('HITSCentrality', graph))
        if graph:
            G, _ = graph.coalesced_graph(evaluation)  # FIXME warn if weight > 1

            tol = 1.e-14
            _, a = nx.hits(G, normalized=True, tol=tol)
            h, _ = nx.hits(G, normalized=False, tol=tol)

            def _crop(x):
                return 0 if x < tol else x

            vertices = graph.vertices.expressions
            return Expression(
                'List',
                Expression('List', *[Real(_crop(a.get(v, 0))) for v in vertices]),
                Expression('List', *[Real(_crop(h.get(v, 0))) for v in vertices]))


class VertexDegree(_Centrality):
    '''
    >> VertexDegree[{1 <-> 2, 2 <-> 3, 2 <-> 4}]
     = {1, 3, 1, 1}
    '''

    def apply(self, graph, evaluation, options):
        '%(name)s[graph_, OptionsPattern[%(name)s]]'
        def degrees(graph):
            degrees = graph.G.degree(graph.vertices.expressions)
            return Expression('List', *[Integer(degrees.get(v, 0)) for v in graph.vertices.expressions])
        return self._evaluate_atom(graph, options, degrees)


class FindShortestPath(_NetworkXBuiltin):
    '''
    >> FindShortestPath[{1 <-> 2, 2 <-> 3, 3 <-> 4, 2 <-> 4, 4 -> 5}, 1, 5]
     = {1, 2, 4, 5}

    >> FindShortestPath[{1 <-> 2, 2 <-> 3, 3 <-> 4, 4 -> 2, 4 -> 5}, 1, 5]
     = {1, 2, 3, 4, 5}

    >> FindShortestPath[{1 <-> 2, 2 <-> 3, 4 -> 3, 4 -> 2, 4 -> 5}, 1, 5]
     = {}

    >> g = Graph[{1 -> 2, 2 -> 3, 1 -> 3}, EdgeWeight -> {0.5, a, 3}];
    >> a = 0.5; FindShortestPath[g, 1, 3]
     = {1, 2, 3}
    >> a = 10; FindShortestPath[g, 1, 3]
     = {1, 3}
    '''

    def apply_s_t(self, graph, s, t, evaluation, options):
        '%(name)s[graph_, s_, t_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('FindShortestPath', graph, s, t))
        if graph:
            try:
                weight = graph.update_weights(evaluation)
                return Expression('List', *list(nx.shortest_path(graph.G, source=s, target=t, weight=weight)))
            except nx.exception.NetworkXNoPath:
                return Expression('List')


class GraphDistance(_NetworkXBuiltin):
    '''
    >> GraphDistance[{1 <-> 2, 2 <-> 3, 3 <-> 4, 2 <-> 4, 4 -> 5}, 1, 5]
     = 3

    >> GraphDistance[{1 <-> 2, 2 <-> 3, 3 <-> 4, 4 -> 2, 4 -> 5}, 1, 5]
     = 4

    >> GraphDistance[{1 <-> 2, 2 <-> 3, 4 -> 3, 4 -> 2, 4 -> 5}, 1, 5]
     = Infinity

    >> GraphDistance[{1 <-> 2, 2 <-> 3, 3 <-> 4, 2 <-> 4, 4 -> 5}, 3]
     = {2, 1, 0, 1, 2}

    >> GraphDistance[{1 <-> 2, 3 <-> 4}, 3]
     = {Infinity, Infinity, 0, 1}
    '''

    def apply_s(self, graph, s, evaluation, options):
        '%(name)s[graph_, s_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('GraphDistance', graph))
        if graph:
            weight = graph.update_weights(evaluation)
            d = nx.shortest_path_length(graph.G, source=s, weight=weight)
            inf = Expression('DirectedInfinity', 1)
            return Expression('List', *[d.get(v, inf) for v in graph.vertices.expressions])

    def apply_s_t(self, graph, s, t, evaluation, options):
        '%(name)s[graph_, s_, t_, OptionsPattern[%(name)s]]'
        graph = self._build_graph(graph, evaluation, options, lambda: Expression('GraphDistance', graph))
        if graph:
            try:
                weight = graph.update_weights(evaluation)
                return from_python(nx.shortest_path_length(graph.G, source=s, target=t, weight=weight))
            except nx.exception.NetworkXNoPath:
                return Expression('DirectedInfinity', 1)


class CompleteGraph(_NetworkXBuiltin):
    '''
    >> CompleteGraph[8]
     = -Graph-
    '''

    def apply(self, n, evaluation, options):
        '%(name)s[n_Integer, OptionsPattern[%(name)s]]'
        py_n = n.get_int_value()

        vertices = [Integer(i) for i in range(py_n)]
        edges = [Expression('UndirectedEdge', Integer(e1), Integer(e2))
                 for e1, e2, in permutations(range(py_n), 2)]

        G = nx.Graph()
        G.add_nodes_from(vertices)
        G.add_edges_from(e.leaves for e in edges)

        return Graph(
            _Collection(vertices),
            _Collection(edges),
            G, _circular_layout, options)

    def apply_multipartite(self, n, evaluation, options):
        '%(name)s[n_List, OptionsPattern[%(name)s]]'
        if all(isinstance(i, Integer) for i in n.leaves):
            return Graph(nx.complete_multipartite_graph(*[i.get_int_value() for i in n.leaves]))


def _parse_vertex(x, attr_dict=None):
    if x.get_head_name() == 'System`Property' and len(x.leaves) == 2:
        expr, prop = x.leaves
        attr_dict = _parse_property(prop, attr_dict)
        return _parse_vertex(expr, attr_dict)
    else:
        return x, attr_dict


class VertexAdd(_NetworkXBuiltin):
    '''
    >> g1 = Graph[{1 -> 2, 2 -> 3}];
    >> g2 = VertexAdd[g1, 4]
     = -Graph-
    >> g3 = VertexAdd[g2, {5, 10}]
     = -Graph-
    '''

    def apply(self, graph, v, evaluation, options):
        '%(name)s[graph_Graph, v_, OptionsPattern[%(name)s]]'
        if v.has_form('List', None):
            return graph.add_vertices(*zip(*[_parse_vertex(x) for x in v.leaves]))
        else:
            return graph.add_vertices(*zip(*[_parse_vertex(v)]))


