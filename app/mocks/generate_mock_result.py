import time


def generate_node_and_edge_count_mock():
    print("GENERATING COUNT", flush=True)
    time.sleep(1 * 60)
    node_count = 1800
    edge_count = 2100

    print("FINSIHED GENERATING COUNT", flush=True)

    return {'node_count': node_count, 'edge_count': edge_count}


def generate_title_mock():
    title = 'Mocked title'
    return title


def generate_result_graph_mock():
    time.sleep(2 * 60)
    annotation = {
        "nodes": [
            {
                "data": {
                    "id": "gene ensg00000017427",
                    "type": "gene",
                    "gene_name": "IGF1",
                    "gene_type": "protein_coding",
                    "start": "102395874",
                    "end": "102481744",
                    "label": "gene",
                    "chr": "chr12",
                    "name": "gene ensg00000017427"
                }
            },
            {
                "data": {
                    "id": "promoter chr12_102478548_102478607_grch38",
                    "type": "promoter",
                    "start": "102478548",
                    "end": "102478607",
                    "label": "promoter",
                    "chr": "chr12",
                    "name": "promoter chr12_102478548_102478607_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102496370_102496987_grch38",
                    "type": "enhancer",
                    "start": "102496370",
                    "end": "102496987",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284828",
                    "name": "enhancer chr12_102496370_102496987_grch38"
                }
            },
            {
                "data": {
                    "id": "pathway r-hsa-2428924",
                    "type": "pathway",
                    "pathway_name": "IGF1R signaling cascade",
                    "label": "pathway",
                    "name": "pathway r-hsa-2428924"
                }
            },
            {
                "data": {
                    "id": "pathway r-hsa-2404192",
                    "type": "pathway",
                    "pathway_name": "Signaling by Type 1 Insulin-like Growth Factor 1 Receptor (IGF1R)",
                    "label": "pathway",
                    "name": "pathway r-hsa-2404192"
                }
            },
            {
                "data": {
                    "id": "transcript enst00000424202",
                    "type": "transcript",
                    "gene_name": "IGF1",
                    "transcript_id": "ENST00000424202.6",
                    "transcript_name": "IGF1-205",
                    "start": "102402459",
                    "end": "102478651",
                    "label": "transcript",
                    "transcript_type": "protein_coding",
                    "chr": "chr12",
                    "name": "transcript enst00000424202"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102483532_102483780_grch38",
                    "type": "enhancer",
                    "start": "102483532",
                    "end": "102483780",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284825",
                    "name": "enhancer chr12_102483532_102483780_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102504869_102505263_grch38",
                    "type": "enhancer",
                    "start": "102504869",
                    "end": "102505263",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284833",
                    "name": "enhancer chr12_102504869_102505263_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102503840_102504418_grch38",
                    "type": "enhancer",
                    "start": "102503840",
                    "end": "102504418",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284832",
                    "name": "enhancer chr12_102503840_102504418_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102452575_102452904_grch38",
                    "type": "enhancer",
                    "start": "102452575",
                    "end": "102452904",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284807",
                    "name": "enhancer chr12_102452575_102452904_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102501732_102502542_grch38",
                    "type": "enhancer",
                    "start": "102501732",
                    "end": "102502542",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284830",
                    "name": "enhancer chr12_102501732_102502542_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102503189_102503641_grch38",
                    "type": "enhancer",
                    "start": "102503189",
                    "end": "102503641",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284831",
                    "name": "enhancer chr12_102503189_102503641_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102484187_102484813_grch38",
                    "type": "enhancer",
                    "start": "102484187",
                    "end": "102484813",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284826",
                    "name": "enhancer chr12_102484187_102484813_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102497396_102497681_grch38",
                    "type": "enhancer",
                    "start": "102497396",
                    "end": "102497681",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284829",
                    "name": "enhancer chr12_102497396_102497681_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102486207_102486549_grch38",
                    "type": "enhancer",
                    "start": "102486207",
                    "end": "102486549",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284827",
                    "name": "enhancer chr12_102486207_102486549_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102441106_102441527_grch38",
                    "type": "enhancer",
                    "start": "102441106",
                    "end": "102441527",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284806",
                    "name": "enhancer chr12_102441106_102441527_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102454364_102454685_grch38",
                    "type": "enhancer",
                    "start": "102454364",
                    "end": "102454685",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284808",
                    "name": "enhancer chr12_102454364_102454685_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102455030_102455483_grch38",
                    "type": "enhancer",
                    "start": "102455030",
                    "end": "102455483",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284809",
                    "name": "enhancer chr12_102455030_102455483_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102411128_102411405_grch38",
                    "type": "enhancer",
                    "start": "102411128",
                    "end": "102411405",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284780",
                    "name": "enhancer chr12_102411128_102411405_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102415197_102415568_grch38",
                    "type": "enhancer",
                    "start": "102415197",
                    "end": "102415568",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284781",
                    "name": "enhancer chr12_102415197_102415568_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102407709_102408725_grch38",
                    "type": "enhancer",
                    "start": "102407709",
                    "end": "102408725",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284778",
                    "name": "enhancer chr12_102407709_102408725_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102415593_102415846_grch38",
                    "type": "enhancer",
                    "start": "102415593",
                    "end": "102415846",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284782",
                    "name": "enhancer chr12_102415593_102415846_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102419167_102419459_grch38",
                    "type": "enhancer",
                    "start": "102419167",
                    "end": "102419459",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284784",
                    "name": "enhancer chr12_102419167_102419459_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102418398_102418675_grch38",
                    "type": "enhancer",
                    "start": "102418398",
                    "end": "102418675",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284783",
                    "name": "enhancer chr12_102418398_102418675_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102419597_102419859_grch38",
                    "type": "enhancer",
                    "start": "102419597",
                    "end": "102419859",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284785",
                    "name": "enhancer chr12_102419597_102419859_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102410004_102410767_grch38",
                    "type": "enhancer",
                    "start": "102410004",
                    "end": "102410767",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "ENCODE",
                    "enhancer_id": "EH37E0284779",
                    "name": "enhancer chr12_102410004_102410767_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102427022_102427223_grch38",
                    "type": "enhancer",
                    "start": "102427022",
                    "end": "102427223",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "Ensembl",
                    "enhancer_id": "72146",
                    "name": "enhancer chr12_102427022_102427223_grch38"
                }
            },
            {
                "data": {
                    "id": "enhancer chr12_102498523_102498856_grch38",
                    "type": "enhancer",
                    "start": "102498523",
                    "end": "102498856",
                    "label": "enhancer",
                    "chr": "chr12",
                    "data_source": "FANTOM",
                    "enhancer_id": "12315",
                    "name": "enhancer chr12_102498523_102498856_grch38"
                }
            },
            {
                "data": {
                    "id": "transcript enst00000337514",
                    "type": "transcript",
                    "gene_name": "IGF1",
                    "transcript_id": "ENST00000337514.11",
                    "transcript_name": "IGF1-202",
                    "start": "102395874",
                    "end": "102480563",
                    "label": "transcript",
                    "transcript_type": "protein_coding",
                    "chr": "chr12",
                    "name": "transcript enst00000337514"
                }
            }
        ],
        "edges": [
            {
                "data": {
                    "edge_id": "promoter_associated_with_gene",
                    "label": "associated_with",
                    "source": "promoter chr12_102478548_102478607_grch38",
                    "target": "gene ensg00000017427"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102496370_102496987_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "gene_genes_pathways_pathway",
                    "label": "genes_pathways",
                    "source": "gene ensg00000017427",
                    "target": "pathway r-hsa-2404192"
                }
            },
            {
                "data": {
                    "edge_id": "pathway_child_pathway_of_pathway",
                    "label": "child_pathway_of",
                    "source": "pathway r-hsa-2428924",
                    "target": "pathway r-hsa-2404192"
                }
            },
            {
                "data": {
                    "edge_id": "gene_transcribed_to_transcript",
                    "label": "transcribed_to",
                    "source": "gene ensg00000017427",
                    "target": "transcript enst00000424202"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102483532_102483780_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102504869_102505263_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102503840_102504418_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102452575_102452904_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102501732_102502542_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102503189_102503641_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102484187_102484813_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102497396_102497681_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102486207_102486549_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102441106_102441527_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102454364_102454685_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102455030_102455483_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102411128_102411405_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102415197_102415568_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102407709_102408725_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102415593_102415846_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102419167_102419459_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102418398_102418675_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102419597_102419859_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0009047"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102410004_102410767_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102427022_102427223_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "enhancer_associated_with_gene",
                    "label": "associated_with",
                    "source": "enhancer chr12_102498523_102498856_grch38",
                    "target": "gene ensg00000017427",
                    "biological_context": "CLO_0007606"
                }
            },
            {
                "data": {
                    "edge_id": "gene_transcribed_to_transcript",
                    "label": "transcribed_to",
                    "source": "gene ensg00000017427",
                    "target": "transcript enst00000337514"
                }
            }
        ]
    }

    return annotation


def generate_summary_mock():
    time.sleep(2 * 60)
    summary = '''mocked summary, mocked summary,
    mocked summary, mocked summayr, mocked summary'''

    return summary


def generate_label_count_mock():
    node_count_by_label = [{
        "count": 1,
        "label": "gene"
    },
        {
        "count": 2,
        "label": "promoter"
    },
        {
        "count": 23,
        "label": "enhancer"
    },
        {
        "count": 10,
        "label": "pathway"
    },
        {
        "count": 7,
        "label": "transcript"
    }]
    edge_count_by_label = [{
        "count": 25,
        "relationship_type": "associated_with"
    },
        {
            "count": 10,
            "relationship_type": "genes_pathways"
    },
        {
            "count": 64,
            "relationship_type": "child_pathway_of"
    },
        {
            "count": 7,
            "relationship_type": "transcribed_to"
    }]

    return {'node_count_by_label': node_count_by_label, 'edge_count_by_label': edge_count_by_label}
