from abc import ABC, abstractmethod

class QueryGeneratorInterface(ABC):
    @abstractmethod
    def query_Generator(self, data, schema)-> str:
        pass

    @abstractmethod
    def run_query(self, query_code)-> list:
        pass

    @abstractmethod
    def parse_and_serialize(self, input, schema, all_properties)-> list:
        pass

    @abstractmethod
    def convert_to_dict(self, results, schema)-> tuple:
        pass

    @abstractmethod
    def parse_id(self, request)-> dict:
        pass
