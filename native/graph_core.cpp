#include "graph_core.hpp"
#include <random>
#include <algorithm>
#include <sstream>
#include <set>
#include <tuple>

using namespace std;


string generate_nanoid() {
    static const char alphabet[] = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ";
    static random_device rd;
    static mt19937 gen(rd());
    static uniform_int_distribution<> dis(0, sizeof(alphabet) - 2);
    
    string id = "";
    for (int i = 0; i < 21; ++i) {
        id += alphabet[dis(gen)];
    }
    return id;
}

string extract_middle(const string& s) {
    size_t first = s.find('_');
    size_t last = s.rfind('_');
    if (first == string::npos || first == last) {
        if (first != string::npos) return s.substr(first + 1);
        return "";
    }
    return s.substr(first + 1, last - first - 1);
}

Graph group_node_only(const Graph& graph, const py::dict& request) {
    Graph new_graph;
    unordered_map<string, vector<py::dict>> node_map_by_label;
    
    py::list request_nodes = request["nodes"];
    for (auto item : request_nodes) {
        py::dict node = item.cast<py::dict>();
        node_map_by_label[node["type"].cast<string>()] = {};
    }
    
    for (const auto& node : graph.nodes) {
        string type = node.attrs.at("type").cast<string>();
        if (node_map_by_label.count(type)) {
            py::dict data;
            for (auto const& [key, val] : node.attrs) {
                data[py::str(key)] = val;
            }
            node_map_by_label[type].push_back(data);
        }
    }
    
    for (auto& [node_type, nodes] : node_map_by_label) {
        if (nodes.empty()) continue;
        
        Node new_node;
        new_node.id = generate_nanoid();
        new_node.attrs["id"] = py::cast(new_node.id);
        new_node.attrs["type"] = py::cast(node_type);
        new_node.attrs["name"] = py::cast(to_string(nodes.size()) + " " + node_type + " nodes");
        
        py::list nodes_list;
        for (const auto& n : nodes) nodes_list.append(n);
        new_node.attrs["nodes"] = nodes_list;
        
        new_graph.nodes.push_back(new_node);
    }
    
    return new_graph;
}

pair<unordered_map<string, unordered_map<string, py::dict>>, unordered_map<string, py::dict>> get_node_to_connections_map(const Graph& graph) {
    unordered_map<string, py::dict> node_to_id_map;
    for (const auto& node : graph.nodes) {
        py::dict data;
        for (auto const& [key, val] : node.attrs) data[py::str(key)] = val;
        node_to_id_map[node.id] = data;
    }
    
    unordered_map<string, unordered_map<string, py::dict>> node_mapping;
    
    auto add_to_map = [&](const Edge& edge, bool is_source) {
        string node_key = is_source ? edge.source : edge.target;
        string other_node = is_source ? edge.target : edge.source;
        
        auto& connections = node_mapping[node_key];
        if (connections.find(edge.edge_id) == connections.end()) {
            py::dict conn;
            conn["is_source"] = py::cast(is_source);
            conn["nodes"] = py::set();
            conn["edge_id"] = py::cast(edge.edge_id);
            connections[edge.edge_id] = conn;
        }
        connections[edge.edge_id]["nodes"].cast<py::set>().add(other_node);
    };
    
    for (const auto& edge : graph.edges) {
        add_to_map(edge, true);
        add_to_map(edge, false);
    }
    
    return {node_mapping, node_to_id_map};
}

py::dict convert_to_graph_json(const Graph& graph, bool allow_data) {
    py::dict res;
    py::list nodes;
    for (const auto& n : graph.nodes) {
        if (allow_data) {
            py::dict d;
            d["data"] = n.attrs;
            nodes.append(d);
        } else {
            nodes.append(n.attrs);
        }
    }
    py::list edges;
    for (const auto& e : graph.edges) {
        py::dict ed;
        py::dict ed_data;
        // copy attrs first
        for (auto const& [k, v] : e.attrs) ed_data[py::str(k)] = v;
        // then overwrite with the correct remapped values
        ed_data["id"] = py::cast(e.id);
        ed_data["source"] = py::cast(e.source);
        ed_data["target"] = py::cast(e.target);
        ed_data["edge_id"] = py::cast(e.edge_id);
        ed_data["label"] = py::cast(e.label);
        if (allow_data) {
            ed["data"] = ed_data;
            edges.append(ed);
        } else {
            edges.append(ed_data);
        }
    }
    res["nodes"] = nodes;
    res["edges"] = edges;
    return res;
}

Graph collapse_nodes(const Graph& graph) {
    auto [node_mapping, node_to_id_map] = get_node_to_connections_map(graph);
    
    unordered_map<string, py::dict> map_string;
    unordered_map<string, string> ids;
    unordered_map<string, string> sig_to_id;
    
    for (auto const& [node_id, connections] : node_mapping) {
        vector<string> sig_parts;
        for (auto const& [edge_id, conn] : connections) {
            py::list nodes_list = py::list(conn["nodes"]);
            vector<string> nodes_vec;
            for (auto n : nodes_list) nodes_vec.push_back(n.cast<string>());
            sort(nodes_vec.begin(), nodes_vec.end());
            
            string part = (conn["is_source"].cast<bool>() ? "S" : "T") + edge_id;
            for (const auto& n : nodes_vec) part += "|" + n;
            sig_parts.push_back(part);
        }
        sort(sig_parts.begin(), sig_parts.end());
        string full_sig = "";
        for (const auto& s : sig_parts) full_sig += s + ";";
        
        // generate a clean nanoid for each unique signature
        if (sig_to_id.find(full_sig) == sig_to_id.end()) {
            sig_to_id[full_sig] = generate_nanoid();
        }
        string group_id = sig_to_id[full_sig];
        
        if (map_string.find(full_sig) == map_string.end()) {
            py::dict group;
            group["nodes"] = py::list();
            py::list conns_list;
            for (auto const& [edge_id, conn] : connections) conns_list.append(conn);
            group["connections"] = conns_list;
            map_string[full_sig] = group;
        }
        map_string[full_sig]["nodes"].cast<py::list>().append(node_to_id_map[node_id]);
        ids[node_id] = full_sig;  // still maps node → sig for lookup
    }
    
    Graph new_graph;
    for (auto const& [group_sig, group] : map_string) {
        py::list group_nodes = group["nodes"].cast<py::list>();
        if (group_nodes.empty()) continue;
        
        string group_id = sig_to_id[group_sig];
        
        unordered_set<string> group_node_ids;
        for (auto n : group_nodes) group_node_ids.insert(n.cast<py::dict>()["id"].cast<string>());
        
        py::dict rep_node;
        for (const auto& n : graph.nodes) {
            if (group_node_ids.count(n.id)) {
                for (auto const& [k, v] : n.attrs) rep_node[py::str(k)] = v;
                break;
            }
        }
        
        string node_type = rep_node["type"].cast<string>();
        string name = (group_nodes.size() == 1)
                      ? rep_node["name"].cast<string>()
                      : to_string(group_nodes.size()) + " " + node_type + " nodes";
        
        Node new_node;
        new_node.id = group_id;
        new_node.attrs["id"] = py::cast(group_id);
        new_node.attrs["type"] = py::cast(node_type);
        new_node.attrs["name"] = py::cast(name);
        new_node.attrs["nodes"] = group_nodes;
        new_graph.nodes.push_back(new_node);
        
        unordered_set<string> added;
        py::list conns = group["connections"].cast<py::list>();
        for (auto c_item : conns) {
            py::dict c = c_item.cast<py::dict>();
            if (c["is_source"].cast<bool>()) {
                py::list target_nodes = py::list(c["nodes"]);
                for (auto tn : target_nodes) {
                    string tn_str = tn.cast<string>();
                    if (ids.count(tn_str)) {
                        string other_sig = ids[tn_str];
                        string other_id = sig_to_id[other_sig];
                        string edge_id = c["edge_id"].cast<string>();
                        string key = edge_id + group_id + other_id;
                        if (added.find(key) == added.end()) {
                            Edge e;
                            e.id = generate_nanoid();
                            e.edge_id = edge_id;
                            e.label = extract_middle(edge_id);
                            e.source = group_id;   
                            e.target = other_id;
                            new_graph.edges.push_back(e);
                            added.insert(key);
                        }
                    }
                }
            }
        }
    }
    return new_graph;
}

Graph collapse_node_nx(const Graph& graph) {
    struct Adj {
        set<pair<string, string>> in;
        set<pair<string, string>> out;
    };
    unordered_map<string, Adj> adj;
    unordered_map<string, py::dict> node_data_map;
    unordered_map<string, string> original_to_group;

    for (const auto& n : graph.nodes) {
        py::dict data;
        for (auto const& [k, v] : n.attrs) data[py::str(k)] = v;
        node_data_map[n.id] = data;

        if (n.attrs.count("nodes")) {
            py::list children = n.attrs.at("nodes").cast<py::list>();
            for (auto child : children) {
                try {
                    py::dict child_dict = child.cast<py::dict>();
                    if (child_dict.contains("id")) {
                        string orig_id = child_dict["id"].cast<std::string>();
                        original_to_group[orig_id] = n.id;
                    }
                } catch (...) {}
            }
        }
        original_to_group[n.id] = n.id;
    }

    int dbg = 0;
    for (const auto& e : graph.edges) {
        if (dbg++ >= 3) break;
        bool src_found = original_to_group.count(e.source) > 0;
        bool tgt_found = original_to_group.count(e.target) > 0;
    }

    for (const auto& e : graph.edges) {
        string src = original_to_group.count(e.source) ? original_to_group[e.source] : e.source;
        string tgt = original_to_group.count(e.target) ? original_to_group[e.target] : e.target;
        adj[tgt].in.insert({src, e.edge_id});
        adj[src].out.insert({tgt, e.edge_id});
    }

    unordered_map<string, vector<string>> groups;
    for (const auto& n : graph.nodes) {
        string sig = "I";
        for (auto const& p : adj[n.id].in) sig += "|" + p.first + ":" + p.second;
        sig += ";O";
        for (auto const& p : adj[n.id].out) sig += "|" + p.first + ":" + p.second;
        groups[sig].push_back(n.id);
    }

    Graph result;
    unordered_map<string, string> old_to_new;

    for (auto const& [sig, nodes] : groups) {
        string merged_id = generate_nanoid();
        for (const auto& old_id : nodes) old_to_new[old_id] = merged_id;

        string base_type = node_data_map[nodes[0]]["type"].cast<string>();
        string name = (nodes.size() == 1)
                      ? node_data_map[nodes[0]]["name"].cast<string>()
                      : to_string(nodes.size()) + " " + base_type + " nodes";

        Node mn;
        mn.id = merged_id;
        mn.attrs["id"]   = py::cast(merged_id);
        mn.attrs["type"] = py::cast(base_type);
        mn.attrs["name"] = py::cast(name);

        py::list children;
        for (const auto& old_id : nodes) children.append(node_data_map[old_id]);
        mn.attrs["nodes"] = children;

        result.nodes.push_back(mn);
    }

    set<tuple<string, string, string>> added_edges;
    for (const auto& e : graph.edges) {
        string raw_s = original_to_group.count(e.source) ? original_to_group[e.source] : e.source;
        string raw_t = original_to_group.count(e.target) ? original_to_group[e.target] : e.target;
        string s = old_to_new.count(raw_s) ? old_to_new[raw_s] : raw_s;
        string t = old_to_new.count(raw_t) ? old_to_new[raw_t] : raw_t;

        if (s.empty() || t.empty() || s == t) continue;

        auto key = make_tuple(s, t, e.edge_id);
        if (added_edges.find(key) == added_edges.end()) {
            Edge ne = e;
            ne.id     = generate_nanoid();
            ne.source = s;
            ne.target = t;
            result.edges.push_back(ne);
            added_edges.insert(key);
        }
    }

    return result;
}

Graph group_into_parents(Graph graph) {
    auto [node_mapping, node_to_id_map] = get_node_to_connections_map(graph);
    
    struct ParentInfo {
        string id;
        string node;
        string edge_id;
        string label;
        int count;
        bool is_source;
        set<string> key_nodes_set;
    };
    
    unordered_map<string, ParentInfo> parent_map;
    
    for (auto const& [node_id, connections] : node_mapping) {
        for (auto const& [edge_id, record] : connections) {
            py::set nodes_set = record["nodes"].cast<py::set>();
            if (nodes_set.size() < 2) continue;
            
            vector<string> key_nodes;
            for (auto n : nodes_set) key_nodes.push_back(n.cast<string>());
            sort(key_nodes.begin(), key_nodes.end());
            
            string key = "";
            for (const auto& k : key_nodes) key += (key.empty() ? "" : ",") + k;
            
            if (parent_map.find(key) == parent_map.end()) {
                ParentInfo pi;
                pi.id = generate_nanoid();
                pi.node = node_id;
                pi.edge_id = edge_id;
                pi.label = extract_middle(edge_id);
                pi.count = key_nodes.size();
                pi.is_source = record["is_source"].cast<bool>();
                for (const auto& k : key_nodes) pi.key_nodes_set.insert(k);
                parent_map[key] = pi;
            }
        }
    }
    
    unordered_set<string> invalid_groups;
    for (auto const& [k1, p1] : parent_map) {
        for (auto const& [k2, p2] : parent_map) {
            if (k1 == k2) continue;
            if (p1.is_source == p2.is_source && p2.count > p1.count) {
                bool intersect = false;
                for (const auto& n : p1.key_nodes_set) {
                    if (p2.key_nodes_set.count(n)) { intersect = true; break; }
                }
                if (intersect) { invalid_groups.insert(k1); break; }
            }
        }
    }
    for (const auto& k : invalid_groups) parent_map.erase(k);
    
    unordered_set<string> active_parents;
    unordered_map<string, vector<string>> grouped_nodes;
    
    for (auto& n : graph.nodes) {
        int max_count = 0;
        string selected_parent = "";
        for (auto const& [key, p] : parent_map) {
            if (p.key_nodes_set.count(n.id) && p.count > max_count) {
                selected_parent = p.id;
                max_count = p.count;
            }
        }
        if (!selected_parent.empty()) {
            n.attrs["parent"] = py::cast(selected_parent);
            active_parents.insert(selected_parent);
            grouped_nodes[selected_parent].push_back(n.id);
        }
    }
    
    for (auto const& [pid, nodes] : grouped_nodes) {
        if (nodes.size() < 2) {
            active_parents.erase(pid);
            for (auto& n : graph.nodes) {
                if (n.attrs.count("parent") && n.attrs["parent"].cast<string>() == pid) {
                    n.attrs["parent"] = py::cast("");
                }
            }
        }
    }
    
    for (const auto& p : active_parents) {
        Node pn;
        pn.id = p;
        pn.attrs["id"] = py::cast(p);
        pn.attrs["type"] = py::cast("parent");
        pn.attrs["name"] = py::cast(p);
        graph.nodes.push_back(pn);
    }
    
    vector<Edge> new_edges;
    for (const auto& e : graph.edges) {
        bool keep = true;
        for (auto const& [key, p] : parent_map) {
            if (active_parents.find(p.id) == active_parents.end()) continue;
            string edge_neighbor = p.is_source ? e.target : e.source;
            string edge_parent = p.is_source ? e.source : e.target;
            
            if (p.key_nodes_set.count(edge_neighbor) && p.node == edge_parent && p.edge_id == e.edge_id) {
                keep = false;
                break;
            }
        }
        if (keep) new_edges.push_back(e);
    }
    
    for (auto const& [key, p] : parent_map) {
        if (active_parents.find(p.id) == active_parents.end()) continue;
        Edge ne;
        ne.id = generate_nanoid();
        ne.edge_id = p.edge_id;
        ne.label = p.label;
        if (p.is_source) { ne.source = p.node; ne.target = p.id; }
        else { ne.source = p.id; ne.target = p.node; }
        new_edges.push_back(ne);
    }
    graph.edges = new_edges;
    return graph;
}

Graph group_graph(const Graph& graph) {
    return group_into_parents(collapse_node_nx(graph));
}

Graph break_grouping(const Graph& graph) {
    unordered_map<string, vector<string>> parent_to_children;
    unordered_set<string> parent_ids;
    for (const auto& n : graph.nodes) {
        if (n.attrs.count("type") && n.attrs.at("type").cast<string>() == "parent") {
            parent_ids.insert(n.id);
            parent_to_children[n.id] = {};
        }
    }
    for (const auto& n : graph.nodes) {
        if (n.attrs.count("parent")) {
            string pid = n.attrs.at("parent").cast<string>();
            if (parent_ids.count(pid)) parent_to_children[pid].push_back(n.id);
        }
    }
    
    vector<Edge> intermediate_edges;
    for (const auto& e : graph.edges) {
        if (parent_ids.count(e.source)) {
            for (const auto& child : parent_to_children[e.source]) {
                Edge ne = e; ne.id = generate_nanoid(); ne.source = child; intermediate_edges.push_back(ne);
            }
        } else if (parent_ids.count(e.target)) {
            for (const auto& child : parent_to_children[e.target]) {
                Edge ne = e; ne.id = generate_nanoid(); ne.target = child; intermediate_edges.push_back(ne);
            }
        } else {
            intermediate_edges.push_back(e);
        }
    }
    
    unordered_map<string, py::dict> node_id_map;
    for (const auto& n : graph.nodes) node_id_map[n.id] = py::cast(n.attrs);
    
    struct EdgeRel { string s, l, t; };
    map<string, EdgeRel> final_rels;
    
    for (const auto& e : intermediate_edges) {
        if (node_id_map.count(e.source) && node_id_map.count(e.target)) {
            py::dict s_data = node_id_map[e.source];
            py::dict t_data = node_id_map[e.target];
            
            vector<string> s_nodes, t_nodes;
            if (s_data["type"].cast<string>() != "parent") {
                if (s_data.contains("nodes")) {
                    for (auto n : s_data["nodes"].cast<py::list>()) s_nodes.push_back(n.cast<py::dict>()["id"].cast<string>());
                } else s_nodes.push_back(e.source);
            }
            if (t_data["type"].cast<string>() != "parent") {
                if (t_data.contains("nodes")) {
                    for (auto n : t_data["nodes"].cast<py::list>()) t_nodes.push_back(n.cast<py::dict>()["id"].cast<string>());
                } else t_nodes.push_back(e.target);
            }
            
            for (const auto& sn : s_nodes) {
                for (const auto& tn : t_nodes) {
                    string key = sn + "_" + e.label + "_" + tn;
                    final_rels[key] = {sn, e.label, tn};
                }
            }
        }
    }
    
    Graph result;
    for (auto const& [key, rel] : final_rels) {
        Edge ne;
        ne.id = generate_nanoid();
        ne.source = rel.s;
        ne.target = rel.t;
        ne.label = rel.l;
        // Edge ID reconstruction logic from Python: f'{edge_id_arr[0]}_{middle}'
        ne.edge_id = rel.s + "_" + rel.l; 
        result.edges.push_back(ne);
    }
    
    unordered_set<string> added_nodes;
    for (const auto& n : graph.nodes) {
        if (n.attrs.count("type") && n.attrs.at("type").cast<string>() != "parent") {
            if (n.attrs.count("nodes")) {
                for (auto sn : n.attrs.at("nodes").cast<py::list>()) {
                    py::dict snd = sn.cast<py::dict>();
                    string sid = snd["id"].cast<string>();
                    if (added_nodes.find(sid) == added_nodes.end()) {
                        Node nn; 
                        nn.id = sid; 
                        for (auto const& [k, v] : snd) nn.attrs[k.cast<string>()] = py::reinterpret_borrow<py::object>(v);
                        result.nodes.push_back(nn); 
                        added_nodes.insert(sid);
                    }
                }
            } else {
                if (added_nodes.find(n.id) == added_nodes.end()) {
                    result.nodes.push_back(n); added_nodes.insert(n.id);
                }
            }
        }
    }
    return result;
}

Graph collapse_node_nx_location(const Graph& graph) {
    Graph expanded;
    unordered_map<string, string> orig_to_main;
    unordered_map<string, py::dict> node_data;
    
    for (const auto& n : graph.nodes) {
        string locs = n.attrs.count("location") ? n.attrs.at("location").cast<string>() : "";
        vector<string> loc_list;
        stringstream ss(locs);
        string item;
        while (getline(ss, item, ',')) {
            item.erase(0, item.find_first_not_of(" "));
            item.erase(item.find_last_not_of(" ") + 1);
            if (!item.empty()) loc_list.push_back(item);
        }
        if (loc_list.empty()) loc_list.push_back("");
        
        string main_id = "";
        for (size_t i = 0; i < loc_list.size(); ++i) {
            Node dn = n;
            string did = (loc_list.size() > 1) ? n.id + "_loc_" + to_string(i) : n.id;
            dn.id = did;
            dn.attrs["id"] = py::cast(did);
            dn.attrs["location"] = py::cast(loc_list[i]);
            if (i == 0) main_id = did;
            else dn.attrs["duplicate"] = py::cast(true);
            expanded.nodes.push_back(dn);
            py::dict d;
            for (auto const& [k, v] : dn.attrs) d[py::str(k)] = v;
            node_data[did] = d;
        }
        orig_to_main[n.id] = main_id;
    }
    
    for (const auto& e : graph.edges) {
        Edge ne = e;
        ne.source = orig_to_main[e.source];
        ne.target = orig_to_main[e.target];
        expanded.edges.push_back(ne);
    }
    
    
    return collapse_node_nx(expanded); 
}

vector<Graph> build_subgraph_nx(const Graph& graph) {
    // Weakly connected components
    unordered_map<string, vector<string>> adj;
    for (const auto& e : graph.edges) {
        adj[e.source].push_back(e.target);
        adj[e.target].push_back(e.source);
    }
    
    unordered_set<string> visited;
    vector<Graph> components;
    
    for (const auto& n : graph.nodes) {
        if (visited.find(n.id) == visited.end()) {
            unordered_set<string> component_nodes;
            vector<string> q = {n.id};
            visited.insert(n.id);
            while (!q.empty()) {
                string curr = q.back(); q.pop_back();
                component_nodes.insert(curr);
                for (const auto& nb : adj[curr]) {
                    if (visited.find(nb) == visited.end()) {
                        visited.insert(nb); q.push_back(nb);
                    }
                }
            }
            
            Graph cg;
            for (const auto& node : graph.nodes) if (component_nodes.count(node.id)) cg.nodes.push_back(node);
            for (const auto& edge : graph.edges) if (component_nodes.count(edge.source) && component_nodes.count(edge.target)) cg.edges.push_back(edge);
            components.push_back(cg);
        }
    }
    return components;
}