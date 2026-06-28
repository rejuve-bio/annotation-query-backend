#pragma once
#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <utility>

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

struct Node {
    std::string id;
    std::unordered_map<std::string, py::object> attrs;
};

struct Edge {
    std::string id;
    std::string source;
    std::string target;
    std::string edge_id;
    std::string label;
    std::unordered_map<std::string, py::object> attrs;
};

struct Graph {
    std::vector<Node> nodes;
    std::vector<Edge> edges;
};

// Internal signature types
struct Connection {
    std::string edge_id;
    bool is_source;
    std::vector<std::string> target_nodes; // sorted
    bool operator<(const Connection& other) const {
        if (is_source != other.is_source) return is_source < other.is_source;
        if (edge_id != other.edge_id)     return edge_id < other.edge_id;
        return target_nodes < other.target_nodes;
    }
};

// Function prototypes
std::string generate_nanoid();

Graph group_node_only(const Graph& graph, const py::dict& request);

std::pair<
    std::unordered_map<std::string, std::unordered_map<std::string, py::dict>>,
    std::unordered_map<std::string, py::dict>
> get_node_to_connections_map(const Graph& graph);

Graph collapse_nodes(const Graph& graph);
Graph collapse_node_nx(const Graph& graph);

py::dict convert_to_graph_json(const Graph& graph, bool allow_data = true);

Graph group_into_parents(Graph graph);
Graph group_graph(const Graph& graph);
Graph break_grouping(const Graph& graph);
Graph collapse_node_nx_location(const Graph& graph);

std::vector<Graph> build_subgraph_nx(const Graph& graph);