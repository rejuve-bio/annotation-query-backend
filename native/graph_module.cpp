#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include "graph_core.hpp"

namespace py = pybind11;

Graph py_to_graph(const py::dict& obj) {
    Graph g;

    if (obj.contains("nodes")) {
        py::list nodes = obj["nodes"].cast<py::list>();
        for (auto item : nodes) {
            try {
                py::dict n_dict = item.cast<py::dict>();
                Node n;
                py::dict data = n_dict.contains("data")
                                ? n_dict["data"].cast<py::dict>()
                                : n_dict;

                if (!data.contains("id")) {
                    throw std::runtime_error("Node is missing required field 'id'");
                }
                n.id = data["id"].cast<std::string>();

                for (auto const& [k, v] : data) {
                    n.attrs[k.cast<std::string>()] = v.cast<py::object>();
                }
                g.nodes.push_back(std::move(n));

            } catch (const py::cast_error& e) {
                throw std::runtime_error(
                    std::string("Failed to parse node: ") + e.what());
            }
        }
    }

    if (obj.contains("edges")) {
        py::list edges = obj["edges"].cast<py::list>();
        for (auto item : edges) {
            try {
                py::dict e_dict = item.cast<py::dict>();
                Edge e;
                py::dict data = e_dict.contains("data")
                                ? e_dict["data"].cast<py::dict>()
                                : e_dict;

                // source and target are required — fail clearly if missing
                if (!data.contains("source") || !data.contains("target")) {
                    throw std::runtime_error(
                        "Edge is missing required field 'source' or 'target'");
                }

                e.id      = data.contains("id")
                            ? data["id"].cast<std::string>()
                            : generate_nanoid();
                e.source  = data["source"].cast<std::string>();
                e.target  = data["target"].cast<std::string>();
                e.edge_id = data.contains("edge_id")
                            ? data["edge_id"].cast<std::string>()
                            : "";
                e.label   = data.contains("label")
                            ? data["label"].cast<std::string>()
                            : "";

                for (auto const& [k, v] : data) {
                    e.attrs[k.cast<std::string>()] = v.cast<py::object>();
                }
                g.edges.push_back(std::move(e));

            } catch (const py::cast_error& e) {
                throw std::runtime_error(
                    std::string("Failed to parse edge: ") + e.what());
            }
        }
    }

    return g;
}

py::dict graph_to_py_wrapped(const Graph& g) {
    return convert_to_graph_json(g, true);
}

PYBIND11_MODULE(graph_native, m) {

    m.def("group_node_only", [](py::dict g, py::dict r) {
        return graph_to_py_wrapped(group_node_only(py_to_graph(g), r));
    });

    // Returns a dict with two named keys instead of a raw std::pair,
    // which avoids pybind11 conversion issues with deeply nested map types.
    m.def("get_node_to_connections_map", [](py::dict g) {
        auto [mapping, nodes] = get_node_to_connections_map(py_to_graph(g));
        py::dict result;
        result["mapping"] = mapping;
        result["nodes"]   = nodes;
        return result;
    });

    m.def("collapse_nodes", [](py::dict g) {
        return graph_to_py_wrapped(collapse_nodes(py_to_graph(g)));
    });

    m.def("collapse_node_nx", [](py::dict g) {
        return graph_to_py_wrapped(collapse_node_nx(py_to_graph(g)));
    });

    m.def("convert_to_graph_json", [](py::dict g, bool allow_data) {
        return convert_to_graph_json(py_to_graph(g), allow_data);
    }, py::arg("g"), py::arg("allow_data") = true);

    m.def("group_into_parents", [](py::dict g) {
        return graph_to_py_wrapped(group_into_parents(py_to_graph(g)));
    });

    m.def("group_graph", [](py::dict g) {
        return graph_to_py_wrapped(group_graph(py_to_graph(g)));
    });

    m.def("break_grouping", [](py::dict g) {
        return graph_to_py_wrapped(break_grouping(py_to_graph(g)));
    });

    m.def("collapse_node_nx_location", [](py::dict g) {
        return graph_to_py_wrapped(collapse_node_nx_location(py_to_graph(g)));
    });

    m.def("build_subgraph_nx", [](py::dict g) {
        auto components = build_subgraph_nx(py_to_graph(g));
        py::list res;
        for (const auto& cg : components) {
            res.append(graph_to_py_wrapped(cg));
        }
        return res;
    });
}