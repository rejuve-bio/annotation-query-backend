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

3. Example API Request and Output: 


```bash

curl -X POST http://localhost:5000/query \
-H "Content-Type: application/json" \
-d '{
  "requests": [
    {"predicate": "transcribed to", "source": "gene ENSG00000166913", "target": "$b60385cc"}
  ]
}'


```
Output
```
{
"Generated query":"!(match &space (transcribed_to (gene ENSG00000166913) $b60385cc) (transcribed_to (gene ENSG00000166913) $b60385cc))",

"Properties":[{"node":"gene ENSG00000166913","properties":{"chr":"chr20","end":"44908532","gene_type":"protein_coding","start":"44885702"},"type":"gene"}],

"Result":[{"id":"561cafe4-0c72-4923-a75e-c50378d8ba81","predicate":"transcribed_to","source":"gene ENSG00000166913","target":"transcript ENST00000353703"},{"id":"138adf12-a5be-45ed-8ee1-5226e0b35633","predicate":"transcribed_to","source":"gene ENSG00000166913","target":"transcript ENST00000372839"}]}
```


```bash
curl -X GET http://localhost:5000/nodes
```
Sample Output
```
[{"label":"gene","properties":{"chr":"str","end":"int","gene_type":"str","name":"str","source":"str","source_url":"str","start":"int"},"type":"gene"},{"label":"protein","properties":{"accessions":"int","name":"str","organism_id":"int","source":"str","source_url":"str"},"type":"protein"}...]
```


```bash
curl -X GET http://localhost:5000/relations/gene
```
Sample Output
```
[{"label":"transcribed_to","source":"gene","target":"transcript","type":"transcribed to"},{"label":"transcribed_from","source":"transcript","target":"gene","type":"transcribed from"...}]
```
