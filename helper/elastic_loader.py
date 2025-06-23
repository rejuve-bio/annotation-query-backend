from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
import os
import csv
from dotenv import load_dotenv

# Load environmental variables
load_dotenv()

class ElastiSearchLoader:
    def __init__(self, file_path, URL, API_KEY=None):
        self.es = Elasticsearch(URL, api_key= API_KEY if API_KEY is not None else '')
        self.file_path = file_path

    def load_index(self, index):
        mapping = {
            "properties": {
                f"{index}_name": { "type": "completion" },
                "id": { "type": "completion" }
            }
        }
        
        if not self.es.indices.exists(index=index):
            self.es.indices.create(index=index, mappings=mapping)
        else:
            print("Index already exist")
            
    def load_data(self):
        path = set()
        for directory in os.listdir(self.file_path):
            full_dir = f'{self.file_path}/{directory}'

            self.get_path(full_dir, path)
            
        for single_path in path:
            index = self.get_index(single_path)
            self.load_index(index)
            
            data = []

            with open(single_path, newline='') as f:
                reader = csv.DictReader(f, delimiter='|')
                
                for row in reader:
                    data.append({
                        '_index': index,
                        '_source': {
                            'id': row['id'],
                            f'{index}_name': row.get(f'{index}_name', '')
                        }
                    })
                    
            bulk(self.es, data)
            
    def get_index(self, path):
        filename, extension = os.path.splitext(path)
        
        filename = filename.split('/')[-1]
        index = '_'.join(filename.split('_')[1:])
        
        return index
            
    def get_path(self, full_dir, path):
        if os.path.isdir(full_dir):
            for file in os.listdir(full_dir):
                full_path_1 = f'{full_dir}/{file}'
                if os.path.isdir(full_path_1):
                    for directory in os.listdir(full_path_1):
                        full_path = f'{full_path_1}/{directory}'
                        self.get_path(full_path, path)
                else:
                    filename, file_extension = os.path.splitext(file)
                    if file_extension != '.csv':
                        continue
                    
                    # check get the node type from the file name
                    is_node = filename.split('_')[0]
                    if is_node != 'nodes':
                        continue

                    path.add(f'{full_dir}/{file}')
        else:
            filename, file_extension = os.path.splitext(full_dir)
            if file_extension != '.csv':
                return
            
            # get the node type form the file name
            filename = filename.split('/')[-1]
            is_node = filename.split('_')[0]
            
            if is_node != 'nodes':
                return
            path.add(full_dir)
            
        
        
        


if __name__ == "__main__":
    ELASTIC_URL = os.getenv('ES_URL')
    PARETN_DIR = os.getenv('PARENT_DIR')
    es_loader = ElastiSearchLoader(PARETN_DIR, ELASTIC_URL)

    es_loader.load_data()