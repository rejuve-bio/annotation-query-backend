### Annotaion Service

backend API.

*Supported OS:* **Linux & Mac**

**Follow these steps to run :**
1. Install required dependencies (preferably in a virtual environment):
    ```bash
    pip install -r requirements.txt
    ```
2. To Run: Replace the environment variables specified in the `start.sh` file with your own
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
    {"predicate": "transcribed_to", "source": "gene ENSG00000166913", "target": "$b60385cc"},
    {"predicate": "translates_to", "source": "$b60385cc", "target": "$d2044ee8"}
  ]
}'

```

```output

{"query":"!(match &self (, (transcribed_to (gene ENSG00000166913) $b60385cc) (translates_to $b60385cc $d2044ee8) )  (, (transcribed_to (gene ENSG00000166913) $b60385cc) (translates_to $b60385cc $d2044ee8)))",

"result":"[[(, (transcribed_to (gene ENSG00000166913) (transcript ENST00000372839)) (translates_to (transcript ENST00000372839) (protein P31946))), (, (transcribed_to (gene ENSG00000166913) (transcript ENST00000353703)) (translates_to (transcript ENST00000353703) (protein P31946)))]]"}

```

