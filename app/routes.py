from flask import Flask, request, jsonify, Response
import logging
import json
from app import app, databases, schema_manager

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

@app.route('/nodes', methods=['GET'])
def get_nodes_endpoint():
    nodes = json.dumps(schema_manager.get_nodes(), indent=4)
    return Response(nodes, mimetype='application/json')

@app.route('/edges', methods=['GET'])
def get_edges_endpoint():
    edges = json.dumps(schema_manager.get_edges(), indent=4)
    return Response(edges, mimetype='application/json')

@app.route('/relations/<node_label>', methods=['GET'])
def get_relations_for_node_endpoint(node_label):
    relations = json.dumps(schema_manager.get_relations_for_node(node_label), indent=4)
    return Response(relations, mimetype='application/json')

@app.route('/query', methods=['POST'])
def process_query():
    data = request.get_json()
    if not data or 'requests' not in data:
        return jsonify({"error": "Missing requests data"}), 400
    database_type = 'metta'# data.get('database')
    # if not database_type or database_type not in databases:
    #     return jsonify({"error": "Invalid or missing database parameter"}), 400
    try:
        db_instance = databases[database_type]
        requests = data['requests']
        query_code = db_instance.query_Generator(requests)
        result = db_instance.run_query(query_code)
        parsed_result = db_instance.parse_and_serialize(str(result))
        parsed_result_list = json.loads(parsed_result)
        unique_nodes = set()
        for item in parsed_result_list:
            source, target = item["source"], item["target"]
            unique_nodes.add(source)
            unique_nodes.add(target)
        properties = []
        for node in unique_nodes:
            properties.append(db_instance.get_node_properties([node], schema_manager.schema))
        parsed_properties = db_instance.parse_and_serialize_properties(str(properties))
        response_data = {
            "Generated query": query_code,
            "Result": json.loads(parsed_result),
            "Properties": json.loads(parsed_properties)
        }
        formatted_response = json.dumps(response_data, indent=4)
        return Response(formatted_response, mimetype='application/json')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

