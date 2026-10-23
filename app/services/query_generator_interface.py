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

    # Optional capabilities; backends override them when supported.
    supports_logic = False

    def estimate_rows(self, query_code, species="human"):
        """Estimated peak row count of a query without running it, or None if unknown."""
        return None

    # Neighbourhood expansion — not abstract so backends can adopt it one at
    # a time. Callers (endpoint / Celery task) only use these two methods, so
    # adding a backend never requires touching them.
    def validate_neighbourhood_request(self, request, species="human") -> list:
        """Return a list of error strings; empty means the request is valid."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support neighbourhood expansion yet")

    def expand_neighbourhood(self, request, species="human", stop_event=None,
                             on_hop_complete=None) -> dict:
        """
        Expand the N-hop neighbourhood around request['seed'].

        on_hop_complete(hop_summary) is called after each hop so the caller
        can report progress. Returns the graph, per-hop summaries and counts.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support neighbourhood expansion yet")
