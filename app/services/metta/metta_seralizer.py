from hyperon import SymbolAtom, ExpressionAtom, GroundedAtom

def recurssive_seralize(metta_expression, result):
    for node in metta_expression:
        if isinstance(node, SymbolAtom):
         result.append(node.get_name())
        elif isinstance(node, GroundedAtom):
            result.append(str(node))
        else:
            recurssive_seralize(node.get_children(), result)
    return result

def metta_seralizer(metta_result):
    result = []
    for node in metta_result:
        node = node.get_children()
        for metta_symbol in node:
            if isinstance(metta_symbol, SymbolAtom) and  metta_symbol.get_name() == ",":
                continue
            if isinstance(metta_symbol, ExpressionAtom):
                res = recurssive_seralize(metta_symbol.get_children(), [])
                result.append(tuple(res))
    return result
