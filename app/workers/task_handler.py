import json
import logging
import os
import traceback
from pathlib import Path

import pysam
from celery import chord

# Global Variables
from app.api.deps import (
    get_db_instance,
    get_llm_handler,
    get_redis_client,
    get_schema_manager,
)
from app.constants import TaskStatus, QUERY_MAX_NODES
from app.core.config import settings
from app.error import TaskCancelledException
from app.events import RedisStopEvent
from app.lib import Graph
from app.persistence import AnnotationStorageService
import datetime as dt
from app.lib.utils import format_duration as _format_duration
from .celery_app import celery_app, redis_state
import time

logger = logging.getLogger(__name__)

# Initialize globals via deps
schema_manager = get_schema_manager()

def get_db_for_species(species):
    return get_db_instance(species)


redis_client = get_redis_client()

EXP = os.getenv("REDIS_EXPIRATION", 3600)

llm = get_llm_handler()
db_type = settings.DATABASE_TYPE.get("type")


def update_task(annotation_id, task_type, status):
    if task_type == "graph":
        redis_state.hset(f"annotation:{annotation_id}", "graph_done", status)
    if task_type == "total_count":
        redis_state.hset(f"annotation:{annotation_id}", "total_count_done", status)
    if task_type == "label_count":
        redis_state.hset(f"annotation:{annotation_id}", "count_by_label_done", status)
    if task_type == "summary":
        redis_state.hset(f"annotation:{annotation_id}", "summary_done", status)

def get_status(annotation_id):
    val = redis_state.hget(f"annotation:{annotation_id}", "status")
    return val.decode("utf-8") if val else None

def set_status(annotation_id, status):
    redis_state.hset(f"annotation:{annotation_id}", "status", status)


def get_annotation_redis(annotation_id):
    cache = redis_client.get(str(annotation_id))
    if cache is not None:
        cache = json.loads(cache)
        return cache
    else:
        return None


def check_for_cancellation(annotation_id):
    """
    Checks for the cancellation flag.
    If cancelled, raises an exception to abort the flow.
    """
    current_status = get_status(annotation_id)

    if current_status is None or current_status == TaskStatus.CANCELLED.value:
        raise TaskCancelledException()


def reset_status(annotation_id):
    redis_client.delete(f"{annotation_id}_tasks")
    set_status(annotation_id, TaskStatus.PENDING.value)


def reset_task(annotation_id):
    redis_client.delete(f"{annotation_id}_tasks")
    redis_client.delete(str(annotation_id))


def save_result_redis(annotation_id, result):
    redis_client.setex(str(annotation_id), EXP, json.dumps(result))


def generate_empty_label_count(requests):
    update = {"node_count_by_label": [], "edge_count_by_label": []}
    node_count_by_label = {}
    edge_count_by_label = {}

    for node in requests["nodes"]:
        node_count_by_label[node["type"]] = 0

    for edges in requests["predicates"]:
        edge_count_by_label[edges["type"]] = 0

    for key, value in node_count_by_label.items():
        update["node_count_by_label"].append({key: value})

    for key, value in edge_count_by_label.items():
        update["edge_count_by_label"].append({key: value})

    return update


# --- TASKS ---


@celery_app.task
def summary_task(chord_results, annotation_id, request, all_status, summary=None):
    try:
        if get_status(annotation_id) == TaskStatus.FAILED.value:
            summary = "Failed to generate summary"
            update_task(annotation_id, "summary", 1)
            set_status(annotation_id, TaskStatus.FAILED.value)
            AnnotationStorageService.update(
                annotation_id, {"status": TaskStatus.FAILED.value, "summary": summary}
            )
            socket_event = {
                "status": TaskStatus.FAILED.value,
                "update": {"summary": summary},
                "annotation_id": annotation_id,
            }
            redis_client.publish("socket_event", json.dumps(socket_event))
            return

        check_for_cancellation(annotation_id)

        if summary is not None:
            created_at = getattr(meta_data, 'created_at', None)
            total_ms = round((dt.datetime.now() - created_at).total_seconds() * 1000) if created_at else None
            update_task(annotation_id, "summary", 1)
            set_status(annotation_id, TaskStatus.COMPLETE.value)
            AnnotationStorageService.update(
                annotation_id, {"status": TaskStatus.COMPLETE.value, "summary": summary}
            )
            socket_event = {
                "status": TaskStatus.COMPLETE.value,
                "update": {"summary": summary},
                "annotation_id": annotation_id,
            }
            redis_client.publish("socket_event", json.dumps(socket_event))
            return

        # 1. Fetch Existing Cache (Populated by graph_task)
        cache = get_annotation_redis(annotation_id)
        check_for_cancellation(annotation_id)

        meta_data = AnnotationStorageService.get_by_id(annotation_id)

        response = {"nodes": [], "edges": []}
        if cache is not None:
            graph = cache.get("graph")
            if graph is not None:
                response = {
                    "nodes": graph.get("nodes", []),
                    "edges": graph.get("edges", []),
                }
        else:
            # If cache is missing for some reason, initialize it so we don't crash
            cache = {}

        response["node_count"] = meta_data.node_count
        response["edge_count"] = meta_data.edge_count
        response["node_count_by_label"] = meta_data.node_count_by_label
        response["edge_count_by_label"] = meta_data.edge_count_by_label

        if len(response["nodes"]) == 0:
            summary = "No summary for this graph because the graph is empty"
        else:
            summary = llm.generate_summary(response, request)
            summary = summary if summary else "Graph too big, could not summarize"

        created_at = getattr(meta_data, 'created_at', None)
        total_ms = round((dt.datetime.now() - created_at).total_seconds() * 1000) if created_at else None

        AnnotationStorageService.update(annotation_id, {
            "summary": summary,
            "status": TaskStatus.COMPLETE.value,
            "total_duration": _format_duration(total_ms),
        })
        
        update_task(annotation_id, "summary", 1)

        # 2. Update the Cache with Summary and Status
        cache["summary"] = summary
        cache["status"] = TaskStatus.COMPLETE.value  # This marks the whole flow as done

        # 3. Save back to Redis
        save_result_redis(annotation_id, cache)

        socket_event = {
            "status": TaskStatus.COMPLETE.value,
            "update": {"summary": summary},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))

        redis_state.expire(f"annotation:{annotation_id}", 60)
    except TaskCancelledException as e:
        set_status(annotation_id, TaskStatus.CANCELLED.value)
        socket_event = {
            "status": TaskStatus.CANCELLED.value,
            "update": {"summary": "Summary cancelled"},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        redis_state.expire(f"annotation:{annotation_id}", 60)
        logger.error("Cancelled generating result graph %s", e)
    except Exception as e:
        AnnotationStorageService.update(
            annotation_id, {"summary": summary, "status": TaskStatus.COMPLETE.value}
        )
        cache = get_annotation_redis(annotation_id) or {}
        # 2. Update the Cache with Summary and Status
        cache["summary"] = "Graph too big, could not summarize"
        cache["status"] = TaskStatus.COMPLETE.value  # This marks the whole flow as done

        # 3. Save back to Redis
        save_result_redis(annotation_id, cache)
        logger.exception("Error generating summary %s", e)
        socket_event = {
            "status": TaskStatus.COMPLETE.value,
            "update": {"summary": "Graph too big, could not summarize"},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        redis_state.expire(f"annotation:{annotation_id}", 60)


@celery_app.task
def graph_task(
    query_code, annotation_id, requests, result_status, species, status=None
):
    try:
        db_instance = get_db_for_species(species)
        check_for_cancellation(annotation_id)

        if get_status(annotation_id) == TaskStatus.CANCELLED.value:
            socket_event = {
                "status": TaskStatus.CANCELLED.value,
                "update": {"graph": False},
                "annotation_id": annotation_id,
            }
            redis_client.publish("socket_event", json.dumps(socket_event))
            return

        stop_event = RedisStopEvent(annotation_id, redis_state)

        t0 = time.time()
        response_data = db_instance.run_query(query_code, stop_event, species)
        retrieval_ms = round((time.time() - t0) * 1000)
        
        if db_type == "mork_cli":
            all_atoms = response_data[0] if response_data else []
            truncated = len(all_atoms) > QUERY_MAX_NODES
            if truncated:
                logging.info(f"[graph_task] Capping {len(all_atoms)} atoms → {QUERY_MAX_NODES} for {annotation_id}")
                all_atoms = all_atoms[:QUERY_MAX_NODES]

        graph_components = {
            "nodes": requests["nodes"],
            "predicates": requests["predicates"],
            "properties": True,
        }
        
        t1 = time.time()
        response = db_instance.parse_and_serialize(
            response_data,
            schema_manager.full_schema_representation,
            graph_components,
            "graph",
        )
        processing_ms = round((time.time() - t1) * 1000)
        
        if db_type == "mork_cli":
            response['truncated'] = truncated
            if truncated:
                AnnotationStorageService.update(annotation_id, {"node_count": response['node_count']})
    
        snp_nodes = [n for n in response["nodes"] if n["data"].get("label") == "snp"]

        if snp_nodes:
            snp_nodes.sort(
                key=lambda x: (x["data"].get("chr", ""), int(x["data"].get("start", 0)))
            )
            unique_chroms = sorted(
                list(
                    set(n["data"].get("chr") for n in snp_nodes if n["data"].get("chr"))
                )
            )

            vcf_dir = Path("/app/public/vcf")
            vcf_dir.mkdir(parents=True, exist_ok=True)
            vcf_path = vcf_dir / f"{annotation_id}.vcf"

            with open(vcf_path, "w") as vcf_file:
                vcf_file.write("##fileformat=VCFv4.2\n")
                vcf_file.write(f"##source=GenomicGraphAnnotation_{annotation_id}\n")
                vcf_file.write("##reference=hg38\n")
                for chrom in unique_chroms:
                    vcf_file.write(f"##contig=<ID={chrom}>\n")

                vcf_file.write(
                    '##INFO=<ID=CAF_REF,Number=1,Type=Float,Description="Reference allele frequency">\n'
                )
                vcf_file.write(
                    '##INFO=<ID=CAF_ALT,Number=.,Type=Float,Description="Alternate allele frequency">\n'
                )
                vcf_file.write(
                    '##INFO=<ID=CADD_RAW,Number=1,Type=Float,Description="Raw CADD score">\n'
                )
                vcf_file.write(
                    '##INFO=<ID=CADD_PHRED,Number=1,Type=Float,Description="Phred CADD score">\n'
                )
                vcf_file.write(
                    '##INFO=<ID=NAME,Number=1,Type=String,Description="Variant Name">\n'
                )
                vcf_file.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n")

                for snp in snp_nodes:
                    d = snp["data"]
                    chrom = d.get("chr", ".")
                    pos = d.get("start", "0")
                    raw_id = d.get("id", ".")
                    vid = raw_id.replace(" ", "_") if raw_id else "."
                    ref = d.get("ref", ".")
                    alt = d.get("alt", ".")
                    qual = "."
                    filt = "PASS"

                    info_parts = []
                    if "caf_ref" in d:
                        info_parts.append(f"CAF_REF={d['caf_ref']}")
                    if "caf_alt" in d:
                        info_parts.append(f"CAF_ALT={d['caf_alt']}")
                    if "raw_cadd_score" in d:
                        info_parts.append(f"CADD_RAW={d['raw_cadd_score']}")
                    if "phred_score" in d:
                        info_parts.append(f"CADD_PHRED={d['phred_score']}")
                    if "name" in d:
                        safe_name = str(d["name"]).replace(";", "_").replace(" ", "_")
                        info_parts.append(f"NAME={safe_name}")

                    info_str = ";".join(info_parts) if info_parts else "."
                    vcf_file.write(
                        f"{chrom}\t{pos}\t{vid}\t{ref}\t{alt}\t{qual}\t{filt}\t{info_str}\n"
                    )

            pysam.tabix_index(str(vcf_path), preset="vcf", force=True)

        graph = Graph()

        if len(response["edges"]) == 0 and len(response["nodes"]) > 0:
            grouped_graph = graph.group_node_only(response, requests)
        else:
            grouped_graph = graph.group_graph(response)

        base_graph_dir = Path("/app/public/graph")
        file_path = base_graph_dir / f"{annotation_id}.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, "w") as file:
            json.dump(grouped_graph, file)
            
        
        timing_update = {
            "retrieval_duration": _format_duration(retrieval_ms),
            "processing_duration": _format_duration(processing_ms),
        }

        if snp_nodes:
            AnnotationStorageService.update(
                annotation_id,
                {
                    "path_url": str(file_path.resolve()),
                    "files": [
                        {
                            "type": "vcf",
                            "file": f"/public/vcf/{annotation_id}.vcf.gz",
                            "index": f"/public/vcf/{annotation_id}.vcf.gz.tbi",
                        }
                    ], **timing_update
                },
            )
        else:
            AnnotationStorageService.update(
                annotation_id, {"path_url": str(file_path.resolve()), "files": None, **timing_update}
            )

        status = status or TaskStatus.PENDING.value
        set_status(annotation_id, status)

        update_task(annotation_id, "graph", 1)

        # Save Result with Status
        save_result_redis(annotation_id, {"status": status, "graph": grouped_graph})

        socket_event = {
            "status": status,
            "update": {"graph": True},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        return

    except TaskCancelledException as e:
        set_status(annotation_id, TaskStatus.CANCELLED.value)
        # Even on fail/cancel, save empty structure with status so client doesn't hang
        save_result_redis(
            annotation_id,
            {
                "status": TaskStatus.CANCELLED.value,
                "nodes": [],
                "edges": [],
                "graph": {"nodes": [], "edges": []},
            },
        )
        socket_event = {
            "status": TaskStatus.CANCELLED.value,
            "update": {"graph": False},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        logger.error("Cancelling generating result graph %s", e)
    except Exception as e:
        set_status(annotation_id, TaskStatus.FAILED.value)
        socket_event = {
            "status": TaskStatus.FAILED.value,
            "update": {"graph": False},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        AnnotationStorageService.update(
            annotation_id, {"status": TaskStatus.FAILED.value}
        )
        logger.error("Error generating result graph %s", e)


@celery_app.task
def total_count_task(
    count_query, annotation_id, requests, total_count_status, species, meta_data=None
):
    db_instance = get_db_for_species(species)
    if get_status(annotation_id) == TaskStatus.FAILED.value:
        socket_event = {
            "status": TaskStatus.FAILED.value,
            "update": {"node_count": 0, "edge_count": 0},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        return

    if get_status(annotation_id) == TaskStatus.CANCELLED.value:
        socket_event = {
            "status": TaskStatus.CANCELLED.value,
            "update": {"node_count": 0, "edge_count": 0},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        return

    if meta_data:
        update_task(annotation_id, "total_count", 0)
        socket_event = {
            "status": TaskStatus.PENDING.value,
            "update": {
                "node_count": meta_data["node_count"],
                "edge_count": meta_data["edge_count"],
            },
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        return

    try:
        total_count = db_instance.run_query(count_query, None, species)

        if db_type in ["mork", "mork_cli"]:
            result = db_instance.parse_and_serialize(
                total_count,
                schema_manager.full_schema_representation,
                {
                    "nodes": requests.get("nodes", []),
                    "predicates": requests.get("predicates", []),
                    "properties": True,
                },
                "graph",
            )

            count_result = [result, {}]
            total_count = db_instance.parse_and_serialize(
                count_result, schema_manager.full_schema_representation, {}, "count"
            )
            update_task(annotation_id, "total_count", 1)
            AnnotationStorageService.update(
                annotation_id,
                {
                    "node_count": result["node_count"],
                    "edge_count": result["edge_count"],
                    "status": TaskStatus.PENDING.value,
                },
            )
            socket_event = {
                "status": TaskStatus.PENDING.value,
                "update": {
                    "node_count": total_count["node_count"],
                    "edge_count": total_count["edge_count"],
                },
                "annotation_id": annotation_id,
            }
            redis_client.publish("socket_event", json.dumps(socket_event))
            return

        if len(total_count) == 0:
            update_task(annotation_id, "total_count", 1)
            AnnotationStorageService.update(
                annotation_id,
                {"status": TaskStatus.PENDING.value, "node_count": 0, "edge_count": 0},
            )
            socket_event = {
                "status": TaskStatus.PENDING.value,
                "update": {"node_count": 0, "edge_count": 0},
                "annotation_id": annotation_id,
            }
            redis_client.publish("socket_event", json.dumps(socket_event))
            return

        count_result = [total_count[0], {}]
        graph_components = {
            "nodes": requests["nodes"],
            "predicates": requests["predicates"],
            "properties": False,
        }
        response = db_instance.parse_and_serialize(
            count_result,
            schema_manager.full_schema_representation,
            graph_components,
            "count",
        )

        update_task(annotation_id, "total_count", 1)
        status = TaskStatus.PENDING.value
        AnnotationStorageService.update(
            annotation_id,
            {
                "node_count": response["node_count"],
                "edge_count": response["edge_count"],
                "status": status,
            },
        )
        socket_event = {
            "status": status,
            "update": {
                "node_count": response["node_count"],
                "edge_count": response["edge_count"],
            },
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))

    except TaskCancelledException:
        set_status(annotation_id, TaskStatus.CANCELLED.value)
        update_task(annotation_id, "total_count", 1)
        socket_event = {
            "status": TaskStatus.CANCELLED.value,
            "update": {"node_count": 0, "edge_count": 0},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        logger.error("Cancelled generating total count")

    except Exception as e:
        set_status(annotation_id, TaskStatus.FAILED.value)
        update_task(annotation_id, "total_count", 0)
        AnnotationStorageService.update(
            annotation_id,
            {"status": TaskStatus.FAILED.value, "node_count": 0, "edge_count": 0},
        )
        socket_event = {
            "status": TaskStatus.FAILED.value,
            "update": {"node_count": 0, "edge_count": 0},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        logger.error("Error generating total count %s", e)
        traceback.print_exc()


@celery_app.task
def label_count_task(
    count_query,
    annotation_id,
    requests,
    count_label_status,
    species="human",
    meta_data=None,
):
    db_instance = get_db_for_species(species)
    if get_status(annotation_id) == TaskStatus.FAILED.value:
        update = generate_empty_label_count(requests)
        update_task(annotation_id, "label_count", 0)
        socket_event = {
            "status": TaskStatus.FAILED.value,
            "update": update,
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        return

    if get_status(annotation_id) == TaskStatus.CANCELLED.value:
        update_task(annotation_id, "label_count", 1)
        socket_event = {
            "status": TaskStatus.CANCELLED.value,
            "update": {"node_count_by_label": [], "edge_count_by_label": []},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        return

    try:
        if meta_data:
            status = TaskStatus.PENDING.value
            update_task(annotation_id, "label_count", 1)
            socket_event = {
                "status": status,
                "update": {
                    "node_count_by_label": meta_data["node_count_by_label"],
                    "edge_count_by_label": meta_data["edge_count_by_label"],
                },
                "annotation_id": annotation_id,
            }
            redis_client.publish("socket_event", json.dumps(socket_event))
            return

        if db_type in ["mork", "mork_cli"]:
            count_result = db_instance.run_query(count_query, None, species)
            result = db_instance.parse_and_serialize(
                count_result,
                schema_manager.full_schema_representation,
                {
                    "nodes": requests.get("nodes", []),
                    "predicates": requests.get("predicates", []),
                    "properties": True,
                },
                "graph",
            )

            count_result = [{}, result]
            total_count = db_instance.parse_and_serialize(
                count_result, schema_manager.full_schema_representation, {}, "count"
            )
            update_task(annotation_id, "label_count", 1)
            status = TaskStatus.PENDING.value
            AnnotationStorageService.update(
                annotation_id,
                {
                    "node_count_by_label": result["node_count_by_label"],
                    "edge_count_by_label": result["edge_count_by_label"],
                    "status": status,
                },
            )
            socket_event = {
                "status": status,
                "update": {
                    "node_count_by_label": total_count["node_count_by_label"],
                    "edge_count_by_label": total_count["edge_count_by_label"],
                },
                "annotation_id": annotation_id,
            }
            redis_client.publish("socket_event", json.dumps(socket_event))
            return

        label_count = db_instance.run_query(count_query, None, species)
        count_result = [{}, label_count[0]]
        graph_components = {
            "nodes": requests["nodes"],
            "predicates": requests["predicates"],
            "properties": False,
        }
        response = db_instance.parse_and_serialize(
            count_result,
            schema_manager.full_schema_representation,
            graph_components,
            "count",
        )

        AnnotationStorageService.update(
            annotation_id,
            {
                "node_count_by_label": response["node_count_by_label"],
                "edge_count_by_label": response["edge_count_by_label"],
            },
        )
        update_task(annotation_id, "label_count", 1)
        status = TaskStatus.PENDING.value
        socket_event = {
            "status": status,
            "update": {
                "node_count_by_label": response["node_count_by_label"],
                "edge_count_by_label": response["edge_count_by_label"],
            },
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))

    except TaskCancelledException:
        set_status(annotation_id, TaskStatus.CANCELLED.value)
        update_task(annotation_id, "label_count", 1)
        socket_event = {
            "status": TaskStatus.CANCELLED.value,
            "update": {"node_count_by_label": [], "edge_count_by_label": []},
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        logger.error("Cancelled generating label count")

    except Exception as e:
        set_status(annotation_id, TaskStatus.FAILED.value)
        update_task(annotation_id, "label_count", 0)
        update = generate_empty_label_count(requests)
        AnnotationStorageService.update(
            annotation_id,
            {
                "status": TaskStatus.FAILED.value,
                "node_count_by_label": update["node_count_by_label"],
                "edge_count_by_label": update["edge_count_by_label"],
            },
        )
        socket_event = {
            "status": TaskStatus.FAILED.value,
            "update": update,
            "annotation_id": annotation_id,
        }
        redis_client.publish("socket_event", json.dumps(socket_event))
        logger.error("Error generating label count %s", e)
        traceback.print_exc()


def start_thread(annotation_id, args):
    annotation_id = str(annotation_id)
    all_status = args["all_status"]
    find_query = args["query"][0]
    total_count_query = args["query"][1]
    label_count_query = args["query"][2]
    request = args["request"]
    summary = args["summary"]
    meta_data = args["meta_data"]
    species = args["species"]

    workflow = chord(
        [
            graph_task.s(
                find_query, annotation_id, request, all_status["result_done"], species
            ),
            total_count_task.s(
                total_count_query,
                annotation_id,
                request,
                all_status["total_count_done"],
                species,
                meta_data,
            ),
            label_count_task.s(
                label_count_query,
                annotation_id,
                request,
                all_status["label_count_done"],
                species,
                meta_data,
            ),
        ],
        summary_task.s(annotation_id, request, all_status, summary),
    )

    workflow.apply_async()
