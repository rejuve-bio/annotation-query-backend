 def construct_or_operation(self, logic, node_map, predicate_map):
        where_clause = []
        where_clause_dict={}
        return_clause=""
        node_conditions = []
        nodes=[]
        while_conditions=[]
        where_clause=""

         
         
        

        # Check if there are properties to process
        if logic['predicates']:
            for p in logic['predicates']:
                node=predicate_map[p]['source']
                node=predicate_map[p]['target']
            for  n in nodes:
                if node_map[n]["id"]:
                   where_clause_dict[f"{node_map[n]}.id = {node_map[n]['id']}"]=n
                   where_clause.append(f"{node_map[n]}.id = {node_map[n]['id']}")
            combined_conditions = f" OR ".join(where_clauses)
            where_clause += f"({combined_conditions})"


            # for return 
            for key,value in where_clause_dict:
                return_clause+=f"WHEN {key} THEN {value} ELSE NULL END AS {value},"
            return_clause




                    












            # Build OR conditions
            for node_id, props in logic['properties'].items():
                for key, value in props.items():
                    node_conditions.append(f"{node_id}.{key} = '{value}'")
                    nodes.append(node_id)
                    
            
            # Combine OR conditions
            combined_conditions = f" OR ".join(node_conditions)
            where_clause += f"({combined_conditions})"
            while node_conditions and nodes:
                while_conditions.append(f"WHEN {node_conditions} THEN {nodes} ELSE NULL END AS {nodes}")

            return_clause= f" CASE ".join(while_conditions)
 
             
            # # Clear node_conditions for the next set of conditions
            # node_conditions = []

            # # Build IS NULL OR conditions
            # for node_id, props in logic['nodes']['properties'].items():
            #     for key, value in props.items():
            #         node_conditions.append(f"({node_id}.{key} IS NULL OR {node_id}.{key} = '{value}')")
            
            # Combine AND conditions
            
            print("______________________where clause ___________________________________________")
            print(where_clause)
            print("_______________________ where clause __________________________________________")
            print("________________________return clause _________________________________________")
            print(return_clause)
            print("_____________________________return clause________________________________")
        return where_clause,return_clause