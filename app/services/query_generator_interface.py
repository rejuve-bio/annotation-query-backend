from abc import ABC, abstractmethod


class QueryGeneratorInterface(ABC):
    @abstractmethod
    def load_dataset(self, path: str)-> None:
        pass

    @abstractmethod
    def query_Generator(self, requests, node_map, limit, node_only) -> str:
        pass

    @abstractmethod
    def run_query(self, query_code) -> list:
        pass

    @abstractmethod
    def parse_and_serialize(self, input, schema, graph_component, result_type) -> list:
        pass

    @abstractmethod
    def convert_to_dict(self, results, schema) -> tuple:
        pass

    @abstractmethod
    def parse_id(self, request) -> dict:
        pass
