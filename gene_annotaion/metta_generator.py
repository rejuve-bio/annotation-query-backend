import glob
import os
from hyperon import MeTTa
from typing import List
import re
import pickle
import logging

# from utility import get_schema, generate_id

metta = MeTTa()
# ref_dict = get_schema()
# print(ref_dict)


def validate_request(request, schema, previous_target=None):
    predicate = request['predicate']
    # Validate predicate
    if predicate not in schema:
        return False

    # Validate source and target against schema requirements
    pred_schema = schema[predicate]
    # Check if the source is a continuation from the previous target
    source = request['source']
    if previous_target and source == previous_target:
        logging.debug(f"Source {source} is a continuation from the previous target")
    elif not source.startswith('$'):  # Validate source type if not a unique identifier
        source_type = source.split()[0]
        if source_type != pred_schema['source']:
            logging.debug(f"Source type mismatch: expected {pred_schema['source']}, got {source_type}")
            return False

    # Target handling and validation
    target = request['target']
    if not target.startswith('$'):
        logging.debug(f"Invalid target format: {target}")
        return False

    return True


def generate_metta(requests,schema):
    
    metta = ''
    output = ''
    # Validation step
    last_target = None
    all_valid = True

    for request in requests:
        print(f"Validating request: {request}")  # Add logging before validation
        if validate_request(request, schema, last_target):
            last_target = request['target']  # Update last_target for continuity
            print(f"Request validated successfully, moving to next: {request['target']}")  # Logging on success
        else:
            print(f"Request validation failed: {request}")  # Confirmation of failure
            all_valid = False
            break  
    if all_valid:

        if len(requests) == 1:
            metta = (f'''!(match &space ({requests[0]['predicate'].replace(" ", "_")} ({requests[0]['source']}) {requests[0]['target']}) ({requests[0]['predicate']} ({requests[0]['source']}) {requests[0]['target']}))''')
            return metta 
        
        elif len(requests) > 0:
            metta = ('''!(match &space (,''') 
            output = (''' (,''')
            for request in requests:
                predicate = request['predicate'].replace(" ", "_")
                source = (request['source']if request['source'].startswith("$") else  f"({request['source']})")
                target = (request['target']if request['target'].startswith("$") else  f"({request['target']})")
                metta  += " " + f'({predicate} {source} {target})'
                output += " " + f'({predicate} {source} {target})'
            metta+= f" ) {output}))"

        return metta
    else:
        print("Processing stopped due to invalid request.")
# target_value1 = '$' + generate_id()
# target_value2 = '$' + generate_id()
# target_value3 = '$' + generate_id()

# requests = [
#     {"predicate":"transcribed_to", "source":'gene ENSG00000166913' , "target":"$target_value1"},
#     {"predicate":"translates_to", "source":"$target_value1" , "target":"$target_value2"},
#     {"predicate":"genes_pathways", "source":'gene ENSG00000166913' , "target":"$target_value3"},
   
#     {"predicate":"go_gene_product", "source":"$target_value3" , "target":"$target_value2"}
#     ]
#  {"predicate":"transcribed_to", "source":target_value1 , "target":target_value2}


# print("\ngenerated metta code:\n", generate_metta(requests))


# print("\nresult from the metta code:\n",metta.run(generate_metta(requests)))

