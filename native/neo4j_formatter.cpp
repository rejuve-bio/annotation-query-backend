#include "neo4j_formatter.hpp"
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <functional>
#include <cctype>
#include <iostream>

namespace py = pybind11;

// ---------------------------------------------------------------------------
// Logging helper — all output goes to stderr so it appears in container logs
// ---------------------------------------------------------------------------
static void log(const std::string& level, const std::string& msg) {
    std::cerr << "[neo4j_formatter][" << level << "] " << msg << std::endl;
}
#define LOG_INFO(msg)  log("INFO",  msg)
#define LOG_WARN(msg)  log("WARN",  msg)
#define LOG_ERROR(msg) log("ERROR", msg)
#define LOG_DEBUG(msg) log("DEBUG", msg)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static const std::vector<std::string> NAMED_TYPES = {
    "gene_name", "transcript_name", "protein_name", "pathway_name", "term_name"
};

static const std::unordered_map<std::string, std::string> NAMED_TYPES_DICT = {
    {"gene",        "gene_name"},
    {"transcript",  "transcript_name"},
    {"protein",     "protein_name"},
    {"pathway",     "pathway_name"},
    {"term",        "term_name"},
};

static std::string to_lower(std::string s) {
    for (auto& c : s) c = std::tolower(c);
    return s;
}

static std::string get_type_name(const py::object& obj) {
    try {
        return py::str(obj.get_type().attr("__name__")).cast<std::string>();
    } catch (...) {
        return "<unknown>";
    }
}

// Use attribute-based duck typing instead of class name comparison.
// The Neo4j driver names relationship objects after their rel-type string
// (e.g. "translates_to"), not "Relationship", so is_neo4j_type(..., "Relationship")
// never matches. Check structural attributes instead.
static bool is_neo4j_relationship(const py::object& obj) {
    try {
        return py::hasattr(obj, "start_node") &&
               py::hasattr(obj, "end_node") &&
               py::hasattr(obj, "type");
    } catch (...) {
        return false;
    }
}

static bool is_neo4j_node(const py::object& obj) {
    try {
        return py::hasattr(obj, "labels") && py::hasattr(obj, "items");
    } catch (...) {
        return false;
    }
}

// ---------------------------------------------------------------------------
// Graph formatting
// ---------------------------------------------------------------------------

py::dict format_neo4j_graph(py::object results, py::dict graph_components) {
    LOG_INFO("format_neo4j_graph called");

    py::list nodes;
    py::list edges;
    std::unordered_map<std::string, bool> node_seen;
    std::unordered_set<std::string> edge_seen;

    bool properties_enabled = true;
    if (graph_components.contains("properties")) {
        try {
            properties_enabled = graph_components["properties"].cast<bool>();
        } catch (...) {
            LOG_WARN("Could not cast graph_components['properties'] to bool, defaulting to true");
        }
    }
    LOG_INFO("properties_enabled = " + std::string(properties_enabled ? "true" : "false"));

    // -- register a neo4j Node object --
    auto register_node = [&](py::object item) {
        try {
            py::object labels = item.attr("labels");
            std::string label = py::str(*labels.begin()).cast<std::string>();
            std::string raw_id = py::str(item.attr("__getitem__")(py::str("id"))).cast<std::string>();
            std::string node_id = label + " " + raw_id;

            if (node_seen.count(node_id)) {
                LOG_DEBUG("Node already seen, skipping: " + node_id);
                return;
            }
            node_seen[node_id] = true;
            LOG_INFO("Registering node: " + node_id);

            py::dict node_data;
            node_data["id"]   = py::str(node_id);
            node_data["type"] = py::str(label);

            int prop_count = 0;
            for (auto kv : item.attr("items")()) {
                py::tuple pair = kv.cast<py::tuple>();
                std::string key = pair[0].cast<std::string>();
                py::object  val = pair[1].cast<py::object>();
                
                std::unordered_set<std::string> to_avoid = {
                    "id",
                    "synonym",
                    "build_id",
                    "import_timestamp",
                    "atomspace_version",
                    "source_url"
                };

                if (properties_enabled) {
                    if (to_avoid.find(key) == to_avoid.end()) {
                        node_data[py::str(key)] = val;
                        prop_count++;
                    }
                } else {
                    for (const auto& nt : NAMED_TYPES) {
                        if (key == nt) {
                            node_data["name"] = val;
                            break;
                        }
                    }
                }
            }
            LOG_DEBUG("Node " + node_id + " properties copied: " + std::to_string(prop_count));

            // name fallback
            if (!node_data.contains("name")) {
                std::string lower_label = to_lower(label);
                auto it = NAMED_TYPES_DICT.find(lower_label);
                if (it != NAMED_TYPES_DICT.end()) {
                    std::string fallback_key = it->second;
                    if (node_data.contains(py::str(fallback_key))) {
                        node_data["name"] = node_data[py::str(fallback_key)];
                        LOG_DEBUG("Node " + node_id + " name set from fallback key: " + fallback_key);
                    } else {
                        node_data["name"] = py::str(node_id);
                        LOG_DEBUG("Node " + node_id + " name defaulted to node_id");
                    }
                } else {
                    node_data["name"] = py::str(node_id);
                    LOG_DEBUG("Node " + node_id + " name defaulted to node_id (no named_types entry)");
                }
            }

            py::dict wrapped;
            wrapped["data"] = node_data;
            nodes.append(wrapped);
            LOG_INFO("Node registered successfully: " + node_id);

        } catch (const std::exception& e) {
            LOG_ERROR("register_node threw exception: " + std::string(e.what()));
        } catch (...) {
            LOG_ERROR("register_node threw unknown exception");
        }
    };

    // -- register a neo4j Relationship object --
    auto register_relationship = [&](py::object item) {
        try {
            py::object start_node = item.attr("start_node");
            py::object end_node   = item.attr("end_node");

            std::string src_label = py::str(*start_node.attr("labels").begin()).cast<std::string>();
            std::string tgt_label = py::str(*end_node.attr("labels").begin()).cast<std::string>();
            std::string src_raw   = py::str(start_node.attr("__getitem__")(py::str("id"))).cast<std::string>();
            std::string tgt_raw   = py::str(end_node.attr("__getitem__")(py::str("id"))).cast<std::string>();
            std::string source_id = src_label + " " + src_raw;
            std::string target_id = tgt_label + " " + tgt_raw;
            std::string rel_type  = py::str(item.attr("type")).cast<std::string>();

            std::string sig = source_id + " - " + rel_type + " - " + target_id;
            LOG_INFO("Registering relationship: " + sig);

            if (edge_seen.count(sig)) {
                LOG_DEBUG("Relationship already seen, skipping: " + sig);
                return;
            }
            edge_seen.insert(sig);

            py::dict edge_data;
            edge_data["edge_id"] = py::str(src_label + "_" + rel_type + "_" + tgt_label);
            edge_data["label"]   = py::str(rel_type);
            edge_data["source"]  = py::str(source_id);
            edge_data["target"]  = py::str(target_id);

            int prop_count = 0;
            for (auto kv : item.attr("items")()) {
                py::tuple pair = kv.cast<py::tuple>();
                std::string key = pair[0].cast<std::string>();
                py::object  val = pair[1].cast<py::object>();
                if (key == "source") {
                    edge_data["source_data"] = val;
                } else {
                    edge_data[py::str(key)] = val;
                }
                prop_count++;
            }
            LOG_DEBUG("Relationship " + sig + " properties copied: " + std::to_string(prop_count));

            py::dict wrapped;
            wrapped["data"] = edge_data;
            edges.append(wrapped);
            LOG_INFO("Relationship registered successfully: " + sig);

            // always register endpoint nodes
            LOG_DEBUG("Registering start_node of relationship: " + sig);
            register_node(start_node);
            LOG_DEBUG("Registering end_node of relationship: " + sig);
            register_node(end_node);

        } catch (const std::exception& e) {
            LOG_ERROR("register_relationship threw exception: " + std::string(e.what()));
        } catch (...) {
            LOG_ERROR("register_relationship threw unknown exception");
        }
    };

    // -- process a single value from a record --
    // Relationship is identified by start_node + end_node + type attributes.
    // Node is identified by labels + items attributes.
    std::function<void(py::object)> process_value = [&](py::object item) {
        std::string type_name = get_type_name(item);
        LOG_DEBUG("process_value: type = " + type_name);

        if (is_neo4j_relationship(item)) {
            // Must check relationship before node — both have .items()
            LOG_DEBUG("process_value: dispatching to register_relationship");
            register_relationship(item);
        } else if (is_neo4j_node(item)) {
            LOG_DEBUG("process_value: dispatching to register_node");
            register_node(item);
        } else if (py::isinstance<py::list>(item)) {
            LOG_DEBUG("process_value: item is a list (CALL subquery path)");
            py::list lst = item.cast<py::list>();
            LOG_DEBUG("process_value: list length = " + std::to_string(lst.size()));
            for (auto entry : lst) {
                py::object entry_obj = entry.cast<py::object>();
                std::string entry_type = get_type_name(entry_obj);
                LOG_DEBUG("process_value: list entry type = " + entry_type);
                if (py::isinstance<py::dict>(entry_obj)) {
                    LOG_DEBUG("process_value: list entry is dict, iterating values");
                    for (auto kv : entry_obj.cast<py::dict>()) {
                        process_value(kv.second.cast<py::object>());
                    }
                } else {
                    process_value(entry_obj);
                }
            }
        } else {
            LOG_DEBUG("process_value: unhandled type = " + type_name + ", skipping");
        }
    };

    // -- iterate records --
    // into plain dicts/tuples, destroying type information needed for dispatch.
    // Use record.keys() + record.__getitem__() to preserve raw Neo4j objects.
    LOG_INFO("Starting record iteration");
    int record_idx = 0;
    for (auto record : results) {
        py::object rec = record.cast<py::object>();
        LOG_DEBUG("Processing record #" + std::to_string(record_idx));

        try {
            py::list keys = rec.attr("keys")().cast<py::list>();
            LOG_DEBUG("Record #" + std::to_string(record_idx) +
                      ": keys count = " + std::to_string(keys.size()));

            for (auto key : keys) {
                std::string key_str = key.cast<std::string>();
                py::object val = rec.attr("__getitem__")(key).cast<py::object>();
                LOG_DEBUG("Record #" + std::to_string(record_idx) +
                          ": key = " + key_str +
                          ", value type = " + get_type_name(val));
                process_value(val);
            }
        } catch (const std::exception& e) {
            LOG_ERROR("Record #" + std::to_string(record_idx) +
                      ": key iteration failed: " + std::string(e.what()));
        } catch (...) {
            LOG_ERROR("Record #" + std::to_string(record_idx) +
                      ": key iteration failed (unknown)");
        }

        record_idx++;
    }

    LOG_INFO("Record iteration complete. nodes=" + std::to_string(py::len(nodes)) +
             " edges=" + std::to_string(py::len(edges)));

    py::dict result;
    result["nodes"] = nodes;
    result["edges"] = edges;
    return result;
}

// ---------------------------------------------------------------------------
// Count formatting
// ---------------------------------------------------------------------------

py::dict format_neo4j_count(py::object results, py::dict graph_components) {
    LOG_INFO("format_neo4j_count called");

    py::list results_list;
    try {
        results_list = results.cast<py::list>();
    } catch (...) {
        LOG_ERROR("format_neo4j_count: could not cast results to list");
        return py::dict();
    }

    LOG_INFO("format_neo4j_count: results list size = " +
             std::to_string(results_list.size()));

    if (results_list.empty()) {
        LOG_WARN("format_neo4j_count: empty results, returning empty dict");
        return py::dict();
    }

    long node_count = 0;
    long edge_count = 0;

    try {
        py::object first = results_list[0].cast<py::object>();
        bool read_first = false;

        // Try plain dict cast first
        try {
            py::dict first_dict = first.cast<py::dict>();
            try {
                node_count = first_dict["total_nodes"].cast<long>();
                LOG_INFO("format_neo4j_count: total_nodes = " + std::to_string(node_count));
            } catch (...) {
                LOG_WARN("format_neo4j_count: could not read total_nodes from dict");
            }
            try {
                edge_count = first_dict["total_edges"].cast<long>();
                LOG_INFO("format_neo4j_count: total_edges = " + std::to_string(edge_count));
            } catch (...) {
                LOG_WARN("format_neo4j_count: could not read total_edges from dict");
            }
            read_first = true;
        } catch (...) {
            LOG_WARN("format_neo4j_count: first result is not a plain dict, trying Neo4j Record");
        }

        // Fall back to keys() + __getitem__ for Neo4j Record
        if (!read_first) {
            try {
                py::list keys = first.attr("keys")().cast<py::list>();
                LOG_DEBUG("format_neo4j_count: first result keys count = " +
                          std::to_string(keys.size()));
                for (auto key : keys) {
                    std::string key_str = key.cast<std::string>();
                    py::object val = first.attr("__getitem__")(key).cast<py::object>();
                    LOG_DEBUG("format_neo4j_count: first result key = " + key_str);
                    if (key_str == "total_nodes") {
                        try {
                            node_count = val.cast<long>();
                            LOG_INFO("format_neo4j_count: total_nodes = " +
                                     std::to_string(node_count));
                        } catch (...) {
                            LOG_WARN("format_neo4j_count: could not cast total_nodes");
                        }
                    } else if (key_str == "total_edges") {
                        try {
                            edge_count = val.cast<long>();
                            LOG_INFO("format_neo4j_count: total_edges = " +
                                     std::to_string(edge_count));
                        } catch (...) {
                            LOG_WARN("format_neo4j_count: could not cast total_edges");
                        }
                    }
                }
            } catch (...) {
                LOG_ERROR("format_neo4j_count: keys() iteration also failed on first result");
            }
        }
    } catch (...) {
        LOG_ERROR("format_neo4j_count: failed to read first result row");
    }

    // Build aggregation maps from graph_components
    std::unordered_map<std::string, long> node_agg;
    std::unordered_map<std::string, long> edge_agg;

    if (graph_components.contains("nodes")) {
        try {
            for (auto n : graph_components["nodes"].cast<py::list>()) {
                std::string type = n.cast<py::dict>()["type"].cast<std::string>();
                node_agg[type] = 0;
                LOG_DEBUG("format_neo4j_count: tracking node type: " + type);
            }
        } catch (...) {
            LOG_WARN("format_neo4j_count: failed to read graph_components nodes");
        }
    }

    if (graph_components.contains("predicates")) {
        try {
            for (auto p : graph_components["predicates"].cast<py::list>()) {
                std::string type = p.cast<py::dict>()["type"].cast<std::string>();
                std::string key;
                for (char c : type) key += (c == ' ') ? '_' : std::tolower(c);
                edge_agg[key] = 0;
                LOG_DEBUG("format_neo4j_count: tracking edge type: " + key);
            }
        } catch (...) {
            LOG_WARN("format_neo4j_count: failed to read graph_components predicates");
        }
    }

    // Aggregate counts by label from second result
    if (results_list.size() > 1) {
        try {
            py::object second = results_list[1].cast<py::object>();
            py::dict label_data;
            bool got_data = false;

            // Try plain dict cast first
            try {
                label_data = second.cast<py::dict>();
                got_data = true;
                LOG_DEBUG("format_neo4j_count: read label counts via direct dict cast");
            } catch (...) {
                LOG_WARN("format_neo4j_count: second result is not a plain dict, trying .data()");
            }

            // Fall back to .data()
            if (!got_data) {
                try {
                    label_data = second.attr("data")().cast<py::dict>();
                    got_data = true;
                    LOG_DEBUG("format_neo4j_count: read label counts via .data()");
                } catch (...) {
                    LOG_WARN("format_neo4j_count: .data() also failed on second result");
                }
            }

            // Fall back to keys() + __getitem__
            if (!got_data) {
                try {
                    py::list keys = second.attr("keys")().cast<py::list>();
                    for (auto key : keys) {
                        std::string key_str = key.cast<std::string>();
                        py::object val = second.attr("__getitem__")(key).cast<py::object>();
                        label_data[py::str(key_str)] = val;
                    }
                    got_data = true;
                    LOG_DEBUG("format_neo4j_count: read label counts via keys() + __getitem__");
                } catch (...) {
                    LOG_ERROR("format_neo4j_count: all methods failed to read second result");
                }
            }

            if (got_data) {
                for (auto kv : label_data) {
                    std::string key = kv.first.cast<std::string>();
                    long value = 0;
                    try {
                        value = kv.second.cast<long>();
                    } catch (...) {
                        LOG_WARN("format_neo4j_count: could not cast value for key: " + key);
                    }

                    // strip node_var prefix: "n5_Gene" -> "Gene", "p0_regulates" -> "regulates"
                    size_t pos = key.find('_');
                    std::string label_key = (pos != std::string::npos)
                        ? key.substr(pos + 1)
                        : key;

                    LOG_DEBUG("format_neo4j_count: label key = " + label_key +
                              ", value = " + std::to_string(value));

                    if (node_agg.count(label_key)) {
                        node_agg[label_key] += value;
                        LOG_DEBUG("format_neo4j_count: added to node_agg[" + label_key +
                                  "] = " + std::to_string(node_agg[label_key]));
                    }
                    if (edge_agg.count(label_key)) {
                        edge_agg[label_key] += value;
                        LOG_DEBUG("format_neo4j_count: added to edge_agg[" + label_key +
                                  "] = " + std::to_string(edge_agg[label_key]));
                    }
                }
            }
        } catch (...) {
            LOG_ERROR("format_neo4j_count: exception processing second result row");
        }
    }

    // Build output lists
    py::list node_count_by_label;
    for (auto const& [k, v] : node_agg) {
        py::dict entry;
        entry["label"] = py::str(k);
        entry["count"] = py::int_(v);
        node_count_by_label.append(entry);
        LOG_INFO("format_neo4j_count: node label count: " + k +
                 " = " + std::to_string(v));
    }

    py::list edge_count_by_label;
    for (auto const& [k, v] : edge_agg) {
        py::dict entry;
        entry["label"] = py::str(k);
        entry["count"] = py::int_(v);
        edge_count_by_label.append(entry);
        LOG_INFO("format_neo4j_count: edge label count: " + k +
                 " = " + std::to_string(v));
    }

    py::dict result;
    result["node_count"]          = py::int_(node_count);
    result["edge_count"]          = py::int_(edge_count);
    result["node_count_by_label"] = node_count_by_label;
    result["edge_count_by_label"] = edge_count_by_label;

    LOG_INFO("format_neo4j_count complete: node_count=" + std::to_string(node_count) +
             " edge_count=" + std::to_string(edge_count));
    return result;
}