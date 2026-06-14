import logging
import meilisearch
import os
from typing import Optional

logger = logging.getLogger(__name__)

LABEL_NAME_PROPERTY: dict[str, Optional[str]] = {
    # shared (human + fly)
    "gene": "gene_name",
    "transcript": "transcript_name",
    "protein": "protein_name",
    "pathway": "pathway_name",
    "reaction": "reaction_name",
    "motif": "tf_name",
    "ontology_term": "term_name",
    "anatomy": "term_name",
    "biological_process": "term_name",
    "cellular_component": "term_name",
    "molecular_function": "term_name",
    "disease": "term_name",
    "phenotype": "term_name",
    "developmental_stage": "term_name",
    "experimental_factor": "term_name",
    "small_molecule": "term_name",
    "sequence_type": "term_name",
    "molecular_interaction": "term_name",
    # fly-only
    "allele": "allele_symbol",
    "gene_group": "group_name",
    "genotype": "genotype_symbols",
    "dmel_disease_model": "do_term_name",
    "rnaseq_library": "name",
    "metabolic_pathway_gene_group": "group_name",
    "signaling_pathway_gene_group": "group_name",
    "phenotype_set": "phenotype_ontology_id",
    # human-only
    "cell_line": "term_name",
    "cell_type": "term_name",
    "tissue": "term_name",
    "snp": None,
    "enhancer": None,
    "super_enhancer": None,
    "tad": None,
    "chromosome": None,
    "sequence_variant": "rsid",
    "structural_variant": "variant_accession",
    "regulatory_region": None,
    "tfbs": None,
}

# Labels that only exist in one species
HUMAN_ONLY_LABELS = {
    "cell_line",
    "cell_type",
    "tissue",
    "snp",
    "enhancer",
    "super_enhancer",
    "tad",
    "chromosome",
    "sequence_variant",
    "structural_variant",
    "regulatory_region",
    "tfbs",
}
FLY_ONLY_LABELS = {
    "allele",
    "gene_group",
    "genotype",
    "dmel_disease_model",
    "rnaseq_library",
    "metabolic_pathway_gene_group",
    "signaling_pathway_gene_group",
    "phenotype_set",
}

INDEX_NAME = "kg_entities"
BATCH_SIZE = 5000


def get_meili_client() -> meilisearch.Client:
    url = os.getenv("MEILI_URL", "http://meilisearch:7700")
    key = os.getenv("MEILI_MASTER_KEY", "")
    return meilisearch.Client(url, key)


def configure_index(client: meilisearch.Client) -> meilisearch.index.Index:
    """Create / update index settings."""
    try:
        client.create_index(INDEX_NAME, {"primaryKey": "id"})
    except Exception:
        pass  # already exists — that's fine
    index = client.index(INDEX_NAME)
    index.update_settings(
        {
            "searchableAttributes": ["name"], 
            "filterableAttributes": ["species", "label"],
            "typoTolerance": {
                "enabled": True,
                "minWordSizeForTypos": {"oneTypo": 3, "twoTypos": 7},
            },
            "rankingRules": [
                "words",
                "typo",
                "proximity",
                "attribute",
                "sort",
                "exactness",
            ],
        }
    )
    return index


def index_is_populated(client: meilisearch.Client) -> bool:
    try:
        return client.index(INDEX_NAME).get_stats().number_of_documents > 0
    except Exception:
        return False


def fetch_and_index(neo4j_generator, client: meilisearch.Client) -> dict:
    """
    Iterate over every indexable label, call
    neo4j_generator.fetch_nodes_for_index() (which uses the existing
    run_query / ResilientDriver infrastructure), then push batches to
    Meilisearch.
    """
    index = configure_index(client)
    total = 0
    errors = []

    for label, name_prop in LABEL_NAME_PROPERTY.items():

        # Decide which species to index for this label
        if label in HUMAN_ONLY_LABELS:
            species_list = ["human"]
        elif label in FLY_ONLY_LABELS:
            # skip fly labels if fly driver is not configured
            if neo4j_generator.fly_driver is None:
                logger.warning(f"[Warning] Skipping {label} — fly driver not configured")
                continue
            species_list = ["fly"]
        else:
            species_list = ["human"]
            if neo4j_generator.fly_driver is not None:
                species_list.append("fly")

        for species in species_list:
            try:
                docs = neo4j_generator.fetch_nodes_for_index(
                    label=label,
                    name_prop=name_prop,
                    species=species,
                )

                if not docs:
                    logger.info(f"ℹ️  No docs for {label}/{species} — skipping")
                    continue

                # Push in batches
                for i in range(0, len(docs), BATCH_SIZE):
                    batch = docs[i : i + BATCH_SIZE]
                    index.add_documents(batch)
                    total += len(batch)

                logger.info(
                    f"[] Indexed {len(docs)} docs  [{label} / {species}]  "
                    f"(running total: {total})"
                )

            except Exception as e:
                msg = f"[Error] {label}/{species}: {e}"
                logger.error(msg)
                errors.append(msg)

    return {"total_indexed": total, "errors": errors}


def search_entities(
    client: meilisearch.Client,
    query: str,
    species: str,
    label: str = None,
    limit: int = 5,
    offset: int = 0,
) -> dict:
    """
    Search kg_entities.
    Filter order: species → label → fuzzy name match.
    """
    filters = [f"species = {species}"]
    if label:
        filters.append(f"label = {label}")

    results = client.index(INDEX_NAME).search(
        query,
        {
            "filter": " AND ".join(filters),
            "limit": limit,
            "offset": offset,
            "attributesToRetrieve": ["neo4j_id", "name", "label", "species"],
        },
    )

    return {
        "hits": results["hits"],
        "total": results.get("estimatedTotalHits", 0),
        "query": query,
        "species": species,
        "label": label,
    }
