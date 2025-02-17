from datetime import datetime, timezone


class MockDatabase:
    def __init__(self):
        self.db = []

    def store_result(self, annotation):
        data = {
            'annotation_id': str(annotation['annotation_id']),
            'title': annotation['title'],
            'node_count': annotation.get('node_count', 0),
            'edge_count': annotation.get('edge_count', 0),
            'node_types': annotation['node_types'],
            'request': annotation['request'],
            'annotation_list_item_status': annotation.get('annotation_list_item_status', 'PENDING'),
            'nodes': annotation.get('nodes', []),
            'edges': annotation.get('edges', []),
            'node_count_by_label': annotation.get('node_count_by_label', []),
            'edge_count_by_label': annotation.get('edge_count_by_label', []),
            'annotation_result_status': annotation.get('annotation_result_status', 'PENDING'),
            'summary': annotation.get('summary', ''),
            'annoation_label_status': annotation.get('annoation_label_status', 'PENDING'),
            'annotation_summary_status': annotation.get('annotation_summary_status', 'PENDING'),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }

        self.db.append(data)
        return True

    def get_result(self):
        return self.db

    def get_result_by_id(self, id):
        for data in self.db:
            if data['annotation_id'] == id:
                return data

        return None

    def update_count(self, id, count, status):
        for data in self.db:
            if data['annotation_id'] == str(id):
                data['node_count'] = count['node_count']
                data['edge_count'] = count['edge_count']
                data['annotation_list_item_status'] = status

    def update_result(self, id, nodes, edges, status):
        for data in self.db:
            if data['annotation_id'] == str(id):
                data['nodes'] = nodes
                data['edges'] = edges
                data['annotation_result_status'] = status

    def update_summary(self, id, summary):
        for data in self.db:
            if data['annotation_id'] == str(id):
                data['summary'] = summary
                data['annotation_summary_status'] = 'COMPLETE'
                if len(data['node_count_by_label']) > 0:
                    return 'COMPLETE'
                else:
                    return 'PENDING'

    def update_label_count(self, id, count):
        for data in self.db:
            if data['annotation_id'] == str(id):
                data['node_count_by_label'] = count['node_count_by_label']
                data['edge_count_by_label'] = count['edge_count_by_label']
                data['annotation_label_status'] = 'COMPLETE'
                if data['summary'] != '':
                    return 'COMPLETE'
                else:
                    return 'PENDING'
