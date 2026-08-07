import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from typing import List, Optional, Dict, Any
import json
import logging
from app.api.deps import get_current_user, get_schema_manager
from app.services.schema_data import SchemaManager
from app.persistence import UserStorageService
from app.constants import Species, form_fields
from nanoid import generate
from app.api.deps import get_db_instance, get_schema_manager
from app.lib import Graph
from app.persistence import AnnotationStorageService
from app.lib.utils import convert_to_tsv
import datetime

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/kg-info")
def get_graph_info(
    current_user_id: str = Depends(get_current_user),
    schema_manager: SchemaManager = Depends(get_schema_manager)
):
    return schema_manager.graph_info

@router.get("/nodes")
def get_nodes(
    current_user_id: str = Depends(get_current_user),
    schema_manager: SchemaManager = Depends(get_schema_manager)
):
    user = UserStorageService.get(current_user_id)
    species = user.species if user else 'human'
    nodes = schema_manager.get_nodes()
    return nodes.get(species, [])

@router.get("/edges")
def get_edges(
    current_user_id: str = Depends(get_current_user),
    schema_manager: SchemaManager = Depends(get_schema_manager)
):
    user = UserStorageService.get(current_user_id)
    species = user.species if user else 'human'
    edges = schema_manager.get_edges()
    return edges.get(species, [])

@router.get("/relations/{node_label}")
def get_relations_for_node(
    node_label: str,
    current_user_id: str = Depends(get_current_user),
    schema_manager: SchemaManager = Depends(get_schema_manager)
):
    user = UserStorageService.get(current_user_id)
    species = user.species if user else 'human'
    return schema_manager.get_relations_for_node(node_label, species)

# Helper functions for schema logic (copied/adapted from routes.py)
def node_exists(response, name):
    name = name.strip().lower()
    return any(n['data']['name'].strip().lower() == name for n in response['schema']['nodes'])

def flatten_edges(value):
    sources = value['source'] if isinstance(value['source'], list) else [value['source']]
    targets = value['target'] if isinstance(value['target'], list) else [value['target']]
    label = value.get('output_label') or value.get('input_label') or 'unknown'

    return [
        {
            'data': {
                'source': src,
                'target': tgt,
                'possible_connection': [label]
            }
        }
        for src in sources
        for tgt in targets
    ]

def get_schema_by_source_logic(schema_manager, species, query_string):
    response = {'schema': {'nodes': [], 'edges': []}}

    if species == 'human':
        schema = schema_manager.schmea_representation
    else:
        schema = getattr(schema_manager, 'fly_schmea_representation', None) or \
                 getattr(schema_manager, 'fly_schema_represetnation', {})

    if query_string == 'all' and species == 'fly':
        # Detect if schema is per-source format {SOURCE: {nodes, edges}}
        # or flat format {nodes: {}, edges: {}} from BioCypher fallback
        is_per_source = all(
            isinstance(v, dict) and 'nodes' in v and 'edges' in v
            for v in schema.values()
        ) if schema else False

        if is_per_source:
            for source_name, source_data in schema.items():
                for node_key, node_val in source_data.get('nodes', {}).items():
                    if not node_exists(response, node_val['label']):
                        response['schema']['nodes'].append({
                            'data': {
                                'name': node_val['label'],
                                'properites': [property for property in node_val['properties'].keys()]
                            }
                        })
                for edge_key, edge_val in source_data.get('edges', {}).items():
                    is_new = True
                    for ed in response['schema']['edges']:
                        if edge_val.get('source') == ed['data']['source'] and \
                           edge_val.get('target') == ed['data']['target']:
                            is_new = False
                            ed['data']['possible_connection'].append(
                                edge_val.get('label') or edge_val.get('output_label') or edge_val.get('input_label') or 'unknown'
                            )
                    if is_new:
                        response['schema']['edges'].extend(flatten_edges(edge_val))
        else:
            # Flat format — fly_schema_represetnation from BioCypher
            for key, value in schema.get('nodes', {}).items():
                response['schema']['nodes'].append({
                    'data': {
                        'name': value['label'],
                        'properites': [property for property in value['properties'].keys()]
                    }
                })
            for key, value in schema.get('edges', {}).items():
                is_new = True
                for ed in response['schema']['edges']:
                    if value['source'] == ed['data']['source'] and \
                       value['target'] == ed['data']['target']:
                        is_new = False
                        ed['data']['possible_connection'].append(
                            value.get('label') or value.get('output_label') or value.get('input_label') or 'unknown'
                        )
                if is_new:
                    response['schema']['edges'].extend(flatten_edges(value))
        return response

    # Handle list of sources
    if isinstance(query_string, str):
        query_list = [query_string]
    else:
        query_list = query_string

    sub_schema = None
    source = None

    for schema_type in query_list:
        if schema_type == 'all':
            continue
        source = schema_type.upper()
        sub_schema = schema.get(source, None)

        if sub_schema is None:
            continue

        for _, edge in sub_schema['edges'].items():
            edge_data = {
                'data': {
                    "possible_connection": [edge.get('label') or edge.get('output_label') or edge.get('input_label')],
                    "source": edge.get('source'),
                    "target": edge.get('target')
                }
            }
            response['schema']['edges'].append(edge_data)

            if 'nodes' in schema[source]:
                src_key = edge.get('source', '')
                src_node = schema[source]['nodes'].get(src_key) or \
                           schema[source]['nodes'].get(src_key.replace(' ', '_'))
                if src_node:
                    if not node_exists(response, src_node['label']):
                        response['schema']['nodes'].append({
                            'data': {
                                'name': src_node['label'],
                                'properites': [property for property in src_node['properties'].keys()]
                            }
                        })

            if 'nodes' in schema[source]:
                tgt_key = edge.get('target', '')
                tgt_node = schema[source]['nodes'].get(tgt_key) or \
                           schema[source]['nodes'].get(tgt_key.replace(' ', '_'))
                if tgt_node:
                    if not node_exists(response, tgt_node['label']):
                        response['schema']['nodes'].append({
                            'data': {
                                'name': tgt_node['label'],
                                'properites': [property for property in tgt_node['properties'].keys()]
                            }
                        })

    if len(response['schema']['edges']) == 0 and sub_schema is not None and source is not None:
        for node in sub_schema['nodes']:
            if node in schema[source]['nodes']:
                response['schema']['nodes'].append({
                    'data': {
                        'name': schema[source]['nodes'][node]['label'],
                        'properties': [property for property in schema[source]['nodes'][node]['properties'].keys()]
                    }
                })

    return response

@router.get("/preference-option")
def get_preference_option(
    current_user_id: str = Depends(get_current_user),
    schema_manager: SchemaManager = Depends(get_schema_manager)
):
    response = {
        'species': [specie.value for specie in Species],
        'sources': {
            'human': [],
            'fly': []
        }
    }

    schema_list = schema_manager.schema_list

    for source in schema_list:
        if source['id'] not in ['polyphen-2', 'bgee']:
            sch = get_schema_by_source_logic(schema_manager, 'human', [source['name']])
            data = {
                'id': source['id'],
                'name': source['name'],
                'url': source['url'],
                'schema': sch['schema']
            }
            response['sources']['human'].append(data)

    fly_schema_list = getattr(schema_manager, 'fly_schema_list', [])

    if fly_schema_list:
        for source in fly_schema_list:
            sch = get_schema_by_source_logic(schema_manager, 'fly', [source['name']])
            data = {
                'id': source['id'],
                'name': source['name'],
                'url': source['url'],
                'schema': sch['schema']
            }
            response['sources']['fly'].append(data)
    else:
        # Fallback — no per-source YAML files configured, expose single flyall option
        sch = get_schema_by_source_logic(schema_manager, 'fly', 'all')
        response['sources']['fly'].append({
            'id': 'flyall',
            'name': 'flyall',
            'url': None,
            'schema': sch['schema']
        })

    return response

@router.get("/schema")
def get_schema_by_data_source(
    species: str = 'human',
    data_source: List[str] = Query(default=[]),
    schema_manager: SchemaManager = Depends(get_schema_manager)
):
    
    if len(data_source) == 1 and data_source[0] == 'flyall':
            data_source = 'all'

    schemas = get_schema_by_source_logic(schema_manager, species, data_source)
    
    response = {'nodes': [], 'edges': []}
    nodes = schemas['schema']['nodes']
    edges = schemas['schema']['edges']
    
    for node in nodes:
        label = node['data']['name']
        if label in form_fields:
            node_data = form_fields[label]
        else:
            node_data = []

        response['nodes'].append({
            'id': label,
            'name': label,
            'inputs': node_data
        })

    for edge in edges:
        source = edge['data']['source']
        target = edge['data']['target']
        possible_connections = edge['data']['possible_connection']
        for possible_connection in possible_connections:
            response['edges'].append({
                'id': generate(),
                'source': source,
                'target': target,
                'label': possible_connection
            })
            
    return response

def get_schema_list():
    schema_manager = get_schema_manager()
    schema_list = schema_manager.schema_list
    response = schema_list

    return response

@router.post('/save-preference')
async def update_settings(
    data: Dict[str, Any] = Body(...),
    current_user_id: str = Depends(get_current_user),
    schema_manager: SchemaManager = Depends(get_schema_manager)
):
    data_source = data.get('sources')
    species = data.get('species', 'human')

    if data_source is None:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "error", "error": "Missing data source",
                     "timestamp": datetime.datetime.now().isoformat()}
        )

    # Case 1: String-based — 'all' or 'flyall'
    if isinstance(data_source, str):
        if data_source.lower() in ['all', 'flyall']:
            UserStorageService.upsert_by_user_id(
                current_user_id,
                {'data_source': 'all', 'species': species}
            )
            display_source = ['flyall'] if species == 'fly' else ['all']
            return {'message': 'Data source updated successfully', 'data_source': display_source}
        else:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"status": "error", "error": "Invalid data source format",
                         "timestamp": datetime.datetime.now().isoformat()}
            )

    # Case 2: List-based — validate against the correct species schema list
    if species == 'fly':
        schema_list = getattr(schema_manager, 'fly_schema_list', [])
    else:
        schema_list = schema_manager.schema_list

    valid_ids = {schema['id'].lower() for schema in schema_list if schema.get('id')}

    for ds in data_source:
        if str(ds).lower() not in valid_ids:
            raise HTTPException(status_code=400, detail=f"Invalid data source: {ds}")

    try:
        UserStorageService.upsert_by_user_id(
            current_user_id,
            {'data_source': data_source, 'species': species}
        )
        logger.info(json.dumps({
            "status": "success", "method": "POST",
            "timestamp": datetime.datetime.now().isoformat(),
            "endpoint": "/save-preference"
        }))
        return {'message': 'Data source updated successfully', 'data_source': data_source}

    except Exception as e:
        logger.error(json.dumps({
            "status": "error", "method": "POST",
            "timestamp": datetime.datetime.now().isoformat(),
            "endpoint": "/save-preference", "exception": str(e)
        }), exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "error",
                     "error": "An internal server error occurred. Please try again later.",
                     "timestamp": datetime.datetime.now().isoformat()}
        )

@router.get('/saved-preference')
def get_saved_preferences(current_user_id: str = Depends(get_current_user)):
    try:
        preferences = UserStorageService.get(current_user_id)
        if preferences:
            data_source = preferences.data_source
            species = preferences.species
        else:
            data_source = ['all']
            species = 'human'

        # Normalize to list
        if isinstance(data_source, str):
            data_source = ['flyall'] if species == 'fly' and data_source == 'all' else [data_source]
        
        response_data = {
            'species': species,
            'source': data_source
        }

        logger.info(json.dumps({
            "status": "success", "method": "GET",
            "timestamp": datetime.datetime.now().isoformat(),
            "endpoint": "/saved-preference"
        }))

        return response_data

    except Exception as e:
        logger.error(json.dumps({
            "status": "error", "method": "GET",
            "timestamp": datetime.datetime.now().isoformat(),
            "endpoint": "/saved-preference",
            "exception": str(e)
        }), exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": "An internal server error occurred. Please try again later.",
                "timestamp": datetime.datetime.now().isoformat()
            }
        )

@router.get('/annotation/{id}/download-tsv')
async def download_tsv(id: str, current_user_id: str = Depends(get_current_user)):
    # Fetch annotation metadata
    cursor = AnnotationStorageService.get_by_id(id)
    
    if cursor is None:
        raise HTTPException(status_code=404, detail="Annotation not found")

    file_path = cursor.path_url
    
    try:
        # Load the graph file
        with open(file_path, 'r') as f:
            graph = json.load(f)
        
        # Process graph grouping
        g = Graph()
        new_graph = g.break_grouping(graph)
        
        # Convert to TSV (assuming this returns a BytesIO object)
        file_obj = convert_to_tsv(new_graph)
        
        if file_obj:
            logger.error(json.dumps({"status": "success", "method": "GET",
                      "timestamp":  datetime.datetime.now().isoformat(),
                      "endpoint": "/annotation/<id>/download-tsv"}))
            # Seek to start of stream if it's a file-like object
            file_obj.seek(0)
            
            return StreamingResponse(
                file_obj,
                media_type='application/zip',
                headers={
                    'Content-Disposition': 'attachment; filename="graph_export.zip"'
                }
            )
        else:
            logger.error(json.dumps({
                "status": "error", 
                "method": "GET",
                "timestamp": datetime.datetime.now().isoformat(),
                "endpoint": f"/annotation/{id}/download-tsv",
                "exception": "Error generating the file"
            }))
            return JSONResponse(
                status_code=500,
                content={"status": "error", "message": "Error generating the file"}
            )
        
    except Exception as e:
        logger.error(json.dumps({
            "status": "error", 
            "method": "GET",
            "timestamp": datetime.datetime.now().isoformat(),
            "endpoint": f"/annotation/{id}/download-tsv",
            "exception": str(e)
        }), exc_info=True)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": "An internal server error occurred. Please try again later.",
                "timestamp": datetime.datetime.now().isoformat()
            }
        )
@router.get("/public/vcf/{filename}")
def download_vcf_file(filename: str):
    # Sanitize — strip any path components, only allow the bare filename
    safe_filename = Path(filename).name
    
    # Only allow .vcf.gz and .vcf.gz.tbi extensions
    if not (safe_filename.endswith('.vcf.gz') or safe_filename.endswith('.vcf.gz.tbi')):
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    # Resolve the full path and verify it stays within the allowed directory
    base_dir = Path("/app/public/vcf").resolve()
    file_path = (base_dir / safe_filename).resolve()
    
    if not str(file_path).startswith(str(base_dir)):
        raise HTTPException(status_code=400, detail="Invalid file path")
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="VCF file not found")
    
    return FileResponse(
        path=str(file_path),
        filename=safe_filename,
        media_type="application/octet-stream"
    )