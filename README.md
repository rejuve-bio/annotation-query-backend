### Annotaion Service

backend API.

*Supported OS:* **Linux & Mac**

**Follow these steps to run :**
1. Install required dependencies (preferably in a virtual environment):
    ```bash
    pip install -r requirements.txt
    ```
2. To Run: 
    ```bash
    ./start.sh
    ```

```bash
http://127.0.0.1:5000/query
```

3. Example request: 
```bash

curl -X POST http://localhost:5000/query -H "Content-Type: application/json" -d '{
  "requests": [
    {"predicate": "transcribed to", "source": "gene ENSG00000166913", "target": "$b60385cc"},
    {"predicate": "translates to", "source": "$b60385cc", "target": "$d2044ee8"}
  ]
}'

```

```output

{"query":"!(match &self (, (transcribed_to (gene ENSG00000166913) $b60385cc) (translates_to $b60385cc $d2044ee8) )  (, (transcribed_to (gene ENSG00000166913) $b60385cc) (translates_to $b60385cc $d2044ee8)))",

"Result":[
    {"id":"f195855b-08c0-46e1-aad5-a2ad91ef42bc","predicate":"transcribed_to","source":"gene ENSG00000166913","target":"transcript ENST00000353703"},
    {"id":"299d355e-9e90-46eb-90fc-1b36bda5d438","predicate":"translates_to","source":"transcript ENST00000353703","target":"protein P31946"},
    {"id":"3213f041-b7e6-42ce-878b-8a0bdd9a408f","predicate":"transcribed_to","source":"gene ENSG00000166913","target":"transcript ENST00000372839"},
    {"id":"fa0c85f1-59bc-423f-9c88-7fe94ee31b62","predicate":"translates_to","source":"transcript ENST00000372839","target":"protein P31946"}]}

```


```bash
curl -X GET http://localhost:5000/nodes
```

```
[{"label":"gene","properties":{"chr":"str","end":"int","gene_type":"str","name":"str","source":"str","source_url":"str","start":"int"},"type":"gene"},{"label":"protein","properties":{"accessions":"int","name":"str","organism_id":"int","source":"str","source_url":"str"},"type":"protein"}]
```


```bash
curl -X GET http://localhost:5000/relations/gene
```

```
[{"label":"transcribed_to","source":"gene","target":"transcript","type":"transcribed to"},{"label":"transcribed_from","source":"transcript","target":"gene","type":"transcribed from"},{"label":"genes_pathways","source":"gene","target":"pathway","type":"gene to pathway association"},{"label":"go_gene","source":"gene","target":"go","type":"go gene"},{"label":"coexpressed_with","source":"gene","target":"gene","type":"gene to gene coexpression association"},{"label":"enhancer_gene","source":"enhancer","target":"gene","type":"enhancer to gene association"},{"label":"promoter_gene","source":"promoter","target":"gene","type":"promoter to gene association"},{"label":"super_enhancer_gene","source":"super enhancer","target":"gene","type":"super enhancer to gene association"},{"label":"tf_gene","source":"gene","target":"gene","type":"transcription factor to gene association"},{"label":"correlates_with","source":"snp","target":"gene","type":"gtex variant to gene expression association"},{"label":"closest_gene","source":"snp","target":"gene","type":"closest gene to variant association"},{"label":"upstream_gene","source":"snp","target":"gene","type":"upstream gene to variant association"},{"label":"downstream_gene","source":"snp","target":"gene","type":"downstream gene to variant association"},{"label":"in_gene","source":"snp","target":"gene","type":"in gene to variant association"}]
```

