#pragma once
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

// Formats a list of Neo4j records into {"nodes": [...], "edges": [...]}
// Handles flat Node/Relationship records AND CALL subquery list-of-maps results.
py::dict format_neo4j_graph(py::object results, py::dict graph_components);

// Formats count query results into
// {"node_count", "edge_count", "node_count_by_label", "edge_count_by_label"}
py::dict format_neo4j_count(py::object results, py::dict graph_components);