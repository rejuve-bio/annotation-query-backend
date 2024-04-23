import glob
import os
from hyperon import MeTTa
from typing import List
import re
import pickle
# from utility import get_schema, generate_id

metta = MeTTa()
# ref_dict = get_schema()
# print(ref_dict)
def generate_metta(requests):
    metta = ''
    output = ''

    if len(requests) == 1:
        metta = (f'''!(match &space ({requests[0]['predicate']} ({requests[0]['source']}) {requests[0]['target']}) ({requests[0]['predicate']} ({requests[0]['source']}) {requests[0]['target']}))''')
        return metta 
    
    
    elif len(requests) > 0:
        metta = ('''!(match &space (,''') 
        output = (''' (,''')
        for request in requests:
          predicate = request['predicate']
          source = (request['source']if request['source'].startswith("$") else  f"({request['source']})")
          target = (request['target']if request['target'].startswith("$") else  f"({request['target']})")
          metta  += " " + f'({predicate} {source} {target})'
          output += " " + f'({predicate} {source} {target})'
        metta+= f" ) {output}))"

    return metta
    
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

